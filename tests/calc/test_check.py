"""``calc.check``: one negative test per CEN rule and per UBL/CII asymmetry (validation-1.3.16).

Outcomes are written as the rule id for a fatal finding and ``~RULE@BINDING`` for a portability
warning (only BINDING rejects RULE).
"""

from decimal import Decimal

import pytest

from _calc_drafts import allowance, charge, draft, group, line, replace, with_breakdown, with_totals
from euinvoice import calc
from euinvoice.model import DocumentLevelAllowance, DocumentLevelCharge, Invoice, LineDraft, VatBreakdown
from euinvoice.report import Finding, Severity
from euinvoice.syntax import Syntax

E_REASON = {"E": calc.ExemptionReason(code="VATEX-EU-132")}
O_REASON = {"O": calc.ExemptionReason(code="VATEX-EU-O")}


@pytest.fixture
def invoice() -> Invoice:
    """S 20 % 100.00 - allowance 10.00, S 10 % 50.00 + charge 5.00, E 20.00.

    Breakdown: S 20 90.00/18.00, S 10 55.00/5.50, E 20.00/0.00. Totals: BT-106 170.00, BT-107 10.00,
    BT-108 5.00, BT-109 165.00, BT-110 23.50, BT-112 188.50, BT-115 188.50.
    """
    result = calc.complete(
        draft(
            line("1", "100", "S", "20", identifier="1"),
            line("1", "50", "S", "10", identifier="2"),
            line("1", "20", "E", "0", identifier="3"),
            allowances=(allowance("10.00", "S", "20"),),
            charges=(charge("5.00", "S", "10"),),
        ),
        exemption_reasons=E_REASON,
    )
    assert calc.check(result) == ()
    assert result.totals.total_with_vat == Decimal("188.50")
    return result


def outcome(finding: Finding) -> str:
    """``BR-x`` for a fatal finding, ``~BR-x@UBL`` / ``~BR-x@CII`` for a portability warning."""
    assert finding.source == calc.SOURCE
    if finding.severity is Severity.FATAL:
        return finding.rule_id
    assert (finding.rule_id, finding.severity) == (calc.PORTABILITY, Severity.WARNING)
    rule, rest = finding.message.split(" fails in the ", 1)
    return f"~{rule}@{rest.split()[0]}"


def outcomes(invoice: Invoice) -> set[str]:
    return {outcome(finding) for finding in calc.check(invoice)}


def located(invoice: Invoice) -> set[tuple[str, str | None]]:
    return {(outcome(finding), finding.location) for finding in calc.check(invoice)}


def breakdown(category: str, rate: str | None, taxable: str = "0.00", tax: str = "0.00", **kw: str) -> VatBreakdown:
    return VatBreakdown(
        taxable_amount=Decimal(taxable),
        tax_amount=Decimal(tax),
        category_code=category,
        rate=None if rate is None else Decimal(rate),
        **kw,
    )


def test_fatal_findings_carry_rule_id_model_path_and_values(invoice: Invoice) -> None:
    (finding,) = calc.check(with_totals(invoice, amount_due="1.00"))

    assert (finding.rule_id, finding.severity, finding.source, finding.location) == (
        "BR-CO-16",
        Severity.FATAL,
        calc.SOURCE,
        "totals.amount_due",
    )
    assert "BT-115" in finding.message
    assert "1.00" in finding.message


def test_portability_warning_names_rule_and_rejecting_binding(invoice: Invoice) -> None:
    (finding,) = calc.check(with_totals(invoice, total_vat=None, total_with_vat="165.00", amount_due="165.00"))

    assert (finding.rule_id, finding.severity, finding.location) == (
        "EUINV-CALC-PORTABILITY",
        Severity.WARNING,
        "totals.total_with_vat",
    )
    assert finding.message.startswith("BR-CO-15 fails in the UBL binding only (schematron/UBL/EN16931-UBL-model.sch)")
    assert "the CII binding's test accepts it." in finding.message


