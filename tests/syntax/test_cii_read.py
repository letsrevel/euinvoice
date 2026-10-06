"""Alternatives, errors and ``unmapped`` reporting of the CII reader (per-term table: ``test_cii_read_bts.py``).

Most tests write a synthetic invoice, change the parsed tree the way another producer could have written it, and
read the tree back.
"""

import dataclasses
import datetime
import typing as t
from decimal import Decimal

import pytest
from _cii_invoices import all_terms_invoice
from hypothesis import HealthCheck, given, settings
from lxml import etree

from _invoices import TEST_IBAN, full_invoice, minimal_invoice, payment, price, rebuild
from _strategies import cii_invoices
from euinvoice import _xml
from euinvoice.errors import ParseError
from euinvoice.model import CreditTransfer, Identifier, Invoice, InvoiceLine, PriceDetails
from euinvoice.syntax import cii
from euinvoice.syntax.result import ParseResult

ROOT: t.Final = "/rsm:CrossIndustryInvoice"
DOC: t.Final = f"{ROOT}/rsm:ExchangedDocument"
TX: t.Final = f"{ROOT}/rsm:SupplyChainTradeTransaction"
AGR: t.Final = f"{TX}/ram:ApplicableHeaderTradeAgreement"
STL: t.Final = f"{TX}/ram:ApplicableHeaderTradeSettlement"
LAGR: t.Final = f"{TX}/ram:IncludedSupplyChainTradeLineItem[1]/ram:SpecifiedLineTradeAgreement"


def tree(invoice: Invoice) -> etree._Element:
    """``invoice`` written as CII and parsed back."""
    return _xml.parse(cii.write(invoice))


def one(root: etree._Element, xpath: str) -> etree._Element:
    """The single element an XPath selects."""
    (found,) = t.cast(list[etree._Element], root.xpath(xpath, namespaces=_xml.CII_NSMAP))
    return found


def add(parent: etree._Element, name: str, text: str | None = None, **attributes: str) -> etree._Element:
    """Append ``ram:<name>`` (``prefix:name`` for another CII namespace)."""
    prefix, _, local = name.rpartition(":")
    element = etree.SubElement(parent, f"{{{_xml.CII_NSMAP[prefix or 'ram']}}}{local}", attributes)
    element.text = text
    return element


def with_price(invoice: Invoice, **changes: t.Any) -> Invoice:
    """``invoice`` with the price details of its first line changed."""
    first = rebuild(invoice.lines[0], price_details=price(**changes))
    return rebuild(invoice, lines=(first, *invoice.lines[1:]))


# --- result and round trips -------------------------------------------------------------------------------------


def test_result_is_a_frozen_parse_result() -> None:
    result = cii.read(tree(minimal_invoice()))
    assert isinstance(result, ParseResult)
    assert cii.ParseResult is ParseResult
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.unmapped = ("x",)  # type: ignore[misc]  # frozen dataclass: the assignment must fail


@pytest.mark.parametrize("invoice", [minimal_invoice(), minimal_invoice(type_code="381"), full_invoice()])
def test_synthetic_invoices_round_trip(invoice: Invoice) -> None:
    assert cii.read(tree(invoice)) == ParseResult(invoice=invoice, unmapped=())


def test_derived_gross_price_is_read_as_bt_148() -> None:
    # Normalization: BT-147 without BT-148 is written with BT-148 = BT-146 + BT-147 (bt-mapping.md).
    invoice = with_price(full_invoice(), item_gross_price=None)
    read = cii.read(tree(invoice)).invoice
    assert read.lines[0].price_details == price(item_gross_price=Decimal("50.5"))


