"""The FatturaPA reader maps App. 4.1 of the Regole tecniche v2.6 in reverse, one row at a time (#120).

Every document comes from ``tests/_fatturapa_read.py`` (synthetic, XSD 1.2.3-valid: the conformance suite checks
each one). Refusals, ``unmapped`` reporting, lotti and signed input are in ``test_fatturapa_read_policies.py``.
"""

import datetime
import typing as t
from collections.abc import Callable
from decimal import Decimal

import pytest

from _fatturapa_read import (
    FULL,
    VARIANTS,
    adjusted_document,
    body,
    document,
    natura_document,
    other_data_document,
    payment_document,
)
from euinvoice import calc, parse, parse_detailed
from euinvoice.model import Invoice
from euinvoice.model.it import (
    CondizioniPagamento,
    EsigibilitaIVA,
    ModalitaPagamento,
    Natura,
    RegimeFiscale,
    SoggettoEmittente,
    TipoCessionePrestazione,
    TipoDocumento,
)
from euinvoice.syntax.fatturapa._read import SPECIFICATION
from euinvoice.syntax.fatturapa._read_codes import NATURE_CATEGORY, TYPE_CODE

D = Decimal

# (FatturaPA row of the Rappresentazione tabellare, the model value it maps to, the value FULL holds there). The
# getters take Any: FULL sets every optional group they reach into.
ROWS: t.Final[list[tuple[str, Callable[[t.Any], object], object]]] = [
    ("1.2.1.1 IdFiscaleIVA -> BT-31", lambda i: i.seller.vat_identifier, "IT00000000001"),
    (
        "1.2.1.2 CodiceFiscale -> BT-30",
        lambda i: i.seller.legal_registration_identifier.model_dump(),
        {"value": "00000000001", "scheme_id": "0210"},
    ),
    ("1.2.1.3.1 Denominazione -> BT-27", lambda i: i.seller.name, "Example Srl"),
    ("1.2.1.3.5 CodEORI -> BT-29", lambda i: [x.value for x in i.seller.identifiers], ["EORI:IT00000000001"]),
    ("1.2.1.8 RegimeFiscale -> it.tax_regime", lambda i: i.it.tax_regime, RegimeFiscale.RF19),
    ("1.2.2.1 Indirizzo -> BT-35", lambda i: i.seller.postal_address.address_line_1, "Via Esempio"),
    ("1.2.2.2 NumeroCivico -> BT-36", lambda i: i.seller.postal_address.address_line_2, "1"),
    ("1.2.2.3 CAP -> BT-38", lambda i: i.seller.postal_address.post_code, "00100"),
    ("1.2.2.4 Comune -> BT-37", lambda i: i.seller.postal_address.city, "Roma"),
    ("1.2.2.5 Provincia -> BT-39", lambda i: i.seller.postal_address.country_subdivision, "RM"),
    ("1.2.2.6 Nazione -> BT-40", lambda i: i.seller.postal_address.country_code, "IT"),
    ("1.2.5.1 Telefono -> BT-42", lambda i: i.seller.contact.telephone, "0600000000"),
    ("1.2.5.3 Email -> BT-43", lambda i: i.seller.contact.email, "info@example.com"),
    ("1.2.6 RiferimentoAmministrazione -> BT-19", lambda i: i.buyer_accounting_reference, "ADM-1"),
    ("1.4.1.1 IdFiscaleIVA -> BT-48", lambda i: i.buyer.vat_identifier, "IT00000000002"),
    ("1.4.1.2 CodiceFiscale -> BT-47", lambda i: i.buyer.legal_registration_identifier.value, "AAAAAA00A00A000A"),
    ("1.4.1.3.1 Denominazione -> BT-44", lambda i: i.buyer.name, "Buyer Spa"),
    ("1.4.1.3.5 CodEORI -> BT-46", lambda i: i.buyer.identifier.value, "EORI:IT00000000002"),
    (
        "1.4.2 Sede -> BG-8",
        lambda i: (i.buyer.postal_address.city, i.buyer.postal_address.country_code),
        ("Roma", "IT"),
    ),
    ("1.6 SoggettoEmittente -> it.issuer", lambda i: i.it.issuer, SoggettoEmittente.CC),
    ("2.1.1.1 TipoDocumento -> it.document_type", lambda i: i.it.document_type, TipoDocumento.TD01),
    ("2.1.1.1 TipoDocumento -> BT-3 (App. 5.4)", lambda i: i.type_code, "380"),
    ("2.1.1.2 Divisa -> BT-5", lambda i: i.currency_code, "EUR"),
    ("2.1.1.3 Data -> BT-2", lambda i: i.issue_date, datetime.date(2026, 1, 15)),
    ("2.1.1.4 Numero -> BT-1", lambda i: i.number, "FT-1"),
    ("2.1.1.9 ImportoTotaleDocumento -> BT-112", lambda i: i.totals.total_with_vat, D("119.80")),
    ("2.1.1.10 Arrotondamento -> BT-114", lambda i: i.totals.rounding_amount, D("0.00")),
    ("2.1.1.11 Causale -> BT-22", lambda i: [n.note for n in i.notes], ["First note", "Second note"]),
    ("2.1.2.2 DatiOrdineAcquisto/IdDocumento -> BT-13", lambda i: i.purchase_order_reference, "PO-1"),
    ("2.1.3.2 DatiContratto/IdDocumento -> BT-12", lambda i: i.contract_reference, "C-1"),
    ("2.1.3.6 CodiceCUP -> BT-11", lambda i: i.project_reference, "CUP-1"),
    ("2.1.3.7 CodiceCIG -> BT-17", lambda i: i.tender_or_lot_reference, "CIG-1"),
    (
        "2.1.4.2 DatiConvenzione/IdDocumento -> BT-18 (AVV)",
        lambda i: i.invoiced_object_identifier.model_dump(),
        {"value": "CV-1", "scheme_id": "AVV"},
    ),
    ("2.1.5.2 DatiRicezione/IdDocumento -> BT-15", lambda i: i.receiving_advice_reference, "R-1"),
    (
        "2.1.6.2 DatiFattureCollegate/IdDocumento -> BT-25",
        lambda i: i.preceding_invoice_references[0].reference,
        "FT-0",
    ),
    (
        "2.1.6.3 DatiFattureCollegate/Data -> BT-26",
        lambda i: i.preceding_invoice_references[0].issue_date,
        datetime.date(2025, 12, 1),
    ),
    ("2.1.8.1 NumeroDDT -> BT-16", lambda i: i.despatch_advice_reference, "DDT-1"),
    (
        "2.1.9.12 IndirizzoResa -> BG-15",
        lambda i: i.delivery.deliver_to_address.model_dump(exclude_none=True),
        {
            "address_line_1": "Via Consegna",
            "address_line_2": "2",
            "post_code": "20100",
            "city": "Milano",
            "country_subdivision": "MI",
            "country_code": "IT",
        },
    ),
    ("2.1.9.13 DataOraConsegna -> BT-72", lambda i: i.delivery.actual_delivery_date, datetime.date(2026, 1, 12)),
    ("2.2.1.1 NumeroLinea -> BT-126", lambda i: [x.identifier for x in i.lines], ["1", "2"]),
    (
        "2.2.1.2 TipoCessionePrestazione -> line it.supply_type",
        lambda i: i.lines[0].it.supply_type,
        TipoCessionePrestazione.AC,
    ),
    ("2.2.1.3 CodiceArticolo -> BT-155", lambda i: i.lines[0].item.sellers_identifier, "SKU-1"),
    ("2.2.1.4 Descrizione -> BT-153", lambda i: i.lines[0].item.name, "Ticket"),
    ("2.2.1.5 Quantita -> BT-129", lambda i: i.lines[0].invoiced_quantity, D("2.00")),
    ("2.2.1.6 UnitaMisura -> BT-130", lambda i: i.lines[0].invoiced_quantity_unit_code, "C62"),
    ("2.2.1.7 DataInizioPeriodo -> BT-134", lambda i: i.lines[0].period.start_date, datetime.date(2026, 1, 1)),
    ("2.2.1.8 DataFinePeriodo -> BT-135", lambda i: i.lines[0].period.end_date, datetime.date(2026, 1, 31)),
    ("2.2.1.9 PrezzoUnitario -> BT-148", lambda i: i.lines[0].price_details.item_gross_price, D("50.00")),
    ("2.2.1.10 ScontoMaggiorazione SC -> BT-147", lambda i: i.lines[0].price_details.item_price_discount, D("5.00")),
    ("2.2.1.9/10 -> BT-146", lambda i: i.lines[0].price_details.item_net_price, D("45.00")),
    ("2.2.1.9 PrezzoUnitario -> BT-146 (no discount)", lambda i: i.lines[1].price_details.item_net_price, D("10.00")),
    ("2.2.1.11 PrezzoTotale -> BT-131", lambda i: [x.net_amount for x in i.lines], [D("90.00"), D("10.00")]),
    ("2.2.1.12 AliquotaIVA -> BT-152", lambda i: [x.vat_information.rate for x in i.lines], [D("22.00"), D("0.00")]),
    ("2.2.1.14 Natura -> line it.nature", lambda i: i.lines[1].it.nature, Natura.N2_2),
    ("2.2.1.14 Natura -> BT-151 (App. 5.1)", lambda i: [x.vat_information.category_code for x in i.lines], ["S", "E"]),
    ("2.2.1.15 RiferimentoAmministrazione -> BT-133", lambda i: i.lines[0].buyer_accounting_reference, "ACC-1"),
    (
        "2.2.1.16 AltriDatiGestionali -> BG-32",
        lambda i: [(a.name, a.value) for a in i.lines[0].item.attributes],
        [("CUSTOM", "Row text")],
    ),
    ("2.2.2.1 AliquotaIVA -> BT-119", lambda i: [g.rate for g in i.vat_breakdown], [D("22.00"), D("0.00")]),
    (
        "2.2.2.2 Natura -> BT-118, BT-120, BT-121 (App. 5.1)",
        lambda i: [(g.category_code, g.exemption_reason, g.exemption_reason_code) for g in i.vat_breakdown],
        [("S", None, None), ("E", "N2.2 Art. 7 DPR 633/72", "VATEX-EU-132")],
    ),
    (
        "2.2.2.5 ImponibileImporto -> BT-116",
        lambda i: [g.taxable_amount for g in i.vat_breakdown],
        [D("90.00"), D("10.00")],
    ),
    ("2.2.2.6 Imposta -> BT-117", lambda i: [g.tax_amount for g in i.vat_breakdown], [D("19.80"), D("0.00")]),
    ("2.2.2.7 EsigibilitaIVA -> it.vat_summaries", lambda i: i.it.vat_summaries[0].vat_chargeability, EsigibilitaIVA.I),
    (
        "2.2.2.8 RiferimentoNormativo -> it.vat_summaries",
        lambda i: i.it.vat_summaries[1].legal_reference,
        "Art. 7 DPR 633/72",
    ),
    ("2.4.1 CondizioniPagamento -> it.payment", lambda i: i.it.payment.conditions, CondizioniPagamento.TP02),
    ("2.4.1 + 2.4.2.4 CondizioniPagamento, GiorniTerminiPagamento -> BT-20", lambda i: i.payment_terms, "TP02 30"),
    ("2.4.2.1 Beneficiario -> BT-59", lambda i: i.payee.name, "Payee Srl"),
    ("2.4.2.8-9 Cognome/NomeQuietanzante -> BT-60", lambda i: i.payee.identifier.value, "Rossi Anna"),
    (
        "2.4.2.10 CFQuietanzante -> BT-61",
        lambda i: i.payee.legal_registration_identifier.model_dump(),
        {"value": "BBBBBB00B00B000B", "scheme_id": "0210"},
    ),
    ("2.1.2.5 CodiceCommessaConvenzione -> BT-10", lambda i: i.buyer_reference, "BR-1"),
    ("2.4.2.2 ModalitaPagamento -> it.payment.method", lambda i: i.it.payment.method, ModalitaPagamento.MP05),
    ("2.4.2.2 ModalitaPagamento -> BT-81", lambda i: i.payment_instructions.payment_means_type_code, "30"),
    ("2.4.2.5 DataScadenzaPagamento -> BT-9", lambda i: i.payment_due_date, datetime.date(2026, 2, 15)),
    ("2.4.2.6 ImportoPagamento -> BT-115", lambda i: i.totals.amount_due, D("119.80")),
    (
        "2.4.2.13 IBAN -> BT-84",
        lambda i: i.payment_instructions.credit_transfers[0].payment_account_identifier,
        "DE02120300000000202051",
    ),
    (
        "2.4.2.16 BIC -> BT-86",
        lambda i: i.payment_instructions.credit_transfers[0].payment_service_provider_identifier,
        "BYLADEM1001",
    ),
    ("2.4.2.21 CodicePagamento -> BT-83", lambda i: i.payment_instructions.remittance_information, "RF-1"),
    ("BT-24: EN 16931 core (#132 item 7)", lambda i: i.process_control.specification_identifier, SPECIFICATION),
    ("2.2.2.7 EsigibilitaIVA I -> no BT-8 (3 or 35)", lambda i: i.vat_point_date_code, None),
    ("BT-106 derived (BR-CO-10)", lambda i: i.totals.sum_of_line_net_amounts, D("100.00")),
    ("BT-109 derived (BR-CO-13)", lambda i: i.totals.total_without_vat, D("100.00")),
    ("BT-110 derived (BR-CO-14)", lambda i: i.totals.total_vat, D("19.80")),
]


