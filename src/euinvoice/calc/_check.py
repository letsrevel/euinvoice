"""``check``: report where an invoice's amounts break the CEN calculation and VAT category rules.

Rule sources, the D8 severity policy and the UBL/CII asymmetry table: see :mod:`euinvoice.calc`.

BR-45, BR-46 and BR-47 (a VAT breakdown has BT-116, BT-117 and BT-118) cannot fail on an
:class:`~euinvoice.model.Invoice`: the model makes those terms mandatory.
"""

from collections.abc import Iterator

from euinvoice.calc._categories import category_findings, vat_in_tolerance
from euinvoice.calc._common import ZERO, at, fatal, fmt, total, verdict, xpath_round
from euinvoice.model import Invoice, VatBreakdown
from euinvoice.report import Finding

__all__ = ["check"]


def _sums(invoice: Invoice) -> Iterator[Finding]:
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


def _with_vat(invoice: Invoice) -> Iterator[Finding]:
    """BR-CO-15: BT-112 = BT-109 + BT-110.

    UBL: exactly one ``cbc:TaxAmount`` in BT-5 and BT-112 = BT-109 + BT-110. CII: that, or
    BT-112 = BT-109 (its second disjunct, which also accepts an absent BT-110).
    """
    totals = invoice.totals
    adds_up = totals.total_vat is not None and totals.total_with_vat == totals.total_without_vat + totals.total_vat
    yield from verdict(
        "BR-CO-15",
        at("BT-112"),
        f"Invoice total amount with VAT (BT-112) {fmt(totals.total_with_vat)} != BT-109 "
        f"{fmt(totals.total_without_vat)} + BT-110 {fmt(totals.total_vat)}.",
        ubl=adds_up,
        cii=adds_up or totals.total_with_vat == totals.total_without_vat,
    )


def _accounting_currency(invoice: Invoice) -> Iterator[Finding]:
    """BR-53. UBL: a ``cbc:TaxAmount`` exists in BT-6. CII: BT-111 in BT-6 and BT-6 != BT-5.

    BT-6 = BT-5 with BT-111 fails CII's BR-53 and, in UBL, BR-CO-15 (two ``cbc:TaxAmount`` in BT-5): a
    fatal BR-53. Without BT-111 only CII rejects BT-6 = BT-5 (UBL's BT-110 is then in BT-6).
    """
    code, bt111 = invoice.vat_accounting_currency_code, invoice.totals.total_vat_in_accounting_currency
    if code is None:
        return
    same = code == invoice.currency_code
    yield from verdict(
        "BR-53",
        at("BT-111"),
        f"With the VAT accounting currency code (BT-6) {code}, the Invoice total VAT amount in accounting "
        f"currency (BT-111) shall be provided, and BT-6 shall differ from the invoice currency (BT-5) "
        f"{invoice.currency_code}; BT-111 is {fmt(bt111)}.",
        ubl=same if bt111 is None else not same,
        cii=bt111 is not None and not same,
    )


def _group(index: int, group: VatBreakdown) -> Iterator[Finding]:
    """BR-48 (same in both bindings) and BR-CO-17 (UBL strict ``<``/``>``, CII ``<=``/``>=``)."""
    rate, tax = group.rate, group.tax_amount
    if rate is None and group.category_code != "O":
        yield from fatal(
            "BR-48",
            at("BT-119", index),
            f"The VAT breakdown of category {group.category_code} has no VAT category rate (BT-119); only "
            "category O may omit it.",
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
        cii=cii,
    )


def check(invoice: Invoice) -> tuple[Finding, ...]:
    """Report where the amounts of a complete invoice break the CEN calculation and VAT rules.

    Checked (CEN validation-1.3.16, every rule ``fatal`` in both bindings): BR-CO-10 … BR-CO-17,
    BR-48, BR-53; per VAT category code S, Z, E, AE, K, G, O, L and M the rules ``BR-<x>-01``
    (breakdown present), ``-05``/``-06``/``-07`` (line, allowance and charge VAT rates), ``-08``
    (taxable amount), ``-09`` (tax amount) and ``-10`` (exemption reason); BR-O-11 … BR-O-14 and
    BR-B-02. Each rule is evaluated as the UBL and the CII binding test it: ``fatal`` under the rule's
    id when both reject it, a ``warning`` :data:`~euinvoice.calc.PORTABILITY` when only one does (see
    :mod:`euinvoice.calc`). The official Schematron stays the oracle (D8): this is an early,
    syntax-free warning, not a replacement for ``validate()``.

    Args:
        invoice: A complete invoice.

    Returns:
        The findings, each with the model path as location (e.g. ``vat_breakdown[0].tax_amount``, see
        :mod:`euinvoice.model.bt_index`) and source ``"calc"``; empty if every rule holds in both
        bindings.
    """
    findings = [*_sums(invoice), *_with_vat(invoice), *_accounting_currency(invoice)]
    for index, group in enumerate(invoice.vat_breakdown):
        findings += _group(index, group)
    findings += category_findings(invoice)
    return tuple(findings)
