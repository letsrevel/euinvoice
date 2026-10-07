"""``check``: report where an invoice breaks the CEN calculation, VAT category and period rules.

Rule sources, the D8 severity policy and the UBL/CII asymmetry table: see :mod:`euinvoice.calc`.

BR-45, BR-46 and BR-47 (a VAT breakdown has BT-116, BT-117 and BT-118) cannot fail on an
:class:`~euinvoice.model.Invoice`: the model makes those terms mandatory.
"""

import typing as t
from collections.abc import Iterator

from euinvoice._syntax import Syntax
from euinvoice.calc._categories import category_verdicts, vat_in_tolerance
from euinvoice.calc._common import ZERO, Verdict, at, fatal, fmt, total, verdict, xpath_round
from euinvoice.model import Invoice, InvoiceLinePeriod, InvoicingPeriod, VatBreakdown
from euinvoice.model.codes import VatCategory
from euinvoice.report import Finding

__all__ = ["check"]

type _Period = InvoicingPeriod | InvoiceLinePeriod


def _sums(invoice: Invoice) -> Iterator[Verdict]:
    """BR-CO-10 … BR-CO-14 and BR-CO-16: the same test in both bindings."""
    totals = invoice.totals
    lines = total(line.net_amount for line in invoice.lines)
    if totals.sum_of_line_net_amounts != lines:
        yield from fatal(
            "BR-CO-10",
            at("BT-106"),
            f"Sum of Invoice line net amount (BT-106) {fmt(totals.sum_of_line_net_amounts)} != "
            f"sum of Invoice line net amount (BT-131) {fmt(lines)}.",
        )
    for rule, ident, items, actual, what in (
        ("BR-CO-11", "BT-107", invoice.allowances, totals.sum_of_allowances, "allowance amount (BT-92)"),
        ("BR-CO-12", "BT-108", invoice.charges, totals.sum_of_charges, "charge amount (BT-99)"),
    ):
        expected = total(item.amount for item in items)
        # absent is fine without allowances (charges); present, it must equal the sum (0 for none)
        if not (actual is None and not items) and actual != expected:
            yield from fatal(rule, at(ident), f"{ident} {fmt(actual)} != sum of Document level {what} {fmt(expected)}.")
    without_vat = totals.sum_of_line_net_amounts - (totals.sum_of_allowances or ZERO) + (totals.sum_of_charges or ZERO)
    if totals.total_without_vat != without_vat:
        yield from fatal(
            "BR-CO-13",
            at("BT-109"),
            f"Invoice total amount without VAT (BT-109) {fmt(totals.total_without_vat)} != "
            f"BT-106 - BT-107 + BT-108 = {fmt(without_vat)}.",
        )
    vat = total(group.tax_amount for group in invoice.vat_breakdown)
    if totals.total_vat is not None and totals.total_vat != vat:  # absent BT-110: see BR-CO-15
        yield from fatal(
            "BR-CO-14",
            at("BT-110"),
            f"Invoice total VAT amount (BT-110) {fmt(totals.total_vat)} != "
            f"sum of VAT category tax amount (BT-117) {fmt(vat)}.",
        )
    due = totals.total_with_vat - (totals.paid_amount or ZERO) + (totals.rounding_amount or ZERO)
    if totals.amount_due != due:
        yield from fatal(
            "BR-CO-16",
            at("BT-115"),
            f"Amount due for payment (BT-115) {fmt(totals.amount_due)} != BT-112 - BT-113 + BT-114 = {fmt(due)}.",
        )


def _ordered(rule: str, dates: tuple[str, str], period: _Period, *indices: int) -> Iterator[Verdict]:
    """BR-29 / BR-30: with both dates given, the end date is not before the start date."""
    start, end = period.start_date, period.end_date
    if start is not None and end is not None and end < start:
        yield from fatal(
            rule,
            at(dates[1], *indices),
            f"The period end date ({dates[1]}) {end} is before the period start date ({dates[0]}) {start}.",
        )