# --- BR-CO-10 … BR-CO-16, BR-53 (document totals) -----------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "rule"),
    [
        ({"sum_of_line_net_amounts": "171.00", "total_without_vat": "166.00"}, "BR-CO-10"),
        ({"sum_of_allowances": "11.00", "total_without_vat": "164.00"}, "BR-CO-11"),
        ({"sum_of_allowances": None, "total_without_vat": "175.00"}, "BR-CO-11"),
        ({"sum_of_charges": "6.00", "total_without_vat": "166.00"}, "BR-CO-12"),
        ({"sum_of_charges": None, "total_without_vat": "160.00"}, "BR-CO-12"),
        ({"total_without_vat": "166.00"}, "BR-CO-13"),
        ({"total_vat": "23.51", "total_with_vat": "188.51", "amount_due": "188.51"}, "BR-CO-14"),
        ({"total_with_vat": "188.51", "amount_due": "188.51"}, "BR-CO-15"),
        ({"amount_due": "188.00"}, "BR-CO-16"),
        ({"paid_amount": "100.00"}, "BR-CO-16"),
        ({"rounding_amount": "0.01"}, "BR-CO-16"),
    ],
)
def test_document_total_rules(invoice: Invoice, changes: dict[str, str | None], rule: str) -> None:
    broken = with_totals(invoice, **changes)
    if "total_without_vat" in changes:  # keep BR-CO-15 / BR-CO-16 consistent with the changed BT-109
        with_vat = broken.totals.total_without_vat + Decimal("23.50")
        broken = with_totals(broken, total_with_vat=str(with_vat), amount_due=str(with_vat))

    assert outcomes(broken) == {rule}


def test_absent_allowance_and_charge_sums_are_fine_without_allowances_and_charges() -> None:
    invoice = calc.complete(draft())
    assert invoice.totals.sum_of_allowances is None

    assert calc.check(with_totals(invoice, sum_of_allowances="0.00", sum_of_charges="0.00")) == ()


def test_paid_and_rounding_amounts_enter_the_amount_due(invoice: Invoice) -> None:
    paid = with_totals(invoice, paid_amount="100.00", rounding_amount="0.01", amount_due="88.51")

    assert calc.check(paid) == ()


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        # BT-110 absent: UBL needs exactly one cbc:TaxAmount; CII's 2nd disjunct accepts BT-112 = BT-109
        ({"total_vat": None, "total_with_vat": "165.00", "amount_due": "165.00"}, {"~BR-CO-15@UBL"}),
        ({"total_vat": None}, {"BR-CO-15"}),  # BT-112 188.50 != BT-109: CII rejects too
        # BT-110 present but left out of BT-112: CII's 2nd disjunct still accepts it
        ({"total_with_vat": "165.00", "amount_due": "165.00"}, {"~BR-CO-15@UBL"}),
    ],
)
def test_br_co_15_binding_asymmetry(invoice: Invoice, changes: dict[str, str | None], expected: set[str]) -> None:
    assert outcomes(with_totals(invoice, **changes)) == expected


BT111 = "totals.total_vat_in_accounting_currency"
BT112 = "totals.total_with_vat"


@pytest.mark.parametrize(
    ("currency", "bt111", "expected"),
    [
        ("SEK", None, {("BR-53", BT111)}),  # no amount in BT-6 in either syntax
        ("SEK", "270.00", set()),
        # BT-6 = BT-5 with BT-111: UBL finds an amount in BT-6, so BR-53 is CII-only; two VAT totals in
        # EUR break BR-CO-15 in UBL and the first CII disjunct, and BT-112 != BT-109 fails the second
        ("EUR", "23.50", {("~BR-53@CII", BT111), ("BR-CO-15", BT112)}),
        ("EUR", None, {("~BR-53@CII", BT111)}),  # UBL finds BT-110 in EUR; CII refuses BT-6 = BT-5
    ],
)
def test_br53_vat_accounting_currency(
    invoice: Invoice, currency: str, bt111: str | None, expected: set[tuple[str, str]]
) -> None:
    with_bt6 = with_totals(
        replace(invoice, vat_accounting_currency_code=currency), total_vat_in_accounting_currency=bt111
    )

    assert located(with_bt6) == expected


