"""Behaviour of the UBL reader beyond the per-BT table: binding decisions of issue #11, unmapped content, errors."""

import datetime
import typing as t
from decimal import Decimal

import pytest
from lxml import etree

from _invoices import TEST_IBAN, full_invoice, minimal_invoice, payment, simple_line
from euinvoice import _xml
from euinvoice.errors import ParseError
from euinvoice.model import (
    CreditTransfer,
    DirectDebit,
    Invoice,
    InvoiceNote,
    Payee,
    PaymentInstructions,
    PriceDetails,
)
from euinvoice.model.codes import UNTDID_4451_TEXT_SUBJECT
from euinvoice.syntax import ubl

CAC: t.Final = f"{{{_xml.UBL_CAC}}}"
CBC: t.Final = f"{{{_xml.UBL_CBC}}}"
SEPA_ID: t.Final = "DE98ZZZ09999999999"


def find(root: etree._Element, path: str) -> etree._Element:
    """The first element at ``path`` (``cac`` / ``cbc`` prefixes); fails the test if there is none."""
    element = root.find(path, _xml.UBL_NSMAP)
    assert element is not None, path
    return element


def add(parent: etree._Element, tag: str, text: str | None = None, **attributes: str) -> etree._Element:
    """Append ``cac:…`` or ``cbc:…`` with text and attributes."""
    prefix, local = tag.split(":")
    element = etree.SubElement(parent, (CAC if prefix == "cac" else CBC) + local, attributes)
    element.text = text
    return element


def read_changed(invoice: Invoice, change: t.Callable[[etree._Element], object]) -> ubl.ParseResult:
    """Write ``invoice``, apply ``change`` to the tree, serialize and read it back through the hardened parser."""
    root = _xml.parse(ubl.write(invoice))
    change(root)
    return ubl.read(_xml.parse(etree.tostring(root)))


def read_back(invoice: Invoice) -> ubl.ParseResult:
    return ubl.read(_xml.parse(ubl.write(invoice)))


@pytest.mark.parametrize("type_code", ["380", "381", "81", "384"])
def test_full_invoice_and_credit_note_round_trip(type_code: str) -> None:
    invoice = full_invoice(type_code=type_code)
    assert read_back(invoice) == ubl.ParseResult(invoice=invoice)


def test_credit_note_reads_due_date_project_and_credited_quantity() -> None:
    # bt-mapping.md N3 / issue #11: BT-9 from cac:PaymentMeans/cbc:PaymentDueDate, BT-11 from the ADR with
    # DocumentTypeCode 50, BT-129 from cbc:CreditedQuantity.
    invoice = full_invoice(type_code="381")
    root = _xml.parse(ubl.write(invoice))
    assert etree.QName(root).localname == "CreditNote"
    result = ubl.read(root)
    assert result.invoice.payment_due_date == datetime.date(2026, 2, 14)
    assert result.invoice.project_reference == "PROJ-1"
    assert result.invoice.lines[0].invoiced_quantity == Decimal("2")
    assert result.unmapped == ()


def test_invoice_with_code_81_reads_back_from_a_credit_note() -> None:
    # bt-mapping.md "Normalizations": a UBL Invoice with BT-3 = 81 is written again as a CreditNote; the
    # model has no root hint, so the model round trip is exact.
    invoice = minimal_invoice(type_code="81")

    def as_invoice(root: etree._Element) -> None:
        root.tag = f"{{{_xml.UBL_INVOICE}}}Invoice"
        for code in root.iterfind("cbc:CreditNoteTypeCode", _xml.UBL_NSMAP):
            code.tag = CBC + "InvoiceTypeCode"
        for line in root.iterfind("cac:CreditNoteLine", _xml.UBL_NSMAP):
            line.tag = CAC + "InvoiceLine"
            find(line, "cbc:CreditedQuantity").tag = CBC + "InvoicedQuantity"

    from_invoice_root = read_changed(invoice, as_invoice)
    assert from_invoice_root == ubl.ParseResult(invoice=invoice)
    assert etree.QName(_xml.parse(ubl.write(from_invoice_root.invoice))).localname == "CreditNote"