@pytest.fixture(scope="module")
def full() -> Invoice:
    return parse(FULL)


@pytest.mark.parametrize(("row", "get", "expected"), ROWS, ids=[row for row, _, _ in ROWS])
def test_row(row: str, get: Callable[[t.Any], object], expected: object, full: Invoice) -> None:
    assert get(full) == expected


def test_full_reports_only_what_has_no_model_home() -> None:
    assert parse_detailed(FULL).unmapped == (
        "/p:FatturaElettronica/FatturaElettronicaHeader/DatiTrasmissione",  # writer options (#118)
        "/p:FatturaElettronica/FatturaElettronicaBody/DatiGenerali/DatiDDT/DataDDT",  # EXT
        "/p:FatturaElettronica/FatturaElettronicaBody/DatiGenerali/DatiTrasporto/DataOraConsegna/text()",  # the time
    )


def test_full_is_consistent_for_the_cen_calculation_rules(full: Invoice) -> None:
    assert calc.check(full) == ()


@pytest.mark.parametrize("nature", list(NATURE_CATEGORY), ids=str)
def test_natura_gives_the_app_5_1_category_and_exemption_code(nature: Natura) -> None:
    data = natura_document(nature.value)

    invoice = parse(data)

    category, code = NATURE_CATEGORY[nature]
    assert invoice.lines[0].vat_information.category_code == category
    (group,) = invoice.vat_breakdown
    # App. 5.1: BT-120 is the Natura code, except for N1 (Z), whose row has none (BR-Z-10 forbids it).
    reason = None if category == "Z" else nature
    assert (group.category_code, group.exemption_reason_code, group.exemption_reason) == (category, code, reason)
    assert invoice.lines[0].it is not None
    assert invoice.lines[0].it.nature is nature


