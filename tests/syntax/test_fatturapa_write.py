"""The FPR12 writer's mapping, row by row (App. 4.1 of the Regole tecniche v2.6; element order of XSD 1.2.3; #119).

The XSD and SdI verdicts on these documents are in tests/conformance/test_fatturapa_write_official.py.
"""

import datetime
from decimal import Decimal

import pytest
from lxml import etree

from _fatturapa_write import (
    BUYER,
    BUYER_CF,
    BUYER_VAT,
    GENERAL,
    GOODS,
    PAYMENT,
    SELLER,
    TEST_IBAN,
    TRANSMISSION,
    buyer,
    it_draft,
    it_invoice,
    it_line,
    italian,
    samples,
    seller,
    written,
)
from euinvoice import _xml, calc
from euinvoice.errors import ModelError
from euinvoice.model import (
    CreditTransfer,
    Identifier,
    InvoiceLinePeriod,
    InvoiceNote,
    PaymentInstructions,
    PrecedingInvoiceReference,
    PriceDetails,
    SellerContact,
    SellerPostalAddress,
)
from euinvoice.model.it import (
    CondizioniPagamento,
    EsigibilitaIVA,
    ItalianPayment,
    ItalianVatSummary,
    ModalitaPagamento,
    Natura,
    RegimeFiscale,
    SoggettoEmittente,
    TipoCessionePrestazione,
    TipoDocumento,
)
from euinvoice.syntax.fatturapa import RECIPIENT_UNKNOWN, Transmission, preflight, write
from euinvoice.syntax.fatturapa._write_rules import SUMMARY


def _tags(element: etree._Element | None) -> list[str]:
    assert element is not None
    return [str(child.tag) for child in element]


def _find(root: etree._Element, path: str) -> etree._Element:
    found = root.find(path)
    assert found is not None, path
    return found


def _pairs(element: etree._Element | None) -> list[tuple[str, str | None]]:
    assert element is not None
    return [(str(child.tag), child.text) for child in element]


def test_root_is_an_unsigned_fpr12_with_one_body() -> None:
    root = written(it_invoice())

    assert root.tag == f"{{{_xml.FATTURAPA}}}FatturaElettronica"
    assert root.get("versione") == "FPR12"
    assert _tags(root) == ["FatturaElettronicaHeader", "FatturaElettronicaBody"]
    assert write(it_invoice(), TRANSMISSION).startswith(b"<?xml version='1.0' encoding='UTF-8'?>")


def test_transmission_header_comes_from_the_options() -> None:
    options = Transmission(
        transmitter_country="IT",
        transmitter_code="00000000003",
        transmission_number="ZZ9",
        recipient_pec="a@example.com",
    )
    transmission = _find(written(it_invoice(), options), "FatturaElettronicaHeader/DatiTrasmissione")

    assert transmission is not None
    assert [(e.tag, e.text) for e in transmission.iter() if e.text] == [
        ("IdPaese", "IT"),
        ("IdCodice", "00000000003"),
        ("ProgressivoInvio", "ZZ9"),
        ("FormatoTrasmissione", "FPR12"),
        ("CodiceDestinatario", RECIPIENT_UNKNOWN),
        ("PECDestinatario", "a@example.com"),
    ]


def test_seller_maps_bt_31_30_27_and_the_tax_regime() -> None:
    invoice = it_invoice(
        seller=seller(legal_registration_identifier=Identifier(value="00000000001", scheme_id="0210")),
        it=italian(tax_regime=RegimeFiscale.RF19),
    )
    data = _find(written(invoice), f"{SELLER}/DatiAnagrafici")

    assert data is not None
    assert _tags(data) == ["IdFiscaleIVA", "CodiceFiscale", "Anagrafica", "RegimeFiscale"]
    assert (data.findtext("IdFiscaleIVA/IdPaese"), data.findtext("IdFiscaleIVA/IdCodice")) == ("IT", "00000000001")
    assert data.findtext("CodiceFiscale") == "00000000001"
    assert data.findtext("Anagrafica/Denominazione") == "Esempio Eventi S.r.l."
    assert data.findtext("RegimeFiscale") == "RF19"


