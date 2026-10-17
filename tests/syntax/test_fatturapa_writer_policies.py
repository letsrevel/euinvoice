"""The FPR12 writer policies decided on #133 and built in #149: items 3, 11b, 11c, 13b, 15b and the Natura warning."""

import re
from decimal import Decimal

import pytest

from _fatturapa_write import (
    GOODS,
    PAYMENT,
    TRANSMISSION,
    buyer,
    it_invoice,
    it_line,
    italian,
    seller,
    written,
)
from euinvoice import calc, parse_all, to_xml
from euinvoice.errors import ModelError, PreflightError
from euinvoice.model import Identifier, Invoice, ItemInformation, ProcessControl
from euinvoice.model.it import CondizioniPagamento, ItalianPayment, ItalianVatSummary, ModalitaPagamento, Natura
from euinvoice.report import Severity
from euinvoice.syntax import Syntax
from euinvoice.syntax.fatturapa import Transmission, preflight, write
from euinvoice.syntax.fatturapa._write_rules import SUMMARY, UNWRITTEN

LINE = "FatturaElettronicaBody/DatiBeniServizi/DettaglioLinee"


def _errors(invoice: Invoice, transmission: Transmission = TRANSMISSION) -> list[tuple[str, str | None]]:
    return [(f.rule_id, f.location) for f in preflight(invoice, transmission) if f.severity is not Severity.WARNING]


def _to_xml(invoice: Invoice, transmission: Transmission = TRANSMISSION) -> bytes:
    return to_xml(invoice, syntax=Syntax.FATTURAPA, fatturapa_transmission=transmission)


# Item 3b: Descrizione = BT-153 + " - " + BT-154


def _described(name: str, description: str | None) -> Invoice:
    return it_invoice(it_line(item=ItemInformation(name=name, description=description)))


def test_descrizione_joins_bt_153_and_bt_154() -> None:
    root = written(_described("Biglietto", "ingresso unico"))

    assert root.findtext(f"{LINE}/Descrizione") == "Biglietto - ingresso unico"


def test_descrizione_without_bt_154_is_bt_153() -> None:
    assert written(_described("Biglietto", None)).findtext(f"{LINE}/Descrizione") == "Biglietto"


def test_an_empty_bt_154_is_absent() -> None:
    invoice = _described("Biglietto", "")

    assert _errors(invoice) == []
    assert written(invoice).findtext(f"{LINE}/Descrizione") == "Biglietto"


def test_descrizione_of_exactly_1000_characters_is_written() -> None:
    invoice = _described("n" * 500, "d" * 497)

    assert _errors(invoice) == []
    assert len(written(invoice).findtext(f"{LINE}/Descrizione") or "") == 1000


def test_descrizione_above_1000_characters_is_refused() -> None:
    invoice = _described("n" * 500, "d" * 498)

    assert _errors(invoice) == [(UNWRITTEN, "lines[0].item.description")]
    (found,) = (f for f in preflight(invoice) if f.severity is Severity.ERROR)
    assert re.search(r"BT-154.*1001 characters.*String1000LatinType.*at most 1000", found.message)
    with pytest.raises(ModelError, match=r"UNWRITTEN at lines\[0\]\.item\.description"):
        write(invoice, TRANSMISSION)


@pytest.mark.parametrize("bad", ["a\tb", "a\nb", "a\u20acb"], ids=["tab", "line break", "not Latin-1"])
def test_bad_character_in_bt_154_is_a_preflight_finding(bad: str) -> None:
    invoice = _described("Biglietto", bad)

    assert _errors(invoice) == [(UNWRITTEN, "lines[0].item.description")]
    with pytest.raises(PreflightError):
        _to_xml(invoice)


def test_descrizione_reads_back_as_the_joined_name_and_is_a_fixed_point() -> None:
    data = _to_xml(_described("Biglietto", "ingresso unico"))
    (result,) = parse_all(data)

    assert result.invoice.lines[0].item.name == "Biglietto - ingresso unico"
    assert result.invoice.lines[0].item.description is None
    assert _to_xml(result.invoice) == data


# Item 11b: BT-20 "TP02 30" is CondizioniPagamento and GiorniTerminiPagamento


