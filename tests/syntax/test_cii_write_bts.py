"""Per-term write tests of the CII writer: one row per EN 16931 business term and group.

Each row is ``(id, changes, xpath, expected)``. ``changes`` are model overrides applied to
``_cii_invoices.all_terms_invoice()`` (which sets every term CII can carry), ``{}`` where the base suffices.
``expected`` is the tuple of texts / attribute values the XPath selects, or, for a group, the number of
elements it selects. XPaths are those of
``docs/reference/bt-mapping.md``; the BT id comes first so the BT coverage gate (#32) can read the table.
"""

import typing as t

import pytest
from _cii_invoices import all_terms_invoice
from lxml import etree

from _invoices import TEST_IBAN, buyer, payment, rebuild
from euinvoice import _xml
from euinvoice.model import BT_INDEX, CreditTransfer, Identifier
from euinvoice.syntax import cii

ROOT: t.Final = "/rsm:CrossIndustryInvoice"
DOC: t.Final = f"{ROOT}/rsm:ExchangedDocument/"
TX: t.Final = f"{ROOT}/rsm:SupplyChainTradeTransaction/"
AGR: t.Final = f"{TX}ram:ApplicableHeaderTradeAgreement/"
DLV: t.Final = f"{TX}ram:ApplicableHeaderTradeDelivery/"
STL: t.Final = f"{TX}ram:ApplicableHeaderTradeSettlement/"
LINE: t.Final = f"{TX}ram:IncludedSupplyChainTradeLineItem[1]/"
SELLER: t.Final = f"{AGR}ram:SellerTradeParty/"
BUYER: t.Final = f"{AGR}ram:BuyerTradeParty/"
REP: t.Final = f"{AGR}ram:SellerTaxRepresentativeTradeParty/"
SHIP: t.Final = f"{DLV}ram:ShipToTradeParty/"
PAYEE: t.Final = f"{STL}ram:PayeeTradeParty/"
MEANS: t.Final = f"{STL}ram:SpecifiedTradeSettlementPaymentMeans/"
SUM: t.Final = f"{STL}ram:SpecifiedTradeSettlementHeaderMonetarySummation/"
TAX1: t.Final = f"{STL}ram:ApplicableTradeTax[1]/"
TAX2: t.Final = f"{STL}ram:ApplicableTradeTax[2]/"
ALLOW: t.Final = f"{STL}ram:SpecifiedTradeAllowanceCharge[ram:ChargeIndicator/udt:Indicator='false']/"
CHARGE: t.Final = f"{STL}ram:SpecifiedTradeAllowanceCharge[ram:ChargeIndicator/udt:Indicator='true']/"
LSTL: t.Final = f"{LINE}ram:SpecifiedLineTradeSettlement/"
LALLOW: t.Final = f"{LSTL}ram:SpecifiedTradeAllowanceCharge[ram:ChargeIndicator/udt:Indicator='false']/"
LCHARGE: t.Final = f"{LSTL}ram:SpecifiedTradeAllowanceCharge[ram:ChargeIndicator/udt:Indicator='true']/"
LAGR: t.Final = f"{LINE}ram:SpecifiedLineTradeAgreement/"
PRODUCT: t.Final = f"{LINE}ram:SpecifiedTradeProduct/"
DTS: t.Final = "udt:DateTimeString[@format='102']"

Expected = tuple[str, ...] | int
Row = tuple[str, dict[str, t.Any], str, Expected]
"""``(BT/BG id, model overrides of the all-terms base, XPath, expected)``; ``row[0]`` is the id (#32)."""