@pytest.mark.parametrize("tipo", list(TipoDocumento), ids=str)
def test_tipo_documento_gives_the_app_5_4_type_code(tipo: TipoDocumento) -> None:
    invoice = parse(document(body(tipo=tipo.value)))

    assert (invoice.type_code, invoice.it.document_type if invoice.it else None) == (TYPE_CODE[tipo], tipo)


def test_split_payment_summary_makes_category_b() -> None:
    data = VARIANTS["split payment"]

    invoice = parse(data)

    assert invoice.lines[0].vat_information.category_code == "B"
    assert invoice.vat_breakdown[0].category_code == "B"
    assert invoice.it is not None
    assert invoice.it.vat_summaries[0].vat_chargeability is EsigibilitaIVA.S


def test_a_natural_person_name_is_nome_cognome() -> None:
    data = VARIANTS["person"]

    result = parse_detailed(data)

    assert result.invoice.buyer.name == "Mario De Rossi"
    anagrafica = "/p:FatturaElettronica/FatturaElettronicaHeader/CessionarioCommittente/DatiAnagrafici/Anagrafica"
    assert result.unmapped[1:] == (f"{anagrafica}/Nome", f"{anagrafica}/Cognome", f"{anagrafica}/Titolo")


def test_a_foreign_seller_reads_with_the_core_bt_24() -> None:
    data = VARIANTS["foreign seller"]

    invoice = parse(data)

    assert invoice.process_control.specification_identifier == SPECIFICATION
    assert invoice.seller.vat_identifier == "DE00000000001"


