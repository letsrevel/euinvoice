"""Structure and edge cases of the CII writer (the per-term table is ``test_cii_write_bts.py``)."""

import datetime
import typing as t
from decimal import Decimal

import pytest
from _cii_invoices import TEST_IBAN, all_terms_invoice, full_invoice, minimal_invoice, rebuild
from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ModelError
from euinvoice.model import (
    AdditionalSupportingDocument,
    BinaryObject,
    Buyer,
    BuyerPostalAddress,
    CreditTransfer,
    DeliverToAddress,
    DeliveryInformation,
    DirectDebit,
    DocumentTotals,
    Identifier,
    Invoice,
    InvoiceNote,
    PaymentInstructions,
    PrecedingInvoiceReference,
    PriceDetails,
)
from euinvoice.syntax import Syntax, cii
from euinvoice.syntax.cii._build import VAT_POINT_DATE_CODES, is_iban

STL: t.Final = "//ram:ApplicableHeaderTradeSettlement/"


def written(invoice: Invoice) -> etree._Element:
    """Write ``invoice`` and parse the result back."""
    return _xml.parse(cii.write(invoice))


def select(root: etree._Element, xpath: str) -> list[t.Any]:
    """Evaluate an XPath with the CII prefixes, returning element texts and attribute values as strings."""
    found = t.cast(list[t.Any], root.xpath(xpath, namespaces=_xml.CII_NSMAP))
    return [f if isinstance(f, str) else f.text for f in found]


def with_line(invoice: Invoice, **price: t.Any) -> Invoice:
    """``invoice`` with the price details of its first line replaced."""
    line = invoice.lines[0]
    changed = line.model_validate({**dict(line), "price_details": PriceDetails(**price)})
    return rebuild(invoice, lines=(changed, *invoice.lines[1:]))


def test_syntax_enum() -> None:
    assert Syntax("cii") is Syntax.CII


def test_output_is_utf8_with_declaration_and_cii_root() -> None:
    out = cii.write(minimal_invoice())
    assert out.startswith(b"<?xml version='1.0' encoding='UTF-8'?>")
    root = _xml.parse(out)
    assert root.tag == f"{{{_xml.CII_RSM}}}CrossIndustryInvoice"
    assert root.nsmap == _xml.CII_NSMAP


def test_credit_note_uses_the_same_root_with_its_type_code() -> None:
    root = written(minimal_invoice(type_code="381"))
    assert root.tag == f"{{{_xml.CII_RSM}}}CrossIndustryInvoice"
    assert select(root, "/rsm:CrossIndustryInvoice/rsm:ExchangedDocument/ram:TypeCode") == ["381"]


def test_transaction_children_follow_the_xsd_sequence() -> None:
    transaction = written(full_invoice()).find(f"{{{_xml.CII_RSM}}}SupplyChainTradeTransaction")
    assert transaction is not None
    assert [etree.QName(child).localname for child in transaction] == [
        "IncludedSupplyChainTradeLineItem",
        "IncludedSupplyChainTradeLineItem",
        "ApplicableHeaderTradeAgreement",
        "ApplicableHeaderTradeDelivery",
        "ApplicableHeaderTradeSettlement",
    ]


def test_every_date_uses_format_102() -> None:
    # BT-2, BT-7, BT-9, BT-26, BT-72, BT-73, BT-74, BT-134, BT-135 (binding note on #13).
    root = written(all_terms_invoice())
    dates = root.xpath("//udt:DateTimeString | //udt:DateString | //qdt:DateTimeString", namespaces=_xml.CII_NSMAP)
    assert isinstance(dates, list)
    assert len(dates) == 9
    assert {t.cast(etree._Element, d).get("format") for d in dates} == {"102"}


@pytest.mark.parametrize(("untdid_2005", "untdid_2475"), [("3", "5"), ("35", "29"), ("432", "72")])
def test_vat_point_date_code_is_written_as_untdid_2475(untdid_2005: str, untdid_2475: str) -> None:
    root = written(minimal_invoice(vat_point_date_code=untdid_2005))
    assert select(root, f"{STL}ram:ApplicableTradeTax/ram:DueDateTypeCode") == [untdid_2475]


def test_vat_point_date_code_map_covers_the_model_list() -> None:
    from euinvoice.model.codes import UNTDID_2005_VAT_POINT_DATE_UBL

    assert set(VAT_POINT_DATE_CODES) == set(UNTDID_2005_VAT_POINT_DATE_UBL)