def test_a_cf_prefix_marks_a_codice_fiscale() -> None:
    invoice = it_invoice(buyer=buyer(legal_registration_identifier=Identifier(value=f"CF:{BUYER_CF}")))

    assert written(invoice).findtext(f"{BUYER}/DatiAnagrafici/CodiceFiscale") == BUYER_CF


def test_seller_address_contacts_and_buyer_accounting_reference() -> None:
    invoice = it_invoice(
        seller=seller(
            postal_address=SellerPostalAddress(
                address_line_1="Via Esempio",
                address_line_2="1/A",
                city="Roma",
                post_code="00100",
                country_subdivision="RM",
                country_code="IT",
            ),
            contact=SellerContact(telephone="0600000000", email="fatture@example.com"),
        ),
        buyer_accounting_reference="RIF-1",
    )
    party = _find(written(invoice), SELLER)

    assert party is not None
    assert _tags(party) == ["DatiAnagrafici", "Sede", "Contatti", "RiferimentoAmministrazione"]
    assert _pairs(party.find("Sede")) == [
        ("Indirizzo", "Via Esempio"),
        ("NumeroCivico", "1/A"),
        ("CAP", "00100"),
        ("Comune", "Roma"),
        ("Provincia", "RM"),
        ("Nazione", "IT"),
    ]
    assert _pairs(party.find("Contatti")) == [
        ("Telefono", "0600000000"),
        ("Email", "fatture@example.com"),
    ]
    assert party.findtext("RiferimentoAmministrazione") == "RIF-1"


def test_buyer_maps_bt_48_47_44_and_bg_8() -> None:
    invoice = it_invoice(buyer=buyer(vat_identifier=BUYER_VAT))
    party = _find(written(invoice), BUYER)

    assert party is not None
    assert _tags(party.find("DatiAnagrafici")) == ["IdFiscaleIVA", "CodiceFiscale", "Anagrafica"]
    assert party.findtext("DatiAnagrafici/IdFiscaleIVA/IdCodice") == "00000000002"
    assert party.findtext("DatiAnagrafici/CodiceFiscale") == BUYER_CF
    assert party.findtext("DatiAnagrafici/Anagrafica/Denominazione") == "Mario Rossi"
    assert party.findtext("Sede/Comune") == "Milano"
    assert party.find("Sede/Provincia") is None


def test_soggetto_emittente_comes_last_in_the_header() -> None:
    root = written(samples()["TD17 self-billing"].invoice)

    header = _find(root, "FatturaElettronicaHeader")
    assert _tags(header)[-1] == "SoggettoEmittente"
    assert root.findtext("FatturaElettronicaHeader/SoggettoEmittente") == SoggettoEmittente.CC
    assert root.findtext(f"{SELLER}/DatiAnagrafici/IdFiscaleIVA/IdPaese") == "DE"
    assert root.findtext(f"{GENERAL}/TipoDocumento") == "TD17"


def test_general_data_in_xsd_order() -> None:
    invoice = it_invoice(
        notes=(InvoiceNote(note="Prima"), InvoiceNote(note="Seconda")),
        purchase_order_reference="PO-1",
        contract_reference="CT-1",
        receiving_advice_reference="RA-1",
    )
    root = written(invoice)

    document = _find(root, GENERAL)
    assert _tags(document) == [
        "TipoDocumento",
        "Divisa",
        "Data",
        "Numero",
        "ImportoTotaleDocumento",
        "Causale",
        "Causale",
    ]
    assert [e.text for e in document] == ["TD01", "EUR", "2026-01-15", "FT-1", "122.00", "Prima", "Seconda"]
    general = _find(root, "FatturaElettronicaBody/DatiGenerali")
    assert _tags(general) == ["DatiGeneraliDocumento", "DatiOrdineAcquisto", "DatiContratto", "DatiRicezione"]
    assert [general.findtext(f"{t}/IdDocumento") for t in _tags(general)[1:]] == ["PO-1", "CT-1", "RA-1"]


