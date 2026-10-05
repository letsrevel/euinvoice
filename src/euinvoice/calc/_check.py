"""``check``: report where an invoice's amounts break the CEN arithmetic and VAT category rules.

Rule sources and the choice between UBL and CII tolerances: see :mod:`euinvoice.calc`. Every rule
checked here is ``flag="fatal"`` in ``schematron/abstract/EN16931-model.sch`` (validation-1.3.16).

BR-45, BR-46 and BR-47 (a VAT breakdown has BT-116, BT-117 and BT-118) cannot fail on an
:class:`~euinvoice.model.Invoice`: the model makes those terms mandatory.
"""

import typing as t
from collections.abc import Iterator
from decimal import Decimal
from fractions import Fraction

from euinvoice.calc._common import CATEGORY_RULES, ZERO, CategoryRules, round_cents, total, xpath_round
from euinvoice.model import Invoice, VatBreakdown
from euinvoice.model.bt_index import path_of
from euinvoice.report import Finding, Severity

__all__ = ["SOURCE", "check"]

SOURCE: t.Final = "calc"
"""The ``source`` of every :class:`~euinvoice.report.Finding` that :func:`check` returns."""


def _at(ident: str, *indices: int) -> str:
    """The model path of a BT/BG id with concrete indices, e.g. ``vat_breakdown[1].tax_amount``."""
    path = path_of(ident)
    for index in indices:
        path = path.replace("[]", f"[{index}]", 1)
    return path


def _finding(rule_id: str, location: str, message: str) -> Finding:
    return Finding(rule_id=rule_id, severity=Severity.FATAL, location=location, message=message, source=SOURCE)


def _fmt(value: Decimal | None) -> str:
    return "absent" if value is None else format(value, "f")


def _vat_in_tolerance(tax: Decimal, taxable: Decimal, rate: Decimal) -> bool:
    """BR-CO-17 / BR-S-09: |BT-117| - 1 < round(|BT-116| * BT-119 / 100, 2) < |BT-117| + 1 (UBL, strict).

    The product is non-negative, so half-up rounding equals XPath ``round()`` here.
    """
    expected = round_cents(Fraction(abs(taxable)) * Fraction(rate) / 100)
    return abs(tax) - 1 < expected < abs(tax) + 1


def _totals(invoice: Invoice) -> Iterator[Finding]:
    """BR-CO-10 … BR-CO-16 and BR-53 on the DOCUMENT TOTALS (BG-22)."""
    totals = invoice.totals
    lines = total(line.net_amount for line in invoice.lines)
    if totals.sum_of_line_net_amounts != lines:
        yield _finding(
            "BR-CO-10",
            _at("BT-106"),
            f"Sum of Invoice line net amount (BT-106) {_fmt(totals.sum_of_line_net_amounts)} != "
            f"Σ Invoice line net amount (BT-131) {_fmt(lines)}.",
        )
    for rule, ident, items, actual, what in (
        ("BR-CO-11", "BT-107", invoice.allowances, totals.sum_of_allowances, "allowance amount (BT-92)"),
        ("BR-CO-12", "BT-108", invoice.charges, totals.sum_of_charges, "charge amount (BT-99)"),
    ):
        expected = total(item.amount for item in items)
        # absent is fine without allowances (charges); present, it must equal the sum (0 for none)
        if not (actual is None and not items) and actual != expected:
            yield _finding(rule, _at(ident), f"{ident} {_fmt(actual)} != Σ Document level {what} {_fmt(expected)}.")
    without_vat = totals.sum_of_line_net_amounts - (totals.sum_of_allowances or ZERO) + (totals.sum_of_charges or ZERO)
    if totals.total_without_vat != without_vat:
        yield _finding(
            "BR-CO-13",
            _at("BT-109"),
            f"Invoice total amount without VAT (BT-109) {_fmt(totals.total_without_vat)} != "
            f"BT-106 - BT-107 + BT-108 = {_fmt(without_vat)}.",
        )
    vat = total(group.tax_amount for group in invoice.vat_breakdown)
    if totals.total_vat is not None and totals.total_vat != vat:
        yield _finding(
            "BR-CO-14",
            _at("BT-110"),
            f"Invoice total VAT amount (BT-110) {_fmt(totals.total_vat)} != "
            f"Σ VAT category tax amount (BT-117) {_fmt(vat)}.",
        )
    with_vat = totals.total_without_vat + (totals.total_vat or ZERO)
    if totals.total_with_vat != with_vat:
        yield _finding(
            "BR-CO-15",
            _at("BT-112"),
            f"Invoice total amount with VAT (BT-112) {_fmt(totals.total_with_vat)} != "
            f"BT-109 + BT-110 = {_fmt(with_vat)}.",
        )
    due = totals.total_with_vat - (totals.paid_amount or ZERO) + (totals.rounding_amount or ZERO)
    if totals.amount_due != due:
        yield _finding(
            "BR-CO-16",
            _at("BT-115"),
            f"Amount due for payment (BT-115) {_fmt(totals.amount_due)} != BT-112 - BT-113 + BT-114 = {_fmt(due)}.",
        )
    if invoice.vat_accounting_currency_code is not None and totals.total_vat_in_accounting_currency is None:
        yield _finding(
            "BR-53",
            _at("BT-111"),
            "The VAT accounting currency code (BT-6) is present, so the Invoice total VAT amount in "
            "accounting currency (BT-111) shall be provided.",
        )


