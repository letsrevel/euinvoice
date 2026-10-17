"""Line allowances and charges (BG-27, BG-28) in FPR12 (#151, #133 item 12 option c).

Each is a 2.2.1.10 ScontoMaggiorazione (SC / MG, ``Importo`` per unit, App. 4.1) and its reasons (BT-139 / BT-140,
BT-144 / BT-145) are 2.2.1.16 AltriDatiGestionali with ``TipoDato`` the term id, ``RiferimentoTesto`` the value and
``RiferimentoNumero`` the 1-based position of the ScontoMaggiorazione it explains.
"""

import re
import typing as t
from decimal import Decimal

import pytest

import _fatturapa_read
from _fatturapa_write import GOODS, TRANSMISSION, it_invoice, it_line, written
from euinvoice import _xml, parse_all, to_xml
from euinvoice.errors import ModelError, ParseError
from euinvoice.model import Invoice, InvoiceLineAllowance, InvoiceLineCharge, PriceDetails
from euinvoice.model.it import ItalianLineExtension
from euinvoice.report import Severity
from euinvoice.syntax import Syntax
from euinvoice.syntax.fatturapa import preflight, write
from euinvoice.syntax.fatturapa._write_rules import LINE_TOTAL, UNWRITTEN
from euinvoice.validation import sdi

D = Decimal
LINE = f"{GOODS}/DettaglioLinee"


def _allowance(amount: str = "5.00", **changes: t.Any) -> InvoiceLineAllowance:
    return InvoiceLineAllowance(amount=D(amount), **({"reason": "Promo"} | changes))


def _charge(amount: str = "2.00", **changes: t.Any) -> InvoiceLineCharge:
    return InvoiceLineCharge(amount=D(amount), **({"reason": "Spedizione"} | changes))


def _sconti(invoice: Invoice) -> list[tuple[str | None, str | None]]:
    element = written(invoice).find(LINE)
    assert element is not None
    return [(s.findtext("Tipo"), s.findtext("Importo")) for s in element.findall("ScontoMaggiorazione")]


def _reasons(invoice: Invoice) -> list[tuple[str | None, str | None, str | None]]:
    element = written(invoice).find(LINE)
    assert element is not None
    return [
        (a.findtext("TipoDato"), a.findtext("RiferimentoTesto"), a.findtext("RiferimentoNumero"))
        for a in element.findall("AltriDatiGestionali")
    ]


def test_an_allowance_and_a_charge_are_sconto_and_maggiorazione_with_their_reasons() -> None:
    line = it_line(
        quantity="4",
        price="50",
        allowances=(_allowance("10.00", reason="Promo", reason_code="95"),),
        charges=(_charge("2.00", reason=None, reason_code="FC"),),
    )
    invoice = it_invoice(line)
    element = written(invoice).find(LINE)
    assert element is not None

    assert [str(e.tag) for e in element] == [
        "NumeroLinea",
        "Descrizione",
        "Quantita",
        "UnitaMisura",
        "PrezzoUnitario",
        "ScontoMaggiorazione",
        "ScontoMaggiorazione",
        "PrezzoTotale",
        "AliquotaIVA",
        "AltriDatiGestionali",
        "AltriDatiGestionali",
        "AltriDatiGestionali",
    ]
    assert _sconti(invoice) == [("SC", "2.50"), ("MG", "0.50")]
    assert element.findtext("PrezzoTotale") == "192.00"  # (50 - 2.50 + 0.50) * 4
    assert _reasons(invoice) == [("BT-139", "Promo", "1.00"), ("BT-140", "95", "1.00"), ("BT-145", "FC", "2.00")]