def test_rounding_amount_is_arrotondamento() -> None:
    invoice = calc.complete(it_draft(), rounding_amount=Decimal("0.01"))

    assert written(invoice).findtext(f"{GENERAL}/Arrotondamento") == "0.01"


def test_credit_note_links_the_invoice_and_carries_the_stamp_duty() -> None:
    root = written(samples()["TD04 credit note"].invoice)

    assert root.findtext(f"{GENERAL}/TipoDocumento") == "TD04"
    assert root.findtext(f"{GENERAL}/DatiBollo/BolloVirtuale") == "SI"
    assert root.findtext(f"{GENERAL}/DatiBollo/ImportoBollo") == "0.00"
    linked = _find(root, "FatturaElettronicaBody/DatiGenerali/DatiFattureCollegate")
    assert _pairs(linked) == [("IdDocumento", "FT-1"), ("Data", "2026-01-15")]


def test_invoice_stamp_duty_comes_from_the_sae_charge() -> None:
    document = _find(written(samples()["TD01 stamp duty"].invoice), GENERAL)

    assert _tags(document)[4] == "DatiBollo"
    assert document.findtext("DatiBollo/BolloVirtuale") == "SI"


def test_line_maps_every_written_term_in_xsd_order() -> None:
    line = it_line(
        "7",
        "1.5",
        "9",
        price_details=PriceDetails(
            item_net_price=Decimal(9), item_gross_price=Decimal(10), item_price_discount=Decimal(1)
        ),
        period=InvoiceLinePeriod(start_date=datetime.date(2026, 1, 1), end_date=datetime.date(2026, 1, 31)),
        buyer_accounting_reference="CDC-1",
        supply_type=TipoCessionePrestazione.PR,
    )
    element = _find(written(it_invoice(line)), f"{GOODS}/DettaglioLinee")

    assert [(e.tag, e.text) for e in element.iter() if e is not element and e.tag != "ScontoMaggiorazione"] == [
        ("NumeroLinea", "7"),
        ("TipoCessionePrestazione", "PR"),
        ("Descrizione", "Biglietto evento"),
        ("Quantita", "1.50"),
        ("UnitaMisura", "C62"),
        ("DataInizioPeriodo", "2026-01-01"),
        ("DataFinePeriodo", "2026-01-31"),
        ("PrezzoUnitario", "10.00"),
        ("Tipo", "SC"),
        ("Importo", "1.00"),
        ("PrezzoTotale", "13.50"),
        ("AliquotaIVA", "22.00"),
        ("RiferimentoAmministrazione", "CDC-1"),
    ]


def test_negative_price_discount_is_a_markup() -> None:
    line = it_line(
        price_details=PriceDetails(
            item_net_price=Decimal(51), item_gross_price=Decimal(50), item_price_discount=Decimal(-1)
        )
    )
    adjustment = _find(written(it_invoice(line)), f"{GOODS}/DettaglioLinee/ScontoMaggiorazione")

    assert _pairs(adjustment) == [("Tipo", "MG"), ("Importo", "1.00")]


@pytest.mark.parametrize("gross", [Decimal(50), None])
def test_zero_price_discount_needs_no_element(gross: Decimal | None) -> None:
    line = it_line(
        price_details=PriceDetails(item_net_price=Decimal(50), item_gross_price=gross, item_price_discount=Decimal(0))
    )
    element = _find(written(it_invoice(line)), f"{GOODS}/DettaglioLinee")

    assert element.find("ScontoMaggiorazione") is None
    assert element.findtext("PrezzoUnitario") == "50.00"