# --- BT-21 / BT-22 (issue #11, decision on PR #53) ------------------------------------------------------


def _note_result(text: str) -> ubl.ParseResult:
    def set_note(root: etree._Element) -> None:
        note = etree.Element(CBC + "Note")
        note.text = text
        find(root, "cbc:InvoiceTypeCode").addnext(note)

    return read_changed(minimal_invoice(), set_note)


def test_leading_known_three_letter_code_is_bt21() -> None:
    result = _note_result("#AAI#Text after the code")
    assert result.invoice.notes == (InvoiceNote(subject_code="AAI", note="Text after the code"),)


def test_code_only_note_has_no_bt22() -> None:
    assert _note_result("#AAI#").invoice.notes == (InvoiceNote(subject_code="AAI"),)


@pytest.mark.parametrize(
    "text",
    [
        "Plain note",
        "#ABCD#four characters",
        "#AB#two characters",
        "#A1B#not in UNTDID 4451",
        "# AA#padded",
        "#A A#inner space",
        "foo #AAI# bar",
        "#AAI",
        "##",
    ],
)
def test_anything_else_is_bt22_verbatim(text: str) -> None:
    assert "A1B" not in UNTDID_4451_TEXT_SUBJECT
    result = _note_result(text)
    assert result.invoice.notes == (InvoiceNote(note=text),)
    written = _xml.parse(ubl.write(result.invoice))
    assert find(written, "cbc:Note").text == text  # lossless: the same cbc:Note is written back


def test_empty_note_is_unmapped_not_read() -> None:
    result = _note_result("")
    assert result.invoice.notes == ()
    assert result.unmapped == ("/*/cbc:Note",)


# --- references ------------------------------------------------------------------------------------------


def test_na_order_id_beside_a_sales_order_is_no_purchase_order() -> None:
    invoice = minimal_invoice(sales_order_reference="SO-1")
    assert find(_xml.parse(ubl.write(invoice)), "cac:OrderReference/cbc:ID").text == "NA"
    assert read_back(invoice) == ubl.ParseResult(invoice=invoice)


def test_na_order_id_alone_is_a_purchase_order() -> None:
    invoice = minimal_invoice(purchase_order_reference="NA")
    assert read_back(invoice).invoice.purchase_order_reference == "NA"


def test_project_document_reference_in_an_invoice_is_unmapped() -> None:
    # CEN UBL-SR-43 (fatal): DocumentTypeCode 50 only in a CreditNote; in an Invoice it is no BT-11.
    def add_project(root: etree._Element) -> None:
        reference = add(root, "cac:AdditionalDocumentReference")
        add(reference, "cbc:ID", "PROJ-9")
        add(reference, "cbc:DocumentTypeCode", "50")

    result = read_changed(minimal_invoice(), add_project)
    assert result.invoice.project_reference is None
    assert result.invoice.additional_supporting_documents == ()
    assert result.unmapped == ("/*/cac:AdditionalDocumentReference",)


def test_second_invoiced_object_is_unmapped() -> None:
    def second(root: etree._Element) -> None:
        reference = add(root, "cac:AdditionalDocumentReference")
        add(reference, "cbc:ID", "OBJ-2")
        add(reference, "cbc:DocumentTypeCode", "130")

    result = read_changed(full_invoice(), second)
    assert result.invoice.invoiced_object_identifier is not None
    assert result.invoice.invoiced_object_identifier.value == "OBJ-1"
    assert result.unmapped == ("/*/cac:AdditionalDocumentReference[3]",)


# --- payment ---------------------------------------------------------------------------------------------


