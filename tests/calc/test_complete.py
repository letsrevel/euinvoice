"""``calc.complete``: line net amounts, document totals and the VAT breakdown (D11)."""

from decimal import Decimal

import pydantic
import pytest
from _calc_drafts import allowance, charge, draft, line

from euinvoice import calc
from euinvoice.errors import ModelError
from euinvoice.model import DocumentTotals, LineDraft, VatBreakdown


def dec(value: str) -> Decimal:
    return Decimal(value)


# --- worked example from the CEN artifacts -------------------------------------------------------------


def test_cen_rounding_issue_example_reproduces_its_totals() -> None:
    """``examples/CII-BR-CO-10-RoundingIssue.xml`` (CEN validation-1.3.16, en16931-cii), rebuilt by hand.

    Four lines (quantity, net price, category, rate): (1, 720.81, S, 19.00), (1, 0.01, Z, 0),
    (-1, 720.81, S, 19.00), (-1, 0.01, Z, 0). The file's line totals are 720.81, 0.01, -720.81, -0.01;
    its breakdown is Z 0.00/0.00 at 0 and S 0.00/0.00 at 19.00; its header sums are LineTotal 0.00,
    TaxBasisTotal 0.00, TaxTotal 0.00, GrandTotal 0.00, TotalPrepaid 0 and DuePayable 0.00.
    """
    invoice = calc.complete(
        draft(
            line("1", "720.81", "S", "19.00", identifier="1"),
            line("1", "0.01", "Z", "0", identifier="1"),
            line("-1", "720.81", "S", "19.00", identifier="2"),
            line("-1", "0.01", "Z", "0", identifier="2"),
        ),
        paid_amount=dec("0"),
    )

    assert [ln.net_amount for ln in invoice.lines] == [dec("720.81"), dec("0.01"), dec("-720.81"), dec("-0.01")]
    assert set(invoice.vat_breakdown) == {
        VatBreakdown(taxable_amount=dec("0.00"), tax_amount=dec("0.00"), category_code="Z", rate=dec("0")),
        VatBreakdown(taxable_amount=dec("0.00"), tax_amount=dec("0.00"), category_code="S", rate=dec("19.00")),
    }
    totals = invoice.totals
    assert totals.sum_of_line_net_amounts == dec("0.00")
    # The file states AllowanceTotal and ChargeTotal as 0; complete() leaves them out because there are no
    # document level allowances or charges, which BR-CO-11 / BR-CO-12 accept alike (the sum of none is 0).
    assert totals.sum_of_allowances is None
    assert totals.sum_of_charges is None
    assert totals.total_without_vat == dec("0.00")
    assert totals.total_vat == dec("0.00")
    assert totals.total_with_vat == dec("0.00")
    assert totals.paid_amount == dec("0")
    assert totals.amount_due == dec("0.00")
    assert calc.check(invoice) == ()


# --- BT-131 (Peppol R120 convention) -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ln", "expected"),
    [
        (line("2", "50"), "100.00"),
        (line("3", "0.335"), "1.01"),  # 1.005: a tie, rounded half up
        (line("-3", "0.335"), "-1.01"),  # negative tie: away from zero (D11)
        (line("1", "10", base_quantity="3"), "3.33"),  # price per 3 units
        (line("2", "10", base_quantity="3"), "6.67"),  # 6.666…: the unit price is never rounded first
        (line("5", "1.99", base_quantity="0"), "9.95"),  # base quantity 0 counts as 1 (R120 $baseQuantity)
        (line("1", "100", allowances=("10.00", "5.50"), charges=("2.25",)), "86.75"),
        (line("1", "0.004"), "0.00"),
        (line("1", "0.004999999999999999999999999999999"), "0.00"),  # below a tie, beyond 28 digits
    ],
)
def test_line_net_amount(ln: LineDraft, expected: str) -> None:
    assert calc.line_net_amount(ln) == dec(expected)


def test_line_net_amount_has_two_decimals() -> None:
    assert format(calc.line_net_amount(line("7", "1")), "f") == "7.00"


# --- the consumer scenarios of the plan (§8 10.1), synthetic -------------------------------------------


def test_domestic_austrian_invoice_at_20_percent() -> None:
    invoice = calc.complete(
        draft(line("10", "85.00", identifier="1"), line("1", "149.99", identifier="2")),
        paid_amount=dec("500.00"),
    )

    assert invoice.vat_breakdown == (
        VatBreakdown(taxable_amount=dec("999.99"), tax_amount=dec("200.00"), category_code="S", rate=dec("20")),
    )
    assert invoice.totals == DocumentTotals(
        sum_of_line_net_amounts=dec("999.99"),
        total_without_vat=dec("999.99"),
        total_vat=dec("200.00"),  # 199.998 rounded half up
        total_with_vat=dec("1199.99"),
        paid_amount=dec("500.00"),
        amount_due=dec("699.99"),
    )
    assert calc.check(invoice) == ()


