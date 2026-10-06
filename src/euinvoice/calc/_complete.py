"""``complete``: derive BT-131, the DOCUMENT TOTALS (BG-22) and the VAT BREAKDOWN (BG-23) of a draft.

Rule sources and rounding: see :mod:`euinvoice.calc`.
"""

import types
import typing as t
from collections.abc import Mapping
from decimal import Decimal
from fractions import Fraction

import pydantic

from euinvoice.calc._common import ZERO, round_cents, total
from euinvoice.errors import ModelError
from euinvoice.model import (
    DocumentLevelAllowance,
    DocumentLevelCharge,
    DocumentTotals,
    Invoice,
    InvoiceDraft,
    InvoiceLine,
    LineDraft,
    VatBreakdown,
)
from euinvoice.model._base import EuInvoiceModel
from euinvoice.model.amounts import Amount
from euinvoice.model.datatypes import Text, VatExemptionReasonCode

__all__ = ["ExemptionReason", "complete", "line_net_amount"]


class ExemptionReason(EuInvoiceModel):
    """The VAT exemption reason of one VAT category, an input of :func:`complete`.

    It fills BT-120 and BT-121 of every VAT breakdown (BG-23) of that category. BR-E-10, BR-AE-10,
    BR-IC-10, BR-G-10 and BR-O-10 require one of the two for categories E, AE, K, G and O.
    """

    text: Text | None = None
    """VAT exemption reason text (BT-120)."""
    code: VatExemptionReasonCode | None = None
    """VAT exemption reason code (BT-121), CEF VATEX (BR-CL-22), stored upper-cased."""

    @pydantic.model_validator(mode="after")
    def _check_present(self) -> t.Self:
        if self.text is None and self.code is None:
            raise ModelError("a VAT exemption reason needs a text (BT-120) or a code (BT-121) or both")
        return self


_NO_REASONS: t.Final[Mapping[str, ExemptionReason]] = types.MappingProxyType({})
# validates BT-111, BT-113 and BT-114 before any arithmetic touches them (a float would raise TypeError)
_OPTIONAL_AMOUNT: t.Final[pydantic.TypeAdapter[Decimal | None]] = pydantic.TypeAdapter(Amount | None)


def line_net_amount(line: LineDraft | InvoiceLine) -> Decimal:
    """Compute the invoice line net amount (BT-131): BT-129 * BT-146 / BT-149 + Σ BT-141 - Σ BT-136.

    The product is rounded half up to two decimals per D11 (the line charges and allowances already
    have two). EN 16931 has no rule for this arithmetic; the formula is the one of Peppol BIS 3.0.21
    rule PEPPOL-EN16931-R120 (``rules/sch/PEPPOL-EN16931-UBL.sch``), which compares the unrounded value
    with a slack of 0.02 (``u:slack(…, 0.02)``), so the rounded result is always consistent with it.
    A missing or zero base quantity (BT-149) counts as 1, as R120's ``$baseQuantity`` variable does;
    Peppol's PEPPOL-EN16931-R121 rejects a base quantity of 0, which is a profile pre-flight concern.

    Args:
        line: A line draft (or a complete line, whose own BT-131 is ignored).

    Returns:
        The line net amount, with two decimals.
    """
    price = line.price_details
    base = price.base_quantity or Decimal(1)
    gross = round_cents(Fraction(line.invoiced_quantity) * Fraction(price.item_net_price) / Fraction(base))
    charges = total(charge.amount for charge in line.charges)
    allowances = total(allowance.amount for allowance in line.allowances)
    return gross + charges - allowances