def test_card_network_id_is_taken_only_as_the_writer_filler() -> None:
    # bt-mapping.md N2: NetworkID has no business term; the writer's "NA" is recognised, any other value is
    # information the model cannot hold.
    assert read_back(full_invoice()).unmapped == ()

    def other_network(root: etree._Element) -> None:
        find(root, "cac:PaymentMeans/cac:CardAccount/cbc:NetworkID").text = "mapped-from-cii"

    result = read_changed(full_invoice(), other_network)
    assert result.invoice == full_invoice()
    assert result.unmapped == ("/*/cac:PaymentMeans/cac:CardAccount/cbc:NetworkID",)


def test_every_payment_means_is_a_credit_transfer() -> None:
    accounts = (
        CreditTransfer(payment_account_identifier=TEST_IBAN),
        CreditTransfer(payment_account_identifier="NL91ABNA0417164300"),
    )
    invoice = minimal_invoice(payment_instructions=payment(credit_transfers=accounts))
    root = _xml.parse(ubl.write(invoice))
    assert len(root.findall("cac:PaymentMeans", _xml.UBL_NSMAP)) == 2
    assert ubl.read(root) == ubl.ParseResult(invoice=invoice)


def test_repeated_payment_terms_are_taken_when_equal_and_reported_when_not() -> None:
    accounts = (
        CreditTransfer(payment_account_identifier=TEST_IBAN),
        CreditTransfer(payment_account_identifier="NL91ABNA0417164300"),
    )
    invoice = minimal_invoice(
        type_code="381",
        payment_due_date=datetime.date(2026, 2, 1),
        payment_instructions=payment(credit_transfers=accounts),
    )

    def repeat(root: etree._Element) -> None:
        second = root.findall("cac:PaymentMeans", _xml.UBL_NSMAP)[1]
        find(second, "cbc:PaymentMeansCode").set("name", "SEPA credit transfer")  # same BT-82
        find(second, "cbc:PaymentMeansCode").addnext(etree.Element(CBC + "PaymentDueDate"))
        find(second, "cbc:PaymentDueDate").text = "2026-03-01"  # another BT-9
        find(second, "cbc:PaymentDueDate").addnext(etree.Element(CBC + "PaymentID"))
        find(second, "cbc:PaymentID").text = "INV-2026-0001"  # same BT-83

    result = read_changed(invoice, repeat)
    assert result.invoice == invoice
    assert result.unmapped == ("/*/cac:PaymentMeans[2]/cbc:PaymentDueDate",)


def test_other_payment_means_code_is_reported() -> None:
    accounts = (
        CreditTransfer(payment_account_identifier=TEST_IBAN),
        CreditTransfer(payment_account_identifier="NL91ABNA0417164300"),
    )
    invoice = minimal_invoice(
        payment_instructions=PaymentInstructions(payment_means_type_code="58", credit_transfers=accounts)
    )

    def other_code(root: etree._Element) -> None:
        find(root, "cac:PaymentMeans[2]/cbc:PaymentMeansCode").text = "30"

    assert read_changed(invoice, other_code).unmapped == ("/*/cac:PaymentMeans[2]/cbc:PaymentMeansCode",)


def test_payment_due_date_in_an_invoice_payment_means_is_unmapped() -> None:
    invoice = minimal_invoice(payment_instructions=PaymentInstructions(payment_means_type_code="58"))

    def due(root: etree._Element) -> None:
        add(find(root, "cac:PaymentMeans"), "cbc:PaymentDueDate", "2026-03-01")

    result = read_changed(invoice, due)
    assert result.invoice.payment_due_date is None
    assert result.unmapped == ("/*/cac:PaymentMeans/cbc:PaymentDueDate",)


_DEBIT = PaymentInstructions(
    payment_means_type_code="59", direct_debit=DirectDebit(bank_assigned_creditor_identifier=SEPA_ID)
)


@pytest.mark.parametrize("payee", [None, Payee(name="Payee Example Ltd")], ids=["seller", "payee"])
def test_sepa_party_identifier_is_bt90(payee: Payee | None) -> None:
    invoice = minimal_invoice(payment_instructions=_DEBIT, payee=payee)
    assert read_back(invoice) == ubl.ParseResult(invoice=invoice)