def test_quantity_absent_is_one_and_units_default_to_c62() -> None:
    data = VARIANTS["no quantity"]

    (invoice_line,) = parse(data).lines

    assert (invoice_line.invoiced_quantity, invoice_line.invoiced_quantity_unit_code) == (D(1), "C62")


def test_a_rec_20_unit_is_kept() -> None:
    data = VARIANTS["unit HUR"]

    assert parse(data).lines[0].invoiced_quantity_unit_code == "HUR"


@pytest.mark.parametrize(
    ("adjustment", "net", "discount"),
    [
        ("<Tipo>SC</Tipo><Percentuale>10.00</Percentuale>", D("45.0000"), D("5.0000")),
        ("<Tipo>MG</Tipo><Importo>5.00</Importo>", D("55.00"), D("-5.00")),
        ("<Tipo>MG</Tipo><Percentuale>10.00</Percentuale>", D("55.0000"), D("-5.0000")),
    ],
    ids=["SC percentage", "MG amount", "MG percentage"],
)
def test_one_line_adjustment_reads_as_a_price_discount(adjustment: str, net: Decimal, discount: Decimal) -> None:
    data = adjusted_document(adjustment, "90.00" if net < 50 else "110.00")

    price = parse(data).lines[0].price_details

    assert (price.item_gross_price, price.item_price_discount, price.item_net_price) == (D("50.00"), discount, net)