def _as_written(invoice: Invoice) -> Invoice:
    """What a CII round trip of ``invoice`` returns: the model with the writer's normalizations applied.

    See ``docs/reference/bt-mapping.md`` "Normalizations": empty BG-1, BG-13 and BG-19 are not written; BT-29
    identifiers without a scheme come first (``ram:ID`` precedes ``ram:GlobalID`` in the XSD); a BT-147 without
    BT-148 gains BT-148 = BT-146 + BT-147.
    """
    delivery = invoice.delivery
    if delivery is not None and all(v is None for v in dict(delivery).values()):
        delivery = None
    payment_instructions = invoice.payment_instructions
    debit = None if payment_instructions is None else payment_instructions.direct_debit
    if payment_instructions is not None and debit is not None and all(v is None for v in dict(debit).values()):
        payment_instructions = payment_instructions.model_copy(update={"direct_debit": None})
    lines: list[InvoiceLine] = []
    for item in invoice.lines:
        prices = item.price_details
        if prices.item_gross_price is None and prices.item_price_discount is not None:
            gross = prices.item_net_price + prices.item_price_discount
            prices = PriceDetails.model_validate({**dict(prices), "item_gross_price": gross})
        lines.append(rebuild(item, price_details=prices))
    seller = invoice.seller.model_copy(
        update={"identifiers": tuple(sorted(invoice.seller.identifiers, key=lambda i: i.scheme_id is not None))}
    )
    return rebuild(
        invoice,
        notes=tuple(n for n in invoice.notes if (n.note, n.subject_code) != (None, None)),
        delivery=delivery,
        payment_instructions=payment_instructions,
        lines=tuple(lines),
        seller=seller,
    )


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(cii_invoices)
def test_random_invoices_round_trip(invoice: Invoice) -> None:
    result = cii.read(tree(invoice))
    assert result.invoice == _as_written(invoice)
    assert result.unmapped == ()


# --- alternatives another producer may use ---------------------------------------------------------------------


def test_department_name_is_the_contact_point_without_person_name() -> None:
    root = tree(full_invoice())
    person = one(root, f"{AGR}/ram:SellerTradeParty/ram:DefinedTradeContact/ram:PersonName")
    person.tag = f"{{{_xml.CII_RAM}}}DepartmentName"
    result = cii.read(root)
    assert result.invoice.seller.contact is not None
    assert result.invoice.seller.contact.contact_point == "Sales"
    assert result.unmapped == ()


def test_department_name_beside_person_name_is_unmapped() -> None:
    root = tree(full_invoice())
    contact = one(root, f"{AGR}/ram:SellerTradeParty/ram:DefinedTradeContact")
    contact.insert(1, etree.Element(f"{{{_xml.CII_RAM}}}DepartmentName"))
    result = cii.read(root)
    assert result.unmapped == (f"{AGR}/ram:SellerTradeParty/ram:DefinedTradeContact/ram:DepartmentName",)


def test_party_id_with_scheme_and_global_id_without_scheme() -> None:
    root = tree(full_invoice())
    seller_id = one(root, f"{AGR}/ram:SellerTradeParty/ram:ID")
    seller_id.set("schemeID", "0088")
    del one(root, f"{AGR}/ram:SellerTradeParty/ram:GlobalID").attrib["schemeID"]
    read = cii.read(root)
    assert read.invoice.seller.identifiers == (
        Identifier(value="SELLER-1", scheme_id="0088"),
        Identifier(value="4000001000005"),
    )
    assert read.unmapped == ()


def test_iban_in_proprietary_id_is_bt_84() -> None:
    root = tree(full_invoice())
    one(root, f"{STL}//ram:PayeePartyCreditorFinancialAccount/ram:IBANID").tag = f"{{{_xml.CII_RAM}}}ProprietaryID"
    instructions = cii.read(root).invoice.payment_instructions
    assert instructions is not None
    assert instructions.credit_transfers[0].payment_account_identifier == TEST_IBAN


def test_each_payment_means_with_the_same_code_adds_a_credit_transfer() -> None:
    two = (CreditTransfer(payment_account_identifier=TEST_IBAN), CreditTransfer(payment_account_identifier="ACCOUNT-2"))
    invoice = full_invoice(payment_instructions=payment(credit_transfers=two))
    assert cii.read(tree(invoice)).invoice == invoice


