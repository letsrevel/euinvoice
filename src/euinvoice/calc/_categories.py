"""The per-VAT-category rules of :func:`check`: ``BR-<x>-01``, ``-05`` … ``-10``, BR-O-11 … 14, BR-B-02.

Each rule is evaluated as the UBL binding (``schematron/UBL/EN16931-UBL-model.sch``) and as the CII
binding (``schematron/CII/EN16931-CII-model.sch``) test it, CEN validation-1.3.16; see the asymmetry
table in :mod:`euinvoice.calc`.
"""

import dataclasses
import enum
import typing as t
from collections.abc import Iterator
from decimal import Decimal
from fractions import Fraction

from euinvoice.calc._common import Verdict, at, fatal, fmt, round_cents, total, verdict
from euinvoice.model import Invoice, VatBreakdown
from euinvoice.model.codes import VatCategory

__all__ = ["CATEGORY_RULES", "CategoryRules", "RateRule", "category_verdicts", "vat_in_tolerance"]


class RateRule(enum.Enum):
    """What a ``-05``/``-06``/``-07`` test requires of BT-152, BT-96 or BT-103."""

    POSITIVE = "greater than zero"
    NOT_NEGATIVE = "zero or greater than zero"
    ZERO = "0 (zero)"
    ABSENT = "absent"

    def accepts(self, rate: Decimal | None) -> bool:
        """Whether ``rate`` passes the test.

        A missing rate fails every rule but ``ABSENT``: XPath compares an empty sequence as false.

        Args:
            rate: The VAT rate, or ``None``.

        Returns:
            ``True`` if the test passes.
        """
        if self is RateRule.ABSENT:
            return rate is None
        if rate is None:
            return False
        if self is RateRule.POSITIVE:
            return rate > 0
        if self is RateRule.NOT_NEGATIVE:
            return rate >= 0
        return rate == 0


@dataclasses.dataclass(frozen=True, slots=True)
class CategoryRules:
    """The CEN rules of one VAT category code (``BR-<prefix>-01`` … ``-10``).

    Attributes:
        prefix: The rule id prefix, e.g. ``BR-S`` for ``S`` or ``BR-IC`` for ``K``.
        name: The category name the rule texts use.
        ubl_rate: The UBL ``-05``/``-06``/``-07`` test.
        cii_rate: The CII ``-05``/``-06``/``-07`` test.
        per_rate: S, L, M: ``-01`` asks for "at least one" breakdown and ``-08`` sums per rate.
            Otherwise ``-01`` asks for "exactly one" and ``-08`` sums the whole category.
        zero_tax: ``-09`` requires BT-117 = 0 (both bindings); otherwise ``-09`` is the ±1 test.
        cii_tax_test: Whether CII tests ``-09`` at all (``true()`` for BR-AF-09 and BR-AG-09).
        needs_reason: ``-10`` requires BT-120 or BT-121; otherwise it forbids both.
    """

    prefix: str
    name: str
    ubl_rate: RateRule
    cii_rate: RateRule
    per_rate: bool
    zero_tax: bool
    cii_tax_test: bool
    needs_reason: bool


_P, _N, _Z, _A = RateRule.POSITIVE, RateRule.NOT_NEGATIVE, RateRule.ZERO, RateRule.ABSENT

CATEGORY_RULES: t.Final[dict[str, CategoryRules]] = {
    VatCategory.STANDARD_RATED: CategoryRules("BR-S", "Standard rated", _P, _P, True, False, True, False),
    VatCategory.ZERO_RATED: CategoryRules("BR-Z", "Zero rated", _Z, _Z, False, True, True, False),
    VatCategory.EXEMPT: CategoryRules("BR-E", "Exempt from VAT", _Z, _Z, False, True, True, True),
    VatCategory.REVERSE_CHARGE: CategoryRules("BR-AE", "Reverse charge", _Z, _Z, False, True, True, True),
    VatCategory.INTRA_COMMUNITY_SUPPLY: CategoryRules(
        "BR-IC", "Intra-community supply", _Z, _Z, False, True, True, True
    ),
    VatCategory.EXPORT_OUTSIDE_EU: CategoryRules("BR-G", "Export outside the EU", _Z, _Z, False, True, True, True),
    VatCategory.NOT_SUBJECT_TO_VAT: CategoryRules("BR-O", "Not subject to VAT", _A, _A, False, True, True, True),
    # BR-AF-05/06/07: UBL "(cbc:Percent) >= 0", CII "ram:RateApplicablePercent > 0"; BR-AF-09: CII true()
    VatCategory.IGIC: CategoryRules("BR-AF", "IGIC", _N, _P, True, False, False, False),
    VatCategory.IPSI: CategoryRules("BR-AG", "IPSI", _N, _N, True, False, False, False),
}
"""The rules of each VAT category code. ``B`` (split payment) has none of these; its rules BR-B-01 (a
domestic Italian invoice, out of calc's scope) and BR-B-02 (no mixing with ``S``) are document rules."""


