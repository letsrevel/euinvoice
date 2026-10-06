"""One write test per EN 16931 business term and group in UBL (``docs/reference/bt-mapping.md``).

``BT_ROWS`` is keyed by the BT/BG id (first element of each row) so the BT coverage gate (#32) can introspect
it. Each row: the id, the invoice fields set on top of the minimal invoice, an XPath (``string(...)``) and
the text it must yield in the output. Paths use the ``Invoice`` root; credit-note specifics are tested in
``test_ubl_write.py``.
"""

import datetime
import typing as t
from decimal import Decimal

import pytest
from _ubl_support import written, xpath

from _invoices import TEST_IBAN, minimal_invoice, simple_line
from euinvoice.model import (
    BT_INDEX,
    AdditionalSupportingDocument,
    BinaryObject,
    Buyer,
    BuyerContact,
    BuyerPostalAddress,
    CreditTransfer,
    DeliverToAddress,
    DeliveryInformation,
    DirectDebit,
    DocumentLevelAllowance,
    DocumentLevelCharge,
    DocumentTotals,
    Identifier,
    InvoiceLineAllowance,
    InvoiceLineCharge,
    InvoiceLinePeriod,
    InvoiceNote,
    InvoicingPeriod,
    ItemAttribute,
    ItemClassificationIdentifier,
    ItemInformation,
    LineVatInformation,
    Payee,
    PaymentCardInformation,
    PaymentInstructions,
    PrecedingInvoiceReference,
    PriceDetails,
    ProcessControl,
    Seller,
    SellerContact,
    SellerPostalAddress,
    SellerTaxRepresentative,
    TaxRepresentativePostalAddress,
    VatBreakdown,
)


def _totals(**changes: t.Any) -> DocumentTotals:
    """The minimal invoice's totals with ``changes``."""
    return DocumentTotals.model_validate({**dict(minimal_invoice().totals), **changes})


S: t.Final = "/*/cac:AccountingSupplierParty/cac:Party"
B: t.Final = "/*/cac:AccountingCustomerParty/cac:Party"
L: t.Final = "/*/cac:InvoiceLine"
PM: t.Final = "/*/cac:PaymentMeans"
D = Decimal
DAY = datetime.date(2026, 1, 31)

_ADDRESS = {
    "address_line_1": "Street 1",
    "address_line_2": "Building A",
    "address_line_3": "Floor 2",
    "city": "City",
    "post_code": "10000",
    "country_subdivision": "State",
}
_SELLER = Seller(
    name="Seller Example GmbH",
    vat_identifier="DE000000000",
    trading_name="Seller Trading",
    identifiers=(Identifier(value="SELLER-1"), Identifier(value="4000001000005", scheme_id="0088")),
    legal_registration_identifier=Identifier(value="HRB 00000", scheme_id="0002"),
    tax_registration_identifier="000/000/00000",
    additional_legal_information="Share capital",
    electronic_address=Identifier(value="seller@example.com", scheme_id="EM"),
    postal_address=SellerPostalAddress(country_code="DE", **_ADDRESS),
    contact=SellerContact(contact_point="Sales", telephone="+49 0", email="sales@example.com"),
)
_BUYER = Buyer(
    name="Buyer Example AG",
    trading_name="Buyer Trading",
    identifier=Identifier(value="BUYER-1", scheme_id="0088"),
    legal_registration_identifier=Identifier(value="CHE-000", scheme_id="0183"),
    vat_identifier="ATU00000000",
    electronic_address=Identifier(value="buyer@example.com", scheme_id="EM"),
    postal_address=BuyerPostalAddress(country_code="AT", **_ADDRESS),
    contact=BuyerContact(contact_point="AP", telephone="+43 0", email="ap@example.com"),
)
_PAYEE = Payee(
    name="Payee Ltd",
    identifier=Identifier(value="PAYEE-1", scheme_id="0088"),
    legal_registration_identifier=Identifier(value="00000000", scheme_id="0002"),
)
_TAX_REP = SellerTaxRepresentative(
    name="Tax Rep SARL",
    vat_identifier="FR00000000000",
    postal_address=TaxRepresentativePostalAddress(country_code="FR", **_ADDRESS),
)
_DELIVERY = DeliveryInformation(
    deliver_to_party_name="Warehouse",
    deliver_to_location_identifier=Identifier(value="4000001000012", scheme_id="0088"),
    actual_delivery_date=DAY,
    invoicing_period=InvoicingPeriod(start_date=datetime.date(2026, 1, 1), end_date=DAY),
    deliver_to_address=DeliverToAddress(country_code="NL", **_ADDRESS),
)
_PAYMENT = PaymentInstructions(
    payment_means_type_code="58",
    payment_means_text="SEPA credit transfer",
    remittance_information="REF-1",
    credit_transfers=(
        CreditTransfer(
            payment_account_identifier=TEST_IBAN,
            payment_account_name="Seller",
            payment_service_provider_identifier="EXAMPLEXXXX",
        ),
    ),
    payment_card=PaymentCardInformation(primary_account_number="******1234", holder_name="A. Holder"),
    direct_debit=DirectDebit(
        mandate_reference_identifier="MANDATE-1",
        bank_assigned_creditor_identifier="DE98ZZZ09999999999",
        debited_account_identifier=TEST_IBAN,
    ),
)
_ALLOWANCE = DocumentLevelAllowance(
    amount=D("10.00"), base_amount=D("100.00"), percentage=D("10"), vat_category_code="S", vat_rate=D("19"),
    reason="Discount", reason_code="95",
)  # fmt: skip
_CHARGE = DocumentLevelCharge(
    amount=D("7.00"), base_amount=D("70.00"), percentage=D("10"), vat_category_code="Z", vat_rate=D("0"),
    reason="Freight", reason_code="FC",
)  # fmt: skip
_TOTALS = _totals(
    sum_of_allowances=D("10.00"),
    sum_of_charges=D("7.00"),
    paid_amount=D("5.00"),
    rounding_amount=D("0.01"),
)
_BREAKDOWN = VatBreakdown(
    taxable_amount=D("100.00"), tax_amount=D("0.00"), category_code="E", rate=D("0"),
    exemption_reason="Exempt", exemption_reason_code="VATEX-EU-132",
)  # fmt: skip
_DOCUMENT = AdditionalSupportingDocument(
    reference="DOC-1",
    description="Timesheet",
    external_location="https://example.com/doc.pdf",
    attached_document=BinaryObject(content=b"%PDF", mime_code="application/pdf", filename="doc.pdf"),
)
_LINE = simple_line(
    note="Line note",
    object_identifier=Identifier(value="LINE-OBJ", scheme_id="AAA"),
    purchase_order_line_reference="PO-1-10",
    buyer_accounting_reference="ACC-LINE",
    period=InvoiceLinePeriod(start_date=datetime.date(2026, 1, 1), end_date=DAY),
    allowances=(
        InvoiceLineAllowance(
            amount=D("5.00"), base_amount=D("100.00"), percentage=D("5"), reason="Disc", reason_code="95"
        ),
    ),
    charges=(
        InvoiceLineCharge(
            amount=D("3.00"), base_amount=D("100.00"), percentage=D("3"), reason="Pack", reason_code="ABL"
        ),
    ),
    price_details=PriceDetails(
        item_net_price=D("49.9900"),
        item_price_discount=D("0.51"),
        item_gross_price=D("50.50"),
        base_quantity=D("1.5"),
        base_quantity_unit_code="KGM",
    ),
    vat_information=LineVatInformation(category_code="Z", rate=D("0.0")),
    item=ItemInformation(
        name="Widget",
        description="A widget",
        sellers_identifier="SKU-1",
        buyers_identifier="BUY-SKU-1",
        standard_identifier=Identifier(value="4000001000029", scheme_id="0160"),
        classification_identifiers=(
            ItemClassificationIdentifier(value="43211503", scheme_id="STI", scheme_version_id="19.0501"),
        ),
        country_of_origin="CN",
        attributes=(ItemAttribute(name="Colour", value="Blue"),),
    ),
)