def test_tax_point_date_and_code_on_a_later_breakdown() -> None:
    invoice = full_invoice(vat_point_date_code="3")
    root = tree(invoice)
    code = one(root, f"{STL}/ram:ApplicableTradeTax[1]/ram:DueDateTypeCode")
    later = one(root, f"{STL}/ram:ApplicableTradeTax[2]")
    later.insert(len(later) - 1, code)  # before RateApplicablePercent
    assert cii.read(root) == ParseResult(invoice=invoice, unmapped=())


def test_repeated_equal_tax_point_values_are_consumed_and_different_ones_unmapped() -> None:
    invoice = rebuild(all_terms_invoice(), vat_point_date_code="3")
    root = tree(invoice)
    second = one(root, f"{STL}/ram:ApplicableTradeTax[2]")
    add(add(second, "TaxPointDate"), "udt:DateString", "20260110", format="102")
    add(second, "DueDateTypeCode", "72")
    result = cii.read(root)
    assert result.invoice == invoice
    assert result.unmapped == (f"{STL}/ram:ApplicableTradeTax[2]/ram:DueDateTypeCode",)


def test_xs_boolean_one_and_zero_are_indicators() -> None:
    root = tree(full_invoice())
    for indicator in t.cast(list[etree._Element], root.xpath("//udt:Indicator", namespaces=_xml.CII_NSMAP)):
        indicator.text = {"true": "1", "false": "0"}[t.cast(str, indicator.text)]
    assert cii.read(root).invoice == full_invoice()


def test_empty_note_is_skipped_without_being_unmapped() -> None:
    root = tree(minimal_invoice())
    one(root, DOC).append(etree.Element(f"{{{_xml.CII_RAM}}}IncludedNote"))
    assert cii.read(root) == ParseResult(invoice=minimal_invoice(), unmapped=())


def test_attachment_base64_may_hold_whitespace() -> None:
    root = tree(full_invoice())
    binary = one(root, f"{AGR}/ram:AdditionalReferencedDocument/ram:AttachmentBinaryObject")
    binary.text = "JVBE\nRi0x LjcKAP8="
    assert cii.read(root).invoice == full_invoice()


# --- unmapped ----------------------------------------------------------------------------------------------------


def test_procuring_project_name_is_consumed() -> None:
    root = tree(full_invoice())
    assert one(root, f"{AGR}/ram:SpecifiedProcuringProject/ram:Name").text == "Project reference"
    assert cii.read(root).unmapped == ()


def test_out_of_model_content_is_unmapped_in_document_order() -> None:
    root = tree(full_invoice())
    root.set("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation", "urn:example x.xsd")
    root.insert(0, etree.Comment("generated"))
    add(one(root, DOC), "Name", "Extended name")
    one(root, f"{DOC}/ram:IncludedNote").append(etree.Element(f"{{{_xml.CII_RAM}}}Content"))
    one(root, f"{DOC}/ram:ID").set("schemeID", "X")
    add(one(root, f"{AGR}/ram:BuyerTradeParty/ram:SpecifiedTaxRegistration/.."), "SpecifiedTaxRegistration").append(
        etree.Element(f"{{{_xml.CII_RAM}}}ID", schemeID="FC")
    )
    other = add(one(root, AGR), "AdditionalReferencedDocument")
    add(other, "IssuerAssignedID", "OTHER-1")
    add(other, "TypeCode", "751")
    tax = add(one(root, STL), "ApplicableTradeTax")
    add(tax, "TypeCode", "GST")
    add(one(root, f"{STL}/ram:SpecifiedTradeSettlementHeaderMonetarySummation"), "TaxTotalAmount", "1.00")
    result = cii.read(root)
    assert result.invoice == full_invoice()
    assert result.unmapped == (
        f"{ROOT}/@xsi:schemaLocation",
        f"{DOC}/ram:ID/@schemeID",
        f"{DOC}/ram:IncludedNote/ram:Content[2]",
        f"{DOC}/ram:Name",
        f"{AGR}/ram:BuyerTradeParty/ram:SpecifiedTaxRegistration[2]",
        f"{AGR}/ram:AdditionalReferencedDocument[4]",
        f"{STL}/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxTotalAmount[3]",
        f"{STL}/ram:ApplicableTradeTax[3]",
    )