def _periods(invoice: Invoice) -> Iterator[Verdict]:
    """BR-29 and BR-CO-19 on the INVOICING PERIOD (BG-14), BR-30 and BR-CO-20 on each INVOICE LINE PERIOD (BG-26).

    Tests from the bindings (contexts ``$Invoice_Period`` / ``$Invoice_Line_Period``):
    BR-29 / BR-30. UBL: ``xs:date(cbc:EndDate) >= xs:date(cbc:StartDate)`` when both exist. CII: the
    same on the ``udt:DateTimeString[@format = '102']`` texts (``YYYYMMDD``, so string order is date
    order). BR-CO-20. Both: ``cbc:StartDate`` / ``ram:StartDateTime`` or the end date exists.
    BR-CO-19. CII: the same. UBL: or ``cbc:DescriptionCode`` exists, and the UBL writer puts the
    VAT point date code (BT-8) in that ``cac:InvoicePeriod``, so UBL accepts an undated BG-14 with BT-8.
    """
    period = invoice.delivery.invoicing_period if invoice.delivery else None
    if period is not None:
        yield from _ordered("BR-29", ("BT-73", "BT-74"), period)
        is_dated = period.start_date is not None or period.end_date is not None
        yield from verdict(
            "BR-CO-19",
            at("BG-14"),
            "The INVOICING PERIOD (BG-14) has neither a start date (BT-73) nor an end date (BT-74).",
            ubl=is_dated or invoice.vat_point_date_code is not None,
            cii=is_dated,
        )
    for index, line in enumerate(invoice.lines):
        if line.period is None:
            continue
        yield from _ordered("BR-30", ("BT-134", "BT-135"), line.period, index)
        is_dated = line.period.start_date is not None or line.period.end_date is not None
        if not is_dated:
            yield from fatal(
                "BR-CO-20",
                at("BG-26", index),
                "The INVOICE LINE PERIOD (BG-26) has neither a start date (BT-134) nor an end date (BT-135).",
            )


def _with_vat(invoice: Invoice) -> Iterator[Verdict]:
    """BR-CO-15: BT-112 = BT-109 + BT-110.

    UBL: exactly one ``cbc:TaxAmount`` in BT-5 and BT-112 = BT-109 + BT-110. CII: exactly one
    ``ram:TaxTotalAmount`` in BT-5 and that sum, or BT-112 = BT-109 (its second disjunct, which also
    accepts an absent BT-110). BT-6 = BT-5 with BT-111 puts a second amount in BT-5, so then only the
    second disjunct can pass. An absent BT-110 with BT-112 = BT-109 and Σ BT-117 = 0 passes UBL too: the UBL
    writer states it as 0.00 there (bt-mapping.md "Normalizations").
    """
    totals = invoice.totals
    second_in_bt5 = (
        invoice.vat_accounting_currency_code == invoice.currency_code
        and totals.total_vat_in_accounting_currency is not None
    )
    adds_up = (
        not second_in_bt5
        and totals.total_vat is not None
        and totals.total_with_vat == totals.total_without_vat + totals.total_vat
    )
    breakdown_vat = total(group.tax_amount for group in invoice.vat_breakdown)
    no_vat_total = totals.total_vat is None and totals.total_with_vat == totals.total_without_vat
    implied_zero = not second_in_bt5 and no_vat_total and breakdown_vat == 0
    yield from verdict(
        "BR-CO-15",
        at("BT-112"),
        f"Invoice total amount with VAT (BT-112) {fmt(totals.total_with_vat)} != BT-109 "
        f"{fmt(totals.total_without_vat)} + BT-110 {fmt(totals.total_vat)}"
        + (
            f"; BT-110 is not implied as 0.00 because Σ BT-117 = {fmt(breakdown_vat)} (BR-CO-14)"
            if no_vat_total and breakdown_vat != 0
            else ""
        )
        + (", or a second VAT total in the invoice currency (BT-6 = BT-5 with BT-111)." if second_in_bt5 else "."),
        ubl=adds_up or implied_zero,
        cii=adds_up or totals.total_with_vat == totals.total_without_vat,
    )


def _accounting_currency(invoice: Invoice) -> Iterator[Verdict]:
    """BR-53. UBL: a ``cbc:TaxAmount`` exists in BT-6. CII: BT-111 in BT-6 and BT-6 != BT-5.

    With BT-6 = BT-5 only CII rejects BR-53: UBL finds BT-110 (or BT-111) in BT-6. BT-6 = BT-5 with
    BT-111 also breaks BR-CO-15 (see :func:`_with_vat`).
    """
    code, bt111 = invoice.vat_accounting_currency_code, invoice.totals.total_vat_in_accounting_currency
    if code is None:
        return
    same = code == invoice.currency_code
    # UBL: BT-111 is written in BT-6, and BT-110 is in BT-6 too when BT-6 = BT-5
    ubl_has_amount_in_bt6 = bt111 is not None or same
    yield from verdict(
        "BR-53",
        at("BT-111"),
        f"With the VAT accounting currency code (BT-6) {code}, the Invoice total VAT amount in accounting "
        f"currency (BT-111) shall be provided, and BT-6 shall differ from the invoice currency (BT-5) "
        f"{invoice.currency_code}; BT-111 is {fmt(bt111)}.",
        ubl=ubl_has_amount_in_bt6,
        cii=bt111 is not None and not same,
    )