def vat_in_tolerance(tax: Decimal, taxable: Decimal, rate: Decimal, *, strict: bool) -> bool:
    """The ±1 test of BR-CO-17 and BR-S/AF/AG-09: BT-117 against round(|BT-116| * BT-119 / 100, 2).

    The product is non-negative, so half-up rounding equals XPath ``round()`` here.

    Args:
        tax: BT-117.
        taxable: BT-116.
        rate: BT-119.
        strict: ``|BT-117| - 1 < expected < |BT-117| + 1`` (strict) or with ``<=`` (not strict).

    Returns:
        Whether the test passes.
    """
    expected = round_cents(Fraction(abs(taxable)) * Fraction(rate) / 100)
    if strict:
        return abs(tax) - 1 < expected < abs(tax) + 1
    return abs(tax) - 1 <= expected <= abs(tax) + 1


def _rates(invoice: Invoice) -> Iterator[Verdict]:
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
        if rules is not None:
            yield from verdict(
                f"{rules.prefix}-{suffix}",
                at(ident, index),
                f"{name} ({ident}) must be {rules.cii_rate.value} for VAT category {category} ({rules.name}), "
                f"got {fmt(rate)}.",
                ubl=rules.ubl_rate.accepts(rate),
                cii=rules.cii_rate.accepts(rate),
            )


def _items(
    invoice: Invoice, category: str, rate: Decimal | None, per_rate: bool, *, lines: bool = True
) -> list[Decimal]:
    """The signed amounts a ``-08`` test sums.

    Line net amounts (unless ``lines`` is false) and charges, minus allowances.
    """

    def matches(item_category: str, item_rate: Decimal | None) -> bool:
        return item_category == category and (not per_rate or item_rate == rate)

    amounts = [
        line.net_amount
        for line in invoice.lines
        if lines and matches(line.vat_information.category_code, line.vat_information.rate)
    ]
    amounts += [charge.amount for charge in invoice.charges if matches(charge.vat_category_code, charge.vat_rate)]
    amounts += [-a.amount for a in invoice.allowances if matches(a.vat_category_code, a.vat_rate)]
    return amounts


def _taxable(invoice: Invoice, index: int, group: VatBreakdown, rules: CategoryRules) -> Iterator[Verdict]:
    """``-08``: the taxable amount of a breakdown.

    CII: S/AF/AG and O exact; Z/E/AE/IC/G within 1. UBL: Z/E/AE/IC/G/O exact; AF/AG within 1 (their
    ``exists(//cac:InvoiceLine)`` guard always holds). UBL BR-S-08 reads, by XPath precedence,
    ``(occurs and within 1 of the full sum) or (an allowance or charge has the rate and within 1 of
    charges - allowances)``: its second disjunct is the credit-note branch, whose line sum is empty on
    an invoice (and the invoice-line one on a credit note), so a document-level-only sum also passes.
    """
    category, rate, taxable = group.category_code, group.rate, group.taxable_amount
    if rules.per_rate and rate is None:  # "every $rate in BT-119 satisfies …": vacuous without a rate
        return
    amounts = _items(invoice, category, rate, rules.per_rate)
    expected = total(amounts)
    within_one = abs(taxable - expected) < 1
    if category == VatCategory.STANDARD_RATED:
        document_level = _items(invoice, category, rate, per_rate=True, lines=False)
        ubl = (bool(amounts) and within_one) or (bool(document_level) and abs(taxable - total(document_level)) < 1)
        cii = taxable == expected
    elif rules.per_rate:
        ubl, cii = within_one, taxable == expected
    elif category == VatCategory.NOT_SUBJECT_TO_VAT:
        ubl = cii = taxable == expected
    else:
        ubl, cii = taxable == expected, within_one
    scope = f"category {category} at rate {fmt(rate)}" if rules.per_rate else f"category {category}"
    yield from verdict(
        f"{rules.prefix}-08",
        at("BT-116", index),
        f"VAT category taxable amount (BT-116) {fmt(taxable)} != sum of BT-131 + BT-99 - BT-92 of {scope} = "
        f"{fmt(expected)}" + ("." if amounts else " (no line, allowance or charge has it)."),
        ubl=ubl,
        cii=cii,
    )


