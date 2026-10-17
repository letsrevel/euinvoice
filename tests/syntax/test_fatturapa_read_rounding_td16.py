"""FatturaPA reader: PrezzoTotale beyond two decimals and a Natura with a rate on TD16 (#152; #132 items 1 and 21)."""

import re
from decimal import Decimal

import pytest

from _fatturapa_read import body, cassa_block, document, line, summary
from _fatturapa_read_cases import LINE
from _fatturapa_write import TRANSMISSION
from euinvoice import calc, parse, parse_detailed, to_xml
from euinvoice.errors import ParseError, PreflightError
from euinvoice.model import without_extensions
from euinvoice.model.it import ItalianLineExtension, Natura
from euinvoice.syntax import Syntax

D = Decimal
TOTAL = f"{LINE}/PrezzoTotale/text()"


def _priced(total: str, *, taxable: str = "100.00", tax: str = "22.00") -> bytes:
    return document(
        body(lines=line(quantity="1.00", unit=total, total=total), summaries=summary("22.00", taxable, tax))
    )


def _write(data: bytes) -> bytes:
    return to_xml(parse(data), syntax=Syntax.FATTURAPA, fatturapa_transmission=TRANSMISSION)


# ------------------------------------------------------------------------------------- item 1: PrezzoTotale


@pytest.mark.parametrize(
    ("declared", "rounded"),
    [
        ("100.00500000", "100.01"),  # a tie rounds half up (D11)
        ("100.004", "100.00"),
        ("100.00499999", "100.00"),
        ("-100.00500000", "-100.01"),  # half up is away from zero
    ],
)
def test_prezzo_totale_beyond_two_decimals_rounds_half_up_and_keeps_the_exact_value(
    declared: str, rounded: str
) -> None:
    result = parse_detailed(_priced(declared))

    (line_,) = result.invoice.lines
    assert line_.net_amount == D(rounded)
    assert line_.it is not None
    assert format(line_.it.total_price, "f") == declared
    assert TOTAL in result.unmapped  # the rounding is reported: the element's text is only partly mapped


def test_a_prezzo_totale_that_needs_no_rounding_has_no_extension_and_no_report() -> None:
    result = parse_detailed(_priced("100.00000000"))

    (line_,) = result.invoice.lines
    assert line_.net_amount == D("100.00")
    assert line_.it is None
    assert TOTAL not in result.unmapped


def test_no_other_declared_amount_is_changed_and_the_reader_adds_no_cen_violation() -> None:
    # Item 22: the summary declares 100.01 / 22.00, as the rounded line does: that is what the CEN rules see.
    invoice = parse(_priced("100.00500000", taxable="100.01"))

    assert invoice.totals.sum_of_line_net_amounts == D("100.01")
    assert (invoice.vat_breakdown[0].taxable_amount, invoice.vat_breakdown[0].tax_amount) == (D("100.01"), D("22.00"))
    assert calc.check(without_extensions(invoice)) == ()


def test_the_exact_prezzo_totale_round_trips_through_the_writer() -> None:
    data = _priced("100.00500000", taxable="100.01")

    written = _write(data)

    assert b"<PrezzoTotale>100.00500000</PrezzoTotale>" in written
    assert parse(written).lines[0] == parse(data).lines[0]


def test_the_writer_refuses_an_exact_value_that_does_not_round_to_bt_131() -> None:
    invoice = parse(_priced("100.00500000", taxable="100.01"))
    wrong = invoice.lines[0].model_copy(update={"it": ItalianLineExtension(total_price=D("100.02000000"))})
    tampered = invoice.model_copy(update={"lines": (wrong,)})

    with pytest.raises(PreflightError, match=re.escape("lines[0].it.total_price")):
        to_xml(tampered, syntax=Syntax.FATTURAPA, fatturapa_transmission=TRANSMISSION)


# ------------------------------------------------------------------------------------- item 21: TD16 + Natura


def _td16(natura: str = "N6.1", rate: str = "22.00", *, tipo: str = "TD16") -> bytes:
    return document(
        body(
            tipo=tipo,
            lines=line(rate=rate, natura=natura),
            summaries=summary(rate, "100.00", "22.00" if rate != "0.00" else "0.00", natura=natura),
        )
    )


def test_td16_reads_a_natura_with_a_rate_as_category_s_and_keeps_the_natura() -> None:
    invoice = parse(_td16())

    (line_,) = invoice.lines
    assert (line_.vat_information.category_code, line_.vat_information.rate) == ("S", D("22.00"))
    assert line_.it is not None
    assert line_.it.nature is Natura.N6_1
    (group,) = invoice.vat_breakdown
    assert (group.category_code, group.rate, group.taxable_amount, group.tax_amount) == (
        "S",
        D("22.00"),
        D(100),
        D(22),
    )
    assert (group.exemption_reason, group.exemption_reason_code) == (None, None)  # BR-S-10
    assert invoice.it is not None
    assert [(s.rate, s.nature) for s in invoice.it.vat_summaries] == [(D("22.00"), Natura.N6_1)]
    assert calc.check(without_extensions(invoice)) == ()  # BR-S-05, BR-S-08, BR-S-09 hold


def test_td16_with_a_natura_at_rate_zero_keeps_its_app_5_1_category() -> None:
    invoice = parse(_td16(rate="0.00"))

    assert invoice.lines[0].vat_information.category_code == "AE"


def test_td16_natura_and_ordinary_lines_at_one_rate_make_one_breakdown() -> None:
    data = document(
        body(
            tipo="TD16",
            lines=line(1, rate="22.00", natura="N6.1") + line(2, rate="22.00"),
            summaries=summary("22.00", "100.00", "22.00", natura="N6.1") + summary("22.00", "100.00", "22.00"),
        )
    )

    invoice = parse(data)

    assert [line_.vat_information.category_code for line_ in invoice.lines] == ["S", "S"]
    (group,) = invoice.vat_breakdown
    assert (group.taxable_amount, group.tax_amount) == (D(200), D(44))  # BR-S-08
    assert calc.check(without_extensions(invoice)) == ()


def _fund_document(tipo: str) -> bytes:
    return document(
        body(
            tipo=tipo,
            document_extra=cassa_block("22.00", natura="N6.1"),
            summaries=summary("22.00", "100.00", "22.00") + summary("22.00", "4.00", "0.88", natura="N6.1"),
        )
    )


def test_td16_applies_to_the_social_security_fund() -> None:
    (charge,) = parse(_fund_document("TD16")).charges

    assert (charge.vat_category_code, charge.vat_rate, charge.reason) == ("S", D("22.00"), "TC04 N6.1")


@pytest.mark.parametrize("tipo", ["TD01", "TD04", "TD17", "TD24"])
def test_other_document_types_keep_refusing_a_natura_with_a_rate(tipo: str) -> None:
    with pytest.raises(ParseError, match=r"Natura N6\.1 .* AliquotaIVA 22\.00.*TD16"):
        parse(_td16(tipo=tipo))


def test_a_fund_natura_with_a_rate_is_refused_off_td16() -> None:
    with pytest.raises(ParseError, match=r"Natura N6\.1"):
        parse(_fund_document("TD01"))


def test_the_writer_refuses_the_td16_reading_with_a_cited_error() -> None:
    # The v1 writer emits TD01, TD04, TD17 and TD24 only, and Natura N6.1 is category AE, not S, in App. 5.1.
    with pytest.raises(PreflightError) as caught:
        _write(_td16())

    message = str(caught.value)
    assert "TD16" in message
    assert "00401" in message