def test_second_vat_total_in_bt5_passes_cii_br_co_15_only_through_bt112_equal_bt109(invoice: Invoice) -> None:
    same = with_totals(
        replace(invoice, vat_accounting_currency_code="EUR"),
        total_vat_in_accounting_currency="23.50",
        total_with_vat="165.00",
        amount_due="165.00",
    )

    assert located(same) == {("~BR-53@CII", BT111), ("~BR-CO-15@UBL", BT112)}


# --- BR-48, BR-CO-17, -09 -------------------------------------------------------------------------------


def test_br_co_17_tolerates_a_difference_below_one(invoice: Invoice) -> None:
    off_by_cents = with_breakdown(invoice, (group(0, invoice, tax_amount="18.99"), *invoice.vat_breakdown[1:]))

    assert calc.check(off_by_cents) == ()


def test_difference_of_exactly_one_on_standard_rate(invoice: Invoice) -> None:
    """UBL BR-CO-17 is strict, CII's uses <=: a portability warning. BR-S-09 is strict in both: fatal."""
    off_by_one = with_breakdown(invoice, (group(0, invoice, tax_amount="19.00"), *invoice.vat_breakdown[1:]))

    assert located(off_by_one) == {
        ("~BR-CO-17@UBL", "vat_breakdown[0].tax_amount"),
        ("BR-S-09", "vat_breakdown[0].tax_amount"),
    }


@pytest.mark.parametrize(
    ("category", "prefix", "tax", "expected"),
    [
        ("L", "BR-AF", "8.00", {"~BR-CO-17@UBL", "~BR-AF-09@UBL"}),  # 7.00 + 1: CII BR-AF-09 is true()
        # CII never runs BR-CO-17 on an L or M breakdown ($VATAF/$VATAG shadow $VAT_breakdown)
        ("L", "BR-AF", "12.00", {"~BR-CO-17@UBL", "~BR-AF-09@UBL"}),
        ("M", "BR-AG", "12.00", {"~BR-CO-17@UBL", "~BR-AG-09@UBL"}),
    ],
)
def test_igic_and_ipsi_tax_amount(category: str, prefix: str, tax: str, expected: set[str]) -> None:
    invoice = calc.complete(draft(line("1", "100", category, "7")))
    assert invoice.vat_breakdown[0].tax_amount == Decimal("7.00")

    assert outcomes(with_breakdown(invoice, (group(0, invoice, tax_amount=tax),))) == expected


def test_br_co_17_rate_rounding_to_zero_needs_tax_rounding_to_zero() -> None:
    """``round(BT-119) = 0`` (rate 0.4) takes BR-CO-17's first branch: ``round(BT-117) = 0``."""
    invoice = calc.complete(draft(line("1", "200", "S", "0.4")))
    assert invoice.vat_breakdown[0].tax_amount == Decimal("0.80")

    assert outcomes(invoice) == {"BR-CO-17"}  # BR-S-09 alone would accept 0.80
    assert calc.check(calc.complete(draft(line("1", "100", "S", "0.4")))) == ()  # tax 0.40 rounds to 0


def test_br48_rate_required_except_category_o(invoice: Invoice) -> None:
    broken = with_breakdown(invoice, (invoice.vat_breakdown[0], group(1, invoice, rate=None), invoice.vat_breakdown[2]))

    assert located(broken) == {
        ("BR-48", "vat_breakdown[1].rate"),
        ("BR-CO-17", "vat_breakdown[1].tax_amount"),  # no rate: round(BT-117) must be 0
        ("BR-S-09", "vat_breakdown[1].tax_amount"),
    }


