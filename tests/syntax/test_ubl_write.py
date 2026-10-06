"""Behaviour of the UBL writer beyond the per-BT table: root choice, credit notes, layout and refusals."""

import datetime
import typing as t
from decimal import Decimal

import pytest
from _ubl_support import written, xpath
from lxml import etree

from _invoices import TEST_IBAN, minimal_invoice, simple_line
from euinvoice import _xml
from euinvoice.errors import ModelError
from euinvoice.model import (
    AdditionalSupportingDocument,
    BinaryObject,
    CreditTransfer,
    DeliveryInformation,
    DirectDebit,
    DocumentTotals,
    Identifier,
    InvoiceLineAllowance,
    InvoiceNote,
    InvoicingPeriod,
    ItemInformation,
    PaymentCardInformation,
    PaymentInstructions,
    PriceDetails,
)
from euinvoice.model.codes import UNTDID_1001_CREDIT_NOTE_TYPE_UBL, UNTDID_1001_INVOICE_TYPE_UBL
from euinvoice.syntax import ubl
from euinvoice.syntax.ubl._write import is_credit_note


def _totals(**changes: t.Any) -> DocumentTotals:
    """The minimal invoice's totals with ``changes``."""
    return DocumentTotals.model_validate({**dict(minimal_invoice().totals), **changes})


def _price(**changes: t.Any) -> PriceDetails:
    return PriceDetails(**{"item_net_price": Decimal("50"), **changes})


def _item(**changes: t.Any) -> ItemInformation:
    return ItemInformation(**{"name": "Widget", **changes})


def _payment(**changes: t.Any) -> PaymentInstructions:
    return PaymentInstructions(**{"payment_means_type_code": "58", **changes})


DAY = datetime.date(2026, 2, 14)


def _local_names(element: etree._Element) -> list[str]:
    return [etree.QName(child).localname for child in element]


@pytest.mark.parametrize("code", sorted(UNTDID_1001_CREDIT_NOTE_TYPE_UBL))
def test_credit_note_codes_write_a_credit_note(code: str) -> None:
    root = written(minimal_invoice(type_code=code))
    assert root.tag == f"{{{_xml.UBL_CREDIT_NOTE}}}CreditNote"
    assert xpath(root, "string(/*/cbc:CreditNoteTypeCode)") == code


@pytest.mark.parametrize("code", sorted(UNTDID_1001_INVOICE_TYPE_UBL - UNTDID_1001_CREDIT_NOTE_TYPE_UBL))
def test_other_codes_write_an_invoice(code: str) -> None:
    root = written(minimal_invoice(type_code=code))
    assert root.tag == f"{{{_xml.UBL_INVOICE}}}Invoice"
    assert xpath(root, "string(/*/cbc:InvoiceTypeCode)") == code


def test_code_81_is_in_both_lists_and_goes_to_credit_note() -> None:
    # Binding decision on issue #10: CEN accepts either root, Peppol only CreditNote (P0101).
    assert "81" in UNTDID_1001_INVOICE_TYPE_UBL
    assert is_credit_note("81")


def test_credit_note_uses_credit_note_line_and_credited_quantity() -> None:
    root = written(minimal_invoice(type_code="381"))
    assert xpath(root, "count(/*/cac:InvoiceLine)") == 0
    assert xpath(root, "string(/*/cac:CreditNoteLine/cbc:CreditedQuantity)") == "2"
    assert xpath(root, "string(/*/cac:CreditNoteLine/cbc:CreditedQuantity/@unitCode)") == "C62"


def test_credit_note_header_follows_credit_note_type_sequence() -> None:
    root = written(
        minimal_invoice(
            type_code="381", vat_point_date=DAY, notes=(InvoiceNote(note="n"),), payment_instructions=_payment()
        )
    )
    names = _local_names(root)
    assert names[names.index("IssueDate") :][:4] == ["IssueDate", "TaxPointDate", "CreditNoteTypeCode", "Note"]
    assert "DueDate" not in names


def test_invoice_header_follows_invoice_type_sequence() -> None:
    root = written(minimal_invoice(vat_point_date=DAY, payment_due_date=DAY, notes=(InvoiceNote(note="n"),)))
    names = _local_names(root)
    assert names[names.index("IssueDate") :][:5] == ["IssueDate", "DueDate", "InvoiceTypeCode", "Note", "TaxPointDate"]