def _with_terms(terms: str | None) -> Invoice:
    payment = ItalianPayment(conditions=CondizioniPagamento.TP02, method=ModalitaPagamento.MP05)
    return it_invoice(payment_terms=terms, it=italian(payment=payment))


@pytest.mark.parametrize("days", ["0", "7", "30", "999"])
def test_bt_20_with_days_is_carried(days: str) -> None:
    invoice = _with_terms(f"TP02 {days}")

    assert _errors(invoice) == []
    detail = written(invoice).find(f"{PAYMENT}/DettaglioPagamento")
    assert detail is not None
    assert [c.tag for c in detail][:3] == ["ModalitaPagamento", "GiorniTerminiPagamento", "ImportoPagamento"]
    assert detail.findtext("GiorniTerminiPagamento") == days


@pytest.mark.parametrize("terms", ["TP02", None])
def test_bt_20_without_days_writes_no_giorni(terms: str | None) -> None:
    assert written(_with_terms(terms)).find(f"{PAYMENT}/DettaglioPagamento/GiorniTerminiPagamento") is None


@pytest.mark.parametrize(
    "terms",
    ["TP02 1000", "TP02 030", "TP02  30", "TP02 -1", "TP02 3 0", "TP01 30", "TP02 trenta", "30 giorni", "TP02 "],
)
def test_other_bt_20_text_is_still_refused(terms: str) -> None:
    assert _errors(_with_terms(terms)) == [(UNWRITTEN, "payment_terms")]


def test_bt_20_days_without_it_payment_is_refused() -> None:
    assert (UNWRITTEN, "payment_terms") in _errors(it_invoice(payment_terms="TP02 30"))


def test_bt_20_with_days_round_trips() -> None:
    invoice = _with_terms("TP02 30")
    data = _to_xml(invoice)
    (result,) = parse_all(data)

    assert result.invoice.payment_terms == "TP02 30"
    assert _to_xml(result.invoice) == data


# Item 11c: BT-120 into every DatiRiepilogo of a breakdown split by Natura that has no RiferimentoNormativo


def _split(reason: str, *summaries: ItalianVatSummary) -> Invoice:
    lines = [it_line(str(i), "1", "10", "E", "0", nature=n) for i, n in enumerate((Natura.N4, Natura.N2_1), 1)]
    return it_invoice(
        *lines, exemption_reasons={"E": calc.ExemptionReason(text=reason)}, it=italian(vat_summaries=summaries)
    )


def _references(invoice: Invoice) -> list[str | None]:
    root = written(invoice)
    return [s.findtext("RiferimentoNormativo") for s in root.findall(f"{GOODS}/DatiRiepilogo")]


def test_bt_120_goes_into_every_summary_of_a_breakdown_split_by_natura() -> None:
    invoice = _split("Art. 10 DPR 633/72")

    assert _errors(invoice) == []
    assert _references(invoice) == ["Art. 10 DPR 633/72"] * 2


def test_bt_120_goes_only_into_the_summaries_without_a_legal_reference() -> None:
    own = ItalianVatSummary(rate=Decimal(0), nature=Natura.N4, legal_reference="Art. 10")
    invoice = _split("Art. 74", own)

    assert _errors(invoice) == []
    assert _references(invoice) == ["Art. 10", "Art. 74"]


def test_bt_120_equal_to_one_legal_reference_of_the_split_is_already_written() -> None:
    own = ItalianVatSummary(rate=Decimal(0), nature=Natura.N4, legal_reference="Art. 10")
    other = ItalianVatSummary(rate=Decimal(0), nature=Natura.N2_1, legal_reference="Art. 2")

    assert _errors(_split("Art. 10", own, other)) == []
    assert _references(_split("Art. 10", own, other)) == ["Art. 10", "Art. 2"]


def test_bt_120_too_long_for_riferimento_normativo_is_refused_on_a_split() -> None:
    assert _errors(_split("x" * 101)) == [(SUMMARY, "vat_breakdown[0].exemption_reason")]


def test_a_split_bt_120_reads_back_and_is_a_fixed_point() -> None:
    data = _to_xml(_split("Art. 10"))
    (result,) = parse_all(data)

    assert result.invoice.vat_breakdown[0].exemption_reason == "N4 Art. 10; N2.1 Art. 10"
    assert _to_xml(result.invoice) == data


# Item 13b: BT-49 equal to the transmission's CodiceDestinatario