BT_ROWS: t.Final[tuple[Row, ...]] = (
    ("BG-0", {}, ROOT, 1),
    ("BT-1", {}, f"{DOC}ram:ID", ("INV-2026-0001",)),
    ("BT-2", {}, f"{DOC}ram:IssueDateTime/{DTS}", ("20260115",)),
    ("BT-3", {}, f"{DOC}ram:TypeCode", ("380",)),
    ("BT-5", {}, f"{STL}ram:InvoiceCurrencyCode", ("EUR",)),
    ("BT-6", {}, f"{STL}ram:TaxCurrencyCode", ("SEK",)),
    ("BT-7", {}, f"{TAX1}ram:TaxPointDate/udt:DateString[@format='102']", ("20260110",)),
    ("BT-8", {}, f"{STL}ram:ApplicableTradeTax/ram:DueDateTypeCode", ("29",)),
    ("BT-9", {}, f"{STL}ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/{DTS}", ("20260214",)),
    ("BT-10", {}, f"{AGR}ram:BuyerReference", ("BUYER-REF-1",)),
    ("BT-11", {}, f"{AGR}ram:SpecifiedProcuringProject/ram:ID", ("PROJ-1",)),
    ("BT-12", {}, f"{AGR}ram:ContractReferencedDocument/ram:IssuerAssignedID", ("CONTRACT-1",)),
    ("BT-13", {}, f"{AGR}ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID", ("PO-1",)),
    ("BT-14", {}, f"{AGR}ram:SellerOrderReferencedDocument/ram:IssuerAssignedID", ("SO-1",)),
    ("BT-15", {}, f"{DLV}ram:ReceivingAdviceReferencedDocument/ram:IssuerAssignedID", ("RA-1",)),
    ("BT-16", {}, f"{DLV}ram:DespatchAdviceReferencedDocument/ram:IssuerAssignedID", ("DA-1",)),
    (
        "BT-17",
        {},
        f"{AGR}ram:AdditionalReferencedDocument/ram:IssuerAssignedID[following-sibling::ram:TypeCode='50']",
        ("LOT-1",),
    ),
    (
        "BT-18",
        {},
        f"{AGR}ram:AdditionalReferencedDocument/ram:IssuerAssignedID[following-sibling::ram:TypeCode='130']",
        ("OBJ-1",),
    ),
    ("BT-18", {}, f"{AGR}ram:AdditionalReferencedDocument[ram:TypeCode='130']/ram:ReferenceTypeCode", ("AAA",)),
    ("BT-19", {}, f"{STL}ram:ReceivableSpecifiedTradeAccountingAccount/ram:ID", ("ACC-1",)),
    ("BT-20", {}, f"{STL}ram:SpecifiedTradePaymentTerms/ram:Description", ("30 days net",)),
    ("BG-1", {}, f"{DOC}ram:IncludedNote", 1),
    ("BT-21", {}, f"{DOC}ram:IncludedNote/ram:SubjectCode", ("AAI",)),
    ("BT-22", {}, f"{DOC}ram:IncludedNote/ram:Content", ("Synthetic test invoice.",)),
    ("BG-2", {}, f"{ROOT}/rsm:ExchangedDocumentContext", 1),
    (
        "BT-23",
        {},
        f"{ROOT}/rsm:ExchangedDocumentContext/ram:BusinessProcessSpecifiedDocumentContextParameter/ram:ID",
        ("urn:example.com:process:01",),
    ),
    (
        "BT-24",
        {},
        f"{ROOT}/rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID",
        ("urn:cen.eu:en16931:2017",),
    ),
    ("BG-3", {}, f"{STL}ram:InvoiceReferencedDocument", 1),
    ("BT-25", {}, f"{STL}ram:InvoiceReferencedDocument/ram:IssuerAssignedID", ("INV-2025-0099",)),
    (
        "BT-26",
        {},
        f"{STL}ram:InvoiceReferencedDocument/ram:FormattedIssueDateTime/qdt:DateTimeString[@format='102']",
        ("20251201",),
    ),
    ("BG-4", {}, f"{AGR}ram:SellerTradeParty", 1),
    ("BT-27", {}, f"{SELLER}ram:Name", ("Seller Example GmbH",)),
    ("BT-28", {}, f"{SELLER}ram:SpecifiedLegalOrganization/ram:TradingBusinessName", ("Seller Example",)),
    ("BT-29", {}, f"{SELLER}ram:ID", ("SELLER-1",)),
    ("BT-29", {}, f"{SELLER}ram:GlobalID[@schemeID='0088']", ("4000001000005",)),
    ("BT-30", {}, f"{SELLER}ram:SpecifiedLegalOrganization/ram:ID[@schemeID='0002']", ("HRB 00000",)),
    ("BT-31", {}, f"{SELLER}ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']", ("DE000000000",)),
    ("BT-32", {}, f"{SELLER}ram:SpecifiedTaxRegistration/ram:ID[@schemeID='FC']", ("000/000/00000",)),
    ("BT-33", {}, f"{SELLER}ram:Description", ("Share capital 25 000 EUR",)),
    ("BT-34", {}, f"{SELLER}ram:URIUniversalCommunication/ram:URIID[@schemeID='EM']", ("seller@example.com",)),
    ("BG-5", {}, f"{SELLER}ram:PostalTradeAddress", 1),
    ("BT-35", {}, f"{SELLER}ram:PostalTradeAddress/ram:LineOne", ("Example Street 1",)),
    ("BT-36", {}, f"{SELLER}ram:PostalTradeAddress/ram:LineTwo", ("Building A",)),
    ("BT-162", {}, f"{SELLER}ram:PostalTradeAddress/ram:LineThree", ("Floor 2",)),
    ("BT-37", {}, f"{SELLER}ram:PostalTradeAddress/ram:CityName", ("Example City",)),
    ("BT-38", {}, f"{SELLER}ram:PostalTradeAddress/ram:PostcodeCode", ("10000",)),
    ("BT-39", {}, f"{SELLER}ram:PostalTradeAddress/ram:CountrySubDivisionName", ("Example State",)),
    ("BT-40", {}, f"{SELLER}ram:PostalTradeAddress/ram:CountryID", ("DE",)),
    ("BG-6", {}, f"{SELLER}ram:DefinedTradeContact", 1),
    ("BT-41", {}, f"{SELLER}ram:DefinedTradeContact/ram:PersonName", ("Sales",)),
    (
        "BT-42",
        {},
        f"{SELLER}ram:DefinedTradeContact/ram:TelephoneUniversalCommunication/ram:CompleteNumber",
        ("+49 000 000000",),
    ),
    (
        "BT-43",
        {},
        f"{SELLER}ram:DefinedTradeContact/ram:EmailURIUniversalCommunication/ram:URIID",
        ("sales@example.com",),
    ),
    ("BG-7", {}, f"{AGR}ram:BuyerTradeParty", 1),
    ("BT-44", {}, f"{BUYER}ram:Name", ("Buyer Example AG",)),
    ("BT-45", {}, f"{BUYER}ram:SpecifiedLegalOrganization/ram:TradingBusinessName", ("Buyer Example",)),
    ("BT-46", {}, f"{BUYER}ram:GlobalID[@schemeID='0088']", ("4000001000036",)),
    ("BT-47", {}, f"{BUYER}ram:SpecifiedLegalOrganization/ram:ID[@schemeID='0183']", ("CHE-000.000.000",)),
    ("BT-48", {}, f"{BUYER}ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']", ("ATU00000000",)),
    ("BT-49", {}, f"{BUYER}ram:URIUniversalCommunication/ram:URIID[@schemeID='EM']", ("buyer@example.com",)),
    ("BG-8", {}, f"{BUYER}ram:PostalTradeAddress", 1),
    ("BT-50", {}, f"{BUYER}ram:PostalTradeAddress/ram:LineOne", ("Sample Road 2",)),
    ("BT-51", {}, f"{BUYER}ram:PostalTradeAddress/ram:LineTwo", ("Unit 3",)),
    ("BT-163", {}, f"{BUYER}ram:PostalTradeAddress/ram:LineThree", ("Back office",)),
    ("BT-52", {}, f"{BUYER}ram:PostalTradeAddress/ram:CityName", ("Sample Town",)),
    ("BT-53", {}, f"{BUYER}ram:PostalTradeAddress/ram:PostcodeCode", ("1010",)),
    ("BT-54", {}, f"{BUYER}ram:PostalTradeAddress/ram:CountrySubDivisionName", ("Sample Region",)),
    ("BT-55", {}, f"{BUYER}ram:PostalTradeAddress/ram:CountryID", ("AT",)),
    ("BG-9", {}, f"{BUYER}ram:DefinedTradeContact", 1),
    ("BT-56", {}, f"{BUYER}ram:DefinedTradeContact/ram:PersonName", ("Accounts payable",)),
    (
        "BT-57",
        {},
        f"{BUYER}ram:DefinedTradeContact/ram:TelephoneUniversalCommunication/ram:CompleteNumber",
        ("+43 0 000000",),
    ),
    ("BT-58", {}, f"{BUYER}ram:DefinedTradeContact/ram:EmailURIUniversalCommunication/ram:URIID", ("ap@example.com",)),
    ("BG-10", {}, f"{STL}ram:PayeeTradeParty", 1),
    ("BT-59", {}, f"{PAYEE}ram:Name", ("Payee Example Ltd",)),
    ("BT-60", {}, f"{PAYEE}ram:ID", ("PAYEE-1",)),
    ("BT-61", {}, f"{PAYEE}ram:SpecifiedLegalOrganization/ram:ID[@schemeID='0002']", ("00000000",)),
    ("BG-11", {}, f"{AGR}ram:SellerTaxRepresentativeTradeParty", 1),
    ("BT-62", {}, f"{REP}ram:Name", ("Tax Rep Example SARL",)),
    ("BT-63", {}, f"{REP}ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']", ("FR00000000000",)),
    ("BG-12", {}, f"{REP}ram:PostalTradeAddress", 1),
    ("BT-64", {}, f"{REP}ram:PostalTradeAddress/ram:LineOne", ("Rue Exemple 3",)),
    ("BT-65", {}, f"{REP}ram:PostalTradeAddress/ram:LineTwo", ("Batiment B",)),
    ("BT-164", {}, f"{REP}ram:PostalTradeAddress/ram:LineThree", ("Etage 1",)),
    ("BT-66", {}, f"{REP}ram:PostalTradeAddress/ram:CityName", ("Exempleville",)),
    ("BT-67", {}, f"{REP}ram:PostalTradeAddress/ram:PostcodeCode", ("75000",)),
    ("BT-68", {}, f"{REP}ram:PostalTradeAddress/ram:CountrySubDivisionName", ("Exemple",)),
    ("BT-69", {}, f"{REP}ram:PostalTradeAddress/ram:CountryID", ("FR",)),
    ("BG-13", {}, f"{DLV}ram:ShipToTradeParty", 1),
    ("BT-70", {}, f"{SHIP}ram:Name", ("Warehouse Example",)),
    ("BT-71", {}, f"{SHIP}ram:GlobalID[@schemeID='0088']", ("4000001000012",)),
    ("BT-72", {}, f"{DLV}ram:ActualDeliverySupplyChainEvent/ram:OccurrenceDateTime/{DTS}", ("20260110",)),
    ("BG-14", {}, f"{STL}ram:BillingSpecifiedPeriod", 1),
    ("BT-73", {}, f"{STL}ram:BillingSpecifiedPeriod/ram:StartDateTime/{DTS}", ("20260101",)),
    ("BT-74", {}, f"{STL}ram:BillingSpecifiedPeriod/ram:EndDateTime/{DTS}", ("20260131",)),
    ("BG-15", {}, f"{SHIP}ram:PostalTradeAddress", 1),
    ("BT-75", {}, f"{SHIP}ram:PostalTradeAddress/ram:LineOne", ("Dock Lane 4",)),
    ("BT-76", {}, f"{SHIP}ram:PostalTradeAddress/ram:LineTwo", ("Gate 5",)),
    ("BT-165", {}, f"{SHIP}ram:PostalTradeAddress/ram:LineThree", ("Bay 6",)),
    ("BT-77", {}, f"{SHIP}ram:PostalTradeAddress/ram:CityName", ("Harbour Town",)),
    ("BT-78", {}, f"{SHIP}ram:PostalTradeAddress/ram:PostcodeCode", ("20000",)),
    ("BT-79", {}, f"{SHIP}ram:PostalTradeAddress/ram:CountrySubDivisionName", ("Harbour State",)),
    ("BT-80", {}, f"{SHIP}ram:PostalTradeAddress/ram:CountryID", ("DE",)),
    ("BG-16", {}, f"{STL}ram:SpecifiedTradeSettlementPaymentMeans", 1),
    ("BT-81", {}, f"{MEANS}ram:TypeCode", ("58",)),
    ("BT-82", {}, f"{MEANS}ram:Information", ("SEPA credit transfer",)),
    ("BT-83", {}, f"{STL}ram:PaymentReference", ("INV-2026-0001",)),
    ("BG-17", {}, f"{MEANS}ram:PayeePartyCreditorFinancialAccount", 1),
    ("BT-84", {}, f"{MEANS}ram:PayeePartyCreditorFinancialAccount/ram:IBANID", (TEST_IBAN,)),
    ("BT-85", {}, f"{MEANS}ram:PayeePartyCreditorFinancialAccount/ram:AccountName", ("Seller Example GmbH",)),
    ("BT-86", {}, f"{MEANS}ram:PayeeSpecifiedCreditorFinancialInstitution/ram:BICID", ("EXAMPLEXXXX",)),
    ("BG-18", {}, f"{MEANS}ram:ApplicableTradeSettlementFinancialCard", 1),
    ("BT-87", {}, f"{MEANS}ram:ApplicableTradeSettlementFinancialCard/ram:ID", ("0000000000",)),
    ("BT-88", {}, f"{MEANS}ram:ApplicableTradeSettlementFinancialCard/ram:CardholderName", ("A. Holder",)),
    ("BG-19", {}, f"{MEANS}ram:PayerPartyDebtorFinancialAccount", 1),
    ("BT-89", {}, f"{STL}ram:SpecifiedTradePaymentTerms/ram:DirectDebitMandateID", ("MANDATE-1",)),
    ("BT-90", {}, f"{STL}ram:CreditorReferenceID", ("DE98ZZZ09999999999",)),
    ("BT-91", {}, f"{MEANS}ram:PayerPartyDebtorFinancialAccount/ram:IBANID", (TEST_IBAN,)),
    ("BG-20", {}, ALLOW.removesuffix("/"), 1),
    ("BT-92", {}, f"{ALLOW}ram:ActualAmount", ("10.00",)),
    ("BT-93", {}, f"{ALLOW}ram:BasisAmount", ("100.00",)),
    ("BT-94", {}, f"{ALLOW}ram:CalculationPercent", ("10",)),
    ("BT-95", {}, f"{ALLOW}ram:CategoryTradeTax[ram:TypeCode='VAT']/ram:CategoryCode", ("S",)),
    ("BT-96", {}, f"{ALLOW}ram:CategoryTradeTax/ram:RateApplicablePercent", ("19",)),
    ("BT-97", {}, f"{ALLOW}ram:Reason", ("Loyalty discount",)),
    ("BT-98", {}, f"{ALLOW}ram:ReasonCode", ("95",)),
    ("BG-21", {}, CHARGE.removesuffix("/"), 1),
    ("BT-99", {}, f"{CHARGE}ram:ActualAmount", ("10.00",)),
    ("BT-100", {}, f"{CHARGE}ram:BasisAmount", ("100.00",)),
    ("BT-101", {}, f"{CHARGE}ram:CalculationPercent", ("10",)),
    ("BT-102", {}, f"{CHARGE}ram:CategoryTradeTax[ram:TypeCode='VAT']/ram:CategoryCode", ("S",)),
    ("BT-103", {}, f"{CHARGE}ram:CategoryTradeTax/ram:RateApplicablePercent", ("19",)),
    ("BT-104", {}, f"{CHARGE}ram:Reason", ("Freight",)),
    ("BT-105", {}, f"{CHARGE}ram:ReasonCode", ("FC",)),
    ("BG-22", {}, f"{STL}ram:SpecifiedTradeSettlementHeaderMonetarySummation", 1),
    ("BT-106", {}, f"{SUM}ram:LineTotalAmount", ("150.00",)),
    ("BT-107", {}, f"{SUM}ram:AllowanceTotalAmount", ("10.00",)),
    ("BT-108", {}, f"{SUM}ram:ChargeTotalAmount", ("10.00",)),
    ("BT-109", {}, f"{SUM}ram:TaxBasisTotalAmount", ("150.00",)),
    ("BT-110", {}, f"{SUM}ram:TaxTotalAmount[@currencyID=../../ram:InvoiceCurrencyCode]", ("19.00",)),
    ("BT-111", {}, f"{SUM}ram:TaxTotalAmount[@currencyID=../../ram:TaxCurrencyCode]", ("210.00",)),
    ("BT-112", {}, f"{SUM}ram:GrandTotalAmount", ("169.00",)),
    ("BT-113", {}, f"{SUM}ram:TotalPrepaidAmount", ("0.00",)),
    ("BT-114", {}, f"{SUM}ram:RoundingAmount", ("0.00",)),
    ("BT-115", {}, f"{SUM}ram:DuePayableAmount", ("169.00",)),
    ("BG-23", {}, f"{STL}ram:ApplicableTradeTax[ram:TypeCode='VAT']", 2),
    ("BT-116", {}, f"{STL}ram:ApplicableTradeTax/ram:BasisAmount", ("100.00", "50.00")),
    ("BT-117", {}, f"{STL}ram:ApplicableTradeTax/ram:CalculatedAmount", ("19.00", "0.00")),
    ("BT-118", {}, f"{STL}ram:ApplicableTradeTax/ram:CategoryCode", ("S", "E")),
    ("BT-119", {}, f"{STL}ram:ApplicableTradeTax/ram:RateApplicablePercent", ("19", "0")),
    ("BT-120", {}, f"{TAX2}ram:ExemptionReason", ("Exempt",)),
    ("BT-121", {}, f"{TAX2}ram:ExemptionReasonCode", ("VATEX-EU-132",)),
    ("BG-24", {}, f"{AGR}ram:AdditionalReferencedDocument[ram:TypeCode='916']", 1),
    (
        "BT-122",
        {},
        f"{AGR}ram:AdditionalReferencedDocument/ram:IssuerAssignedID[following-sibling::ram:TypeCode='916']",
        ("TIMESHEET-1",),
    ),
    ("BT-123", {}, f"{AGR}ram:AdditionalReferencedDocument[ram:TypeCode='916']/ram:Name", ("Timesheet",)),
    (
        "BT-124",
        {},
        f"{AGR}ram:AdditionalReferencedDocument[ram:TypeCode='916']/ram:URIID",
        ("https://example.com/timesheet.pdf",),
    ),
    ("BT-125", {}, f"{AGR}ram:AdditionalReferencedDocument/ram:AttachmentBinaryObject", ("JVBERi0xLjcKAP8=",)),
    ("BT-125", {}, f"{AGR}ram:AdditionalReferencedDocument/ram:AttachmentBinaryObject/@mimeCode", ("application/pdf",)),
    ("BT-125", {}, f"{AGR}ram:AdditionalReferencedDocument/ram:AttachmentBinaryObject/@filename", ("timesheet.pdf",)),
    ("BG-25", {}, f"{TX}ram:IncludedSupplyChainTradeLineItem", 2),
    (
        "BT-126",
        {},
        f"{TX}ram:IncludedSupplyChainTradeLineItem/ram:AssociatedDocumentLineDocument/ram:LineID",
        ("1", "2"),
    ),
    ("BT-127", {}, f"{LINE}ram:AssociatedDocumentLineDocument/ram:IncludedNote/ram:Content", ("Line note",)),
    (
        "BT-128",
        {},
        f"{LSTL}ram:AdditionalReferencedDocument/ram:IssuerAssignedID[following-sibling::ram:TypeCode='130']",
        ("LINE-OBJ-1",),
    ),
    ("BT-128", {}, f"{LSTL}ram:AdditionalReferencedDocument/ram:ReferenceTypeCode", ("AAA",)),
    ("BT-129", {}, f"{LINE}ram:SpecifiedLineTradeDelivery/ram:BilledQuantity", ("2",)),
    ("BT-130", {}, f"{LINE}ram:SpecifiedLineTradeDelivery/ram:BilledQuantity/@unitCode", ("C62",)),
    ("BT-131", {}, f"{LSTL}ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount", ("100.00",)),
    ("BT-132", {}, f"{LAGR}ram:BuyerOrderReferencedDocument/ram:LineID", ("PO-1-10",)),
    ("BT-133", {}, f"{LSTL}ram:ReceivableSpecifiedTradeAccountingAccount/ram:ID", ("ACC-LINE-1",)),
    ("BG-26", {}, f"{LSTL}ram:BillingSpecifiedPeriod", 1),
    ("BT-134", {}, f"{LSTL}ram:BillingSpecifiedPeriod/ram:StartDateTime/{DTS}", ("20260101",)),
    ("BT-135", {}, f"{LSTL}ram:BillingSpecifiedPeriod/ram:EndDateTime/{DTS}", ("20260131",)),
    ("BG-27", {}, LALLOW.removesuffix("/"), 1),
    ("BT-136", {}, f"{LALLOW}ram:ActualAmount", ("5.00",)),
    ("BT-137", {}, f"{LALLOW}ram:BasisAmount", ("100.00",)),
    ("BT-138", {}, f"{LALLOW}ram:CalculationPercent", ("5",)),
    ("BT-139", {}, f"{LALLOW}ram:Reason", ("Line discount",)),
    ("BT-140", {}, f"{LALLOW}ram:ReasonCode", ("95",)),
    ("BG-28", {}, LCHARGE.removesuffix("/"), 1),
    ("BT-141", {}, f"{LCHARGE}ram:ActualAmount", ("5.00",)),
    ("BT-142", {}, f"{LCHARGE}ram:BasisAmount", ("100.00",)),
    ("BT-143", {}, f"{LCHARGE}ram:CalculationPercent", ("5",)),
    ("BT-144", {}, f"{LCHARGE}ram:Reason", ("Packing",)),
    ("BT-145", {}, f"{LCHARGE}ram:ReasonCode", ("ABL",)),
    ("BG-29", {}, f"{LAGR}ram:NetPriceProductTradePrice", 1),
    ("BT-146", {}, f"{LAGR}ram:NetPriceProductTradePrice/ram:ChargeAmount", ("50.0000",)),
    (
        "BT-147",
        {},
        f"{LAGR}ram:GrossPriceProductTradePrice/ram:AppliedTradeAllowanceCharge/ram:ActualAmount",
        ("0.5",),
    ),
    ("BT-148", {}, f"{LAGR}ram:GrossPriceProductTradePrice/ram:ChargeAmount", ("50.5",)),
    ("BT-149", {}, f"{LAGR}ram:NetPriceProductTradePrice/ram:BasisQuantity", ("1",)),
    ("BT-150", {}, f"{LAGR}ram:NetPriceProductTradePrice/ram:BasisQuantity/@unitCode", ("C62",)),
    ("BT-149", {}, f"{LAGR}ram:GrossPriceProductTradePrice/ram:BasisQuantity", ("1",)),
    ("BT-150", {}, f"{LAGR}ram:GrossPriceProductTradePrice/ram:BasisQuantity/@unitCode", ("C62",)),
    ("BG-30", {}, f"{LSTL}ram:ApplicableTradeTax[ram:TypeCode='VAT']", 1),
    ("BT-151", {}, f"{LSTL}ram:ApplicableTradeTax/ram:CategoryCode", ("S",)),
    ("BT-152", {}, f"{LSTL}ram:ApplicableTradeTax/ram:RateApplicablePercent", ("19",)),
    ("BG-31", {}, f"{LINE}ram:SpecifiedTradeProduct", 1),
    ("BT-153", {}, f"{PRODUCT}ram:Name", ("Widget",)),
    ("BT-154", {}, f"{PRODUCT}ram:Description", ("A synthetic widget",)),
    ("BT-155", {}, f"{PRODUCT}ram:SellerAssignedID", ("SKU-1",)),
    ("BT-156", {}, f"{PRODUCT}ram:BuyerAssignedID", ("BUY-SKU-1",)),
    ("BT-157", {}, f"{PRODUCT}ram:GlobalID[@schemeID='0160']", ("4000001000029",)),
    ("BT-158", {}, f"{PRODUCT}ram:DesignatedProductClassification/ram:ClassCode[@listID='STI']", ("43211503",)),
    ("BT-158", {}, f"{PRODUCT}ram:DesignatedProductClassification/ram:ClassCode/@listVersionID", ("19.0501",)),
    ("BT-159", {}, f"{PRODUCT}ram:OriginTradeCountry/ram:ID", ("DE",)),
    ("BG-32", {}, f"{PRODUCT}ram:ApplicableProductCharacteristic", 1),
    ("BT-160", {}, f"{PRODUCT}ram:ApplicableProductCharacteristic/ram:Description", ("Colour",)),
    ("BT-161", {}, f"{PRODUCT}ram:ApplicableProductCharacteristic/ram:Value", ("Blue",)),
    # Alternatives that need a different base value.
    ("BT-8", {"vat_point_date_code": "3"}, f"{STL}ram:ApplicableTradeTax/ram:DueDateTypeCode", ("5",)),
    ("BT-8", {"vat_point_date_code": "432"}, f"{STL}ram:ApplicableTradeTax/ram:DueDateTypeCode", ("72",)),
    (
        "BT-46",
        {"buyer": buyer(identifier=Identifier(value="BUYER-1"))},
        f"{BUYER}ram:ID",
        ("BUYER-1",),
    ),
    (
        "BT-84",
        {"payment_instructions": payment(credit_transfers=(CreditTransfer(payment_account_identifier="ACCOUNT-1"),))},
        f"{MEANS}ram:PayeePartyCreditorFinancialAccount/ram:ProprietaryID",
        ("ACCOUNT-1",),
    ),
)
"""Every business term and group of the model, with the CII XPath(s) it is written to."""


@pytest.fixture(scope="module")
def base() -> etree._Element:
    """The parsed CII output of the all-terms invoice (rows with no overrides share it)."""
    return _xml.parse(cii.write(all_terms_invoice()))


def select(root: etree._Element, xpath: str) -> list[t.Any]:
    """Evaluate an XPath with the CII prefixes."""
    return t.cast(list[t.Any], root.xpath(xpath, namespaces=_xml.CII_NSMAP))


@pytest.mark.parametrize(("term", "changes", "xpath", "expected"), BT_ROWS, ids=[f"{r[0]}:{r[2]}" for r in BT_ROWS])
def test_term_is_written(
    base: etree._Element, term: str, changes: dict[str, t.Any], xpath: str, expected: Expected
) -> None:
    root = _xml.parse(cii.write(rebuild(all_terms_invoice(), **changes))) if changes else base
    found = select(root, xpath)
    if isinstance(expected, int):
        assert len(found) == expected, term
    else:
        assert tuple(str(f) if isinstance(f, str) else f.text for f in found) == expected, term


def test_every_model_term_has_a_row() -> None:
    assert {row[0] for row in BT_ROWS} == set(BT_INDEX)