def test_with_a_price_discount_it_is_the_first_entry_and_has_no_reason() -> None:
    line = it_line(
        quantity="2",
        price="9",
        price_details=PriceDetails(item_net_price=D(9), item_gross_price=D(10), item_price_discount=D(1)),
        allowances=(_allowance("1.00"),),
    )
    invoice = it_invoice(line)

    assert _sconti(invoice) == [("SC", "1.00"), ("SC", "0.50")]
    assert _reasons(invoice) == [("BT-139", "Promo", "2.00")]
    element = written(invoice).find(LINE)
    assert element is not None
    assert (element.findtext("PrezzoUnitario"), element.findtext("PrezzoTotale")) == ("10.00", "17.00")


def test_a_zero_price_discount_leaves_the_allowance_first() -> None:
    line = it_line(
        price_details=PriceDetails(item_net_price=D(50), item_gross_price=D(50), item_price_discount=D(0)),
        allowances=(_allowance("4.00"),),
    )

    assert _reasons(it_invoice(line)) == [("BT-139", "Promo", "1.00")]


def test_several_amounts_are_written_in_order() -> None:
    line = it_line(
        quantity="2",
        allowances=(_allowance("1.00", reason="A"), _allowance("3.00", reason="B")),
        charges=(_charge("4.00", reason="C"),),
    )
    invoice = it_invoice(line)

    assert _sconti(invoice) == [("SC", "0.50"), ("SC", "1.50"), ("MG", "2.00")]
    assert [r[1:] for r in _reasons(invoice)] == [("A", "1.00"), ("B", "2.00"), ("C", "3.00")]
    element = written(invoice).find(LINE)
    assert element is not None
    assert element.findtext("PrezzoTotale") == "100.00"


def test_the_written_line_passes_sdi_00423() -> None:
    line = it_line(quantity="2.5", price="19.99", allowances=(_allowance("5.00"),), charges=(_charge("2.50"),))

    data = to_xml(it_invoice(line), syntax=Syntax.FATTURAPA, fatturapa_transmission=TRANSMISSION)

    assert [f for f in sdi.check(_xml.parse(data)) if f.rule_id == "00423"] == []


def test_allowances_and_charges_read_back_as_written() -> None:
    line = it_line(
        quantity="4",
        price="50",
        allowances=(_allowance("10.00", reason="Promo", reason_code="95"), _allowance("1.00", reason="Altro")),
        charges=(_charge("2.00", reason=None, reason_code="FC"),),
    )
    invoice = it_invoice(line)
    data = to_xml(invoice, syntax=Syntax.FATTURAPA, fatturapa_transmission=TRANSMISSION)

    (result,) = parse_all(data)

    back = result.invoice
    assert back.lines[0].allowances == invoice.lines[0].allowances
    assert back.lines[0].charges == invoice.lines[0].charges
    assert back.lines[0].price_details == invoice.lines[0].price_details
    assert back.lines[0].item.attributes == ()
    assert back.lines[0].net_amount == invoice.lines[0].net_amount
    assert not [p for p in result.unmapped if "DettaglioLinee" in p]
    assert write(back, TRANSMISSION) == write(invoice, TRANSMISSION)


def test_allowances_read_back_with_a_price_discount() -> None:
    line = it_line(
        quantity="2",
        price="9",
        price_details=PriceDetails(item_net_price=D(9), item_gross_price=D(10), item_price_discount=D(1)),
        allowances=(_allowance("1.00"),),
        charges=(_charge("3.00"),),
    )
    invoice = it_invoice(line)

    (result,) = parse_all(to_xml(invoice, syntax=Syntax.FATTURAPA, fatturapa_transmission=TRANSMISSION))

    assert result.invoice.lines[0].price_details == invoice.lines[0].price_details
    assert result.invoice.lines[0].allowances == invoice.lines[0].allowances
    assert result.invoice.lines[0].charges == invoice.lines[0].charges


def _errors(invoice: Invoice) -> list[tuple[str, str | None, str]]:
    return [(f.rule_id, f.location, f.message) for f in preflight(invoice) if f.severity is Severity.ERROR]