def test_codice_articolo_with_a_type_is_prefixed() -> None:
    data = VARIANTS["article CARB"]

    assert parse(data).lines[0].item.sellers_identifier == "CARB:27101249"


@pytest.mark.parametrize(
    ("reference", "value"),
    [
        ("<RiferimentoNumero> 12.50 </RiferimentoNumero>", "12.50"),
        ("<RiferimentoData>2026-01-01</RiferimentoData>", "2026-01-01"),
    ],
)
def test_altri_dati_gestionali_numbers_and_dates(reference: str, value: str) -> None:
    data = other_data_document(reference)

    assert [(a.name, a.value) for a in parse(data).lines[0].item.attributes] == [("KIND", value)]


@pytest.mark.parametrize(("method", "means"), [("MP01", "10"), ("MP19", "59"), ("MP23", "9"), ("MP09", "1")])
def test_modalita_pagamento_gives_bt_81(method: str, means: str) -> None:
    data = payment_document(method)

    invoice = parse(data)

    assert invoice.payment_instructions is not None
    assert invoice.payment_instructions.payment_means_type_code == means
    assert invoice.payment_instructions.credit_transfers == ()
    assert invoice.it is not None
    assert invoice.it.payment is not None
    assert invoice.it.payment.method == method


def test_without_payment_data_the_totals_are_derived() -> None:
    invoice = parse(document())

    assert (invoice.payment_instructions, invoice.it.payment if invoice.it else None) == (None, None)
    assert (invoice.totals.total_with_vat, invoice.totals.amount_due) == (D("122.00"), D("122.00"))