def test_without_a_gross_price_the_net_price_is_prezzo_unitario() -> None:
    line = it_line(price="12.345678")

    assert written(it_invoice(line)).findtext(f"{GOODS}/DettaglioLinee/PrezzoUnitario") == "12.345678"


def test_zero_rate_line_carries_its_natura() -> None:
    line = it_line(category="G", rate="0", nature=Natura.N3_1)

    element = _find(written(it_invoice(line)), f"{GOODS}/DettaglioLinee")
    assert (element.findtext("AliquotaIVA"), element.findtext("Natura")) == ("0.00", "N3.1")


def test_summaries_split_by_natura_and_payment_mode() -> None:
    goods = _find(written(samples()["TD01 exempt and split payment"].invoice), GOODS)

    summaries = [_pairs(s) for s in goods.findall("DatiRiepilogo")]
    assert summaries == [
        [("AliquotaIVA", "22.00"), ("ImponibileImporto", "100.00"), ("Imposta", "22.00"), ("EsigibilitaIVA", "S")],
        [("AliquotaIVA", "0.00"), ("Natura", "N2.1"), ("ImponibileImporto", "30.00"), ("Imposta", "0.00")],
        [
            ("AliquotaIVA", "0.00"),
            ("Natura", "N4"),
            ("ImponibileImporto", "20.00"),
            ("Imposta", "0.00"),
            ("RiferimentoNormativo", "Art. 10 DPR 633/72"),
        ],
    ]
    assert _tags(goods)[-3:] == ["DatiRiepilogo"] * 3


def test_split_and_ordinary_payment_at_one_rate_are_refused() -> None:
    invoice = it_invoice(it_line("1"), it_line("2", category="B"))

    errors = [(f.rule_id, f.location) for f in preflight(invoice)]
    assert errors == [(SUMMARY, "lines[0]")]
    assert "at rate 22.00 (lines 0, 1) would be" in preflight(invoice)[0].message
    with pytest.raises(ModelError, match=r"SUMMARY at lines\[0\]: split payment .* BT-151 would be lost"):
        write(invoice, TRANSMISSION)


def test_split_and_ordinary_payment_at_different_rates_are_two_summaries() -> None:
    invoice = it_invoice(it_line("1"), it_line("2", category="B", rate="10"))

    summaries = written(invoice).findall(f"{GOODS}/DatiRiepilogo")
    assert [(s.findtext("AliquotaIVA"), s.findtext("EsigibilitaIVA")) for s in summaries] == [
        ("22.00", None),
        ("10.00", "S"),
    ]


def test_accessory_lines_fill_spese_accessorie() -> None:
    summary = _find(written(samples()["TD01 rich line"].invoice), f"{GOODS}/DatiRiepilogo")

    assert summary.findtext("SpeseAccessorie") == "5.00"
    assert summary.findtext("ImponibileImporto") == "43.00"


@pytest.mark.parametrize(("code", "expected"), [("3", "I"), ("35", "I"), ("432", "D")])
def test_vat_point_date_code_gives_esigibilita(code: str, expected: str) -> None:
    invoice = it_invoice(vat_point_date_code=code)

    assert written(invoice).findtext(f"{GOODS}/DatiRiepilogo/EsigibilitaIVA") == expected


def test_vat_point_date_code_agreeing_with_the_summary_is_written_once() -> None:
    summary = ItalianVatSummary(rate=Decimal(22), vat_chargeability=EsigibilitaIVA.D)
    invoice = it_invoice(vat_point_date_code="432", it=italian(vat_summaries=(summary,)))

    assert written(invoice).findtext(f"{GOODS}/DatiRiepilogo/EsigibilitaIVA") == "D"