def _refused(invoice: Invoice, rule: str, location: str, match: str) -> None:
    errors = _errors(invoice)
    assert [(r, loc) for r, loc, _ in errors if loc == location] == [(rule, location)], errors
    assert re.search(match, next(m for _, loc, m in errors if loc == location)), errors
    with pytest.raises(ModelError, match=re.escape(location)):
        write(invoice, TRANSMISSION)


def test_an_amount_that_the_unit_price_cannot_carry_exactly_is_refused() -> None:
    # 1.00 / 3 has no Amount8DecimalType value that gives 1.00 again when multiplied by BT-129
    line = it_line(quantity="3", allowances=(_allowance("1.00"),))

    _refused(it_invoice(line), UNWRITTEN, "lines[0].allowances[0].amount", r"^BT-136 .*Amount8DecimalType.*BT-129")


def test_a_charge_that_the_unit_price_cannot_carry_exactly_is_refused() -> None:
    line = it_line(quantity="7", charges=(_charge("1.00"),))

    _refused(it_invoice(line), UNWRITTEN, "lines[0].charges[0].amount", r"^BT-141 ")


def test_a_quantity_that_divides_exactly_is_accepted() -> None:
    line = it_line(quantity="0.25", allowances=(_allowance("0.01"),))

    assert _sconti(it_invoice(line)) == [("SC", "0.04")]


def test_a_zero_quantity_cannot_carry_an_amount() -> None:
    line = it_line(quantity="0", allowances=(_allowance("1.00"),))

    _refused(it_invoice(line), UNWRITTEN, "lines[0].allowances[0].amount", r"BT-129 is 0")


@pytest.mark.parametrize("reason", ["x" * 61, "Cafœ", "line\nbreak"])
def test_a_reason_that_does_not_fit_riferimento_testo_is_refused(reason: str) -> None:
    line = it_line(allowances=(_allowance("2.00", reason=reason),))

    _refused(it_invoice(line), UNWRITTEN, "lines[0].allowances[0].reason", r"^BT-139 .*String60LatinType")


def test_a_charge_reason_that_does_not_fit_is_refused() -> None:
    line = it_line(charges=(_charge("2.00", reason="x" * 61),))

    _refused(it_invoice(line), UNWRITTEN, "lines[0].charges[0].reason", r"^BT-144 ")


@pytest.mark.parametrize(("term", "field"), [("BT-137", "base_amount"), ("BT-138", "percentage")])
def test_an_allowance_base_amount_or_percentage_is_not_written(term: str, field: str) -> None:
    line = it_line(allowances=(_allowance("2.00", **{field: D(10)}),))

    _refused(it_invoice(line), UNWRITTEN, f"lines[0].allowances[0].{field}", rf"^{term} .*Percentuale")


@pytest.mark.parametrize(("term", "field"), [("BT-142", "base_amount"), ("BT-143", "percentage")])
def test_a_charge_base_amount_or_percentage_is_not_written(term: str, field: str) -> None:
    line = it_line(charges=(_charge("2.00", **{field: D(10)}),))

    _refused(it_invoice(line), UNWRITTEN, f"lines[0].charges[0].{field}", rf"^{term} ")


def test_a_line_net_amount_that_the_sdi_would_refuse_is_reported() -> None:
    good = it_invoice(it_line(quantity="2", allowances=(_allowance("2.00"),)))
    line = good.lines[0].model_copy(update={"net_amount": D("99.00")})
    invoice = good.model_copy(update={"lines": (line,)})

    errors = _errors(invoice)

    assert any(
        rule == LINE_TOTAL and loc == "lines[0].net_amount" and "00423" in message and "98.00" in message
        for rule, loc, message in errors
    ), errors


# --- the reader on hand-made documents -------------------------------------------------------------------------

_SC = "<ScontoMaggiorazione><Tipo>SC</Tipo><Importo>5.00</Importo></ScontoMaggiorazione>"
_MG = "<ScontoMaggiorazione><Tipo>MG</Tipo><Importo>1.00</Importo></ScontoMaggiorazione>"