def _rates(invoice: Invoice) -> Iterator[Finding]:
    """BR-<x>-05, -06, -07: the VAT rate of each line, document level allowance and charge."""
    items: list[tuple[str, str, str, int, str, Decimal | None]] = [
        ("05", "BT-152", "Invoiced item VAT rate", i, line.vat_information.category_code, line.vat_information.rate)
        for i, line in enumerate(invoice.lines)
    ]
    items += [
        ("06", "BT-96", "Document level allowance VAT rate", i, a.vat_category_code, a.vat_rate)
        for i, a in enumerate(invoice.allowances)
    ]
    items += [
        ("07", "BT-103", "Document level charge VAT rate", i, c.vat_category_code, c.vat_rate)
        for i, c in enumerate(invoice.charges)
    ]
    for suffix, ident, name, index, category, rate in items:
        rules = CATEGORY_RULES.get(category)
        if rules is not None and not rules.rate.accepts(rate):
            yield _finding(
                f"{rules.prefix}-{suffix}",
                _at(ident, index),
                f"{name} ({ident}) must be {rules.rate.value} for VAT category {category} ({rules.name}), "
                f"got {_fmt(rate)}.",
            )


def _taxable_items(invoice: Invoice, category: str, rate: Decimal | None, per_rate: bool) -> list[Decimal]:
    """The signed amounts a ``-08`` rule sums: line net amounts and charges, minus allowances."""

    def matches(item_category: str, item_rate: Decimal | None) -> bool:
        return item_category == category and (not per_rate or item_rate == rate)

    amounts = [
        line.net_amount
        for line in invoice.lines
        if matches(line.vat_information.category_code, line.vat_information.rate)
    ]
    amounts += [charge.amount for charge in invoice.charges if matches(charge.vat_category_code, charge.vat_rate)]
    amounts += [-a.amount for a in invoice.allowances if matches(a.vat_category_code, a.vat_rate)]
    return amounts


def _group(invoice: Invoice, index: int, group: VatBreakdown) -> Iterator[Finding]:
    """BR-48, BR-CO-17 and the category's ``-08``, ``-09``, ``-10`` rules on one VAT breakdown (BG-23)."""
    category, rate, tax = group.category_code, group.rate, group.tax_amount
    if rate is None and category != "O":
        yield _finding(
            "BR-48",
            _at("BT-119", index),
            f"The VAT breakdown of category {category} has no VAT category rate (BT-119); only category O may omit it.",
        )
    # BR-CO-17's three branches: rate rounds to 0, rate present, rate absent (both others need round(tax) = 0)
    if rate is not None and xpath_round(rate) != 0:
        co17 = _vat_in_tolerance(tax, group.taxable_amount, rate)
    else:
        co17 = xpath_round(tax) == 0
    if not co17:
        yield _finding(
            "BR-CO-17",
            _at("BT-117", index),
            f"VAT category tax amount (BT-117) {_fmt(tax)} != VAT category taxable amount (BT-116) "
            f"{_fmt(group.taxable_amount)} * (VAT category rate (BT-119) {_fmt(rate)} / 100), rounded to two "
            "decimals (the rule tolerates a difference below 1).",
        )
    rules = CATEGORY_RULES.get(category)
    if rules is not None:
        yield from _category_group(invoice, index, group, rules)