def test_a_credit_note_reads_as_381() -> None:
    data = VARIANTS["credit note"]

    assert parse(data).type_code == "381"


def test_deferred_vat_gives_bt_8_432() -> None:
    # Row 2.2.2.7: "Se BT-8 = 432 allora <EsigibilitaIVA> = D".
    assert parse(VARIANTS["deferred VAT"]).vat_point_date_code == "432"


def test_mp05_without_iban_is_no_credit_transfer_code() -> None:
    # BR-61 requires BT-84 for 30 and 58; App. 5.6 row 15 (Bookentry credit) also maps to MP05.
    invoice = parse(VARIANTS["MP05 without IBAN"])

    assert invoice.payment_instructions is not None
    assert (invoice.payment_instructions.payment_means_type_code, invoice.payment_instructions.credit_transfers) == (
        "15",
        (),
    )


def test_two_natura_of_one_category_make_one_vat_breakdown() -> None:
    invoice = parse(VARIANTS["two Natura in category E"])

    (group,) = invoice.vat_breakdown
    assert (group.category_code, group.rate, group.taxable_amount, group.tax_amount) == ("E", D(0), D(200), D(0))
    assert (group.exemption_reason, group.exemption_reason_code) == ("N4 Art. 10; N2.2", "VATEX-EU-132")
    assert invoice.it is not None
    assert [(s.nature, s.legal_reference) for s in invoice.it.vat_summaries] == [
        (Natura.N4, "Art. 10"),
        (Natura.N2_2, None),
    ]


def test_a_negative_unit_price_reads_as_a_negative_quantity() -> None:
    invoice = parse(VARIANTS["negative unit price"])

    discount = invoice.lines[1]
    assert (discount.invoiced_quantity, discount.price_details.item_net_price, discount.net_amount) == (
        D("-1.00"),
        D("10.00"),
        D("-10.00"),
    )
    assert (invoice.vat_breakdown[0].taxable_amount, invoice.totals.total_with_vat) == (D("90.00"), D("109.80"))


def test_a_negative_unit_price_with_an_adjustment_keeps_the_line_amount() -> None:
    line = parse(VARIANTS["negative unit price with an adjustment"]).lines[0]
    price = line.price_details

    assert (line.invoiced_quantity, price.item_gross_price, price.item_price_discount, price.item_net_price) == (
        D("-1.00"),
        D("10.00"),
        D("-1.00"),
        D("11.00"),
    )
    assert line.invoiced_quantity * price.item_net_price == line.net_amount


def test_stamp_duty_is_a_zero_charge_with_its_z_breakdown() -> None:
    # Row 2.1.1.6 and BR-IT-DC-480: BT-105 SAE, BT-104 BOLLO, BT-99 0, category Z; BR-Z-01 needs a Z BG-23.
    invoice = parse(VARIANTS["stamp duty"])

    (charge,) = invoice.charges
    assert (charge.reason_code, charge.reason, charge.amount, charge.vat_category_code) == ("SAE", "BOLLO", D(0), "Z")
    assert [(g.category_code, g.taxable_amount) for g in invoice.vat_breakdown] == [("S", D(100)), ("Z", D(0))]
    assert (invoice.totals.sum_of_charges, invoice.totals.total_without_vat) == (D(0), D(100))