# --- -08, -09, -10 on the VAT breakdown -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("index", "changes", "expected", "location"),
    [
        (0, {"taxable_amount": "91.00"}, "BR-S-08", "vat_breakdown[0].taxable_amount"),
        (0, {"taxable_amount": "90.50"}, "~BR-S-08@CII", "vat_breakdown[0].taxable_amount"),  # UBL: within 1
        (2, {"taxable_amount": "21.00"}, "BR-E-08", "vat_breakdown[2].taxable_amount"),
        (2, {"taxable_amount": "20.50"}, "~BR-E-08@UBL", "vat_breakdown[2].taxable_amount"),  # CII: within 1
        (2, {"tax_amount": "0.01"}, "BR-E-09", "vat_breakdown[2].tax_amount"),
        (2, {"exemption_reason_code": None}, "BR-E-10", "vat_breakdown[2].exemption_reason"),
        (0, {"exemption_reason": "Not exempt"}, "BR-S-10", "vat_breakdown[0].exemption_reason"),
        (0, {"exemption_reason_code": "VATEX-EU-79-C"}, "BR-S-10", "vat_breakdown[0].exemption_reason_code"),
    ],
)
def test_breakdown_category_rules(
    invoice: Invoice, index: int, changes: dict[str, str | None], expected: str, location: str
) -> None:
    groups = list(invoice.vat_breakdown)
    groups[index] = group(index, invoice, **changes)

    assert located(with_breakdown(invoice, groups)) == {(expected, location)}


@pytest.mark.parametrize(("taxable", "expected"), [("100.50", "BR-O-08"), ("101.00", "BR-O-08")])
def test_not_subject_to_vat_taxable_amount_is_exact_in_both_bindings(taxable: str, expected: str) -> None:
    invoice = calc.complete(draft(line("1", "100", "O", None)), exemption_reasons=O_REASON)

    assert outcomes(with_breakdown(invoice, (group(0, invoice, taxable_amount=taxable),))) == {expected}


@pytest.mark.parametrize(
    ("taxable", "tax", "expected"),
    [
        ("0.00", "0.00", {"~BR-S-08@UBL"}),  # UBL needs an item at that rate; CII sums nothing to 0
        ("5.00", "0.35", {"BR-S-08"}),
    ],
)
def test_per_rate_taxable_amount_without_items_at_that_rate(
    invoice: Invoice, taxable: str, tax: str, expected: set[str]
) -> None:
    unused_rate = breakdown("S", "7", taxable, tax)

    findings = calc.check(with_breakdown(invoice, (*invoice.vat_breakdown, unused_rate)))

    assert {outcome(f) for f in findings} == expected
    assert findings[0].location == "vat_breakdown[3].taxable_amount"
    assert "no line, allowance or charge" in findings[0].message


# --- BR-<x>-01 (breakdown present) ----------------------------------------------------------------------


def test_used_category_without_breakdown(invoice: Invoice) -> None:
    assert located(with_breakdown(invoice, invoice.vat_breakdown[:2])) == {("BR-E-01", "vat_breakdown")}


def test_two_breakdowns_of_a_non_rate_category(invoice: Invoice) -> None:
    empty_e = breakdown("E", "0", exemption_reason="x")

    assert outcomes(with_breakdown(invoice, (*invoice.vat_breakdown, empty_e))) == {"BR-E-01", "BR-E-08"}


def test_lone_breakdown_of_an_unused_category(invoice: Invoice) -> None:
    """UBL's ``//cac:TaxCategory`` also matches the breakdown itself, so only CII rejects it."""
    assert outcomes(with_breakdown(invoice, (*invoice.vat_breakdown, breakdown("Z", "0")))) == {"~BR-Z-01@CII"}
    two = (*invoice.vat_breakdown, breakdown("Z", "0"), breakdown("Z", "0"))
    assert outcomes(with_breakdown(invoice, two)) == {"BR-Z-01"}