def _category_group(invoice: Invoice, index: int, group: VatBreakdown, rules: CategoryRules) -> Iterator[Finding]:
    """The ``-08`` (taxable amount), ``-09`` (tax amount) and ``-10`` (exemption reason) rules."""
    category, rate, tax = group.category_code, group.rate, group.tax_amount
    if not (rules.per_rate and rate is None):  # "every $rate in BT-119 satisfies …" is vacuous without a rate
        amounts = _taxable_items(invoice, category, rate, rules.per_rate)
        expected = total(amounts)
        # per rate, the rate must also occur on a line, allowance or charge ("exists(…) and …")
        if group.taxable_amount != expected or (rules.per_rate and not amounts):
            scope = f"category {category} at rate {_fmt(rate)}" if rules.per_rate else f"category {category}"
            yield _finding(
                f"{rules.prefix}-08",
                _at("BT-116", index),
                f"VAT category taxable amount (BT-116) {_fmt(group.taxable_amount)} != Σ BT-131 + Σ BT-99 - Σ BT-92 "
                f"of {scope} = {_fmt(expected)}" + ("." if amounts else " (no line, allowance or charge has it)."),
            )
    # without a rate, the UBL test of S/AF/AG-09 compares with an empty sequence: false
    tax_ok = tax == 0 if rules.zero_tax else rate is not None and _vat_in_tolerance(tax, group.taxable_amount, rate)
    if not tax_ok:
        wanted = "0 (zero)" if rules.zero_tax else "VAT category taxable amount (BT-116) * VAT category rate (BT-119)"
        yield _finding(
            f"{rules.prefix}-09",
            _at("BT-117", index),
            f"The VAT category tax amount (BT-117) of category {category} ({rules.name}) shall equal {wanted}, "
            f"got {_fmt(tax)}.",
        )
    has_reason = group.exemption_reason is not None or group.exemption_reason_code is not None
    if has_reason != rules.needs_reason:
        need = "shall have" if rules.needs_reason else "shall not have"
        yield _finding(
            f"{rules.prefix}-10",
            _at("BT-121" if group.exemption_reason_code is not None else "BT-120", index),
            f"A VAT breakdown with VAT category code {category} ({rules.name}) {need} a VAT exemption reason "
            "code (BT-121) or VAT exemption reason text (BT-120).",
        )


def _presence(invoice: Invoice) -> Iterator[Finding]:
    """BR-<x>-01: a used category has at least one (S, L, M) or exactly one breakdown; an unused one none."""
    used = {line.vat_information.category_code for line in invoice.lines}
    used |= {allowance.vat_category_code for allowance in invoice.allowances}
    used |= {charge.vat_category_code for charge in invoice.charges}
    for category, rules in CATEGORY_RULES.items():
        count = sum(group.category_code == category for group in invoice.vat_breakdown)
        is_used = category in used
        ok = (count > 0) == is_used if rules.per_rate else count == int(is_used)
        if not ok:
            wanted = ("at least one" if rules.per_rate else "exactly one") if is_used else "none"
            yield _finding(
                f"{rules.prefix}-01",
                path_of("BG-23").removesuffix("[]"),
                f"The invoice {'uses' if is_used else 'does not use'} VAT category {category} ({rules.name}) on "
                f"a line, document level allowance or charge and has {count} VAT breakdown(s) (BG-23) of it; it "
                f"needs {wanted}.",
            )


def check(invoice: Invoice) -> tuple[Finding, ...]:
    """Report where the amounts of a complete invoice break the CEN calculation and VAT rules.

    Checked (CEN validation-1.3.16, every rule ``fatal``): BR-CO-10 … BR-CO-17, BR-48, BR-53 and, per
    VAT category code S, Z, E, AE, K, G, O, L and M, the rules ``BR-<x>-01`` (breakdown present),
    ``-05``/``-06``/``-07`` (line, allowance and charge VAT rates), ``-08`` (taxable amount), ``-09``
    (tax amount) and ``-10`` (exemption reason). Where the UBL and CII bindings differ in tolerance,
    the stricter test applies (see :mod:`euinvoice.calc`). The official Schematron stays the oracle
    (D8): this is an early, syntax-free warning, not a replacement for ``validate()``.

    Args:
        invoice: A complete invoice.

    Returns:
        One ``fatal`` :class:`~euinvoice.report.Finding` per broken rule and place, with the official
        rule id, the model path as location (e.g. ``vat_breakdown[0].tax_amount``, see
        :mod:`euinvoice.model.bt_index`) and source ``"calc"``; empty if every rule holds.
    """
    findings = [*_rates(invoice), *_totals(invoice)]
    for index, group in enumerate(invoice.vat_breakdown):
        findings += _group(invoice, index, group)
    findings += _presence(invoice)
    return tuple(findings)