def test_tax_point_date_and_code_only_in_the_first_breakdown() -> None:
    root = written(all_terms_invoice())
    assert len(select(root, f"{STL}ram:ApplicableTradeTax[1]/ram:TaxPointDate/udt:DateString")) == 1
    assert (
        select(root, f"{STL}ram:ApplicableTradeTax[2]/ram:*[self::ram:TaxPointDate or self::ram:DueDateTypeCode]") == []
    )


def test_only_tax_total_amounts_carry_a_currency() -> None:
    # CII-DT-031 forbids @currencyID on every amount except ram:TaxTotalAmount.
    root = written(all_terms_invoice())
    assert {etree.QName(e).localname for e in root.iter() if e.get("currencyID") is not None} == {"TaxTotalAmount"}


def test_minimal_invoice_writes_only_the_mandatory_structure() -> None:
    root = written(minimal_invoice())
    assert select(root, "//ram:ApplicableHeaderTradeDelivery/*") == []
    assert select(root, f"{STL}ram:SpecifiedTradePaymentTerms") == []
    assert select(root, f"{STL}ram:SpecifiedTradeSettlementPaymentMeans") == []
    assert select(root, "//ram:BusinessProcessSpecifiedDocumentContextParameter") == []


def test_decimals_never_use_exponent_notation() -> None:
    totals = DocumentTotals(
        sum_of_line_net_amounts=Decimal("1E+2"),
        total_without_vat=Decimal("100"),
        total_with_vat=Decimal("119"),
        amount_due=Decimal("119"),
    )
    root = written(minimal_invoice(totals=totals))
    assert select(root, f"{STL}ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:LineTotalAmount") == ["100"]


def test_note_with_subject_code_only() -> None:
    root = written(minimal_invoice(notes=(InvoiceNote(subject_code="AAI"),)))
    assert select(root, "//rsm:ExchangedDocument/ram:IncludedNote/*") == ["AAI"]


def test_identifiers_without_scheme_use_ram_id() -> None:
    buyer = Buyer(
        name="Buyer Example AG",
        identifier=Identifier(value="BUYER-1"),
        postal_address=BuyerPostalAddress(country_code="DE"),
    )
    delivery = DeliveryInformation(deliver_to_location_identifier=Identifier(value="LOC-1"))
    root = written(minimal_invoice(buyer=buyer, delivery=delivery))
    assert select(root, "//ram:BuyerTradeParty/ram:ID") == ["BUYER-1"]
    assert select(root, "//ram:ShipToTradeParty/ram:ID") == ["LOC-1"]
    assert select(root, "//ram:BuyerTradeParty/ram:GlobalID | //ram:ShipToTradeParty/ram:GlobalID") == []


def test_seller_ids_without_scheme_precede_global_ids() -> None:
    root = written(full_invoice())
    party = root.xpath("//ram:SellerTradeParty/*", namespaces=_xml.CII_NSMAP)
    assert isinstance(party, list)
    assert [etree.QName(t.cast(etree._Element, e)).localname for e in party][:3] == ["ID", "GlobalID", "Name"]


def test_deliver_to_address_alone_makes_a_ship_to_party() -> None:
    delivery = DeliveryInformation(deliver_to_address=DeliverToAddress(country_code="FR"))
    root = written(minimal_invoice(delivery=delivery))
    assert select(root, "//ram:ShipToTradeParty/ram:PostalTradeAddress/ram:CountryID") == ["FR"]


def test_delivery_without_ship_to_terms() -> None:
    root = written(minimal_invoice(delivery=DeliveryInformation(actual_delivery_date=datetime.date(2026, 1, 2))))
    assert select(root, "//ram:ShipToTradeParty") == []
    assert select(root, "//ram:ActualDeliverySupplyChainEvent/ram:OccurrenceDateTime/udt:DateTimeString") == [
        "20260102"
    ]


def test_one_payment_means_per_credit_transfer() -> None:
    payment = PaymentInstructions(
        payment_means_type_code="30",
        payment_means_text="Transfer",
        credit_transfers=(
            CreditTransfer(payment_account_identifier=TEST_IBAN),
            CreditTransfer(payment_account_identifier="ACCOUNT-2"),
        ),
        direct_debit=DirectDebit(debited_account_identifier=TEST_IBAN),
    )
    root = written(minimal_invoice(payment_instructions=payment))
    means = f"{STL}ram:SpecifiedTradeSettlementPaymentMeans"
    # CII-SR-467 / CII-SR-468: the same BT-81 and BT-82 in every means.
    assert select(root, f"{means}/ram:TypeCode") == ["30", "30"]
    assert select(root, f"{means}/ram:Information") == ["Transfer", "Transfer"]
    assert select(root, f"{means}[1]/ram:PayeePartyCreditorFinancialAccount/ram:IBANID") == [TEST_IBAN]
    # BT-84 that is not an IBAN goes to ram:ProprietaryID.
    assert select(root, f"{means}[2]/ram:PayeePartyCreditorFinancialAccount/*") == ["ACCOUNT-2"]
    assert select(root, f"{means}[2]/ram:PayeePartyCreditorFinancialAccount/ram:ProprietaryID") == ["ACCOUNT-2"]
    assert select(root, f"{means}/ram:PayerPartyDebtorFinancialAccount/ram:IBANID") == [TEST_IBAN]
    assert select(root, f"{STL}ram:CreditorReferenceID | {STL}ram:SpecifiedTradePaymentTerms") == []