def test_breakdown_of_an_unused_per_rate_category() -> None:
    invoice = calc.complete(draft(line("1", "10", "Z", "0")))

    assert outcomes(with_breakdown(invoice, (*invoice.vat_breakdown, breakdown("S", "20")))) == {
        "~BR-S-01@UBL",  # CII S-01 only constrains used categories
        "~BR-S-08@UBL",
    }


@pytest.mark.parametrize(("lines", "expected"), [(1, {"BR-S-01"}), (2, {"~BR-S-01@UBL"})])
def test_standard_rated_lines_without_breakdown(lines: int, expected: set[str]) -> None:
    """CII S-01 counts lines and breakdowns together: two S lines pass it without an S breakdown."""
    s_lines = [line("1", "10", "S", "20", identifier=str(i)) for i in range(lines)]
    invoice = calc.complete(draft(*s_lines, line("1", "10", "Z", "0", identifier="z")))

    assert outcomes(with_breakdown(invoice, invoice.vat_breakdown[1:])) == expected


def test_not_subject_to_vat_items_without_breakdown() -> None:
    """CII O-01 only constrains an existing O breakdown."""
    invoice = calc.complete(draft(line("1", "10", "Z", "0"), allowances=(allowance("1.00", "O", None),)))
    z_only = tuple(g for g in invoice.vat_breakdown if g.category_code == "Z")

    assert outcomes(with_breakdown(invoice, z_only)) == {"~BR-O-01@UBL"}


# --- BR-O-11 … BR-O-14, BR-B-02 ------------------------------------------------------------------------


def test_not_subject_to_vat_with_another_category_on_a_line() -> None:
    invoice = calc.complete(
        draft(line("1", "100", "O", None, identifier="1"), line("1", "10", "S", "20", identifier="2")),
        exemption_reasons=O_REASON,
    )

    assert located(invoice) == {
        ("BR-O-11", "vat_breakdown[1].category_code"),
        ("~BR-O-12@CII", "vat_breakdown[1].category_code"),  # CII 12 tests every ram:ApplicableTradeTax
        ("BR-O-12", "lines[1].vat_information.category_code"),
        ("~BR-O-11@CII", "lines[1].vat_information.category_code"),
    }
    assert {(f.rule_id, f.location) for f in calc.check(invoice, syntax=Syntax.CII)} == {
        ("BR-O-11", "vat_breakdown[1].category_code"),
        ("BR-O-12", "vat_breakdown[1].category_code"),
        ("BR-O-12", "lines[1].vat_information.category_code"),
        ("BR-O-11", "lines[1].vat_information.category_code"),
    }


def test_not_subject_to_vat_with_another_category_on_an_allowance() -> None:
    """UBL tests allowances (13) and charges (14) apart; CII's 13 and 14 both test either."""
    invoice = calc.complete(
        draft(line("1", "100", "O", None), allowances=(allowance("1.00", "S", "20"),)), exemption_reasons=O_REASON
    )

    assert located(invoice) == {
        ("BR-O-11", "vat_breakdown[1].category_code"),
        ("~BR-O-12@CII", "vat_breakdown[1].category_code"),
        ("BR-O-13", "allowances[0].vat_category_code"),
        ("~BR-O-14@CII", "allowances[0].vat_category_code"),
    }
    assert {f.rule_id for f in calc.check(invoice, syntax=Syntax.UBL)} == {"BR-O-11", "BR-O-13"}


def test_not_subject_to_vat_with_another_category_on_a_charge() -> None:
    invoice = calc.complete(
        draft(line("1", "100", "O", None), charges=(charge("1.00", "Z", "0"),)), exemption_reasons=O_REASON
    )

    assert outcomes(invoice) == {"BR-O-11", "~BR-O-12@CII", "BR-O-14", "~BR-O-13@CII"}
    assert {f.rule_id for f in calc.check(invoice, syntax=Syntax.CII)} == {"BR-O-11", "BR-O-12", "BR-O-13", "BR-O-14"}