def _tax(index: int, group: VatBreakdown, rules: CategoryRules) -> Iterator[Verdict]:
    """``-09``: 0 for Z/E/AE/IC/G/O (both bindings); the strict ±1 test for S/AF/AG (CII: S only)."""
    category, rate, tax = group.category_code, group.rate, group.tax_amount
    if rules.zero_tax:
        ubl = cii = tax == 0
    else:  # without a rate both tests compare with an empty sequence: false
        ubl = rate is not None and vat_in_tolerance(tax, group.taxable_amount, rate, strict=True)
        cii = ubl or not rules.cii_tax_test
    wanted = "0 (zero)" if rules.zero_tax else "VAT category taxable amount (BT-116) * VAT category rate (BT-119)"
    yield from verdict(
        f"{rules.prefix}-09",
        at("BT-117", index),
        f"The VAT category tax amount (BT-117) of category {category} ({rules.name}) shall equal {wanted}, "
        f"got {fmt(tax)}.",
        ubl=ubl,
        cii=cii,
    )


def _reason(index: int, group: VatBreakdown, rules: CategoryRules) -> Iterator[Verdict]:
    """``-10``: the same test in both bindings."""
    if (group.exemption_reason is not None or group.exemption_reason_code is not None) != rules.needs_reason:
        need = "shall have" if rules.needs_reason else "shall not have"
        yield from fatal(
            f"{rules.prefix}-10",
            at("BT-121" if group.exemption_reason_code is not None else "BT-120", index),
            f"A VAT breakdown with VAT category code {group.category_code} ({rules.name}) {need} a VAT "
            "exemption reason code (BT-121) or VAT exemption reason text (BT-120).",
        )


def _presence(invoice: Invoice) -> Iterator[Verdict]:
    """``-01`` with ``n`` = lines, ``a`` = document allowances and charges, ``b`` = breakdowns of the category.

    UBL S/AF/AG: ``(n + a > 0) = (b > 0)``. UBL Z/E/AE/IC/G/O: ``b = 1 or n + a + b = 0`` (its
    ``//cac:TaxCategory`` also matches the breakdown itself). CII S/AF/AG: ``(n = 0 or n + b >= 2) and
    (a = 0 or a + b >= 2)``. CII Z/E/AE/IC/G: ``n + a + b = 0 or (b = 1 and n + a > 0)``. CII O:
    ``b = 0 or (b = 1 and n + a > 0)``.
    """
    for category, rules in CATEGORY_RULES.items():
        n = sum(line.vat_information.category_code == category for line in invoice.lines)
        a = sum(x.vat_category_code == category for x in invoice.allowances)
        a += sum(x.vat_category_code == category for x in invoice.charges)
        b = sum(group.category_code == category for group in invoice.vat_breakdown)
        if rules.per_rate:
            ubl = (n + a > 0) == (b > 0)
            cii = (n == 0 or n + b >= 2) and (a == 0 or a + b >= 2)
        else:
            ubl = b == 1 or n + a + b == 0
            if category == VatCategory.NOT_SUBJECT_TO_VAT:
                cii = b == 0 or (b == 1 and n + a > 0)
            else:
                cii = n + a + b == 0 or (b == 1 and n + a > 0)
        wanted = "at least one" if rules.per_rate else "exactly one"
        yield from verdict(
            f"{rules.prefix}-01",
            at("BG-23"),
            f"VAT category {category} ({rules.name}) is on {n} line(s) and {a} document level allowance(s) or "
            f"charge(s) and has {b} VAT breakdown(s) (BG-23); a used category needs {wanted}, an unused one none.",
            ubl=ubl,
            cii=cii,
        )