def _routed(code: str) -> tuple[Invoice, Transmission]:
    address = Identifier(value=code, scheme_id="0205")
    return it_invoice(buyer=buyer(electronic_address=address)), TRANSMISSION.model_copy(update={"recipient_code": code})


def test_bt_49_equal_to_the_codice_destinatario_is_accepted_and_written_once() -> None:
    invoice, transmission = _routed("ABCDEF1")

    assert _errors(invoice, transmission) == []
    root = written(invoice, transmission)
    assert root.findtext("FatturaElettronicaHeader/DatiTrasmissione/CodiceDestinatario") == "ABCDEF1"
    assert write(invoice, transmission).count(b"ABCDEF1") == 1


@pytest.mark.parametrize("transmission", [TRANSMISSION, None], ids=["other code", "no transmission"])
def test_bt_49_otherwise_is_refused(transmission: Transmission | None) -> None:
    invoice, _ = _routed("ABCDEF1")

    found = [(f.rule_id, f.location) for f in preflight(invoice, transmission)]
    assert found == [(UNWRITTEN, "buyer.electronic_address")]


def test_bt_49_not_matching_blocks_to_xml() -> None:
    invoice, _ = _routed("ABCDEF1")

    with pytest.raises(PreflightError):
        _to_xml(invoice)


# Item 15b: BT-23 and BT-34 are accepted like BT-24; a Peppol-shaped invoice can be written


def _peppol_shaped() -> tuple[Invoice, Transmission]:
    invoice, transmission = _routed("ABCDEF1")
    return (
        invoice.model_copy(
            update={
                "process_control": ProcessControl(
                    business_process_type="urn:fdc:peppol.eu:2017:poacc:billing:01:1.0",
                    specification_identifier="urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0",
                ),
                "seller": seller(electronic_address=Identifier(value="seller@example.com", scheme_id="EM")),
            }
        ),
        transmission,
    )


def test_a_peppol_shaped_invoice_is_written_without_its_routing_metadata() -> None:
    invoice, transmission = _peppol_shaped()

    assert _errors(invoice, transmission) == []
    data = _to_xml(invoice, transmission)
    for dropped in (b"seller@example.com", b"peppol.eu"):
        assert dropped not in data
    (result,) = parse_all(data)
    assert result.invoice.buyer.electronic_address is None
    assert result.invoice.seller.electronic_address is None


# Addendum: a Natura DatiRiepilogo without RiferimentoNormativo is a warning


def _natura_without_reference() -> Invoice:
    return it_invoice(it_line(rate="0", category="E", nature=Natura.N4))


def test_natura_without_riferimento_normativo_is_a_warning() -> None:
    (found,) = preflight(_natura_without_reference())

    assert (found.rule_id, found.location, found.severity) == (SUMMARY, "vat_breakdown[0]", Severity.WARNING)
    assert re.search(r"Natura N4 at rate 0 .*2\.2\.2\.8.*Allegato A 1\.9\.1 \(DatiRiepilogo\)", found.message)


def test_the_natura_warning_does_not_block_write_or_to_xml() -> None:
    invoice = _natura_without_reference()

    assert write(invoice, TRANSMISSION) == _to_xml(invoice)


def test_the_natura_warning_does_not_hide_the_totals_check() -> None:
    invoice = _natura_without_reference()
    wrong = invoice.model_copy(update={"totals": invoice.totals.model_copy(update={"total_with_vat": Decimal(1)})})

    assert any(f.location == "totals.total_with_vat" for f in preflight(wrong))


_REFERENCE = ItalianVatSummary(rate=Decimal(0), nature=Natura.N4, legal_reference="Art. 10")


@pytest.mark.parametrize(
    "invoice",
    [
        it_invoice(
            it_line(rate="0", category="E", nature=Natura.N4),
            exemption_reasons={"E": calc.ExemptionReason(text="Art. 10")},
        ),
        it_invoice(it_line(rate="0", category="E", nature=Natura.N4), it=italian(vat_summaries=(_REFERENCE,))),
        it_invoice(),
    ],
    ids=["BT-120", "legal_reference", "no Natura"],
)
def test_no_warning_when_a_reference_is_given_or_no_natura(invoice: Invoice) -> None:
    assert preflight(invoice) == ()