def _adg(term: str, text: str | None = "Motivo", position: str | None = "1.00") -> str:
    return (
        f"<AltriDatiGestionali><TipoDato>{term}</TipoDato>"
        + ("" if text is None else f"<RiferimentoTesto>{text}</RiferimentoTesto>")
        + ("" if position is None else f"<RiferimentoNumero>{position}</RiferimentoNumero>")
        + "</AltriDatiGestionali>"
    )


def _read(adjustments: str, after: str, total: str = "100.00", quantity: str | None = "2.00") -> Invoice:
    taxable = format(Decimal(total), "f")
    tax = format(Decimal(total) * Decimal("0.22"), ".2f")
    line = _fatturapa_read.line(total=total, adjustments=adjustments, after=after, quantity=quantity)
    (result,) = parse_all(
        _fatturapa_read.document(
            _fatturapa_read.body(lines=line, summaries=_fatturapa_read.summary("22.00", taxable, tax))
        )
    )
    return result.invoice


def test_the_reader_multiplies_importo_by_quantita() -> None:
    invoice = _read(_SC + _MG, _adg("BT-139", "Promo") + _adg("BT-145", "FC", "2.00"), total="94.00")

    (allowance,) = invoice.lines[0].allowances
    (charge,) = invoice.lines[0].charges
    assert (allowance.amount, allowance.reason, allowance.reason_code) == (D("10.00"), "Promo", None)
    assert (charge.amount, charge.reason, charge.reason_code) == (D("2.00"), None, "FC")
    assert invoice.lines[0].price_details.item_price_discount is None
    assert invoice.lines[0].item.attributes == ()


def test_without_quantita_the_amount_is_the_importo() -> None:
    invoice = _read(_SC, _adg("BT-139"), total="45.00", quantity=None)

    assert invoice.lines[0].allowances[0].amount == D("5.00")


def test_an_unexplained_sconto_next_to_an_explained_one_is_bt_147() -> None:
    invoice = _read(_SC + _MG, _adg("BT-144", "Spese", "2.00"), total="92.00")

    price = invoice.lines[0].price_details
    assert (price.item_gross_price, price.item_price_discount, price.item_net_price) == (
        D("50.00"),
        D("5.00"),
        D("45.00"),
    )
    assert invoice.lines[0].charges[0].amount == D("2.00")


def test_the_same_term_without_a_pointer_is_an_ordinary_attribute() -> None:
    invoice = _read(_SC, _adg("BT-139", "Promo", position=None), total="90.00")

    assert invoice.lines[0].allowances == ()
    assert [(a.name, a.value) for a in invoice.lines[0].item.attributes] == [("BT-139", "Promo")]
    assert invoice.lines[0].price_details.item_price_discount == D("5.00")


def test_a_pointer_beyond_the_sconti_is_an_ordinary_attribute() -> None:
    invoice = _read(_SC, _adg("BT-139", "Promo", position="2.00"), total="90.00")

    assert invoice.lines[0].allowances == ()
    assert len(invoice.lines[0].item.attributes) == 1


@pytest.mark.parametrize(
    ("adjustments", "after", "match"),
    [
        (_MG, _adg("BT-139"), r"BT-139 explains ScontoMaggiorazione 1, which is not SC"),
        (_SC, _adg("BT-144"), r"BT-144 explains ScontoMaggiorazione 1, which is not MG"),
        (
            "<ScontoMaggiorazione><Tipo>SC</Tipo><Percentuale>10.00</Percentuale></ScontoMaggiorazione>",
            _adg("BT-139"),
            r"which is not SC with an Importo and no Percentuale",
        ),
        (_SC, _adg("BT-139") + _adg("BT-144"), r"as an allowance and as a charge"),
        (
            "<ScontoMaggiorazione><Tipo>SC</Tipo><Importo>0.005</Importo></ScontoMaggiorazione>",
            _adg("BT-139"),
            r"more than two decimals",
        ),
    ],
)
def test_the_reader_refuses_what_it_cannot_map_back(adjustments: str, after: str, match: str) -> None:
    taxable = "100.00"
    line = _fatturapa_read.line(total=taxable, adjustments=adjustments, after=after, quantity="3.00")
    data = _fatturapa_read.document(
        _fatturapa_read.body(lines=line, summaries=_fatturapa_read.summary("22.00", taxable, "22.00"))
    )

    with pytest.raises(ParseError, match=match):
        parse_all(data)