# CII binds $VATAF, $VATAG and $VATO to the same node as $VAT_breakdown (ram:ApplicableTradeTax) and lists
# them first in its single pattern, so Schematron's first-match rule never runs the $VAT_breakdown asserts
# (BR-45 … BR-48, BR-CO-17) on an L, M or O breakdown (schematron/CII/EN16931-CII-model.sch and
# schematron/abstract/EN16931-CII-model.sch). The other categories bind ram:CategoryCode, a child node.
_CII_SHADOWED: t.Final = frozenset({VatCategory.IGIC, VatCategory.IPSI, VatCategory.NOT_SUBJECT_TO_VAT})


def _group(index: int, group: VatBreakdown) -> Iterator[Verdict]:
    """BR-48 and BR-CO-17 (UBL strict ``<``/``>``, CII ``<=``/``>=``; CII never tests L, M and O)."""
    rate, tax = group.rate, group.tax_amount
    cii_tests = group.category_code not in _CII_SHADOWED
    if rate is None and group.category_code != VatCategory.NOT_SUBJECT_TO_VAT:
        yield from verdict(
            "BR-48",
            at("BT-119", index),
            f"The VAT breakdown of category {group.category_code} has no VAT category rate (BT-119); only "
            "category O may omit it.",
            ubl=False,
            cii=not cii_tests,
        )
    # three branches: rate rounds to 0, rate present, rate absent (the first and last need round(BT-117) = 0)
    if rate is not None and xpath_round(rate) != 0:
        ubl = vat_in_tolerance(tax, group.taxable_amount, rate, strict=True)
        cii = vat_in_tolerance(tax, group.taxable_amount, rate, strict=False)
    else:
        ubl = cii = xpath_round(tax) == 0
    yield from verdict(
        "BR-CO-17",
        at("BT-117", index),
        f"VAT category tax amount (BT-117) {fmt(tax)} != VAT category taxable amount (BT-116) "
        f"{fmt(group.taxable_amount)} * (VAT category rate (BT-119) {fmt(rate)} / 100), rounded to two decimals "
        "(the rule tolerates a difference below 1).",
        ubl=ubl,
        cii=cii or not cii_tests,
    )


def check(invoice: Invoice, *, syntax: Syntax | None = None) -> tuple[Finding, ...]:
    """Report where a complete invoice breaks the CEN calculation, VAT and period rules.

    Checked (CEN validation-1.3.16, every rule ``fatal`` in both bindings): BR-CO-10 … BR-CO-17,
    BR-48, BR-53; the period rules BR-29, BR-30, BR-CO-19 and BR-CO-20; per VAT category code S, Z,
    E, AE, K, G, O, L and M the rules ``BR-<x>-01`` (breakdown present), ``-05``/``-06``/``-07``
    (line, allowance and charge VAT rates), ``-08`` (taxable amount), ``-09`` (tax amount) and
    ``-10`` (exemption reason); BR-O-11 … BR-O-14 and BR-B-02. Each rule is evaluated as the UBL
    and the CII binding test it. With a target ``syntax``, a rule its binding rejects is ``fatal``
    under the rule's id, and the other binding is ignored. Without one, a rule is ``fatal`` when
    both bindings reject it and a ``warning`` :data:`~euinvoice.calc.PORTABILITY` when only one does
    (see :mod:`euinvoice.calc`). The official Schematron stays the oracle (D8): this is an early
    warning, not a replacement for ``validate()``.

    Args:
        invoice: A complete invoice.
        syntax: The syntax the invoice will be written in (a :class:`~euinvoice.syntax.Syntax` or its
            value, ``"ubl"`` / ``"cii"``), or ``None`` for either.

    Returns:
        The findings, each with the model path as location (e.g. ``vat_breakdown[0].tax_amount``, see
        :mod:`euinvoice.model.bt_index`) and source ``"calc"``; empty if every rule holds in the target
        syntax (both, without one).

    Raises:
        ValueError: ``syntax`` is not a syntax, or not an EN 16931 one (``Syntax.FATTURAPA`` has no CEN binding).
    """
    target = None if syntax is None else Syntax(syntax)  # "ubl" must not fall through to the CII verdict
    if target is Syntax.FATTURAPA:  # it must not fall through to the CII verdict either
        raise ValueError("calc.check evaluates the CEN rules of the UBL and CII bindings; FatturaPA has none")
    verdicts = [*_sums(invoice), *_with_vat(invoice), *_accounting_currency(invoice), *_periods(invoice)]
    for index, group in enumerate(invoice.vat_breakdown):
        verdicts += _group(index, group)
    verdicts += category_verdicts(invoice)
    return tuple(finding for v in verdicts if (finding := v.finding(target)) is not None)