def test_same_sepa_id_under_seller_and_payee_is_taken_once() -> None:
    invoice = minimal_invoice(payment_instructions=_DEBIT, payee=Payee(name="Payee Example Ltd"))

    def copy_to_seller(root: etree._Element) -> None:
        party = find(root, "cac:AccountingSupplierParty/cac:Party")
        add(add(party, "cac:PartyIdentification"), "cbc:ID", SEPA_ID, schemeID="SEPA")

    assert read_changed(invoice, copy_to_seller) == ubl.ParseResult(invoice=invoice)


def test_different_seller_sepa_id_is_reported() -> None:
    invoice = minimal_invoice(payment_instructions=_DEBIT, payee=Payee(name="Payee Example Ltd"))

    def other_on_seller(root: etree._Element) -> None:
        party = find(root, "cac:AccountingSupplierParty/cac:Party")
        add(add(party, "cac:PartyIdentification"), "cbc:ID", "DE00ZZZ00000000000", schemeID="SEPA")

    result = read_changed(invoice, other_on_seller)
    assert result.invoice == invoice
    assert result.unmapped == ("/*/cac:AccountingSupplierParty/cac:Party/cac:PartyIdentification",)


def test_sepa_id_without_payment_instructions_is_reported() -> None:
    def sepa(root: etree._Element) -> None:
        party = find(root, "cac:AccountingSupplierParty/cac:Party")
        add(add(party, "cac:PartyIdentification"), "cbc:ID", SEPA_ID, schemeID="SEPA")

    result = read_changed(minimal_invoice(), sepa)
    assert result.invoice == minimal_invoice()
    assert result.unmapped == ("/*/cac:AccountingSupplierParty/cac:Party/cac:PartyIdentification",)


# --- VAT totals ------------------------------------------------------------------------------------------


def test_tax_totals_are_told_apart_by_currency() -> None:
    invoice = full_invoice()

    def swap(root: etree._Element) -> None:
        first, second = root.findall("cac:TaxTotal", _xml.UBL_NSMAP)
        first.addprevious(second)  # BT-111 first, BT-110 second

    assert read_changed(invoice, swap) == ubl.ParseResult(invoice=invoice)


def test_unknown_tax_total_is_reported() -> None:
    def third(root: etree._Element) -> None:
        tax_total = etree.Element(CAC + "TaxTotal")
        add(tax_total, "cbc:TaxAmount", "1.00", currencyID="USD")
        find(root, "cac:LegalMonetaryTotal").addprevious(tax_total)

    result = read_changed(minimal_invoice(), third)
    assert result.invoice == minimal_invoice()
    assert result.unmapped == ("/*/cac:TaxTotal[2]",)


def test_amount_in_another_currency_keeps_its_currency_unmapped() -> None:
    def usd(root: etree._Element) -> None:
        find(root, "cac:LegalMonetaryTotal/cbc:PayableAmount").set("currencyID", "USD")

    result = read_changed(minimal_invoice(), usd)
    assert result.invoice == minimal_invoice()
    assert result.unmapped == ("/*/cac:LegalMonetaryTotal/cbc:PayableAmount/@currencyID",)


# --- out-of-model content --------------------------------------------------------------------------------


def test_out_of_model_content_is_listed_in_document_order() -> None:
    def extend(root: etree._Element) -> None:
        extensions = etree.Element(f"{{{_xml.UBL_EXT}}}UBLExtensions", nsmap={"ext": _xml.UBL_EXT})
        root.insert(0, extensions)
        etree.SubElement(extensions, f"{{{_xml.UBL_EXT}}}UBLExtension")
        root.set("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation", "urn:example.com x.xsd")
        find(root, "cbc:ID").set("schemeName", "local")
        line = find(root, "cac:InvoiceLine")
        sub_line = etree.Element(CAC + "SubInvoiceLine")
        add(sub_line, "cbc:ID", "1.1")
        find(line, "cac:Item").addprevious(sub_line)
        root.append(etree.Comment("comments carry no data"))
        add(root, "cac:Delivery")  # an empty container maps nothing

    result = read_changed(minimal_invoice(), extend)
    assert result.invoice == minimal_invoice()
    assert result.unmapped == (
        "/*/@xsi:schemaLocation",
        "/*/ext:UBLExtensions",
        "/*/cbc:ID/@schemeName",
        "/*/cac:InvoiceLine/cac:SubInvoiceLine",
        "/*/cac:Delivery",
    )