def test_credit_note_due_date_goes_into_the_first_payment_means() -> None:
    transfers = (CreditTransfer(payment_account_identifier=TEST_IBAN), CreditTransfer(payment_account_identifier="X"))
    root = written(
        minimal_invoice(
            type_code="381", payment_due_date=DAY, payment_instructions=_payment(credit_transfers=transfers)
        )
    )
    assert xpath(root, "string(/*/cac:PaymentMeans[1]/cbc:PaymentDueDate)") == "2026-02-14"
    assert xpath(root, "count(//cbc:PaymentDueDate)") == 1


def test_credit_note_due_date_without_payment_instructions_is_refused() -> None:
    with pytest.raises(ModelError, match=r"^BT-9 cannot be written in UBL: .*BG-16"):
        ubl.write(minimal_invoice(type_code="381", payment_due_date=DAY))


def test_credit_note_project_and_tender_references() -> None:
    root = written(minimal_invoice(type_code="381", project_reference="P-1", tender_or_lot_reference="LOT-1"))
    assert xpath(root, "string(/*/cac:AdditionalDocumentReference[cbc:DocumentTypeCode='50']/cbc:ID)") == "P-1"
    assert xpath(root, "count(/*/cac:ProjectReference)") == 0
    names = _local_names(root)
    assert names.index("OriginatorDocumentReference") > names.index("AdditionalDocumentReference")


def test_invoice_writes_tender_reference_before_contract_reference() -> None:
    names = _local_names(written(minimal_invoice(tender_or_lot_reference="LOT-1", contract_reference="C-1")))
    assert names.index("OriginatorDocumentReference") < names.index("ContractDocumentReference")


@pytest.mark.parametrize(
    ("note", "text"),
    [
        (InvoiceNote(subject_code="AAI"), "#AAI#"),
        (InvoiceNote(subject_code="AAI", note="body"), "#AAI#body"),
        (InvoiceNote(note="#not a code"), "#not a code"),
    ],
)
def test_note_subject_code_is_the_hash_prefix(note: InvoiceNote, text: str) -> None:
    assert xpath(written(minimal_invoice(notes=(note,))), "string(/*/cbc:Note)") == text


def test_sales_order_reference_alone_gets_na_order_id() -> None:
    root = written(minimal_invoice(sales_order_reference="SO-1"))
    assert xpath(root, "string(/*/cac:OrderReference/cbc:ID)") == "NA"
    assert xpath(root, "string(/*/cac:OrderReference/cbc:SalesOrderID)") == "SO-1"


def test_card_network_id_is_na() -> None:
    card = PaymentCardInformation(primary_account_number="******1234")
    root = written(minimal_invoice(payment_instructions=_payment(payment_means_type_code="48", payment_card=card)))
    assert xpath(root, "string(/*/cac:PaymentMeans/cac:CardAccount/cbc:NetworkID)") == "NA"
    assert xpath(root, "count(/*/cac:PaymentMeans/cac:CardAccount/cbc:HolderName)") == 0


def test_card_without_primary_account_number_is_refused() -> None:
    instructions = _payment(payment_means_type_code="48", payment_card=PaymentCardInformation(holder_name="A"))
    with pytest.raises(ModelError, match=r"^BT-87 cannot be written in UBL: .*M2"):
        ubl.write(minimal_invoice(payment_instructions=instructions))


def test_one_payment_means_per_credit_transfer() -> None:
    instructions = _payment(
        payment_means_text="Transfer",
        remittance_information="REF",
        credit_transfers=(
            CreditTransfer(payment_account_identifier=TEST_IBAN),
            CreditTransfer(payment_account_identifier="X"),
        ),
        payment_card=PaymentCardInformation(primary_account_number="1234"),
        direct_debit=DirectDebit(mandate_reference_identifier="M"),
    )
    root = written(minimal_invoice(payment_instructions=instructions))
    assert xpath(root, "/*/cac:PaymentMeans/cbc:PaymentMeansCode/text()") == ["58", "58"]
    assert xpath(root, "/*/cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID/text()") == [TEST_IBAN, "X"]
    second = xpath(root, "/*/cac:PaymentMeans[2]")[0]
    assert _local_names(second) == ["PaymentMeansCode", "PayeeFinancialAccount"]
    assert xpath(second, "count(cbc:PaymentMeansCode/@name)") == 0