def test_several_sconti_that_nothing_explains_are_still_refused() -> None:
    with pytest.raises(ParseError, match=r"2 ScontoMaggiorazione on one line"):
        _read(_SC + _MG, "", total="96.00")


def test_a_second_reason_of_the_same_kind_stays_an_attribute() -> None:
    invoice = _read(_SC, _adg("BT-139", "Promo") + _adg("BT-139", "Again"), total="90.00")

    assert invoice.lines[0].allowances[0].reason == "Promo"
    assert [(a.name, a.value) for a in invoice.lines[0].item.attributes] == [("BT-139", "Again")]


def test_the_line_total_finding_shows_an_expected_amount_with_many_decimals() -> None:
    good = it_invoice(it_line(quantity="2", price="10.123", allowances=(_allowance("2.00"),)))
    line = good.lines[0].model_copy(update={"net_amount": D("50.00")})
    invoice = good.model_copy(update={"lines": (line,)})

    assert any("18.246" in message for _, _, message in _errors(invoice))


def test_a_negative_quantity_cannot_carry_an_amount() -> None:
    good = it_invoice(it_line(quantity="2", allowances=(_allowance("2.00"),)))
    line = good.lines[0].model_copy(update={"invoiced_quantity": D(-2)})
    invoice = good.model_copy(update={"lines": (line,)})

    errors = [(r, loc, m) for r, loc, m in _errors(invoice) if loc == "lines[0].allowances[0].amount"]

    assert len(errors) == 1
    assert errors[0][0] == UNWRITTEN
    assert "negative" in errors[0][2]
    assert "is 0" not in errors[0][2]


def test_the_reader_refuses_explained_sconti_on_a_negative_line() -> None:
    line = _fatturapa_read.line(unit="-50.00", total="-90.00", adjustments=_SC, after=_adg("BT-139"))
    data = _fatturapa_read.document(
        _fatturapa_read.body(lines=line, summaries=_fatturapa_read.summary("22.00", "-90.00", "-19.80"))
    )

    with pytest.raises(ParseError, match=r"PrezzoUnitario is negative and 2\.2\.1\.16 explains"):
        parse_all(data)


@pytest.mark.parametrize("position", ["sNaN", "NaN", "Infinity", "-Infinity", "1.5", "abc"])
def test_a_pointer_that_is_not_a_position_is_an_ordinary_attribute(position: str) -> None:
    invoice = _read(_SC, _adg("BT-139", "Promo", position=position), total="90.00")

    assert invoice.lines[0].allowances == ()
    assert len(invoice.lines[0].item.attributes) == 1


def test_an_exact_total_price_stays_consistent_with_the_entries() -> None:
    # BT-131 98.00; PrezzoTotale 98.004 rounds to it, and (50 - 1.00) * 2 = 98 is within 0.01 of it
    good = it_invoice(it_line(quantity="2", allowances=(_allowance("2.00"),)))
    ext = ItalianLineExtension(total_price=D("98.004"))
    line = good.lines[0].model_copy(update={"it": ext})
    invoice = good.model_copy(update={"lines": (line,)})

    assert _errors(invoice) == []
    assert written(invoice).findtext(f"{LINE}/PrezzoTotale") == "98.004"

    far = good.lines[0].model_copy(update={"it": ItalianLineExtension(total_price=D("98.014"))})
    other = good.model_copy(update={"lines": (far,)})
    assert [r for r, _, _ in _errors(other)] == ["EUINVOICE-FATTURAPA-TOTAL-PRICE"]