@pytest.mark.parametrize("zone", ["Z", "+01:00", "-14:00"])
def test_date_with_a_time_zone_is_read_and_the_zone_reported(zone: str) -> None:
    # xs:date allows a time zone and no CEN rule restricts it (D8); the model keeps the calendar date only, so the
    # zone is reported as part of the element's text that was not mapped.
    invoice = minimal_invoice(payment_due_date=datetime.date(2026, 2, 14))

    def zoned(root: etree._Element) -> None:
        find(root, "cbc:IssueDate").text = f"2026-01-15{zone}"
        find(root, "cbc:DueDate").text = f" 2026-02-14{zone}\n"

    result = read_changed(invoice, zoned)
    assert result.invoice == invoice
    assert result.unmapped == ("/*/cbc:IssueDate/text()", "/*/cbc:DueDate/text()")


def test_namespaced_attributes_are_named_with_their_prefix() -> None:
    def foreign(root: etree._Element) -> None:
        find(root, "cbc:ID").set("{http://www.w3.org/XML/1998/namespace}lang", "en")
        find(root, "cbc:ID").set("{urn:example.com:x}flag", "1")  # serialized with a generated prefix

    assert read_changed(minimal_invoice(), foreign).unmapped == ("/*/cbc:ID/@xml:lang", "/*/cbc:ID/@ns0:flag")


def test_price_charge_and_line_tax_category_are_unmapped() -> None:
    def extras(root: etree._Element) -> None:
        charge = add(find(root, "cac:InvoiceLine/cac:Price"), "cac:AllowanceCharge")
        add(charge, "cbc:ChargeIndicator", "true")
        add(charge, "cbc:Amount", "1.00", currencyID="EUR")
        allowance = etree.Element(CAC + "AllowanceCharge")
        add(allowance, "cbc:ChargeIndicator", "false")
        add(allowance, "cbc:AllowanceChargeReason", "Discount")
        add(allowance, "cbc:Amount", "1.00", currencyID="EUR")
        add(allowance, "cac:TaxCategory")
        find(root, "cac:InvoiceLine/cac:Item").addprevious(allowance)
        no_indicator = etree.Element(CAC + "AllowanceCharge")
        add(no_indicator, "cbc:Amount", "1.00", currencyID="EUR")
        find(root, "cac:TaxTotal").addprevious(no_indicator)

    result = read_changed(minimal_invoice(), extras)
    assert len(result.invoice.lines[0].allowances) == 1
    assert result.invoice.allowances == ()
    assert result.unmapped == (
        "/*/cac:AllowanceCharge",
        "/*/cac:InvoiceLine/cac:AllowanceCharge/cac:TaxCategory",
        "/*/cac:InvoiceLine/cac:Price/cac:AllowanceCharge",
    )


def test_gross_price_without_discount_reads_back_with_the_derived_discount() -> None:
    # bt-mapping.md "Normalizations": the writer derives BT-147 = BT-148 - BT-146.
    line = simple_line(price_details=PriceDetails(item_net_price=Decimal("50"), item_gross_price=Decimal("50.75")))
    result = read_back(minimal_invoice(lines=(line,)))
    assert result.invoice.lines[0].price_details.item_price_discount == Decimal("0.75")