def test_payment_means_without_credit_transfer() -> None:
    payment = PaymentInstructions(
        payment_means_type_code="10", direct_debit=DirectDebit(mandate_reference_identifier="M-1")
    )
    root = written(minimal_invoice(payment_instructions=payment))
    assert select(root, f"{STL}ram:SpecifiedTradeSettlementPaymentMeans/*") == ["10"]
    assert select(root, f"{STL}ram:SpecifiedTradePaymentTerms/ram:DirectDebitMandateID") == ["M-1"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (TEST_IBAN, True),
        ("DE02 1203 0000 0000 2020 51", True),
        ("DE03120300000000202051", False),  # wrong check digits
        ("ACCOUNT-2", False),
        ("1234567", False),
    ],
)
def test_is_iban(value: str, expected: bool) -> None:
    assert is_iban(value) is expected


def test_base_quantity_without_unit_code() -> None:
    root = written(with_line(minimal_invoice(), item_net_price=Decimal("50"), base_quantity=Decimal("2")))
    quantity = root.xpath("//ram:NetPriceProductTradePrice/ram:BasisQuantity", namespaces=_xml.CII_NSMAP)
    assert isinstance(quantity, list)
    assert [(t.cast(etree._Element, q).text, t.cast(etree._Element, q).get("unitCode")) for q in quantity] == [
        ("2", None)
    ]


def test_gross_price_without_discount() -> None:
    root = written(with_line(minimal_invoice(), item_net_price=Decimal("50"), item_gross_price=Decimal("50")))
    assert select(root, "//ram:GrossPriceProductTradePrice/*") == ["50"]


def test_attachment_without_mime_code_and_filename() -> None:
    document = AdditionalSupportingDocument(reference="DOC-1", attached_document=BinaryObject(content=b"abc"))
    root = written(minimal_invoice(additional_supporting_documents=(document,)))
    binary = root.xpath("//ram:AttachmentBinaryObject", namespaces=_xml.CII_NSMAP)
    assert isinstance(binary, list)
    element = t.cast(etree._Element, binary[0])
    assert element.text == "YWJj"
    assert len(element.attrib) == 0


def test_preceding_invoice_without_issue_date() -> None:
    root = written(minimal_invoice(preceding_invoice_references=(PrecedingInvoiceReference(reference="INV-0"),)))
    assert select(root, f"{STL}ram:InvoiceReferencedDocument/*") == ["INV-0"]


def test_more_than_one_preceding_invoice_cannot_be_written() -> None:
    references = (PrecedingInvoiceReference(reference="A"), PrecedingInvoiceReference(reference="B"))
    with pytest.raises(ModelError, match="BG-3"):
        cii.write(minimal_invoice(preceding_invoice_references=references))


def test_price_discount_needs_gross_price() -> None:
    invoice = with_line(minimal_invoice(), item_net_price=Decimal("50"), item_price_discount=Decimal("1"))
    with pytest.raises(ModelError, match=r"BT-147.*BT-148"):
        cii.write(invoice)


def test_base_quantity_unit_needs_base_quantity() -> None:
    invoice = with_line(minimal_invoice(), item_net_price=Decimal("50"), base_quantity_unit_code="C62")
    with pytest.raises(ModelError, match=r"BT-150.*BT-149"):
        cii.write(invoice)


def test_vat_total_in_accounting_currency_needs_its_currency() -> None:
    totals = DocumentTotals(
        sum_of_line_net_amounts=Decimal("100.00"),
        total_without_vat=Decimal("100.00"),
        total_vat=Decimal("19.00"),
        total_vat_in_accounting_currency=Decimal("200.00"),
        total_with_vat=Decimal("119.00"),
        amount_due=Decimal("119.00"),
    )
    with pytest.raises(ModelError, match=r"BT-111.*BT-6"):
        cii.write(minimal_invoice(totals=totals))