def test_payee_trading_name_and_tax_representative_fc_are_unmapped() -> None:
    root = tree(full_invoice())
    add(one(root, f"{STL}/ram:PayeeTradeParty/ram:SpecifiedLegalOrganization"), "TradingBusinessName", "Payee")
    representative = one(root, f"{AGR}/ram:SellerTaxRepresentativeTradeParty")
    add(add(representative, "SpecifiedTaxRegistration"), "ID", "000", schemeID="FC")
    assert cii.read(root).unmapped == (
        f"{AGR}/ram:SellerTaxRepresentativeTradeParty/ram:SpecifiedTaxRegistration[2]",
        f"{STL}/ram:PayeeTradeParty/ram:SpecifiedLegalOrganization/ram:TradingBusinessName",
    )


def test_gross_basis_quantity_different_from_the_net_one_is_unmapped() -> None:
    root = tree(full_invoice())
    one(root, f"{LAGR}/ram:GrossPriceProductTradePrice/ram:BasisQuantity").text = "2"
    result = cii.read(root)
    assert result.invoice == full_invoice()
    assert result.unmapped == (f"{LAGR}/ram:GrossPriceProductTradePrice/ram:BasisQuantity",)


def test_gross_price_charge_is_unmapped_and_the_next_allowance_is_bt_147() -> None:
    root = tree(full_invoice())
    gross = one(root, f"{LAGR}/ram:GrossPriceProductTradePrice")
    second = add(gross, "AppliedTradeAllowanceCharge")
    add(add(second, "ChargeIndicator"), "udt:Indicator", "false")
    add(second, "ActualAmount", "0.25")
    one(root, f"{LAGR}/ram:GrossPriceProductTradePrice/ram:AppliedTradeAllowanceCharge[1]//udt:Indicator").text = "true"
    result = cii.read(root)
    assert result.invoice.lines[0].price_details.item_price_discount == Decimal("0.25")
    assert result.unmapped == (f"{LAGR}/ram:GrossPriceProductTradePrice/ram:AppliedTradeAllowanceCharge[1]",)


def test_second_gross_price_allowance_is_unmapped() -> None:
    root = tree(full_invoice())
    second = add(one(root, f"{LAGR}/ram:GrossPriceProductTradePrice"), "AppliedTradeAllowanceCharge")
    add(add(second, "ChargeIndicator"), "udt:Indicator", "false")
    add(second, "ActualAmount", "0.25")
    result = cii.read(root)
    assert result.invoice == full_invoice()
    assert result.unmapped == (f"{LAGR}/ram:GrossPriceProductTradePrice/ram:AppliedTradeAllowanceCharge[2]",)


@pytest.mark.parametrize("indicator", [None, "yes"])
def test_gross_price_allowance_without_boolean_indicator_is_unmapped(indicator: str | None) -> None:
    # The D16B XSD makes ram:ChargeIndicator optional and CII-SR-119 (a warning) accepts a price allowance without
    # it: no BT-147 can be read from it, and the invoice is not refused.
    root = tree(full_invoice())
    path = f"{LAGR}/ram:GrossPriceProductTradePrice/ram:AppliedTradeAllowanceCharge"
    if indicator is None:
        _remove(root, f"{path}/ram:ChargeIndicator")
    else:
        one(root, f"{path}/ram:ChargeIndicator/udt:Indicator").text = indicator
    result = cii.read(root)
    assert result.invoice.lines[0].price_details.item_price_discount is None
    assert result.unmapped == (path,)