def test_xs_whitespace_and_boolean_forms_are_accepted() -> None:
    invoice = minimal_invoice(allowances=full_invoice().allowances)

    def lexical(root: etree._Element) -> None:
        find(root, "cbc:IssueDate").text = "\n  2026-01-15 "
        find(root, "cac:AllowanceCharge/cbc:ChargeIndicator").text = " 0 "

    result = read_changed(invoice, lexical)
    assert result.invoice.issue_date == datetime.date(2026, 1, 15)
    assert result.invoice.allowances == invoice.allowances


# --- errors ----------------------------------------------------------------------------------------------


def test_wrong_root_is_a_parse_error() -> None:
    with pytest.raises(ParseError, match="expected the UBL root Invoice or CreditNote") as caught:
        ubl.read(_xml.parse(b"<Invoice/>"))
    assert caught.value.location == "/Invoice"


@pytest.mark.parametrize(
    ("change", "message", "location"),
    [
        (
            lambda root: find(root, "cbc:InvoiceTypeCode").__setattr__("text", "999"),
            r"^cannot read BG-0 Invoice: BT-3 \(type_code\): .*BR-CL-01",
            "/*",
        ),
        (
            lambda root: root.remove(find(root, "cbc:ID")),
            r"^cannot read BG-0 Invoice: BT-1 \(number\): Field required",
            "/*",
        ),
        (lambda root: root.remove(find(root, "cac:AccountingSupplierParty")), r"BG-4 \(seller\): Field required", "/*"),
        (lambda root: root.remove(find(root, "cac:LegalMonetaryTotal")), r"BG-22 \(totals\): Field required", "/*"),
        (
            lambda root: find(root, "cac:InvoiceLine/cbc:InvoicedQuantity").attrib.pop("unitCode"),
            r"^cannot read BG-25 InvoiceLine: BT-130 \(invoiced_quantity_unit_code\)",
            "/*/cac:InvoiceLine",
        ),
        (
            lambda root: find(
                root, "cac:AccountingCustomerParty/cac:Party/cac:PostalAddress/cac:Country/cbc:IdentificationCode"
            ).__setattr__("text", "XX"),
            r"^cannot read BG-8 BuyerPostalAddress: BT-55 \(country_code\): .*BR-CL-14",
            "/*/cac:AccountingCustomerParty/cac:Party/cac:PostalAddress",
        ),
        (
            lambda root: find(root, "cbc:IssueDate").__setattr__("text", "15.01.2026"),
            r"^BT-2: cannot interpret the date '15.01.2026'",
            "/*/cbc:IssueDate",
        ),
        (
            lambda root: find(root, "cac:InvoiceLine/cbc:LineExtensionAmount").__setattr__("text", "1.005"),
            r"BT-131 \(net_amount\): .*BR-DEC",
            "/*/cac:InvoiceLine",
        ),
        (
            lambda root: find(root, "cbc:IssueDate").__setattr__("text", "2026-02-30"),
            r"^BT-2: cannot interpret the date '2026-02-30'",
            "/*/cbc:IssueDate",
        ),
    ],
    ids=[
        "code",
        "missing-number",
        "missing-seller",
        "missing-totals",
        "missing-unit",
        "country",
        "not-xs-date",
        "decimals",
        "no-calendar-date",
    ],
)
def test_model_errors_name_the_term_and_the_element(
    change: t.Callable[[etree._Element], object], message: str, location: str
) -> None:
    with pytest.raises(ParseError, match=message) as caught:
        read_changed(minimal_invoice(), change)
    assert caught.value.location == location


def test_allowance_without_reason_names_its_group() -> None:
    def no_reason(root: etree._Element) -> None:
        allowance = find(root, "cac:AllowanceCharge")
        for name in ("cbc:AllowanceChargeReason", "cbc:AllowanceChargeReasonCode"):
            allowance.remove(find(allowance, name))

    with pytest.raises(ParseError, match=r"^cannot read BG-20 DocumentLevelAllowance: .*BR-33") as caught:
        read_changed(minimal_invoice(allowances=full_invoice().allowances), no_reason)
    assert caught.value.location == "/*/cac:AllowanceCharge"