def _breakdown(
    lines: tuple[InvoiceLine, ...],
    allowances: tuple[DocumentLevelAllowance, ...],
    charges: tuple[DocumentLevelCharge, ...],
    exemption_reasons: Mapping[str, ExemptionReason],
) -> tuple[VatBreakdown, ...]:
    """Derive the VAT breakdown (BG-23): one group per VAT category code and rate.

    BT-116 sums the line net amounts (BT-131) and document level charges (BT-99) minus the document
    level allowances (BT-92) of the category and rate (BR-S-08 and the other ``-08`` rules). BT-117 is
    BT-116 * BT-119 / 100, rounded to two decimals (BR-CO-17); 0 without a rate (category O, BR-O-09).
    Groups appear in the order their key first occurs in the lines, allowances, then charges.
    """
    taxable: dict[tuple[str, Decimal | None], Decimal] = {}
    rates: dict[tuple[str, Decimal | None], Decimal | None] = {}

    def add(category: str, rate: Decimal | None, amount: Decimal) -> None:
        key = (category, rate)  # Decimal("19") == Decimal("19.00"): one group, first spelling kept
        rates.setdefault(key, rate)
        taxable[key] = taxable.get(key, ZERO) + amount

    for line in lines:
        add(line.vat_information.category_code, line.vat_information.rate, line.net_amount)
    for allowance in allowances:
        add(allowance.vat_category_code, allowance.vat_rate, -allowance.amount)
    for charge in charges:
        add(charge.vat_category_code, charge.vat_rate, charge.amount)

    unused = set(exemption_reasons) - {category for category, _ in taxable}
    if unused:
        raise ModelError(
            f"exemption_reasons keys are VAT category codes such as 'AE'; no line, allowance or charge uses "
            f"{sorted(unused)}"
        )
    groups = []
    for key, amount in taxable.items():
        category, _ = key
        rate = rates[key]
        tax = ZERO if rate is None else round_cents(Fraction(amount) * Fraction(rate) / 100)
        reason = exemption_reasons.get(category)
        groups.append(
            VatBreakdown(
                taxable_amount=amount,
                tax_amount=tax,
                category_code=category,
                rate=rate,
                exemption_reason=None if reason is None else reason.text,
                exemption_reason_code=None if reason is None else reason.code,
            )
        )
    return tuple(groups)


def _check_accounting_currency(draft: InvoiceDraft, bt111: Decimal | None) -> None:
    """BR-53: BT-6 needs BT-111, and BT-6 = BT-5 fails both bindings (CII BR-53, UBL BR-CO-15)."""
    code = draft.vat_accounting_currency_code
    if code is None and bt111 is not None:
        raise ModelError("vat_total_in_accounting_currency (BT-111) needs a VAT accounting currency code (BT-6)")
    if code is not None and bt111 is None:
        raise ModelError(
            f"the VAT accounting currency code (BT-6) {code} needs vat_total_in_accounting_currency (BT-111), BR-53"
        )
    if code is not None and code == draft.currency_code:
        raise ModelError(
            f"the VAT accounting currency code (BT-6) must differ from the invoice currency (BT-5) {code}; "
            "leave BT-6 out (BR-53)"
        )