def test_second_payment_means_without_information_adds_a_credit_transfer() -> None:
    # CII-SR-467/468 compare only the TypeCode / Information elements present (normalize-space); a missing one
    # does not differ (EN16931-CII-syntax.sch), as in KoSIT 03.07a and CEN CII_example5.xml.
    root = tree(full_invoice())
    means = one(root, f"{STL}/ram:SpecifiedTradeSettlementPaymentMeans")
    other = etree.Element(means.tag)
    add(other, "TypeCode", " 58 ")
    account = add(other, "PayeePartyCreditorFinancialAccount")
    add(account, "ProprietaryID", "ACCOUNT-2")
    means.addnext(other)
    result = cii.read(root)
    instructions = result.invoice.payment_instructions
    assert instructions is not None
    assert [c.payment_account_identifier for c in instructions.credit_transfers] == [TEST_IBAN, "ACCOUNT-2"]
    assert result.unmapped == ()


def test_information_of_a_later_means_is_bt_82_when_the_first_has_none() -> None:
    root = tree(full_invoice())
    means = one(root, f"{STL}/ram:SpecifiedTradeSettlementPaymentMeans")
    information = one(means, "ram:Information")
    means.remove(information)
    other = etree.Element(means.tag)
    add(other, "TypeCode", "58")
    other.append(information)
    means.addnext(other)
    result = cii.read(root)
    assert result.invoice == full_invoice()
    assert result.unmapped == ()


def test_procuring_project_with_another_name_is_unmapped() -> None:
    root = tree(full_invoice())
    one(root, f"{AGR}/ram:SpecifiedProcuringProject/ram:Name").text = "Projekt"
    result = cii.read(root)
    assert result.invoice == full_invoice()
    assert result.unmapped == (f"{AGR}/ram:SpecifiedProcuringProject/ram:Name",)


def test_note_with_bare_text_is_unmapped() -> None:
    root = tree(minimal_invoice())
    add(one(root, DOC), "IncludedNote", "text outside ram:Content")
    assert cii.read(root).unmapped == (f"{DOC}/ram:IncludedNote",)


def test_payment_means_with_another_code_is_unmapped() -> None:
    root = tree(full_invoice())
    means = one(root, f"{STL}/ram:SpecifiedTradeSettlementPaymentMeans")
    other = etree.Element(means.tag)
    add(other, "TypeCode", "30")
    means.addnext(other)
    result = cii.read(root)
    assert result.invoice == full_invoice()
    assert result.unmapped == (f"{STL}/ram:SpecifiedTradeSettlementPaymentMeans[2]",)


def test_payment_terms_without_payment_means_stay_unmapped() -> None:
    # BG-16 needs BT-81 (BR-49); without a payment means BT-83, BT-89 and BT-90 cannot be held, so they are listed.
    root = tree(full_invoice())
    settlement = one(root, STL)
    settlement.remove(one(root, f"{STL}/ram:SpecifiedTradeSettlementPaymentMeans"))
    result = cii.read(root)
    assert result.invoice.payment_instructions is None
    assert result.unmapped == (
        f"{STL}/ram:CreditorReferenceID",
        f"{STL}/ram:PaymentReference",
        f"{STL}/ram:SpecifiedTradePaymentTerms/ram:DirectDebitMandateID",
    )


def test_line_level_out_of_model_content_is_unmapped() -> None:
    root = tree(full_invoice())
    line_settlement = one(root, f"{TX}/ram:IncludedSupplyChainTradeLineItem[1]/ram:SpecifiedLineTradeSettlement")
    add(
        one(
            root,
            f"{TX}/ram:IncludedSupplyChainTradeLineItem[1]/ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax",
        ),
        "ExemptionReason",
        "x",
    )
    document = add(line_settlement, "AdditionalReferencedDocument")
    add(document, "IssuerAssignedID", "DOC-1")
    add(document, "TypeCode", "916")
    path = f"{TX}/ram:IncludedSupplyChainTradeLineItem[1]/ram:SpecifiedLineTradeSettlement"
    assert cii.read(root).unmapped == (
        f"{path}/ram:ApplicableTradeTax/ram:ExemptionReason",
        f"{path}/ram:AdditionalReferencedDocument[2]",
    )