def test_bad_boolean_is_a_parse_error() -> None:
    def bad(root: etree._Element) -> None:
        find(root, "cac:AllowanceCharge/cbc:ChargeIndicator").text = "yes"

    with pytest.raises(ParseError, match=r"^BG-20/BG-21: expected an xs:boolean") as caught:
        read_changed(minimal_invoice(allowances=full_invoice().allowances), bad)
    assert caught.value.location == "/*/cac:AllowanceCharge/cbc:ChargeIndicator"


def test_bad_base64_is_a_parse_error() -> None:
    def bad(root: etree._Element) -> None:
        find(
            root, "cac:AdditionalDocumentReference/cac:Attachment/cbc:EmbeddedDocumentBinaryObject"
        ).text = "not base64!"

    with pytest.raises(ParseError, match=r"^BT-125: not base64"):
        read_changed(full_invoice(), bad)


def test_base64_with_line_breaks_is_accepted() -> None:
    def wrap(root: etree._Element) -> None:
        element = find(root, "cac:AdditionalDocumentReference/cac:Attachment/cbc:EmbeddedDocumentBinaryObject")
        text = element.text or ""
        element.text = f"\n{text[:4]}\n {text[4:]}\n"

    assert read_changed(full_invoice(), wrap).invoice == full_invoice()


# --- compared the way the official rules compare --------------------------------------------------------


def test_repeated_payment_means_codes_compare_after_normalize_space() -> None:
    # UBL-SR-47 wants one distinct code; the model normalizes codes, so " 58 " repeats "58". A repeat without
    # @name (BT-82, UBL-SR-46: at most one) is no difference either.
    accounts = (
        CreditTransfer(payment_account_identifier=TEST_IBAN),
        CreditTransfer(payment_account_identifier="ACCOUNT-2"),
    )
    invoice = minimal_invoice(
        payment_instructions=PaymentInstructions(
            payment_means_type_code="58", payment_means_text="SEPA", credit_transfers=accounts
        )
    )

    def pad(root: etree._Element) -> None:
        find(root, "cac:PaymentMeans[2]/cbc:PaymentMeansCode").text = "\n 58 "

    assert read_changed(invoice, pad) == ubl.ParseResult(invoice=invoice)


def test_classification_without_code_is_unmapped_not_an_error() -> None:
    def nature(root: etree._Element) -> None:
        classification = etree.Element(CAC + "CommodityClassification")
        add(classification, "cbc:NatureCode", "X")
        find(root, "cac:InvoiceLine/cac:Item/cac:ClassifiedTaxCategory").addprevious(classification)

    result = read_changed(minimal_invoice(), nature)
    assert result.invoice == minimal_invoice()
    assert result.unmapped == ("/*/cac:InvoiceLine/cac:Item/cac:CommodityClassification",)


def test_scheme_ids_other_than_the_binding_values_are_unmapped() -> None:
    # BT-32 is any non-VAT PartyTaxScheme (UBL-SR-13), but only the writer's "FC" is recognised as filler; a VAT
    # category's TaxScheme must be VAT (BR-CO-04 selects with upper-case(normalize-space(cbc:ID))='VAT').
    invoice = minimal_invoice(seller=full_invoice().seller)

    def other(root: etree._Element) -> None:
        party = find(root, "cac:AccountingSupplierParty/cac:Party")
        party.findall("cac:PartyTaxScheme", _xml.UBL_NSMAP)[1].find("cac:TaxScheme/cbc:ID", _xml.UBL_NSMAP).text = "TAX"  # type: ignore[union-attr]  # present in the writer output
        find(root, "cac:InvoiceLine/cac:Item/cac:ClassifiedTaxCategory/cac:TaxScheme/cbc:ID").text = " vat "
        find(root, "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cac:TaxScheme/cbc:ID").text = "GST"

    result = read_changed(invoice, other)
    assert result.invoice == invoice
    assert result.unmapped == (
        "/*/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme[2]/cac:TaxScheme",
        "/*/cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cac:TaxScheme",
    )