_SELLER_ADDRESS = f"{S}/cac:PostalAddress"
_BUYER_ADDRESS = f"{B}/cac:PostalAddress"
_REP = "/*/cac:TaxRepresentativeParty"
_DLV = "/*/cac:Delivery"
_DLV_ADDRESS = f"{_DLV}/cac:DeliveryLocation/cac:Address"
_DOC_AC = "/*/cac:AllowanceCharge"
_ALLOW = f"{_DOC_AC}[cbc:ChargeIndicator='false']"
_CHRG = f"{_DOC_AC}[cbc:ChargeIndicator='true']"
_LMT = "/*/cac:LegalMonetaryTotal"
_SUB = "/*/cac:TaxTotal/cac:TaxSubtotal"
_LINE_ALLOW = f"{L}/cac:AllowanceCharge[cbc:ChargeIndicator='false']"
_LINE_CHRG = f"{L}/cac:AllowanceCharge[cbc:ChargeIndicator='true']"
_ITEM = f"{L}/cac:Item"
_ADR = "/*/cac:AdditionalDocumentReference"

Row = tuple[str, dict[str, t.Any], str, str]

BT_ROWS: t.Final[list[Row]] = [
    ("BG-0", {}, "local-name(/*)", "Invoice"),
    ("BT-1", {"number": "INV-42"}, "string(/*/cbc:ID)", "INV-42"),
    ("BT-2", {"issue_date": datetime.date(2026, 3, 4)}, "string(/*/cbc:IssueDate)", "2026-03-04"),
    ("BT-3", {"type_code": "389"}, "string(/*/cbc:InvoiceTypeCode)", "389"),
    ("BT-5", {"currency_code": "CHF"}, "string(/*/cbc:DocumentCurrencyCode)", "CHF"),
    ("BT-5", {"currency_code": "CHF"}, f"string({_LMT}/cbc:PayableAmount/@currencyID)", "CHF"),
    ("BT-6", {"vat_accounting_currency_code": "SEK"}, "string(/*/cbc:TaxCurrencyCode)", "SEK"),
    ("BT-7", {"vat_point_date": DAY}, "string(/*/cbc:TaxPointDate)", "2026-01-31"),
    ("BT-8", {"vat_point_date_code": "35"}, "string(/*/cac:InvoicePeriod/cbc:DescriptionCode)", "35"),
    ("BT-9", {"payment_due_date": DAY}, "string(/*/cbc:DueDate)", "2026-01-31"),
    ("BT-10", {"buyer_reference": "BR-1"}, "string(/*/cbc:BuyerReference)", "BR-1"),
    ("BT-11", {"project_reference": "PROJ-1"}, "string(/*/cac:ProjectReference/cbc:ID)", "PROJ-1"),
    ("BT-12", {"contract_reference": "C-1"}, "string(/*/cac:ContractDocumentReference/cbc:ID)", "C-1"),
    ("BT-13", {"purchase_order_reference": "PO-1"}, "string(/*/cac:OrderReference/cbc:ID)", "PO-1"),
    ("BT-14", {"sales_order_reference": "SO-1"}, "string(/*/cac:OrderReference/cbc:SalesOrderID)", "SO-1"),
    ("BT-15", {"receiving_advice_reference": "RA-1"}, "string(/*/cac:ReceiptDocumentReference/cbc:ID)", "RA-1"),
    ("BT-16", {"despatch_advice_reference": "DA-1"}, "string(/*/cac:DespatchDocumentReference/cbc:ID)", "DA-1"),
    ("BT-17", {"tender_or_lot_reference": "LOT-1"}, "string(/*/cac:OriginatorDocumentReference/cbc:ID)", "LOT-1"),
    ("BT-18", {"invoiced_object_identifier": Identifier(value="OBJ-1", scheme_id="AAA")}, f"string({_ADR}[cbc:DocumentTypeCode='130']/cbc:ID)", "OBJ-1"),
    ("BT-18", {"invoiced_object_identifier": Identifier(value="OBJ-1", scheme_id="AAA")}, f"string({_ADR}[cbc:DocumentTypeCode='130']/cbc:ID/@schemeID)", "AAA"),
    ("BT-19", {"buyer_accounting_reference": "ACC-1"}, "string(/*/cbc:AccountingCost)", "ACC-1"),
    ("BT-20", {"payment_terms": "30 days"}, "string(/*/cac:PaymentTerms/cbc:Note)", "30 days"),
    ("BG-1", {"notes": (InvoiceNote(note="One"), InvoiceNote(note="Two"))}, "string(count(/*/cbc:Note))", "2"),
    ("BT-21", {"notes": (InvoiceNote(subject_code="AAI", note="Text"),)}, "string(/*/cbc:Note)", "#AAI#Text"),
    ("BT-22", {"notes": (InvoiceNote(note="Plain note"),)}, "string(/*/cbc:Note)", "Plain note"),
    ("BG-2", {}, "string(/*/cbc:CustomizationID)", "urn:cen.eu:en16931:2017"),
    ("BT-23", {"process_control": ProcessControl(business_process_type="urn:example.com:p", specification_identifier="urn:x")}, "string(/*/cbc:ProfileID)", "urn:example.com:p"),
    ("BT-24", {"process_control": ProcessControl(specification_identifier="urn:example.com:spec")}, "string(/*/cbc:CustomizationID)", "urn:example.com:spec"),
    ("BG-3", {"preceding_invoice_references": (PrecedingInvoiceReference(reference="A"), PrecedingInvoiceReference(reference="B"))}, "string(count(/*/cac:BillingReference/cac:InvoiceDocumentReference))", "2"),
    ("BT-25", {"preceding_invoice_references": (PrecedingInvoiceReference(reference="INV-0"),)}, "string(/*/cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID)", "INV-0"),
    ("BT-26", {"preceding_invoice_references": (PrecedingInvoiceReference(reference="INV-0", issue_date=DAY),)}, "string(/*/cac:BillingReference/cac:InvoiceDocumentReference/cbc:IssueDate)", "2026-01-31"),
    ("BG-4", {}, "string(count(/*/cac:AccountingSupplierParty/cac:Party))", "1"),
    ("BT-27", {}, f"string({S}/cac:PartyLegalEntity/cbc:RegistrationName)", "Seller Example GmbH"),
    ("BT-28", {"seller": _SELLER}, f"string({S}/cac:PartyName/cbc:Name)", "Seller Trading"),
    ("BT-29", {"seller": _SELLER}, f"string({S}/cac:PartyIdentification[1]/cbc:ID)", "SELLER-1"),
    ("BT-29", {"seller": _SELLER}, f"string({S}/cac:PartyIdentification[2]/cbc:ID/@schemeID)", "0088"),
    ("BT-30", {"seller": _SELLER}, f"string({S}/cac:PartyLegalEntity/cbc:CompanyID)", "HRB 00000"),
    ("BT-30", {"seller": _SELLER}, f"string({S}/cac:PartyLegalEntity/cbc:CompanyID/@schemeID)", "0002"),
    ("BT-31", {}, f"string({S}/cac:PartyTaxScheme[cac:TaxScheme/cbc:ID='VAT']/cbc:CompanyID)", "DE000000000"),
    ("BT-32", {"seller": _SELLER}, f"string({S}/cac:PartyTaxScheme[cac:TaxScheme/cbc:ID!='VAT']/cbc:CompanyID)", "000/000/00000"),
    ("BT-33", {"seller": _SELLER}, f"string({S}/cac:PartyLegalEntity/cbc:CompanyLegalForm)", "Share capital"),
    ("BT-34", {"seller": _SELLER}, f"string({S}/cbc:EndpointID)", "seller@example.com"),
    ("BT-34", {"seller": _SELLER}, f"string({S}/cbc:EndpointID/@schemeID)", "EM"),
    ("BG-5", {}, f"string(count({_SELLER_ADDRESS}))", "1"),
    ("BT-35", {"seller": _SELLER}, f"string({_SELLER_ADDRESS}/cbc:StreetName)", "Street 1"),
    ("BT-36", {"seller": _SELLER}, f"string({_SELLER_ADDRESS}/cbc:AdditionalStreetName)", "Building A"),
    ("BT-162", {"seller": _SELLER}, f"string({_SELLER_ADDRESS}/cac:AddressLine/cbc:Line)", "Floor 2"),
    ("BT-37", {"seller": _SELLER}, f"string({_SELLER_ADDRESS}/cbc:CityName)", "City"),
    ("BT-38", {"seller": _SELLER}, f"string({_SELLER_ADDRESS}/cbc:PostalZone)", "10000"),
    ("BT-39", {"seller": _SELLER}, f"string({_SELLER_ADDRESS}/cbc:CountrySubentity)", "State"),
    ("BT-40", {}, f"string({_SELLER_ADDRESS}/cac:Country/cbc:IdentificationCode)", "DE"),
    ("BG-6", {"seller": _SELLER}, f"string(count({S}/cac:Contact))", "1"),
    ("BT-41", {"seller": _SELLER}, f"string({S}/cac:Contact/cbc:Name)", "Sales"),
    ("BT-42", {"seller": _SELLER}, f"string({S}/cac:Contact/cbc:Telephone)", "+49 0"),
    ("BT-43", {"seller": _SELLER}, f"string({S}/cac:Contact/cbc:ElectronicMail)", "sales@example.com"),
    ("BG-7", {}, f"string(count({B}))", "1"),
    ("BT-44", {}, f"string({B}/cac:PartyLegalEntity/cbc:RegistrationName)", "Buyer Example AG"),
    ("BT-45", {"buyer": _BUYER}, f"string({B}/cac:PartyName/cbc:Name)", "Buyer Trading"),
    ("BT-46", {"buyer": _BUYER}, f"string({B}/cac:PartyIdentification/cbc:ID)", "BUYER-1"),
    ("BT-46", {"buyer": _BUYER}, f"string({B}/cac:PartyIdentification/cbc:ID/@schemeID)", "0088"),
    ("BT-47", {"buyer": _BUYER}, f"string({B}/cac:PartyLegalEntity/cbc:CompanyID)", "CHE-000"),
    ("BT-47", {"buyer": _BUYER}, f"string({B}/cac:PartyLegalEntity/cbc:CompanyID/@schemeID)", "0183"),
    ("BT-48", {"buyer": _BUYER}, f"string({B}/cac:PartyTaxScheme[cac:TaxScheme/cbc:ID='VAT']/cbc:CompanyID)", "ATU00000000"),
    ("BT-49", {"buyer": _BUYER}, f"string({B}/cbc:EndpointID)", "buyer@example.com"),
    ("BT-49", {"buyer": _BUYER}, f"string({B}/cbc:EndpointID/@schemeID)", "EM"),
    ("BG-8", {}, f"string(count({_BUYER_ADDRESS}))", "1"),
    ("BT-50", {"buyer": _BUYER}, f"string({_BUYER_ADDRESS}/cbc:StreetName)", "Street 1"),
    ("BT-51", {"buyer": _BUYER}, f"string({_BUYER_ADDRESS}/cbc:AdditionalStreetName)", "Building A"),
    ("BT-163", {"buyer": _BUYER}, f"string({_BUYER_ADDRESS}/cac:AddressLine/cbc:Line)", "Floor 2"),
    ("BT-52", {"buyer": _BUYER}, f"string({_BUYER_ADDRESS}/cbc:CityName)", "City"),
    ("BT-53", {"buyer": _BUYER}, f"string({_BUYER_ADDRESS}/cbc:PostalZone)", "10000"),
    ("BT-54", {"buyer": _BUYER}, f"string({_BUYER_ADDRESS}/cbc:CountrySubentity)", "State"),
    ("BT-55", {"buyer": _BUYER}, f"string({_BUYER_ADDRESS}/cac:Country/cbc:IdentificationCode)", "AT"),
    ("BG-9", {"buyer": _BUYER}, f"string(count({B}/cac:Contact))", "1"),
    ("BT-56", {"buyer": _BUYER}, f"string({B}/cac:Contact/cbc:Name)", "AP"),
    ("BT-57", {"buyer": _BUYER}, f"string({B}/cac:Contact/cbc:Telephone)", "+43 0"),
    ("BT-58", {"buyer": _BUYER}, f"string({B}/cac:Contact/cbc:ElectronicMail)", "ap@example.com"),
    ("BG-10", {"payee": _PAYEE}, "string(count(/*/cac:PayeeParty))", "1"),
    ("BT-59", {"payee": _PAYEE}, "string(/*/cac:PayeeParty/cac:PartyName/cbc:Name)", "Payee Ltd"),
    ("BT-60", {"payee": _PAYEE}, "string(/*/cac:PayeeParty/cac:PartyIdentification/cbc:ID[not(@schemeID='SEPA')])", "PAYEE-1"),
    ("BT-60", {"payee": _PAYEE}, "string(/*/cac:PayeeParty/cac:PartyIdentification/cbc:ID/@schemeID)", "0088"),
    ("BT-61", {"payee": _PAYEE}, "string(/*/cac:PayeeParty/cac:PartyLegalEntity/cbc:CompanyID)", "00000000"),
    ("BT-61", {"payee": _PAYEE}, "string(/*/cac:PayeeParty/cac:PartyLegalEntity/cbc:CompanyID/@schemeID)", "0002"),
    ("BG-11", {"seller_tax_representative": _TAX_REP}, f"string(count({_REP}))", "1"),
    ("BT-62", {"seller_tax_representative": _TAX_REP}, f"string({_REP}/cac:PartyName/cbc:Name)", "Tax Rep SARL"),
    ("BT-63", {"seller_tax_representative": _TAX_REP}, f"string({_REP}/cac:PartyTaxScheme[cac:TaxScheme/cbc:ID='VAT']/cbc:CompanyID)", "FR00000000000"),
    ("BG-12", {"seller_tax_representative": _TAX_REP}, f"string(count({_REP}/cac:PostalAddress))", "1"),
    ("BT-64", {"seller_tax_representative": _TAX_REP}, f"string({_REP}/cac:PostalAddress/cbc:StreetName)", "Street 1"),
    ("BT-65", {"seller_tax_representative": _TAX_REP}, f"string({_REP}/cac:PostalAddress/cbc:AdditionalStreetName)", "Building A"),
    ("BT-164", {"seller_tax_representative": _TAX_REP}, f"string({_REP}/cac:PostalAddress/cac:AddressLine/cbc:Line)", "Floor 2"),
    ("BT-66", {"seller_tax_representative": _TAX_REP}, f"string({_REP}/cac:PostalAddress/cbc:CityName)", "City"),
    ("BT-67", {"seller_tax_representative": _TAX_REP}, f"string({_REP}/cac:PostalAddress/cbc:PostalZone)", "10000"),
    ("BT-68", {"seller_tax_representative": _TAX_REP}, f"string({_REP}/cac:PostalAddress/cbc:CountrySubentity)", "State"),
    ("BT-69", {"seller_tax_representative": _TAX_REP}, f"string({_REP}/cac:PostalAddress/cac:Country/cbc:IdentificationCode)", "FR"),
    ("BG-13", {"delivery": _DELIVERY}, f"string(count({_DLV}))", "1"),
    ("BT-70", {"delivery": _DELIVERY}, f"string({_DLV}/cac:DeliveryParty/cac:PartyName/cbc:Name)", "Warehouse"),
    ("BT-71", {"delivery": _DELIVERY}, f"string({_DLV}/cac:DeliveryLocation/cbc:ID)", "4000001000012"),
    ("BT-71", {"delivery": _DELIVERY}, f"string({_DLV}/cac:DeliveryLocation/cbc:ID/@schemeID)", "0088"),
    ("BT-72", {"delivery": _DELIVERY}, f"string({_DLV}/cbc:ActualDeliveryDate)", "2026-01-31"),
    ("BG-14", {"delivery": _DELIVERY}, "string(count(/*/cac:InvoicePeriod))", "1"),
    ("BT-73", {"delivery": _DELIVERY}, "string(/*/cac:InvoicePeriod/cbc:StartDate)", "2026-01-01"),
    ("BT-74", {"delivery": _DELIVERY}, "string(/*/cac:InvoicePeriod/cbc:EndDate)", "2026-01-31"),
    ("BG-15", {"delivery": _DELIVERY}, f"string(count({_DLV_ADDRESS}))", "1"),
    ("BT-75", {"delivery": _DELIVERY}, f"string({_DLV_ADDRESS}/cbc:StreetName)", "Street 1"),
    ("BT-76", {"delivery": _DELIVERY}, f"string({_DLV_ADDRESS}/cbc:AdditionalStreetName)", "Building A"),
    ("BT-165", {"delivery": _DELIVERY}, f"string({_DLV_ADDRESS}/cac:AddressLine/cbc:Line)", "Floor 2"),
    ("BT-77", {"delivery": _DELIVERY}, f"string({_DLV_ADDRESS}/cbc:CityName)", "City"),
    ("BT-78", {"delivery": _DELIVERY}, f"string({_DLV_ADDRESS}/cbc:PostalZone)", "10000"),
    ("BT-79", {"delivery": _DELIVERY}, f"string({_DLV_ADDRESS}/cbc:CountrySubentity)", "State"),
    ("BT-80", {"delivery": _DELIVERY}, f"string({_DLV_ADDRESS}/cac:Country/cbc:IdentificationCode)", "NL"),
    ("BG-16", {"payment_instructions": _PAYMENT}, f"string(count({PM}))", "1"),
    ("BT-81", {"payment_instructions": _PAYMENT}, f"string({PM}/cbc:PaymentMeansCode)", "58"),
    ("BT-82", {"payment_instructions": _PAYMENT}, f"string({PM}/cbc:PaymentMeansCode/@name)", "SEPA credit transfer"),
    ("BT-83", {"payment_instructions": _PAYMENT}, f"string({PM}/cbc:PaymentID)", "REF-1"),
    ("BG-17", {"payment_instructions": _PAYMENT}, f"string(count({PM}/cac:PayeeFinancialAccount))", "1"),
    ("BT-84", {"payment_instructions": _PAYMENT}, f"string({PM}/cac:PayeeFinancialAccount/cbc:ID)", TEST_IBAN),
    ("BT-85", {"payment_instructions": _PAYMENT}, f"string({PM}/cac:PayeeFinancialAccount/cbc:Name)", "Seller"),
    ("BT-86", {"payment_instructions": _PAYMENT}, f"string({PM}/cac:PayeeFinancialAccount/cac:FinancialInstitutionBranch/cbc:ID)", "EXAMPLEXXXX"),
    ("BG-18", {"payment_instructions": _PAYMENT}, f"string(count({PM}/cac:CardAccount))", "1"),
    ("BT-87", {"payment_instructions": _PAYMENT}, f"string({PM}/cac:CardAccount/cbc:PrimaryAccountNumberID)", "******1234"),
    ("BT-88", {"payment_instructions": _PAYMENT}, f"string({PM}/cac:CardAccount/cbc:HolderName)", "A. Holder"),
    ("BG-19", {"payment_instructions": _PAYMENT}, f"string(count({PM}/cac:PaymentMandate))", "1"),
    ("BT-89", {"payment_instructions": _PAYMENT}, f"string({PM}/cac:PaymentMandate/cbc:ID)", "MANDATE-1"),
    ("BT-90", {"payment_instructions": _PAYMENT}, f"string({S}/cac:PartyIdentification/cbc:ID[@schemeID='SEPA'])", "DE98ZZZ09999999999"),
    ("BT-90", {"payment_instructions": _PAYMENT, "payee": _PAYEE}, "string(/*/cac:PayeeParty/cac:PartyIdentification/cbc:ID[@schemeID='SEPA'])", "DE98ZZZ09999999999"),
    ("BT-91", {"payment_instructions": _PAYMENT}, f"string({PM}/cac:PaymentMandate/cac:PayerFinancialAccount/cbc:ID)", TEST_IBAN),
    ("BG-20", {"allowances": (_ALLOWANCE,)}, f"string(count({_ALLOW}))", "1"),
    ("BT-92", {"allowances": (_ALLOWANCE,)}, f"string({_ALLOW}/cbc:Amount)", "10.00"),
    ("BT-92", {"allowances": (_ALLOWANCE,)}, f"string({_ALLOW}/cbc:Amount/@currencyID)", "EUR"),
    ("BT-93", {"allowances": (_ALLOWANCE,)}, f"string({_ALLOW}/cbc:BaseAmount)", "100.00"),
    ("BT-94", {"allowances": (_ALLOWANCE,)}, f"string({_ALLOW}/cbc:MultiplierFactorNumeric)", "10"),
    ("BT-95", {"allowances": (_ALLOWANCE,)}, f"string({_ALLOW}/cac:TaxCategory[cac:TaxScheme/cbc:ID='VAT']/cbc:ID)", "S"),
    ("BT-96", {"allowances": (_ALLOWANCE,)}, f"string({_ALLOW}/cac:TaxCategory/cbc:Percent)", "19"),
    ("BT-97", {"allowances": (_ALLOWANCE,)}, f"string({_ALLOW}/cbc:AllowanceChargeReason)", "Discount"),
    ("BT-98", {"allowances": (_ALLOWANCE,)}, f"string({_ALLOW}/cbc:AllowanceChargeReasonCode)", "95"),
    ("BG-21", {"charges": (_CHARGE,)}, f"string(count({_CHRG}))", "1"),
    ("BT-99", {"charges": (_CHARGE,)}, f"string({_CHRG}/cbc:Amount)", "7.00"),
    ("BT-100", {"charges": (_CHARGE,)}, f"string({_CHRG}/cbc:BaseAmount)", "70.00"),
    ("BT-101", {"charges": (_CHARGE,)}, f"string({_CHRG}/cbc:MultiplierFactorNumeric)", "10"),
    ("BT-102", {"charges": (_CHARGE,)}, f"string({_CHRG}/cac:TaxCategory[cac:TaxScheme/cbc:ID='VAT']/cbc:ID)", "Z"),
    ("BT-103", {"charges": (_CHARGE,)}, f"string({_CHRG}/cac:TaxCategory/cbc:Percent)", "0"),
    ("BT-104", {"charges": (_CHARGE,)}, f"string({_CHRG}/cbc:AllowanceChargeReason)", "Freight"),
    ("BT-105", {"charges": (_CHARGE,)}, f"string({_CHRG}/cbc:AllowanceChargeReasonCode)", "FC"),
    ("BG-22", {}, f"string(count({_LMT}))", "1"),
    ("BT-106", {"totals": _TOTALS}, f"string({_LMT}/cbc:LineExtensionAmount)", "100.00"),
    ("BT-107", {"totals": _TOTALS}, f"string({_LMT}/cbc:AllowanceTotalAmount)", "10.00"),
    ("BT-108", {"totals": _TOTALS}, f"string({_LMT}/cbc:ChargeTotalAmount)", "7.00"),
    ("BT-109", {"totals": _TOTALS}, f"string({_LMT}/cbc:TaxExclusiveAmount)", "100.00"),
    ("BT-110", {"totals": _TOTALS}, "string(/*/cac:TaxTotal/cbc:TaxAmount[@currencyID=/*/cbc:DocumentCurrencyCode])", "19.00"),
    ("BT-111", {"totals": _totals(total_vat_in_accounting_currency=D("210.00")), "vat_accounting_currency_code": "SEK"}, "string(/*/cac:TaxTotal/cbc:TaxAmount[@currencyID=/*/cbc:TaxCurrencyCode])", "210.00"),
    ("BT-112", {"totals": _TOTALS}, f"string({_LMT}/cbc:TaxInclusiveAmount)", "119.00"),
    ("BT-113", {"totals": _TOTALS}, f"string({_LMT}/cbc:PrepaidAmount)", "5.00"),
    ("BT-114", {"totals": _TOTALS}, f"string({_LMT}/cbc:PayableRoundingAmount)", "0.01"),
    ("BT-115", {"totals": _TOTALS}, f"string({_LMT}/cbc:PayableAmount)", "119.00"),
    ("BG-23", {"vat_breakdown": (_BREAKDOWN, _BREAKDOWN)}, f"string(count({_SUB}))", "2"),
    ("BT-116", {"vat_breakdown": (_BREAKDOWN,)}, f"string({_SUB}/cbc:TaxableAmount)", "100.00"),
    ("BT-117", {"vat_breakdown": (_BREAKDOWN,)}, f"string({_SUB}/cbc:TaxAmount)", "0.00"),
    ("BT-118", {"vat_breakdown": (_BREAKDOWN,)}, f"string({_SUB}/cac:TaxCategory[cac:TaxScheme/cbc:ID='VAT']/cbc:ID)", "E"),
    ("BT-119", {"vat_breakdown": (_BREAKDOWN,)}, f"string({_SUB}/cac:TaxCategory/cbc:Percent)", "0"),
    ("BT-120", {"vat_breakdown": (_BREAKDOWN,)}, f"string({_SUB}/cac:TaxCategory/cbc:TaxExemptionReason)", "Exempt"),
    ("BT-121", {"vat_breakdown": (_BREAKDOWN,)}, f"string({_SUB}/cac:TaxCategory/cbc:TaxExemptionReasonCode)", "VATEX-EU-132"),
    ("BG-24", {"additional_supporting_documents": (_DOCUMENT, _DOCUMENT)}, f"string(count({_ADR}[not(cbc:DocumentTypeCode)]))", "2"),
    ("BT-122", {"additional_supporting_documents": (_DOCUMENT,)}, f"string({_ADR}/cbc:ID)", "DOC-1"),
    ("BT-123", {"additional_supporting_documents": (_DOCUMENT,)}, f"string({_ADR}/cbc:DocumentDescription)", "Timesheet"),
    ("BT-124", {"additional_supporting_documents": (_DOCUMENT,)}, f"string({_ADR}/cac:Attachment/cac:ExternalReference/cbc:URI)", "https://example.com/doc.pdf"),
    ("BT-125", {"additional_supporting_documents": (_DOCUMENT,)}, f"string({_ADR}/cac:Attachment/cbc:EmbeddedDocumentBinaryObject)", "JVBERg=="),
    ("BT-125", {"additional_supporting_documents": (_DOCUMENT,)}, f"string({_ADR}/cac:Attachment/cbc:EmbeddedDocumentBinaryObject/@mimeCode)", "application/pdf"),
    ("BT-125", {"additional_supporting_documents": (_DOCUMENT,)}, f"string({_ADR}/cac:Attachment/cbc:EmbeddedDocumentBinaryObject/@filename)", "doc.pdf"),
    ("BG-25", {"lines": (simple_line(), simple_line(identifier="2"))}, f"string(count({L}))", "2"),
    ("BT-126", {"lines": (simple_line(identifier="L-7"),)}, f"string({L}/cbc:ID)", "L-7"),
    ("BT-127", {"lines": (_LINE,)}, f"string({L}/cbc:Note)", "Line note"),
    ("BT-128", {"lines": (_LINE,)}, f"string({L}/cac:DocumentReference[cbc:DocumentTypeCode='130']/cbc:ID)", "LINE-OBJ"),
    ("BT-128", {"lines": (_LINE,)}, f"string({L}/cac:DocumentReference/cbc:ID/@schemeID)", "AAA"),
    ("BT-129", {"lines": (simple_line(invoiced_quantity=D("2.500")),)}, f"string({L}/cbc:InvoicedQuantity)", "2.500"),
    ("BT-130", {"lines": (simple_line(invoiced_quantity_unit_code="HUR"),)}, f"string({L}/cbc:InvoicedQuantity/@unitCode)", "HUR"),
    ("BT-131", {}, f"string({L}/cbc:LineExtensionAmount)", "100.00"),
    ("BT-131", {}, f"string({L}/cbc:LineExtensionAmount/@currencyID)", "EUR"),
    ("BT-132", {"lines": (_LINE,)}, f"string({L}/cac:OrderLineReference/cbc:LineID)", "PO-1-10"),
    ("BT-133", {"lines": (_LINE,)}, f"string({L}/cbc:AccountingCost)", "ACC-LINE"),
    ("BG-26", {"lines": (_LINE,)}, f"string(count({L}/cac:InvoicePeriod))", "1"),
    ("BT-134", {"lines": (_LINE,)}, f"string({L}/cac:InvoicePeriod/cbc:StartDate)", "2026-01-01"),
    ("BT-135", {"lines": (_LINE,)}, f"string({L}/cac:InvoicePeriod/cbc:EndDate)", "2026-01-31"),
    ("BG-27", {"lines": (_LINE,)}, f"string(count({_LINE_ALLOW}))", "1"),
    ("BT-136", {"lines": (_LINE,)}, f"string({_LINE_ALLOW}/cbc:Amount)", "5.00"),
    ("BT-137", {"lines": (_LINE,)}, f"string({_LINE_ALLOW}/cbc:BaseAmount)", "100.00"),
    ("BT-138", {"lines": (_LINE,)}, f"string({_LINE_ALLOW}/cbc:MultiplierFactorNumeric)", "5"),
    ("BT-139", {"lines": (_LINE,)}, f"string({_LINE_ALLOW}/cbc:AllowanceChargeReason)", "Disc"),
    ("BT-140", {"lines": (_LINE,)}, f"string({_LINE_ALLOW}/cbc:AllowanceChargeReasonCode)", "95"),
    ("BG-28", {"lines": (_LINE,)}, f"string(count({_LINE_CHRG}))", "1"),
    ("BT-141", {"lines": (_LINE,)}, f"string({_LINE_CHRG}/cbc:Amount)", "3.00"),
    ("BT-142", {"lines": (_LINE,)}, f"string({_LINE_CHRG}/cbc:BaseAmount)", "100.00"),
    ("BT-143", {"lines": (_LINE,)}, f"string({_LINE_CHRG}/cbc:MultiplierFactorNumeric)", "3"),
    ("BT-144", {"lines": (_LINE,)}, f"string({_LINE_CHRG}/cbc:AllowanceChargeReason)", "Pack"),
    ("BT-145", {"lines": (_LINE,)}, f"string({_LINE_CHRG}/cbc:AllowanceChargeReasonCode)", "ABL"),
    ("BG-29", {}, f"string(count({L}/cac:Price))", "1"),
    ("BT-146", {"lines": (_LINE,)}, f"string({L}/cac:Price/cbc:PriceAmount)", "49.9900"),
    ("BT-146", {"lines": (_LINE,)}, f"string({L}/cac:Price/cbc:PriceAmount/@currencyID)", "EUR"),
    ("BT-147", {"lines": (_LINE,)}, f"string({L}/cac:Price/cac:AllowanceCharge[cbc:ChargeIndicator='false']/cbc:Amount)", "0.51"),
    ("BT-148", {"lines": (_LINE,)}, f"string({L}/cac:Price/cac:AllowanceCharge[cbc:ChargeIndicator='false']/cbc:BaseAmount)", "50.50"),
    ("BT-149", {"lines": (_LINE,)}, f"string({L}/cac:Price/cbc:BaseQuantity)", "1.5"),
    ("BT-150", {"lines": (_LINE,)}, f"string({L}/cac:Price/cbc:BaseQuantity/@unitCode)", "KGM"),
    ("BG-30", {}, f"string(count({_ITEM}/cac:ClassifiedTaxCategory))", "1"),
    ("BT-151", {"lines": (_LINE,)}, f"string({_ITEM}/cac:ClassifiedTaxCategory[cac:TaxScheme/cbc:ID='VAT']/cbc:ID)", "Z"),
    ("BT-152", {"lines": (_LINE,)}, f"string({_ITEM}/cac:ClassifiedTaxCategory/cbc:Percent)", "0.0"),
    ("BG-31", {}, f"string(count({_ITEM}))", "1"),
    ("BT-153", {}, f"string({_ITEM}/cbc:Name)", "Widget"),
    ("BT-154", {"lines": (_LINE,)}, f"string({_ITEM}/cbc:Description)", "A widget"),
    ("BT-155", {"lines": (_LINE,)}, f"string({_ITEM}/cac:SellersItemIdentification/cbc:ID)", "SKU-1"),
    ("BT-156", {"lines": (_LINE,)}, f"string({_ITEM}/cac:BuyersItemIdentification/cbc:ID)", "BUY-SKU-1"),
    ("BT-157", {"lines": (_LINE,)}, f"string({_ITEM}/cac:StandardItemIdentification/cbc:ID)", "4000001000029"),
    ("BT-157", {"lines": (_LINE,)}, f"string({_ITEM}/cac:StandardItemIdentification/cbc:ID/@schemeID)", "0160"),
    ("BT-158", {"lines": (_LINE,)}, f"string({_ITEM}/cac:CommodityClassification/cbc:ItemClassificationCode)", "43211503"),
    ("BT-158", {"lines": (_LINE,)}, f"string({_ITEM}/cac:CommodityClassification/cbc:ItemClassificationCode/@listID)", "STI"),
    ("BT-158", {"lines": (_LINE,)}, f"string({_ITEM}/cac:CommodityClassification/cbc:ItemClassificationCode/@listVersionID)", "19.0501"),
    ("BT-159", {"lines": (_LINE,)}, f"string({_ITEM}/cac:OriginCountry/cbc:IdentificationCode)", "CN"),
    ("BG-32", {"lines": (_LINE,)}, f"string(count({_ITEM}/cac:AdditionalItemProperty))", "1"),
    ("BT-160", {"lines": (_LINE,)}, f"string({_ITEM}/cac:AdditionalItemProperty/cbc:Name)", "Colour"),
    ("BT-161", {"lines": (_LINE,)}, f"string({_ITEM}/cac:AdditionalItemProperty/cbc:Value)", "Blue"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("bt", "changes", "path", "expected"), BT_ROWS, ids=[f"{r[0]}:{i}" for i, r in enumerate(BT_ROWS)]
)
def test_business_term_is_written(bt: str, changes: dict[str, t.Any], path: str, expected: str) -> None:
    assert xpath(written(minimal_invoice(**changes)), path) == expected, bt


def test_every_business_term_has_a_write_row() -> None:
    assert {row[0] for row in BT_ROWS} == set(BT_INDEX)