def test_split_payment_alone_passes() -> None:
    """BR-B-01 (domestic Italian invoice) is out of calc's scope; B has no amount rules."""
    invoice = calc.complete(draft(line("1", "100", "B", "22"), seller_country="IT", buyer_country="IT"))

    assert calc.check(invoice) == ()


def test_split_payment_with_standard_rated() -> None:
    invoice = calc.complete(
        draft(line("1", "100", "B", "22", identifier="1"), line("1", "10", "S", "22", identifier="2"))
    )

    assert located(invoice) == {
        ("BR-B-02", "lines[1].vat_information.category_code"),
        ("BR-B-02", "vat_breakdown[1].category_code"),
    }


# --- BR-<x>-05 / -06 / -07 (rates of lines, allowances and charges) ------------------------------------

REASONS = {c: calc.ExemptionReason(text="Exemption text") for c in ("E", "AE", "K", "G", "O")}
WRONG_RATES = [
    ("S", "BR-S", None),
    ("S", "BR-S", "0"),
    ("L", "BR-AF", "-1"),
    ("L", "BR-AF", None),
    ("M", "BR-AG", "-1"),
    ("M", "BR-AG", None),
    ("Z", "BR-Z", "5"),
    ("E", "BR-E", "5"),
    ("AE", "BR-AE", None),
    ("K", "BR-IC", "5"),
    ("G", "BR-G", "5"),
    ("O", "BR-O", "0"),
]


def complete_with_reasons(
    *lines: LineDraft,
    allowances: tuple[DocumentLevelAllowance, ...] = (),
    charges: tuple[DocumentLevelCharge, ...] = (),
) -> Invoice:
    built = draft(*lines, allowances=allowances, charges=charges)
    used = {ln.vat_information.category_code for ln in built.lines}
    used |= {a.vat_category_code for a in built.allowances} | {c.vat_category_code for c in built.charges}
    return calc.complete(built, exemption_reasons={c: r for c, r in REASONS.items() if c in used})


@pytest.mark.parametrize(("category", "prefix", "rate"), WRONG_RATES)
def test_line_rate_rules(category: str, prefix: str, rate: str | None) -> None:
    invoice = complete_with_reasons(line("1", "100", category, rate))

    assert (f"{prefix}-05", "lines[0].vat_information.rate") in located(invoice)


@pytest.mark.parametrize(("category", "prefix", "rate"), WRONG_RATES)
def test_allowance_and_charge_rate_rules(category: str, prefix: str, rate: str | None) -> None:
    invoice = complete_with_reasons(
        line("1", "100", category, rate),
        allowances=(allowance("1.00", category, rate),),
        charges=(charge("2.00", category, rate),),
    )

    assert {(f"{prefix}-06", "allowances[0].vat_rate"), (f"{prefix}-07", "charges[0].vat_rate")} <= located(invoice)


def test_igic_rate_zero_is_rejected_by_cii_only() -> None:
    """BR-AF-05/06/07: UBL ``(cbc:Percent) >= 0``, CII ``RateApplicablePercent > 0``."""
    invoice = complete_with_reasons(
        line("1", "100", "L", "0"), allowances=(allowance("1.00", "L", "0"),), charges=(charge("2.00", "L", "0"),)
    )

    assert located(invoice) == {
        ("~BR-AF-05@CII", "lines[0].vat_information.rate"),
        ("~BR-AF-06@CII", "allowances[0].vat_rate"),
        ("~BR-AF-07@CII", "charges[0].vat_rate"),
    }


@pytest.mark.parametrize(
    ("category", "rate"), [("S", "20"), ("L", "7"), ("M", "0"), ("Z", "0"), ("E", "0"), ("AE", "0"), ("O", None)]
)
def test_valid_rates_pass(category: str, rate: str | None) -> None:
    assert calc.check(complete_with_reasons(line("1", "100", category, rate))) == ()


# --- round 2 regressions: UBL -08 branches, target syntax ---------------------------------------------