# --- errors ------------------------------------------------------------------------------------------------------


def test_wrong_root_is_a_parse_error() -> None:
    with pytest.raises(ParseError, match="expected the CII root") as caught:
        cii.read(etree.Element("Invoice"))
    assert caught.value.location == "/Invoice"


@pytest.mark.parametrize(
    ("text", "code"), [("20260115", "610"), ("2026-01-15", "102"), ("20260230", "102"), ("20260115", None)]
)
def test_only_valid_format_102_dates_are_read(text: str, code: str | None) -> None:
    root = tree(minimal_invoice())
    string = one(root, f"{DOC}/ram:IssueDateTime/udt:DateTimeString")
    string.text = text
    if code is None:
        del string.attrib["format"]
    else:
        string.set("format", code)
    with pytest.raises(ParseError, match="BT-2: cannot interpret the date") as caught:
        cii.read(root)
    assert caught.value.location == f"{DOC}/ram:IssueDateTime/udt:DateTimeString"


def test_date_without_string_is_a_parse_error() -> None:
    root = tree(full_invoice())
    holder = one(root, f"{STL}/ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime")
    holder.remove(holder[0])
    with pytest.raises(ParseError, match="BT-9: ram:DueDateDateTime has no DateTimeString"):
        cii.read(root)


def test_bt_8_outside_the_cii_list_is_a_parse_error() -> None:
    root = tree(full_invoice())
    one(root, f"{STL}/ram:ApplicableTradeTax[1]/ram:DueDateTypeCode").text = "35"
    with pytest.raises(ParseError, match=r"BT-8: .*'35'.*5, 29, 72 \(CII BR-CL-06\)") as caught:
        cii.read(root)
    assert caught.value.location == f"{STL}/ram:ApplicableTradeTax[1]/ram:DueDateTypeCode"


def test_missing_mandatory_term_names_it() -> None:
    root = tree(minimal_invoice())
    one(root, DOC).remove(one(root, f"{DOC}/ram:ID"))
    with pytest.raises(ParseError, match=r"BT-1 \(number\): Field required") as caught:
        cii.read(root)
    assert caught.value.location == ROOT


def test_missing_lines_name_br_16() -> None:
    # Factur-X MINIMUM and BASIC WL have no lines: the model cannot be built (needs-human #69).
    root = tree(minimal_invoice())
    one(root, TX).remove(one(root, f"{TX}/ram:IncludedSupplyChainTradeLineItem"))
    with pytest.raises(ParseError, match=r"BG-25 \(lines\).*BR-16"):
        cii.read(root)


def test_invalid_code_is_located_at_its_group() -> None:
    root = tree(minimal_invoice())
    one(root, f"{AGR}/ram:SellerTradeParty/ram:PostalTradeAddress/ram:CountryID").text = "XX"
    with pytest.raises(ParseError, match=r"BT-40 \(country_code\).*BR-CL-14") as caught:
        cii.read(root)
    assert caught.value.location == f"{AGR}/ram:SellerTradeParty/ram:PostalTradeAddress"


def test_invalid_classification_scheme_names_bt_158() -> None:
    root = tree(full_invoice())
    one(root, "//ram:ClassCode").set("listID", "XX")
    with pytest.raises(ParseError, match=r"cannot read BT-158 ItemClassificationIdentifier: scheme_id.*BR-CL-13"):
        cii.read(root)


def test_amount_with_three_decimals_is_a_parse_error() -> None:
    root = tree(minimal_invoice())
    one(root, f"{STL}/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:DuePayableAmount").text = "119.001"
    with pytest.raises(ParseError, match=r"BT-115 \(amount_due\)"):
        cii.read(root)


def test_invalid_base64_is_a_parse_error() -> None:
    root = tree(full_invoice())
    one(root, "//ram:AttachmentBinaryObject").text = "not base64!"
    with pytest.raises(ParseError, match="BT-125: the attached document is not base64"):
        cii.read(root)


