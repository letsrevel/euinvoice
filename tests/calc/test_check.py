"""``calc.check``: one negative test per CEN rule it reports (validation-1.3.16, all ``fatal``)."""

from decimal import Decimal

import pytest
from _calc_drafts import allowance, charge, draft, group, line, replace, with_breakdown, with_totals

from euinvoice import calc
from euinvoice.model import DocumentLevelAllowance, DocumentLevelCharge, Invoice, LineDraft, VatBreakdown
from euinvoice.report import Severity

E_REASON = {"E": calc.ExemptionReason(code="VATEX-EU-132")}


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


def rule_ids(invoice: Invoice) -> set[str]:
    return {finding.rule_id for finding in calc.check(invoice)}


def test_findings_are_fatal_from_calc_with_a_model_path(invoice: Invoice) -> None:
    broken = with_totals(invoice, amount_due="1.00")

    (finding,) = calc.check(broken)

    assert (finding.rule_id, finding.severity, finding.source, finding.location) == (
        "BR-CO-16",
        Severity.FATAL,
        calc.SOURCE,
        "totals.amount_due",
    )
    assert "BT-115" in finding.message
    assert "1.00" in finding.message


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

    assert rule_ids(broken) == {rule}


def test_absent_allowance_and_charge_sums_are_fine_without_allowances_and_charges() -> None:
    invoice = calc.complete(draft())
    assert invoice.totals.sum_of_allowances is None

    assert calc.check(with_totals(invoice, sum_of_allowances="0.00", sum_of_charges="0.00")) == ()


def test_paid_and_rounding_amounts_enter_the_amount_due(invoice: Invoice) -> None:
    paid = with_totals(invoice, paid_amount="100.00", rounding_amount="0.01", amount_due="88.51")

    assert calc.check(paid) == ()


def test_absent_total_vat_is_not_compared(invoice: Invoice) -> None:
    """BR-CO-14 is a rule on BT-110 itself; without it BR-CO-15 reads BT-112 = BT-109."""
    no_vat_total = with_totals(invoice, total_vat=None, total_with_vat="165.00", amount_due="165.00")

    assert rule_ids(no_vat_total) == set()


def test_br53_vat_accounting_currency_needs_bt111(invoice: Invoice) -> None:
    broken = replace(invoice, vat_accounting_currency_code="SEK")

    assert [(f.rule_id, f.location) for f in calc.check(broken)] == [
        ("BR-53", "totals.total_vat_in_accounting_currency")
    ]
    assert calc.check(with_totals(broken, total_vat_in_accounting_currency="270.00")) == ()


# --- BR-48, BR-CO-17 and the category rules on the VAT breakdown ---------------------------------------


def test_br_co_17_tolerates_a_difference_below_one(invoice: Invoice) -> None:
    off_by_cents = with_breakdown(invoice, (group(0, invoice, tax_amount="18.99"), *invoice.vat_breakdown[1:]))

    assert calc.check(off_by_cents) == ()


def test_br_co_17_and_br_s_09_flag_a_difference_of_one(invoice: Invoice) -> None:
    """UBL tests ``abs(BT-117) + 1 > expected`` strictly, so exactly 1 fails (CII would accept it)."""
    off_by_one = with_breakdown(invoice, (group(0, invoice, tax_amount="19.00"), *invoice.vat_breakdown[1:]))

    findings = calc.check(off_by_one)

    assert {(f.rule_id, f.location) for f in findings} == {
        ("BR-CO-17", "vat_breakdown[0].tax_amount"),
        ("BR-S-09", "vat_breakdown[0].tax_amount"),
    }


def test_br_co_17_rate_rounding_to_zero_needs_tax_rounding_to_zero() -> None:
    """``round(BT-119) = 0`` (rate 0.4) takes BR-CO-17's first branch: ``round(BT-117) = 0``."""
    invoice = calc.complete(draft(line("1", "200", "S", "0.4")))
    assert invoice.vat_breakdown[0].tax_amount == Decimal("0.80")

    assert rule_ids(invoice) == {"BR-CO-17"}  # BR-S-09 alone would accept 0.80
    small = calc.complete(draft(line("1", "100", "S", "0.4")))  # tax 0.40, rounds to 0
    assert calc.check(small) == ()


def test_br48_rate_required_except_category_o(invoice: Invoice) -> None:
    broken = with_breakdown(invoice, (invoice.vat_breakdown[0], group(1, invoice, rate=None), invoice.vat_breakdown[2]))

    assert {(f.rule_id, f.location) for f in calc.check(broken)} == {
        ("BR-48", "vat_breakdown[1].rate"),
        ("BR-CO-17", "vat_breakdown[1].tax_amount"),  # no rate: round(BT-117) must be 0
        ("BR-S-09", "vat_breakdown[1].tax_amount"),
    }