def test_standard_rated_taxable_equal_to_document_level_amounts_passes_ubl_only(invoice: Invoice) -> None:
    """UBL BR-S-08's second disjunct accepts BT-116 = charges - allowances at the rate (CEN example3 shape)."""
    groups = list(invoice.vat_breakdown)
    groups[1] = group(1, invoice, taxable_amount="5.00", tax_amount="0.50")  # the 5.00 charge at 10 %

    assert located(with_breakdown(invoice, groups)) == {("~BR-S-08@CII", "vat_breakdown[1].taxable_amount")}


@pytest.mark.parametrize("category", ["L", "M"])
def test_igic_ipsi_breakdown_at_an_unused_rate_passes(category: str) -> None:
    """UBL BR-AF-08 / BR-AG-08 have no "the rate occurs on an item" condition, CII sums nothing to 0."""
    invoice = calc.complete(draft(line("1", "100", category, "7")))

    assert calc.check(with_breakdown(invoice, (*invoice.vat_breakdown, breakdown(category, "3")))) == ()


@pytest.mark.parametrize(
    ("changes", "ubl", "cii"),
    [
        ({"total_vat": None, "total_with_vat": "165.00", "amount_due": "165.00"}, {"BR-CO-15"}, set()),
        ({"total_with_vat": "188.51", "amount_due": "188.51"}, {"BR-CO-15"}, {"BR-CO-15"}),
    ],
)
def test_target_syntax_reports_that_bindings_verdict_as_fatal(
    invoice: Invoice, changes: dict[str, str | None], ubl: set[str], cii: set[str]
) -> None:
    broken = with_totals(invoice, **changes)

    for syntax, expected in ((Syntax.UBL, ubl), (Syntax.CII, cii)):
        findings = calc.check(broken, syntax=syntax)
        assert {f.rule_id for f in findings} == expected
        assert all(f.severity is Severity.FATAL for f in findings)


def test_target_syntax_ignores_the_other_bindings_rejections(invoice: Invoice) -> None:
    lone_z = with_breakdown(invoice, (*invoice.vat_breakdown, breakdown("Z", "0")))  # CII-only BR-Z-01
    assert outcomes(lone_z) == {"~BR-Z-01@CII"}

    assert calc.check(lone_z, syntax=Syntax.UBL) == ()
    assert [(f.rule_id, f.severity, f.location) for f in calc.check(lone_z, syntax=Syntax.CII)] == [
        ("BR-Z-01", Severity.FATAL, "vat_breakdown")
    ]


@pytest.mark.parametrize("category", ["L", "M"])
def test_cii_never_runs_the_breakdown_rules_on_igic_and_ipsi(category: str) -> None:
    """``$VATAF`` / ``$VATAG`` match the same node as ``$VAT_breakdown`` first: BR-48 is UBL-only here."""
    invoice = calc.complete(draft(line("1", "100", category, "7")))
    no_rate = with_breakdown(invoice, (group(0, invoice, rate=None, tax_amount="0.00"),))

    assert "~BR-48@UBL" in outcomes(no_rate)


def test_syntax_given_as_its_value_selects_that_binding() -> None:
    invoice = calc.complete(draft(line("1", "10", "Z", "0")))
    lone_s = with_breakdown(invoice, (*invoice.vat_breakdown, breakdown("S", "20")))  # UBL-only BR-S-01/08
    assert calc.check(lone_s, syntax=Syntax.UBL)

    assert calc.check(lone_s, syntax="ubl") == calc.check(lone_s, syntax=Syntax.UBL)  # type: ignore[arg-type]
    assert calc.check(lone_s, syntax="cii") == calc.check(lone_s, syntax=Syntax.CII) == ()  # type: ignore[arg-type]


def test_invalid_syntax_is_refused(invoice: Invoice) -> None:
    with pytest.raises(ValueError, match="pdf"):
        calc.check(invoice, syntax="pdf")  # type: ignore[arg-type]