def test_intra_eu_reverse_charge_needs_and_gets_its_exemption_reason() -> None:
    reverse_charge = draft(line("8", "120.00", "AE", "0"), buyer_country="DE")
    reason = calc.ExemptionReason(code="VATEX-EU-AE", text="Reverse charge")

    invoice = calc.complete(reverse_charge, exemption_reasons={"AE": reason})

    assert invoice.vat_breakdown == (
        VatBreakdown(
            taxable_amount=dec("960.00"),
            tax_amount=dec("0.00"),
            category_code="AE",
            rate=dec("0"),
            exemption_reason="Reverse charge",
            exemption_reason_code="VATEX-EU-AE",
        ),
    )
    assert (invoice.totals.total_vat, invoice.totals.amount_due) == (dec("0.00"), dec("960.00"))
    assert calc.check(invoice) == ()
    assert [f.rule_id for f in calc.check(calc.complete(reverse_charge))] == ["BR-AE-10"]


def test_non_eu_service_out_of_scope_has_no_rate() -> None:
    invoice = calc.complete(
        draft(line("1", "2500.00", "O", None), buyer_country="US"),
        exemption_reasons={"O": calc.ExemptionReason(code="VATEX-EU-O", text="Not subject to VAT")},
    )

    (group,) = invoice.vat_breakdown
    assert (group.category_code, group.rate, group.taxable_amount, group.tax_amount) == (
        "O",
        None,
        dec("2500.00"),
        dec("0.00"),
    )
    assert invoice.totals.amount_due == dec("2500.00")
    assert calc.check(invoice) == ()


def test_ticketing_invoice_with_mixed_rates_allowances_and_charges() -> None:
    """Tickets at 13 %, merchandise at 20 %, a voucher on the merchandise and a booking fee at 20 %."""
    invoice = calc.complete(
        draft(
            line("3", "45.87", "S", "13", identifier="1"),  # tickets: 137.61
            line("2", "16.66", "S", "20", identifier="2", allowances=("1.00",)),  # merchandise: 32.32
            line("1", "8.849", "S", "13", identifier="3"),  # child ticket: 8.85
            allowances=(allowance("5.00", "S", "20"),),
            charges=(charge("2.50", "S", "20"),),
        ),
        rounding_amount=dec("0.01"),
    )

    assert invoice.vat_breakdown == (
        VatBreakdown(taxable_amount=dec("146.46"), tax_amount=dec("19.04"), category_code="S", rate=dec("13")),
        VatBreakdown(taxable_amount=dec("29.82"), tax_amount=dec("5.96"), category_code="S", rate=dec("20")),
    )
    assert invoice.totals == DocumentTotals(
        sum_of_line_net_amounts=dec("178.78"),
        sum_of_allowances=dec("5.00"),
        sum_of_charges=dec("2.50"),
        total_without_vat=dec("176.28"),
        total_vat=dec("25.00"),
        total_with_vat=dec("201.28"),
        rounding_amount=dec("0.01"),
        amount_due=dec("201.29"),
    )
    assert calc.check(invoice) == ()


def test_credit_note_with_negative_tie_in_the_vat_amount() -> None:
    """Taxable -0.50 at 1 %: -0.005 rounds away from zero to -0.01 (D11); BR-CO-17 compares |values|."""
    invoice = calc.complete(draft(line("-1", "0.50", "S", "1"), type_code="381"))

    assert invoice.vat_breakdown[0].tax_amount == dec("-0.01")
    assert invoice.totals.amount_due == dec("-0.51")
    assert calc.check(invoice) == ()


# --- inputs calc cannot derive -------------------------------------------------------------------------


def test_vat_total_in_accounting_currency_is_passed_through() -> None:
    invoice = calc.complete(draft(vat_accounting_currency_code="SEK"), vat_total_in_accounting_currency=dec("230.10"))

    assert invoice.totals.total_vat_in_accounting_currency == dec("230.10")
    assert calc.check(invoice) == ()


def test_rates_spelled_differently_form_one_group_keeping_the_first_spelling() -> None:
    invoice = calc.complete(draft(line(rate="20.00", identifier="1"), line(rate="20", identifier="2")))

    (group,) = invoice.vat_breakdown
    assert format(group.rate, "f") == "20.00"
    assert group.taxable_amount == dec("200.00")


def test_breakdown_follows_first_occurrence_order() -> None:
    invoice = calc.complete(
        draft(
            line("1", "10", "Z", "0", identifier="1"),
            line("1", "10", "S", "20", identifier="2"),
            charges=(charge("1.00", "S", "10"),),
        )
    )

    assert [(g.category_code, g.rate) for g in invoice.vat_breakdown] == [
        ("Z", dec("0")),
        ("S", dec("20")),
        ("S", dec("10")),
    ]


def test_exemption_reason_for_an_unused_category_is_refused() -> None:
    with pytest.raises(ModelError, match=r"\['E'\]"):
        calc.complete(draft(), exemption_reasons={"E": calc.ExemptionReason(text="Exempt")})


def test_exemption_reason_needs_text_or_code() -> None:
    with pytest.raises(pydantic.ValidationError, match="BT-120"):
        calc.ExemptionReason()


def test_exemption_reason_code_is_checked_against_vatex() -> None:
    with pytest.raises(pydantic.ValidationError, match="BR-CL-22"):
        calc.ExemptionReason(code="NOT-A-VATEX-CODE")


@pytest.mark.parametrize("bad", [dec("0.001"), 0.5])
def test_arguments_go_through_model_validation(bad: object) -> None:
    with pytest.raises(pydantic.ValidationError):
        calc.complete(draft(), paid_amount=bad)  # type: ignore[arg-type]  # float on purpose (D3)