def complete(
    draft: InvoiceDraft,
    *,
    paid_amount: Amount | None = None,
    rounding_amount: Amount | None = None,
    vat_total_in_accounting_currency: Amount | None = None,
    exemption_reasons: Mapping[str, ExemptionReason] = _NO_REASONS,
) -> Invoice:
    """Derive BT-131, the DOCUMENT TOTALS (BG-22) and the VAT BREAKDOWN (BG-23) of a draft.

    The keyword arguments are the inputs that cannot be derived. ``check(complete(draft, ...))`` is
    empty, so the amounts pass the CEN rules in both UBL and CII, whenever the draft's VAT categories,
    rates and exemption reasons follow the CEN rules (BR-*-05..07, BR-*-10, BR-O-11..14, BR-B-02); the
    result is not checked for you.

    Whole-unit VAT: the CEN example ``huf_example_cii.xml`` states the VAT of 69180.00 at 27 % as
    18679 (whole forints), not 18678.60. :func:`complete` always rounds to cents (D11).

    Derivations (CEN ``validation-1.3.16``, ``EN16931-model.sch``):

    * BT-131 per line: :func:`line_net_amount`.
    * BT-106 = Σ BT-131 (BR-CO-10); BT-107 = Σ BT-92 and BT-108 = Σ BT-99, left out when there are no
      document level allowances or charges (BR-CO-11, BR-CO-12).
    * BT-109 = BT-106 - BT-107 + BT-108 (BR-CO-13); BT-110 = Σ BT-117 (BR-CO-14);
      BT-112 = BT-109 + BT-110 (BR-CO-15); BT-115 = BT-112 - BT-113 + BT-114 (BR-CO-16).
    * BG-23: one group per VAT category code and rate, see :func:`_breakdown` (BR-CO-17, ``-08``).
    * BT-111 is passed through; BT-6 needs it and must differ from BT-5 (BR-53).

    Args:
        draft: The invoice without totals and VAT breakdown.
        paid_amount: Paid amount (BT-113).
        rounding_amount: Rounding amount (BT-114).
        vat_total_in_accounting_currency: Invoice total VAT amount in accounting currency (BT-111),
            required exactly when the draft has a VAT accounting currency code BT-6 (BR-53).
        exemption_reasons: VAT exemption reason (BT-120, BT-121) per VAT category code (BT-118), e.g.
            ``{"AE": ExemptionReason(code="VATEX-EU-AE", text="Reverse charge")}``; keys are matched
            upper-cased. Every VAT breakdown of that category gets it.

    Returns:
        The complete invoice, built through validation (``Invoice.model_validate``).

    Raises:
        ModelError: ``exemption_reasons`` names a category the draft does not use (or one twice, in
            different case), or BT-6 and BT-111 do not go together: BT-6 without BT-111, BT-111
            without BT-6, or BT-6 equal to BT-5 (BR-53).
        pydantic.ValidationError: An amount argument is not an Amount (e.g. a float, D3, or more than
            two decimals, BR-DEC-*).
    """
    # ponytail: cent rounding only. For whole-unit VAT (e.g. HUF), override BT-117, BT-110, BT-112 and
    # BT-115 of the result and run check(): BR-CO-17 tolerates a VAT difference below 1. Upgrade path: a
    # per-currency rounding unit, if the maintainer wants one.
    paid_amount = _OPTIONAL_AMOUNT.validate_python(paid_amount)
    rounding_amount = _OPTIONAL_AMOUNT.validate_python(rounding_amount)
    vat_total_in_accounting_currency = _OPTIONAL_AMOUNT.validate_python(vat_total_in_accounting_currency)
    _check_accounting_currency(draft, vat_total_in_accounting_currency)
    reasons = {str(category).upper(): reason for category, reason in exemption_reasons.items()}
    if len(reasons) != len(exemption_reasons):
        raise ModelError(f"exemption_reasons names a VAT category twice: {sorted(exemption_reasons)}")
    lines = tuple(
        InvoiceLine.model_validate({**dict(line), "net_amount": line_net_amount(line)}) for line in draft.lines
    )
    breakdown = _breakdown(lines, draft.allowances, draft.charges, reasons)
    line_sum = total(line.net_amount for line in lines)
    allowance_sum = total(allowance.amount for allowance in draft.allowances) if draft.allowances else None
    charge_sum = total(charge.amount for charge in draft.charges) if draft.charges else None
    without_vat = line_sum - (allowance_sum or ZERO) + (charge_sum or ZERO)
    vat = total(group.tax_amount for group in breakdown)
    with_vat = without_vat + vat
    totals = DocumentTotals(
        sum_of_line_net_amounts=line_sum,
        sum_of_allowances=allowance_sum,
        sum_of_charges=charge_sum,
        total_without_vat=without_vat,
        total_vat=vat,
        total_vat_in_accounting_currency=vat_total_in_accounting_currency,
        total_with_vat=with_vat,
        paid_amount=paid_amount,
        rounding_amount=rounding_amount,
        amount_due=with_vat - (paid_amount or ZERO) + (rounding_amount or ZERO),
    )
    return Invoice.model_validate({**dict(draft), "lines": lines, "totals": totals, "vat_breakdown": breakdown})