@pytest.mark.parametrize("text", ["yes", None])
def test_allowance_without_boolean_indicator_is_unmapped(text: str | None) -> None:
    # The CEN rules select BG-20/21 by ram:ChargeIndicator/udt:Indicator; without one it is neither, and unmapped.
    root = tree(full_invoice())
    path = f"{STL}/ram:SpecifiedTradeAllowanceCharge[1]"
    if text is None:
        _remove(root, f"{path}/ram:ChargeIndicator/udt:Indicator")
    else:
        one(root, f"{path}/ram:ChargeIndicator/udt:Indicator").text = text
    result = cii.read(root)
    assert result.invoice.allowances == ()
    assert result.unmapped == (path,)


def _remove(root: etree._Element, xpath: str) -> None:
    element = one(root, xpath)
    parent = element.getparent()
    assert parent is not None
    parent.remove(element)


def test_missing_groups_are_named_together() -> None:
    root = tree(minimal_invoice())
    item = f"{TX}/ram:IncludedSupplyChainTradeLineItem"
    _remove(root, f"{item}/ram:SpecifiedTradeProduct")
    _remove(root, f"{item}/ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice")
    one(root, f"{item}/ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:TypeCode").text = "GST"
    with pytest.raises(ParseError, match=r"BG-29 .*BG-30 .*BG-31 ") as caught:
        cii.read(root)
    assert caught.value.location == item


def test_missing_parties_and_totals_are_named() -> None:
    root = tree(minimal_invoice())
    _remove(root, f"{AGR}/ram:SellerTradeParty")
    _remove(root, f"{AGR}/ram:BuyerTradeParty")
    _remove(root, f"{STL}/ram:SpecifiedTradeSettlementHeaderMonetarySummation")
    with pytest.raises(ParseError, match=r"BG-4 .*BG-7 .*BG-22 "):
        cii.read(root)


def test_supporting_document_without_attachment() -> None:
    supporting = full_invoice().additional_supporting_documents[0].model_copy(update={"attached_document": None})
    invoice = full_invoice(additional_supporting_documents=(supporting,))
    assert cii.read(tree(invoice)).invoice == invoice


def test_different_tax_point_date_on_a_later_breakdown_is_unmapped() -> None:
    invoice = full_invoice(vat_point_date_code=None, vat_point_date=datetime.date(2026, 1, 10))
    root = tree(invoice)
    second = one(root, f"{STL}/ram:ApplicableTradeTax[2]")
    add(add(second, "TaxPointDate"), "udt:DateString", "20260111", format="102")
    result = cii.read(root)
    assert result.invoice == invoice
    assert result.unmapped == (f"{STL}/ram:ApplicableTradeTax[2]/ram:TaxPointDate",)


def test_gross_basis_quantity_without_a_net_one_is_unmapped() -> None:
    root = tree(full_invoice())
    _remove(root, f"{LAGR}/ram:NetPriceProductTradePrice/ram:BasisQuantity")
    assert cii.read(root).unmapped == (f"{LAGR}/ram:GrossPriceProductTradePrice/ram:BasisQuantity",)


def test_invalid_net_basis_quantity_is_a_parse_error() -> None:
    root = tree(full_invoice())
    one(root, f"{LAGR}/ram:NetPriceProductTradePrice/ram:BasisQuantity").text = "x"
    with pytest.raises(ParseError, match=r"BT-149 \(base_quantity\)"):
        cii.read(root)


def test_line_allowance_without_indicator_is_unmapped() -> None:
    root = tree(full_invoice())
    line_settlement = f"{TX}/ram:IncludedSupplyChainTradeLineItem[1]/ram:SpecifiedLineTradeSettlement"
    path = f"{line_settlement}/ram:SpecifiedTradeAllowanceCharge[1]"
    _remove(root, f"{path}/ram:ChargeIndicator")
    result = cii.read(root)
    assert result.invoice.lines[0].allowances == ()
    assert result.unmapped == (path,)