def _not_subject_to_vat(invoice: Invoice) -> Iterator[Verdict]:
    """BR-O-11 … BR-O-14: with a category O breakdown, nothing else may carry another category.

    UBL tests each kind separately: other breakdowns (11), lines (12), allowances (13), charges (14),
    and so does every binding for its own kind: fatal per offending item. CII's tests are wider: 11 and 12
    both test ``not(//ram:ApplicableTradeTax[ram:CategoryCode != 'O'])`` (breakdowns and lines), 13 and 14
    both ``not(//ram:CategoryTradeTax[ram:CategoryCode != 'O'])`` (allowances and charges). So each
    offending item also fails its partner rule in CII only (a CII-only verdict at that item).
    """
    o = VatCategory.NOT_SUBJECT_TO_VAT
    if not any(group.category_code == o for group in invoice.vat_breakdown):
        return
    kinds = [
        (
            "BR-O-11",
            "BR-O-12",
            "a VAT breakdown (BG-23)",
            "ram:ApplicableTradeTax",
            [(at("BT-118", i), g.category_code) for i, g in enumerate(invoice.vat_breakdown) if g.category_code != o],
        ),
        (
            "BR-O-12",
            "BR-O-11",
            "an Invoice line (BG-25)",
            "ram:ApplicableTradeTax",
            [
                (at("BT-151", i), ln.vat_information.category_code)
                for i, ln in enumerate(invoice.lines)
                if ln.vat_information.category_code != o
            ],
        ),
        (
            "BR-O-13",
            "BR-O-14",
            "a Document level allowance (BG-20)",
            "ram:CategoryTradeTax",
            [
                (at("BT-95", i), x.vat_category_code)
                for i, x in enumerate(invoice.allowances)
                if x.vat_category_code != o
            ],
        ),
        (
            "BR-O-14",
            "BR-O-13",
            "a Document level charge (BG-21)",
            "ram:CategoryTradeTax",
            [(at("BT-102", i), x.vat_category_code) for i, x in enumerate(invoice.charges) if x.vat_category_code != o],
        ),
    ]
    for rule, partner, what, element, offenders in kinds:
        for location, category in offenders:
            yield from fatal(
                rule,
                location,
                f"An Invoice with a VAT breakdown of category O (Not subject to VAT) shall not contain {what} "
                f"of another VAT category, here {category}.",
            )
            yield from verdict(
                partner,
                location,
                f"CII's {partner} tests every {element} for a category other than O, so it also rejects {what} "
                f"of category {category} when there is a VAT breakdown of category O.",
                ubl=True,
                cii=False,
            )


def _split_payment(invoice: Invoice) -> Iterator[Verdict]:
    """BR-B-02: no ``S`` anywhere when ``B`` is used (the same test in both bindings)."""
    categories = [(at("BT-151", i), ln.vat_information.category_code) for i, ln in enumerate(invoice.lines)]
    categories += [(at("BT-95", i), x.vat_category_code) for i, x in enumerate(invoice.allowances)]
    categories += [(at("BT-102", i), x.vat_category_code) for i, x in enumerate(invoice.charges)]
    categories += [(at("BT-118", i), g.category_code) for i, g in enumerate(invoice.vat_breakdown)]
    if any(code == VatCategory.SPLIT_PAYMENT for _, code in categories):
        for location, code in categories:
            if code == VatCategory.STANDARD_RATED:
                yield from fatal(
                    "BR-B-02",
                    location,
                    "An Invoice with VAT category code B (Split payment) shall not contain a line, allowance, "
                    "charge or VAT breakdown with VAT category code S (Standard rated).",
                )


def category_verdicts(invoice: Invoice) -> Iterator[Verdict]:
    """Every per-category rule, in document order: rates, breakdowns, presence, O and B rules.

    Args:
        invoice: A complete invoice.

    Yields:
        The verdicts of the rules that fail in at least one binding.
    """
    yield from _rates(invoice)
    for index, group in enumerate(invoice.vat_breakdown):
        rules = CATEGORY_RULES.get(group.category_code)
        if rules is not None:
            yield from _taxable(invoice, index, group, rules)
            yield from _tax(index, group, rules)
            yield from _reason(index, group, rules)
    yield from _presence(invoice)
    yield from _not_subject_to_vat(invoice)
    yield from _split_payment(invoice)