def test_stamp_duty_on_a_credit_note_is_a_zero_allowance() -> None:
    # Row 2.1.1.6.1: "Per la Nota di credito: se BT-98 = 95 allora BolloVirtuale = SI".
    result = parse_detailed(VARIANTS["stamp duty on a credit note"])

    (allowance,) = result.invoice.allowances
    assert (allowance.reason_code, allowance.amount, result.invoice.charges) == ("95", D(0), ())
    assert result.unmapped[1:] == (
        "/p:FatturaElettronica/FatturaElettronicaBody/DatiGenerali/DatiGeneraliDocumento/DatiBollo/ImportoBollo",
    )


def test_a_receipt_referring_to_a_line_still_gives_bt_15() -> None:
    # Row 2.1.5.1 RiferimentoNumeroLinea is "Mappatura non considerabile"; row 2.1.5.2 has no "se unico" condition.
    result = parse_detailed(VARIANTS["line-level receipt"])

    assert result.invoice.receiving_advice_reference == "R-1"
    assert result.unmapped[1:] == (
        "/p:FatturaElettronica/FatturaElettronicaBody/DatiGenerali/DatiRicezione/RiferimentoNumeroLinea",
    )


def test_a_payee_that_is_the_seller_is_no_bg_10() -> None:
    # BG-10 is for a payee other than the seller (UBL-SR-19..21, BR-17).
    result = parse_detailed(VARIANTS["payee is the seller"])

    assert result.invoice.payee is None
    assert result.unmapped[1:] == (
        "/p:FatturaElettronica/FatturaElettronicaBody/DatiPagamento/DettaglioPagamento/Beneficiario",
    )


def test_a_social_security_fund_is_a_document_level_charge() -> None:
    # App. 4.1 rows 2.1.1.7.1-7: BT-99 ImportoContributoCassa, BT-100 ImponibileCassa, BT-101 AlCassa, BT-103
    # AliquotaIVA, BT-104 TipoCassa / Ritenuta / Natura; the declared summary 104.00 then meets BR-S-08 as declared.
    invoice = parse(VARIANTS["professional with a fund"])

    (charge,) = invoice.charges
    assert (charge.amount, charge.base_amount, charge.percentage) == (D("4.00"), D("100.00"), D("4.00"))
    assert (charge.vat_category_code, charge.vat_rate, charge.reason) == ("S", D("22.00"), "TC04")
    assert (invoice.totals.sum_of_charges, invoice.totals.total_without_vat, invoice.totals.total_vat) == (
        D(4),
        D(104),
        D("22.88"),
    )
    assert (invoice.totals.total_with_vat, invoice.totals.amount_due) == (D("126.88"), D("126.88"))
    assert calc.check(invoice) == ()


def test_a_fund_with_natura_takes_its_app_5_1_category() -> None:
    invoice = parse(VARIANTS["fund at another rate with Natura"])

    (charge,) = invoice.charges
    assert (charge.vat_category_code, charge.vat_rate, charge.reason) == ("E", D(0), "TC04 N4")
    assert [(g.category_code, g.taxable_amount) for g in invoice.vat_breakdown] == [("S", D(100)), ("E", D(4))]
    assert calc.check(invoice) == ()


def test_a_fund_subject_to_withholding_says_so_in_bt_104() -> None:
    (charge,) = parse(VARIANTS["professional with a fund and withholding"]).charges

    assert charge.reason == "TC04 SI"


def test_split_payment_and_ordinary_vat_at_two_rates_read_as_b_and_s() -> None:
    # Each rate has one payment mode (row 2.2.2.7), so each line's category is decidable; EN forbids B next to S
    # (BR-B-02), which validation reports on the declared document (#132 item 22).
    invoice = parse(VARIANTS["split payment and ordinary VAT at two rates"])

    assert [x.vat_information.category_code for x in invoice.lines] == ["B", "S"]
    assert [(g.category_code, g.rate) for g in invoice.vat_breakdown] == [("B", D(22)), ("S", D(10))]
    assert "BR-B-02" in {f.rule_id for f in calc.check(invoice)}