@pytest.mark.parametrize(
    ("index", "changes", "rule", "location"),
    [
        (0, {"taxable_amount": "91.00"}, "BR-S-08", "vat_breakdown[0].taxable_amount"),
        (2, {"taxable_amount": "21.00"}, "BR-E-08", "vat_breakdown[2].taxable_amount"),
        (2, {"tax_amount": "0.01"}, "BR-E-09", "vat_breakdown[2].tax_amount"),
        (2, {"exemption_reason_code": None}, "BR-E-10", "vat_breakdown[2].exemption_reason"),
        (0, {"exemption_reason": "Not exempt"}, "BR-S-10", "vat_breakdown[0].exemption_reason"),
        (0, {"exemption_reason_code": "VATEX-EU-79-C"}, "BR-S-10", "vat_breakdown[0].exemption_reason_code"),
    ],
)
def test_breakdown_category_rules(
    invoice: Invoice, index: int, changes: dict[str, str | None], rule: str, location: str
) -> None:
    groups = list(invoice.vat_breakdown)
    groups[index] = group(index, invoice, **changes)

    assert [(f.rule_id, f.location) for f in calc.check(with_breakdown(invoice, groups))] == [(rule, location)]


def test_per_rate_taxable_amount_needs_a_line_allowance_or_charge_at_that_rate(invoice: Invoice) -> None:
    unused_rate = VatBreakdown(
        taxable_amount=Decimal("0.00"), tax_amount=Decimal("0.00"), category_code="S", rate=Decimal(7)
    )

    findings = calc.check(with_breakdown(invoice, (*invoice.vat_breakdown, unused_rate)))

    assert [(f.rule_id, f.location) for f in findings] == [("BR-S-08", "vat_breakdown[3].taxable_amount")]
    assert "no line, allowance or charge" in findings[0].message


# --- BR-<x>-01 (breakdown present) ----------------------------------------------------------------------


def test_used_category_without_breakdown(invoice: Invoice) -> None:
    findings = calc.check(with_breakdown(invoice, invoice.vat_breakdown[:2]))

    assert [(f.rule_id, f.location) for f in findings] == [("BR-E-01", "vat_breakdown")]


def test_exactly_one_breakdown_for_non_rate_categories(invoice: Invoice) -> None:
    empty_e = VatBreakdown(
        taxable_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        category_code="E",
        rate=Decimal(0),
        exemption_reason="x",
    )

    assert rule_ids(with_breakdown(invoice, (*invoice.vat_breakdown, empty_e))) == {"BR-E-01", "BR-E-08"}


def test_unused_category_with_breakdown(invoice: Invoice) -> None:
    unused_z = VatBreakdown(
        taxable_amount=Decimal("0.00"), tax_amount=Decimal("0.00"), category_code="Z", rate=Decimal(0)
    )

    assert rule_ids(with_breakdown(invoice, (*invoice.vat_breakdown, unused_z))) == {"BR-Z-01"}


def test_unused_per_rate_category_with_breakdown() -> None:
    invoice = calc.complete(draft(line("1", "10", "Z", "0")))
    stray_s = VatBreakdown(
        taxable_amount=Decimal("0.00"), tax_amount=Decimal("0.00"), category_code="S", rate=Decimal(20)
    )

    assert rule_ids(with_breakdown(invoice, (*invoice.vat_breakdown, stray_s))) == {"BR-S-01", "BR-S-08"}


def test_split_payment_has_no_category_rules() -> None:
    """Category B's only CEN rules (BR-B-01/02) concern the country and mixing with S, not amounts."""
    invoice = calc.complete(draft(line("1", "100", "B", "22"), seller_country="IT", buyer_country="IT"))

    assert calc.check(invoice) == ()


# --- BR-<x>-05 / -06 / -07 (rates of lines, allowances and charges) ------------------------------------

REASONS = {c: calc.ExemptionReason(text="Exemption text") for c in ("E", "AE", "K", "G", "O")}
WRONG_RATES = [
    ("S", "BR-S", None),
    ("S", "BR-S", "0"),
    ("L", "BR-AF", "0"),  # UBL accepts >= 0, CII requires > 0: the stricter test applies
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

    assert (f"{prefix}-05", "lines[0].vat_information.rate") in {(f.rule_id, f.location) for f in calc.check(invoice)}


@pytest.mark.parametrize(("category", "prefix", "rate"), WRONG_RATES)
def test_allowance_and_charge_rate_rules(category: str, prefix: str, rate: str | None) -> None:
    invoice = complete_with_reasons(
        line("1", "100", "Z", "0"),
        allowances=(allowance("1.00", category, rate),),
        charges=(charge("2.00", category, rate),),
    )

    located = {(f.rule_id, f.location) for f in calc.check(invoice)}
    assert (f"{prefix}-06", "allowances[0].vat_rate") in located
    assert (f"{prefix}-07", "charges[0].vat_rate") in located


@pytest.mark.parametrize(
    ("category", "rate"), [("S", "20"), ("L", "7"), ("M", "0"), ("Z", "0"), ("E", "0"), ("AE", "0"), ("O", None)]
)
def test_valid_rates_pass(category: str, rate: str | None) -> None:
    assert calc.check(complete_with_reasons(line("1", "100", category, rate))) == ()
