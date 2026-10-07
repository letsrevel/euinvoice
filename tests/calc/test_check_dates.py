"""``calc.check``: the period rules BR-29, BR-CO-19 (BG-14) and BR-30, BR-CO-20 (BG-26), CEN 1.3.16."""

import datetime

import pytest

from _calc_drafts import draft, line
from euinvoice import calc
from euinvoice.model import DeliveryInformation, Invoice, InvoiceLinePeriod, InvoicingPeriod, LineDraft
from euinvoice.report import Severity
from euinvoice.syntax import Syntax

JAN = datetime.date(2026, 1, 1)
FEB = datetime.date(2026, 2, 1)


def dated(line_draft: LineDraft, start: datetime.date | None, end: datetime.date | None) -> LineDraft:
    return LineDraft.model_validate({**dict(line_draft), "period": InvoiceLinePeriod(start_date=start, end_date=end)})


def invoice(
    start: datetime.date | None = None,
    end: datetime.date | None = None,
    *,
    period: bool = True,
    code: str | None = None,
    lines: tuple[LineDraft, ...] = (),
    type_code: str = "380",
) -> Invoice:
    delivery = DeliveryInformation(invoicing_period=InvoicingPeriod(start_date=start, end_date=end)) if period else None
    return calc.complete(draft(*lines, delivery=delivery, vat_point_date_code=code, type_code=type_code))


def ids(found: Invoice, syntax: Syntax | None = None) -> set[tuple[str, Severity, str | None]]:
    return {(f.rule_id, f.severity, f.location) for f in calc.check(found, syntax=syntax)}


@pytest.mark.parametrize(
    ("start", "end"),
    [(JAN, FEB), (JAN, JAN), (JAN, None), (None, FEB)],
)
def test_a_dated_invoicing_period_passes(start: datetime.date | None, end: datetime.date | None) -> None:
    assert calc.check(invoice(start, end)) == ()


def test_no_invoicing_period_passes() -> None:
    assert calc.check(invoice(period=False, code="3")) == ()


def test_br_29_end_before_start_is_fatal_in_both_bindings() -> None:
    found = invoice(FEB, JAN)

    (finding,) = calc.check(found)
    assert (finding.rule_id, finding.severity, finding.location) == (
        "BR-29",
        Severity.FATAL,
        "delivery.invoicing_period.end_date",
    )
    assert "BT-74" in finding.message
    assert "2026-01-01" in finding.message
    assert "2026-02-01" in finding.message
    for syntax in (Syntax.UBL, Syntax.CII):
        assert ids(found, syntax) == {("BR-29", Severity.FATAL, "delivery.invoicing_period.end_date")}


def test_br_co_19_empty_invoicing_period_is_fatal_in_both_bindings() -> None:
    found = invoice()

    assert ids(found) == {("BR-CO-19", Severity.FATAL, "delivery.invoicing_period")}
    for syntax in (Syntax.UBL, Syntax.CII):
        assert ids(found, syntax) == {("BR-CO-19", Severity.FATAL, "delivery.invoicing_period")}


def test_br_co_19_ubl_accepts_an_empty_period_with_bt_8() -> None:
    """UBL BR-CO-19 also accepts ``cbc:DescriptionCode`` (BT-8) in ``cac:InvoicePeriod``; CII has no BT-8 there."""
    found = invoice(code="3")

    (finding,) = calc.check(found)
    assert (finding.rule_id, finding.severity, finding.location) == (
        calc.PORTABILITY,
        Severity.WARNING,
        "delivery.invoicing_period",
    )
    assert finding.message.startswith("BR-CO-19 fails in the CII binding only ")
    assert ids(found, Syntax.UBL) == set()
    assert ids(found, Syntax.CII) == {("BR-CO-19", Severity.FATAL, "delivery.invoicing_period")}


@pytest.mark.parametrize(
    ("start", "end"),
    [(JAN, FEB), (FEB, FEB), (JAN, None), (None, FEB)],
)
def test_a_dated_line_period_passes(start: datetime.date | None, end: datetime.date | None) -> None:
    assert calc.check(invoice(period=False, lines=(dated(line(), start, end),))) == ()


def test_br_30_and_br_co_20_are_fatal_per_line() -> None:
    found = invoice(
        period=False,
        lines=(
            dated(line(identifier="1"), JAN, FEB),
            dated(line(identifier="2"), FEB, JAN),
            dated(line(identifier="3"), None, None),
        ),
    )

    expected = {
        ("BR-30", Severity.FATAL, "lines[1].period.end_date"),
        ("BR-CO-20", Severity.FATAL, "lines[2].period"),
    }
    assert ids(found) == expected
    for syntax in (Syntax.UBL, Syntax.CII):
        assert ids(found, syntax) == expected
    messages = {f.rule_id: f.message for f in calc.check(found)}
    assert "BT-135" in messages["BR-30"]
    assert "BG-26" in messages["BR-CO-20"]


def test_br_co_20_does_not_accept_bt_8() -> None:
    found = invoice(period=False, code="3", lines=(dated(line(), None, None),))

    assert ids(found) == {("BR-CO-20", Severity.FATAL, "lines[0].period")}


def test_br_29_bt_8_does_not_excuse_an_inverted_invoicing_period() -> None:
    found = invoice(FEB, JAN, code="3")

    expected = {("BR-29", Severity.FATAL, "delivery.invoicing_period.end_date")}
    assert ids(found) == expected
    for syntax in (Syntax.UBL, Syntax.CII):
        assert ids(found, syntax) == expected


def test_credit_note_periods_follow_the_same_rules() -> None:
    """UBL tests ``cac:CreditNoteLine/cac:InvoicePeriod`` with the same BR-30 / BR-CO-20 asserts."""
    found = invoice(FEB, JAN, type_code="381", lines=(dated(line(), None, None),))

    expected = {
        ("BR-29", Severity.FATAL, "delivery.invoicing_period.end_date"),
        ("BR-CO-20", Severity.FATAL, "lines[0].period"),
    }
    assert ids(found) == expected
    for syntax in (Syntax.UBL, Syntax.CII):
        assert ids(found, syntax) == expected