def test_payment_means_without_credit_transfer() -> None:
    root = written(minimal_invoice(payment_instructions=_payment(payment_means_type_code="1")))
    assert _local_names(xpath(root, "/*/cac:PaymentMeans")[0]) == ["PaymentMeansCode"]


def test_creditor_identifier_alone_writes_no_mandate() -> None:
    debit = DirectDebit(bank_assigned_creditor_identifier="DE98ZZZ09999999999")
    root = written(minimal_invoice(payment_instructions=_payment(payment_means_type_code="59", direct_debit=debit)))
    assert xpath(root, "count(//cac:PaymentMandate)") == 0
    assert xpath(root, "string(//cac:PartyIdentification/cbc:ID[@schemeID='SEPA'])") == "DE98ZZZ09999999999"


def test_mandate_without_debited_account() -> None:
    debit = DirectDebit(mandate_reference_identifier="M-1")
    root = written(minimal_invoice(payment_instructions=_payment(payment_means_type_code="59", direct_debit=debit)))
    assert _local_names(xpath(root, "//cac:PaymentMandate")[0]) == ["ID"]


def test_invoicing_period_alone_writes_no_delivery() -> None:
    period = InvoicingPeriod(start_date=datetime.date(2026, 1, 1))
    root = written(minimal_invoice(delivery=DeliveryInformation(invoicing_period=period), vat_point_date_code="3"))
    assert xpath(root, "count(/*/cac:Delivery)") == 0
    assert _local_names(xpath(root, "/*/cac:InvoicePeriod")[0]) == ["StartDate", "DescriptionCode"]


def test_delivery_party_name_alone_writes_no_location() -> None:
    root = written(minimal_invoice(delivery=DeliveryInformation(deliver_to_party_name="W")))
    assert _local_names(xpath(root, "/*/cac:Delivery")[0]) == ["DeliveryParty"]


def test_delivery_location_identifier_alone_writes_no_address() -> None:
    delivery = DeliveryInformation(deliver_to_location_identifier=Identifier(value="LOC-1"))
    root = written(minimal_invoice(delivery=delivery))
    assert _local_names(xpath(root, "/*/cac:Delivery/cac:DeliveryLocation")[0]) == ["ID"]


def test_total_vat_is_required() -> None:
    with pytest.raises(ModelError, match=r"^BT-110 cannot be written in UBL"):
        ubl.write(minimal_invoice(totals=_totals(total_vat=None)))


def test_accounting_currency_total_needs_its_currency() -> None:
    with pytest.raises(ModelError, match=r"^BT-111 cannot be written in UBL: .*BT-6"):
        ubl.write(minimal_invoice(totals=_totals(total_vat_in_accounting_currency=Decimal("1.00"))))


def test_accounting_currency_total_has_its_own_tax_total_without_subtotals() -> None:
    root = written(
        minimal_invoice(
            vat_accounting_currency_code="SEK", totals=_totals(total_vat_in_accounting_currency=Decimal("210.00"))
        )
    )
    assert xpath(root, "count(/*/cac:TaxTotal)") == 2
    second = xpath(root, "/*/cac:TaxTotal[2]")[0]
    assert _local_names(second) == ["TaxAmount"]
    assert xpath(second, "string(cbc:TaxAmount/@currencyID)") == "SEK"


@pytest.mark.parametrize(("mime", "filename"), [(None, "a.pdf"), ("application/pdf", None)])
def test_attachment_needs_mime_code_and_filename(mime: str | None, filename: str | None) -> None:
    document = AdditionalSupportingDocument(
        reference="D", attached_document=BinaryObject(content=b"x", mime_code=mime, filename=filename)
    )
    with pytest.raises(ModelError, match=r"^BT-125 cannot be written in UBL: .*M3"):
        ubl.write(minimal_invoice(additional_supporting_documents=(document,)))


def test_supporting_document_reference_alone_has_no_attachment() -> None:
    root = written(minimal_invoice(additional_supporting_documents=(AdditionalSupportingDocument(reference="D"),)))
    assert _local_names(xpath(root, "/*/cac:AdditionalDocumentReference")[0]) == ["ID"]


def test_base_quantity_unit_needs_base_quantity() -> None:
    with pytest.raises(ModelError, match=r"^BT-150 cannot be written in UBL: .*BT-149"):
        ubl.write(minimal_invoice(lines=(simple_line(price_details=_price(base_quantity_unit_code="C62")),)))