def test_vat_point_date_code_skips_split_payment_summaries() -> None:
    invoice = it_invoice(it_line("1"), it_line("2", category="B", rate="10"), vat_point_date_code="3")

    summaries = written(invoice).findall(f"{GOODS}/DatiRiepilogo")
    assert [s.findtext("EsigibilitaIVA") for s in summaries] == ["I", "S"]


def test_payment_maps_bg_16_and_it_payment() -> None:
    root = written(samples()["TD24 deferred"].invoice)

    payment = _find(root, PAYMENT)
    assert _tags(payment) == ["CondizioniPagamento", "DettaglioPagamento"]
    assert _pairs(payment.find("DettaglioPagamento")) == [
        ("Beneficiario", "Esempio Incassi S.p.A."),
        ("ModalitaPagamento", "MP05"),
        ("DataScadenzaPagamento", "2026-02-15"),
        ("ImportoPagamento", "83.83"),
        ("IBAN", TEST_IBAN),
        ("CodicePagamento", "RF18000000000000000000001"),
    ]


def test_payment_method_and_bic() -> None:
    invoice = it_invoice(
        it=italian(payment=ItalianPayment(conditions=CondizioniPagamento.TP03, method=ModalitaPagamento.MP05)),
        payment_instructions=PaymentInstructions(
            payment_means_type_code="30",
            credit_transfers=(
                CreditTransfer(payment_account_identifier=TEST_IBAN, payment_service_provider_identifier="AAAADEBBXXX"),
            ),
        ),
    )
    detail = _find(written(invoice), f"{PAYMENT}/DettaglioPagamento")

    assert written(invoice).findtext(f"{PAYMENT}/CondizioniPagamento") == "TP03"
    assert detail.findtext("ModalitaPagamento") == "MP05"
    assert _tags(detail)[-1] == "BIC"
    assert detail.findtext("BIC") == "AAAADEBBXXX"


def test_payment_without_bg_16_uses_the_method() -> None:
    invoice = it_invoice(
        it=italian(payment=ItalianPayment(conditions=CondizioniPagamento.TP02, method=ModalitaPagamento.MP01))
    )

    detail = _find(written(invoice), f"{PAYMENT}/DettaglioPagamento")
    assert _pairs(detail) == [("ModalitaPagamento", "MP01"), ("ImportoPagamento", "122.00")]


def test_no_payment_data_writes_no_dati_pagamento() -> None:
    assert written(it_invoice()).find(PAYMENT) is None


def test_document_type_td24() -> None:
    assert written(samples()["TD24 deferred"].invoice).findtext(f"{GENERAL}/TipoDocumento") == TipoDocumento.TD24


def test_seller_telephone_alone() -> None:
    root = written(it_invoice(seller=seller(contact=SellerContact(telephone="0600000000"))))

    assert _pairs(_find(root, f"{SELLER}/Contatti")) == [("Telefono", "0600000000")]


def test_optional_parts_are_written_alone() -> None:
    invoice = it_invoice(
        it_line(period=InvoiceLinePeriod(start_date=datetime.date(2026, 1, 1))),
        it_line("2", period=InvoiceLinePeriod(end_date=datetime.date(2026, 1, 31))),
        seller=seller(contact=SellerContact(email="fatture@example.com")),
        notes=(InvoiceNote(),),
        preceding_invoice_references=(PrecedingInvoiceReference(reference="FT-0"),),
    )
    root = written(invoice)

    lines = root.findall(f"{GOODS}/DettaglioLinee")
    assert [(line.findtext("DataInizioPeriodo"), line.findtext("DataFinePeriodo")) for line in lines] == [
        ("2026-01-01", None),
        (None, "2026-01-31"),
    ]
    assert _pairs(_find(root, f"{SELLER}/Contatti")) == [("Email", "fatture@example.com")]
    assert root.find(f"{GENERAL}/Causale") is None
    linked = _find(root, "FatturaElettronicaBody/DatiGenerali/DatiFattureCollegate")
    assert _pairs(linked) == [("IdDocumento", "FT-0")]