@pytest.mark.parametrize(
    ("net", "gross", "discount"),
    [("50", "50", "0.00"), ("50", "50.00", "0.00"), ("49.9", "50.50", "0.60"), ("1.2345", "2", "0.7655")],
)
def test_gross_price_without_discount_writes_the_implied_discount(net: str, gross: str, discount: str) -> None:
    # bt-mapping.md "Normalizations": cbc:Amount is mandatory, so BT-147 = BT-148 - BT-146 (PEPPOL-EN16931-R046).
    details = _price(item_net_price=Decimal(net), item_gross_price=Decimal(gross))
    root = written(minimal_invoice(lines=(simple_line(price_details=details),)))
    allowance = xpath(root, "//cac:Price/cac:AllowanceCharge")[0]
    assert _local_names(allowance) == ["ChargeIndicator", "Amount", "BaseAmount"]
    assert xpath(allowance, "string(cbc:ChargeIndicator)") == "false"
    assert xpath(allowance, "string(cbc:Amount)") == discount
    assert xpath(allowance, "string(cbc:BaseAmount)") == gross


def test_gross_price_below_net_price_is_refused() -> None:
    details = _price(item_net_price=Decimal("50"), item_gross_price=Decimal("49.99"))
    with pytest.raises(ModelError, match=r"^BT-148 cannot be written in UBL: .*R044"):
        ubl.write(minimal_invoice(lines=(simple_line(price_details=details),)))


def test_accounting_currency_equal_to_invoice_currency_without_bt111_is_written() -> None:
    # One cac:TaxTotal only, so the invoice is representable; BR-53 is the validator's job (D8).
    root = written(minimal_invoice(vat_accounting_currency_code="EUR"))
    assert xpath(root, "string(/*/cbc:TaxCurrencyCode)") == "EUR"
    assert xpath(root, "count(/*/cac:TaxTotal)") == 1


def test_accounting_currency_equal_to_invoice_currency_is_refused() -> None:
    document = minimal_invoice(
        vat_accounting_currency_code="EUR", totals=_totals(total_vat_in_accounting_currency=Decimal("19.00"))
    )
    with pytest.raises(ModelError, match=r"^BT-6 cannot be written in UBL: .*BR-CO-15"):
        ubl.write(document)


@pytest.mark.parametrize("note", [InvoiceNote(), InvoiceNote(note="")])
def test_empty_note_is_not_written(note: InvoiceNote) -> None:
    # PEPPOL-EN16931-R008: no empty elements; an empty note carries neither BT-21 nor BT-22.
    root = written(minimal_invoice(notes=(note, InvoiceNote(note="kept"))))
    assert xpath(root, "/*/cbc:Note/text()") == ["kept"]


def test_price_discount_without_gross_price() -> None:
    root = written(minimal_invoice(lines=(simple_line(price_details=_price(item_price_discount=Decimal("1"))),)))
    discount = xpath(root, "//cac:Price/cac:AllowanceCharge")[0]
    assert _local_names(discount) == ["ChargeIndicator", "Amount"]


def test_line_allowance_has_no_tax_category() -> None:
    allowance = InvoiceLineAllowance(amount=Decimal("1.00"), reason="R")
    root = written(minimal_invoice(lines=(simple_line(allowances=(allowance,)),)))
    assert _local_names(xpath(root, "//cac:InvoiceLine/cac:AllowanceCharge")[0]) == [
        "ChargeIndicator",
        "AllowanceChargeReason",
        "Amount",
    ]


def test_numbers_are_fixed_point() -> None:
    root = written(
        minimal_invoice(
            lines=(
                simple_line(invoiced_quantity=Decimal("1E+3"), price_details=_price(item_net_price=Decimal("1E-7"))),
            )
        )
    )
    assert xpath(root, "string(//cbc:InvoicedQuantity)") == "1000"
    assert xpath(root, "string(//cbc:PriceAmount)") == "0.0000001"


def test_output_is_utf8_with_declaration_and_only_ubl_namespaces() -> None:
    out = ubl.write(minimal_invoice(lines=(simple_line(item=_item(name="Wïdget €")),)))
    assert out.startswith(b"<?xml version='1.0' encoding='UTF-8'?>")
    assert "Wïdget €".encode() in out
    root = _xml.parse(out)
    assert root.nsmap == {None: _xml.UBL_INVOICE, "cac": _xml.UBL_CAC, "cbc": _xml.UBL_CBC}
