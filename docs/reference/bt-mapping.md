# EN 16931 business terms: model paths, cardinalities and syntax bindings

Every EN 16931 business term (BT) and business group (BG) with its path in `euinvoice.model.Invoice`,
its cardinality in the model, its data type, and its UBL 2.1 and UN/CEFACT CII D16B XPath. The table
is the mapping table of IMPLEMENTATION_PLAN.md §3.
`tests/model/test_bt_index.py::test_bt_mapping_doc_matches_the_model` checks that the ids, names,
model paths and cardinalities below match the model, so those columns cannot drift from the code.
The derived terms BG-22, BG-23 and BT-131 are absent from `InvoiceDraft` / `LineDraft` (the input of
`calc`), which otherwise share every field and check with `Invoice` / `InvoiceLine`.

## Sources

EN 16931-1 and CEN/TS 16931-3-2/-3-3 are paywalled, so every fact here comes from free sources (plan §3).
None of them is committed (D7).

| Abbrev. | Source | Used for |
|---|---|---|
| **CEN** | CEN validation artifacts `validation-1.3.16`: `schematron/abstract/EN16931-model.sch`, `UBL/EN16931-UBL-{model,syntax}.sch`, `CII/EN16931-CII-{model,syntax}.sch`, `codelist/EN16931-{UBL,CII}-codes.sch` (fetched by `make artifacts`) | mandatory terms (BR-01…BR-65, BR-CO-04, BR-CO-18), code lists (BR-CL-*), syntax restrictions (UBL-SR-*, CII-SR-*) |
| **XR** | XRechnung 3.0.2 specification, chapter 11 "Detailbeschreibung" (xeinkauf.de, `302-XRechnung-2024-06-20.pdf`) | the id inventory, names, data types, the semantic tree (which group holds which term) and the cardinality of every term |
| **KoSIT viz** | `itplr-kosit/xrechnung-visualization` `v2026-08-31`, `src/xsl/ubl-invoice-xr.xsl` and `src/xsl/cii-xr.xsl` (Apache-2.0): one `xsl:template mode="BT-n" match="<XPath>"` per term | UBL and CII XPaths |
| **Peppol** | Peppol BIS Billing 3.0.21 syntax binding, `structure/syntax/ubl-invoice.xml` and `ubl-creditnote.xml` from the same commit `806866bd` as the pinned `peppol-bis` artifact, but **not part of it** (the manifest extracts only `rules/`); read from GitHub for reference | UBL XPaths for BT-22, BT-23, BT-24, BG-1, BG-16, cross-check of the others |
| **CEN examples** | `cen-cii/1.3.16/examples/CII_example*.xml` | CII XPaths of BT-7, BT-149, BT-150, which the KoSIT viz does not bind |

### How cardinalities were decided

The XR table restates EN 16931-1 but, as a CIUS, it tightens some terms. The model takes the XR
cardinality unless a source shows that XR tightened it, and then takes the most permissive value that
never rejects an invoice the official CEN Schematron accepts (D8):

* A term is **required** (`1`, `1..n`) only where a `fatal` CEN rule demands it in both syntaxes. The rule
  is cited in the "Why" column ("CEN BR-xx").
* Where XR says `1` but EN 16931 does not, a German or Peppol rule adds the requirement (BR-DE-*,
  PEPPOL-EN16931-R*). The model keeps the term optional and names that rule ("XR 1 via …"). Profiles
  (#11, #12) add these requirements back as pre-flight checks.
* Everywhere else ("XR table") the model's cardinality equals the XR table, upper bounds included.

### Identifiers with a scheme, and code lists

| Term(s) | Model type | Scheme / code list | Rule(s) |
|---|---|---|---|
| BT-3 | code | UNTDID 1001, CEN union of the UBL invoice + credit note lists (62 codes) | BR-CL-01 |
| BT-5, BT-6 | code | ISO 4217 | BR-CL-04, BR-CL-05 |
| BT-8 | code | UNTDID 2005 subset 3, 35, 432 (XR §11.1); CII writes UNTDID 2475 (5, 29, 72) | BR-CL-06 |
| BT-21 | code | UNTDID 4451. UBL: the `#code#` prefix of `cbc:Note`; CII: `ram:SubjectCode`. The UBL list (383 codes) is a subset of the CII list (401); the model accepts the CII list (#52) | BR-CL-08 |
| BT-40, BT-55, BT-69, BT-80, BT-159 | code | ISO 3166-1 alpha-2, union of the UBL and CII lists | BR-CL-14, BR-CL-15 |
| BT-81 | code | UNTDID 4461 | BR-CL-16 |
| BT-95, BT-102, BT-118, BT-151 | code | UNTDID 5305 (= `VatCategory`) | BR-CL-17, BR-CL-18 |
| BT-98, BT-140 | code | UNTDID 5189 | BR-CL-19 |
| BT-105, BT-145 | code | UNTDID 7161 | BR-CL-20 |
| BT-121 | code | CEF VATEX, stored upper-cased | BR-CL-22 |
| BT-130, BT-150 | code | UN/ECE Rec 20 + Rec 21 | BR-CL-23 |
| BT-125 mime code | `BinaryObject.mime_code` | MIME codes, exact match | BR-CL-24 |
| BT-34, BT-49 | `Identifier`, scheme **required** | CEF EAS | BR-62, BR-63, BR-CL-25 |
| BT-29, BT-46, BT-60 | `Identifier`, scheme optional | ISO 6523 ICD | BR-CL-10, BR-CL-11 |
| BT-30, BT-47, BT-61 | `Identifier`, scheme optional | ISO 6523 ICD | BR-CL-11 |
| BT-71 | `Identifier`, scheme optional | ISO 6523 ICD | BR-CL-26 |
| BT-157 | `Identifier`, scheme **required** | ISO 6523 ICD | BR-64, BR-CL-21 |
| BT-158 | `ItemClassificationIdentifier`, scheme **required**, scheme version optional | UNTDID 7143 | BR-65, BR-CL-13 |
| BT-18, BT-128 | `Identifier`, scheme optional | UNTDID 1153 | BR-CL-07 |

The terms with a scheme are exactly those XR lists with a "…/Scheme identifier" row; BT-158 is the only
one with a "Scheme version identifier". Every other Identifier and every Document reference is plain
text. Codes are stored stripped of XML whitespace (and VATEX upper-cased) because upstream compares
them with `normalize-space` (and `upper-case`); see `euinvoice/model/datatypes.py`.

## Table

Legend. **UBL**: paths are shown for the `Invoice` root; a credit note uses `CreditNote`,
`cac:CreditNoteLine`, `cbc:CreditNoteTypeCode` and `cbc:CreditedQuantity` instead. Line-level paths
start at `cac:InvoiceLine`. **CII**: `AGR/` = `/rsm:CrossIndustryInvoice/rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement/`,
`DLV/` = `…/ram:ApplicableHeaderTradeDelivery/`, `STL/` = `…/ram:ApplicableHeaderTradeSettlement/`,
`LINE/` = `…/ram:IncludedSupplyChainTradeLineItem/`; other paths are relative to `/rsm:CrossIndustryInvoice`.
Two XPaths in one cell are alternatives. **Path**: `[]` marks a repeated field (a tuple). **Card.**: `n`
is unbounded.

| ID | Name | Model path | Card. | Why | Data type | UBL XPath | CII XPath |
|---|---|---|---|---|---|---|---|
| BG-0 | INVOICE (root) | `(root)` | 1 | CEN root | Group | `/Invoice (or /CreditNote)` | `/rsm:CrossIndustryInvoice` |
| BT-1 | Invoice number | `number` | 1 | CEN BR-02 | Identifier | `/Invoice/cbc:ID` | `/rsm:ExchangedDocument/ram:ID` |
| BT-2 | Invoice issue date | `issue_date` | 1 | CEN BR-03 | Date | `/Invoice/cbc:IssueDate` | `/rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString[@format='102']` |
| BT-3 | Invoice type code | `type_code` | 1 | CEN BR-04 | Code | `/Invoice/cbc:InvoiceTypeCode` | `/rsm:ExchangedDocument/ram:TypeCode` |
| BT-5 | Invoice currency code | `currency_code` | 1 | CEN BR-05 | Code | `/Invoice/cbc:DocumentCurrencyCode` | `STL/ram:InvoiceCurrencyCode` |
| BT-6 | VAT accounting currency code | `vat_accounting_currency_code` | 0..1 | XR table | Code | `/Invoice/cbc:TaxCurrencyCode` | `STL/ram:TaxCurrencyCode` |
| BT-7 | Value added tax point date | `vat_point_date` | 0..1 | XR table | Date | `/Invoice/cbc:TaxPointDate` | `STL/ram:ApplicableTradeTax/ram:TaxPointDate/udt:DateString` |
| BT-8 | Value added tax point date code | `vat_point_date_code` | 0..1 | XR table | Code | `/Invoice/cac:InvoicePeriod/cbc:DescriptionCode` | `STL/ram:ApplicableTradeTax/ram:DueDateTypeCode` |
| BT-9 | Payment due date | `payment_due_date` | 0..1 | XR table | Date | `/Invoice/cbc:DueDate` | `STL/ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString[@format='102']` |
| BT-10 | Buyer reference | `buyer_reference` | 0..1 | XR 1 via BR-DE-15 | Text | `/Invoice/cbc:BuyerReference` | `AGR/ram:BuyerReference` |
| BT-11 | Project reference | `project_reference` | 0..1 | XR table | Document Reference | `/Invoice/cac:ProjectReference/cbc:ID` | `AGR/ram:SpecifiedProcuringProject/ram:ID` |
| BT-12 | Contract reference | `contract_reference` | 0..1 | XR table | Document Reference | `/Invoice/cac:ContractDocumentReference/cbc:ID` | `AGR/ram:ContractReferencedDocument/ram:IssuerAssignedID` |
| BT-13 | Purchase order reference | `purchase_order_reference` | 0..1 | XR table | Document Reference | `/Invoice/cac:OrderReference/cbc:ID` | `AGR/ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID` |
| BT-14 | Sales order reference | `sales_order_reference` | 0..1 | XR table | Document Reference | `/Invoice/cac:OrderReference/cbc:SalesOrderID` | `AGR/ram:SellerOrderReferencedDocument/ram:IssuerAssignedID` |
| BT-15 | Receiving advice reference | `receiving_advice_reference` | 0..1 | XR table | Document Reference | `/Invoice/cac:ReceiptDocumentReference/cbc:ID` | `DLV/ram:ReceivingAdviceReferencedDocument/ram:IssuerAssignedID` |
| BT-16 | Despatch advice reference | `despatch_advice_reference` | 0..1 | XR table | Document Reference | `/Invoice/cac:DespatchDocumentReference/cbc:ID` | `DLV/ram:DespatchAdviceReferencedDocument/ram:IssuerAssignedID` |
| BT-17 | Tender or lot reference | `tender_or_lot_reference` | 0..1 | XR table | Document Reference | `/Invoice/cac:OriginatorDocumentReference/cbc:ID` | `AGR/ram:AdditionalReferencedDocument/ram:IssuerAssignedID[following-sibling::ram:TypeCode='50']` |
| BT-18 | Invoiced object identifier | `invoiced_object_identifier` | 0..1 | XR table | Identifier | `/Invoice/cac:AdditionalDocumentReference/cbc:ID[following-sibling::cbc:DocumentTypeCode='130']` | `AGR/ram:AdditionalReferencedDocument/ram:IssuerAssignedID[following-sibling::ram:TypeCode='130']` |
| BT-19 | Buyer accounting reference | `buyer_accounting_reference` | 0..1 | XR table | Text | `/Invoice/cbc:AccountingCost` | `STL/ram:ReceivableSpecifiedTradeAccountingAccount/ram:ID` |
| BT-20 | Payment terms | `payment_terms` | 0..1 | XR table | Text | `/Invoice/cac:PaymentTerms/cbc:Note` | `STL/ram:SpecifiedTradePaymentTerms/ram:Description` |
| BG-1 | INVOICE NOTE | `notes[]` | 0..n | XR table | Group | `/Invoice/cbc:Note` | `/rsm:ExchangedDocument/ram:IncludedNote` |
| BT-21 | Invoice note subject code | `notes[].subject_code` | 0..1 | XR table | Code | `/Invoice/cbc:Note (code = text between leading #…#, CEN UBL BR-CL-08)` | `/rsm:ExchangedDocument/ram:IncludedNote/ram:SubjectCode` |
| BT-22 | Invoice note | `notes[].note` | 0..1 | XR 1, no CEN rule: decision M1 | Text | `/Invoice/cbc:Note` | `/rsm:ExchangedDocument/ram:IncludedNote/ram:Content` |
| BG-2 | PROCESS CONTROL | `process_control` | 1 | CEN BR-01 (via BT-24) | Group | `/Invoice (no own element)` | `/rsm:ExchangedDocumentContext` |
| BT-23 | Business process type | `process_control.business_process_type` | 0..1 | XR 1 via PEPPOL-EN16931-R001 (XR changelog 3.0.1) | Text | `/Invoice/cbc:ProfileID` | `/rsm:ExchangedDocumentContext/ram:BusinessProcessSpecifiedDocumentContextParameter/ram:ID` |
| BT-24 | Specification identifier | `process_control.specification_identifier` | 1 | CEN BR-01 | Identifier | `/Invoice/cbc:CustomizationID` | `/rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID` |
| BG-3 | PRECEDING INVOICE REFERENCE | `preceding_invoice_references[]` | 0..n | XR table | Group | `/Invoice/cac:BillingReference/cac:InvoiceDocumentReference` | `STL/ram:InvoiceReferencedDocument` |
| BT-25 | Preceding Invoice reference | `preceding_invoice_references[].reference` | 1 | CEN BR-55 | Document Reference | `/Invoice/cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID` | `STL/ram:InvoiceReferencedDocument/ram:IssuerAssignedID` |
| BT-26 | Preceding Invoice issue date | `preceding_invoice_references[].issue_date` | 0..1 | XR table | Date | `/Invoice/cac:BillingReference/cac:InvoiceDocumentReference/cbc:IssueDate` | `STL/ram:InvoiceReferencedDocument/ram:FormattedIssueDateTime/qdt:DateTimeString[@format='102']` |
| BG-4 | SELLER | `seller` | 1 | CEN BR-06 | Group | `/Invoice/cac:AccountingSupplierParty` | `AGR/ram:SellerTradeParty` |
| BT-27 | Seller name | `seller.name` | 1 | CEN BR-06 | Text | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName` | `AGR/ram:SellerTradeParty/ram:Name` |
| BT-28 | Seller trading name | `seller.trading_name` | 0..1 | XR table | Text | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name` | `AGR/ram:SellerTradeParty/ram:SpecifiedLegalOrganization/ram:TradingBusinessName` |
| BT-29 | Seller identifier | `seller.identifiers[]` | 0..n | XR table | Identifier | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyIdentification/cbc:ID[not(@schemeID='SEPA')]` | `AGR/ram:SellerTradeParty/ram:ID`<br>`AGR/ram:SellerTradeParty/ram:GlobalID[exists(@schemeID)]` |
| BT-30 | Seller legal registration identifier | `seller.legal_registration_identifier` | 0..1 | XR table | Identifier | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:CompanyID` | `AGR/ram:SellerTradeParty/ram:SpecifiedLegalOrganization/ram:ID` |
| BT-31 | Seller VAT identifier | `seller.vat_identifier` | 0..1 | XR table | Identifier | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID[following-sibling::cac:TaxScheme/cbc:ID='VAT']` | `AGR/ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']` |
| BT-32 | Seller tax registration identifier | `seller.tax_registration_identifier` | 0..1 | XR table | Identifier | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID[following-sibling::cac:TaxScheme/cbc:ID != 'VAT']` | `AGR/ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID[@schemeID='FC']` |
| BT-33 | Seller additional legal information | `seller.additional_legal_information` | 0..1 | XR table | Text | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:CompanyLegalForm` | `AGR/ram:SellerTradeParty/ram:Description` |
| BT-34 | Seller electronic address | `seller.electronic_address` | 0..1 | XR 1 via PEPPOL-EN16931-R020 (XR changelog 3.0.1) | Identifier | `/Invoice/cac:AccountingSupplierParty/cac:Party/cbc:EndpointID` | `AGR/ram:SellerTradeParty/ram:URIUniversalCommunication/ram:URIID` |
| BG-5 | SELLER POSTAL ADDRESS | `seller.postal_address` | 1 | CEN BR-08 | Group | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:PostalAddress` | `AGR/ram:SellerTradeParty/ram:PostalTradeAddress` |
| BT-35 | Seller address line 1 | `seller.postal_address.address_line_1` | 0..1 | XR table | Text | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:PostalAddress/cbc:StreetName` | `AGR/ram:SellerTradeParty/ram:PostalTradeAddress/ram:LineOne` |
| BT-36 | Seller address line 2 | `seller.postal_address.address_line_2` | 0..1 | XR table | Text | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:PostalAddress/cbc:AdditionalStreetName` | `AGR/ram:SellerTradeParty/ram:PostalTradeAddress/ram:LineTwo` |
| BT-162 | Seller address line 3 | `seller.postal_address.address_line_3` | 0..1 | XR table | Text | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:PostalAddress/cac:AddressLine/cbc:Line` | `AGR/ram:SellerTradeParty/ram:PostalTradeAddress/ram:LineThree` |
| BT-37 | Seller city | `seller.postal_address.city` | 0..1 | XR 1 via BR-DE-3 | Text | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:PostalAddress/cbc:CityName` | `AGR/ram:SellerTradeParty/ram:PostalTradeAddress/ram:CityName` |
| BT-38 | Seller post code | `seller.postal_address.post_code` | 0..1 | XR 1 via BR-DE-4 | Text | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:PostalAddress/cbc:PostalZone` | `AGR/ram:SellerTradeParty/ram:PostalTradeAddress/ram:PostcodeCode` |
| BT-39 | Seller country subdivision | `seller.postal_address.country_subdivision` | 0..1 | XR table | Text | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:PostalAddress/cbc:CountrySubentity` | `AGR/ram:SellerTradeParty/ram:PostalTradeAddress/ram:CountrySubDivisionName` |
| BT-40 | Seller country code | `seller.postal_address.country_code` | 1 | CEN BR-09 | Code | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:PostalAddress/cac:Country/cbc:IdentificationCode` | `AGR/ram:SellerTradeParty/ram:PostalTradeAddress/ram:CountryID` |
| BG-6 | SELLER CONTACT | `seller.contact` | 0..1 | XR 1 via BR-DE-2 | Group | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:Contact` | `AGR/ram:SellerTradeParty/ram:DefinedTradeContact` |
| BT-41 | Seller contact point | `seller.contact.contact_point` | 0..1 | XR 1 via BR-DE-5 | Text | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:Contact/cbc:Name` | `AGR/ram:SellerTradeParty/ram:DefinedTradeContact/ram:DepartmentName`<br>`AGR/ram:SellerTradeParty/ram:DefinedTradeContact/ram:PersonName` |
| BT-42 | Seller contact telephone number | `seller.contact.telephone` | 0..1 | XR 1 via BR-DE-6 | Text | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:Contact/cbc:Telephone` | `AGR/ram:SellerTradeParty/ram:DefinedTradeContact/ram:TelephoneUniversalCommunication/ram:CompleteNumber` |
| BT-43 | Seller contact email address | `seller.contact.email` | 0..1 | XR 1 via BR-DE-7 | Text | `/Invoice/cac:AccountingSupplierParty/cac:Party/cac:Contact/cbc:ElectronicMail` | `AGR/ram:SellerTradeParty/ram:DefinedTradeContact/ram:EmailURIUniversalCommunication/ram:URIID` |
| BG-7 | BUYER | `buyer` | 1 | CEN BR-07 | Group | `/Invoice/cac:AccountingCustomerParty` | `AGR/ram:BuyerTradeParty` |
| BT-44 | Buyer name | `buyer.name` | 1 | CEN BR-07 | Text | `/Invoice/cac:AccountingCustomerParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName` | `AGR/ram:BuyerTradeParty/ram:Name` |
| BT-45 | Buyer trading name | `buyer.trading_name` | 0..1 | XR table | Text | `/Invoice/cac:AccountingCustomerParty/cac:Party/cac:PartyName/cbc:Name` | `AGR/ram:BuyerTradeParty/ram:SpecifiedLegalOrganization/ram:TradingBusinessName` |
| BT-46 | Buyer identifier | `buyer.identifier` | 0..1 | XR table | Identifier | `/Invoice/cac:AccountingCustomerParty/cac:Party/cac:PartyIdentification/cbc:ID` | `AGR/ram:BuyerTradeParty/ram:ID[empty(following-sibling::ram:GlobalID/@schemeID)]`<br>`AGR/ram:BuyerTradeParty/ram:GlobalID[exists(@schemeID)]` |
| BT-47 | Buyer legal registration identifier | `buyer.legal_registration_identifier` | 0..1 | XR table | Identifier | `/Invoice/cac:AccountingCustomerParty/cac:Party/cac:PartyLegalEntity/cbc:CompanyID` | `AGR/ram:BuyerTradeParty/ram:SpecifiedLegalOrganization/ram:ID` |
| BT-48 | Buyer VAT identifier | `buyer.vat_identifier` | 0..1 | XR table | Identifier | `/Invoice/cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID[following-sibling::cac:TaxScheme/cbc:ID='VAT']` | `AGR/ram:BuyerTradeParty/ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']` |
| BT-49 | Buyer electronic address | `buyer.electronic_address` | 0..1 | XR 1 via PEPPOL-EN16931-R010 (XR changelog 3.0.1) | Identifier | `/Invoice/cac:AccountingCustomerParty/cac:Party/cbc:EndpointID` | `AGR/ram:BuyerTradeParty/ram:URIUniversalCommunication/ram:URIID` |
| BG-8 | BUYER POSTAL ADDRESS | `buyer.postal_address` | 1 | CEN BR-10 | Group | `/Invoice/cac:AccountingCustomerParty/cac:Party/cac:PostalAddress` | `AGR/ram:BuyerTradeParty/ram:PostalTradeAddress` |
| BT-50 | Buyer address line 1 | `buyer.postal_address.address_line_1` | 0..1 | XR table | Text | `/Invoice/cac:AccountingCustomerParty/cac:Party/cac:PostalAddress/cbc:StreetName` | `AGR/ram:BuyerTradeParty/ram:PostalTradeAddress/ram:LineOne` |
| BT-51 | Buyer address line 2 | `buyer.postal_address.address_line_2` | 0..1 | XR table | Text | `/Invoice/cac:AccountingCustomerParty/cac:Party/cac:PostalAddress/cbc:AdditionalStreetName` | `AGR/ram:BuyerTradeParty/ram:PostalTradeAddress/ram:LineTwo` |
| BT-163 | Buyer address line 3 | `buyer.postal_address.address_line_3` | 0..1 | XR table | Text | `/Invoice/cac:AccountingCustomerParty/cac:Party/cac:PostalAddress/cac:AddressLine/cbc:Line` | `AGR/ram:BuyerTradeParty/ram:PostalTradeAddress/ram:LineThree` |
| BT-52 | Buyer city | `buyer.postal_address.city` | 0..1 | XR 1 via BR-DE-8 | Text | `/Invoice/cac:AccountingCustomerParty/cac:Party/cac:PostalAddress/cbc:CityName` | `AGR/ram:BuyerTradeParty/ram:PostalTradeAddress/ram:CityName` |
| BT-53 | Buyer post code | `buyer.postal_address.post_code` | 0..1 | XR 1 via BR-DE-9 | Text | `/Invoice/cac:AccountingCustomerParty/cac:Party/cac:PostalAddress/cbc:PostalZone` | `AGR/ram:BuyerTradeParty/ram:PostalTradeAddress/ram:PostcodeCode` |
| BT-54 | Buyer country subdivision | `buyer.postal_address.country_subdivision` | 0..1 | XR table | Text | `/Invoice/cac:AccountingCustomerParty/cac:Party/cac:PostalAddress/cbc:CountrySubentity` | `AGR/ram:BuyerTradeParty/ram:PostalTradeAddress/ram:CountrySubDivisionName` |
| BT-55 | Buyer country code | `buyer.postal_address.country_code` | 1 | CEN BR-11 | Code | `/Invoice/cac:AccountingCustomerParty/cac:Party/cac:PostalAddress/cac:Country/cbc:IdentificationCode` | `AGR/ram:BuyerTradeParty/ram:PostalTradeAddress/ram:CountryID` |
| BG-9 | BUYER CONTACT | `buyer.contact` | 0..1 | XR table | Group | `/Invoice/cac:AccountingCustomerParty/cac:Party/cac:Contact` | `AGR/ram:BuyerTradeParty/ram:DefinedTradeContact` |
| BT-56 | Buyer contact point | `buyer.contact.contact_point` | 0..1 | XR table | Text | `/Invoice/cac:AccountingCustomerParty/cac:Party/cac:Contact/cbc:Name` | `AGR/ram:BuyerTradeParty/ram:DefinedTradeContact/ram:DepartmentName`<br>`AGR/ram:BuyerTradeParty/ram:DefinedTradeContact/ram:PersonName` |
| BT-57 | Buyer contact telephone number | `buyer.contact.telephone` | 0..1 | XR table | Text | `/Invoice/cac:AccountingCustomerParty/cac:Party/cac:Contact/cbc:Telephone` | `AGR/ram:BuyerTradeParty/ram:DefinedTradeContact/ram:TelephoneUniversalCommunication/ram:CompleteNumber` |
| BT-58 | Buyer contact email address | `buyer.contact.email` | 0..1 | XR table | Text | `/Invoice/cac:AccountingCustomerParty/cac:Party/cac:Contact/cbc:ElectronicMail` | `AGR/ram:BuyerTradeParty/ram:DefinedTradeContact/ram:EmailURIUniversalCommunication/ram:URIID` |
| BG-10 | PAYEE | `payee` | 0..1 | XR table | Group | `/Invoice/cac:PayeeParty` | `STL/ram:PayeeTradeParty` |
| BT-59 | Payee name | `payee.name` | 1 | CEN BR-17 | Text | `/Invoice/cac:PayeeParty/cac:PartyName/cbc:Name` | `STL/ram:PayeeTradeParty/ram:Name` |
| BT-60 | Payee identifier | `payee.identifier` | 0..1 | XR table | Identifier | `/Invoice/cac:PayeeParty/cac:PartyIdentification/cbc:ID[not(@schemeID='SEPA')]` | `STL/ram:PayeeTradeParty/ram:GlobalID[exists(@schemeID)]`<br>`STL/ram:PayeeTradeParty/ram:ID[empty(following-sibling::ram:GlobalID/@schemeID)]` |
| BT-61 | Payee legal registration identifier | `payee.legal_registration_identifier` | 0..1 | XR table | Identifier | `/Invoice/cac:PayeeParty/cac:PartyLegalEntity/cbc:CompanyID` | `STL/ram:PayeeTradeParty/ram:SpecifiedLegalOrganization/ram:ID` |
| BG-11 | SELLER TAX REPRESENTATIVE PARTY | `seller_tax_representative` | 0..1 | XR table | Group | `/Invoice/cac:TaxRepresentativeParty` | `AGR/ram:SellerTaxRepresentativeTradeParty` |
| BT-62 | Seller tax representative name | `seller_tax_representative.name` | 1 | CEN BR-18 | Text | `/Invoice/cac:TaxRepresentativeParty/cac:PartyName/cbc:Name` | `AGR/ram:SellerTaxRepresentativeTradeParty/ram:Name` |
| BT-63 | Seller tax representative VAT identifier | `seller_tax_representative.vat_identifier` | 1 | CEN BR-56 | Identifier | `/Invoice/cac:TaxRepresentativeParty/cac:PartyTaxScheme/cbc:CompanyID[following-sibling::cac:TaxScheme/cbc:ID='VAT']` | `AGR/ram:SellerTaxRepresentativeTradeParty/ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']` |
| BG-12 | SELLER TAX REPRESENTATIVE POSTAL ADDRESS | `seller_tax_representative.postal_address` | 1 | CEN BR-19 | Group | `/Invoice/cac:TaxRepresentativeParty/cac:PostalAddress` | `AGR/ram:SellerTaxRepresentativeTradeParty/ram:PostalTradeAddress` |
| BT-64 | Tax representative address line 1 | `seller_tax_representative.postal_address.address_line_1` | 0..1 | XR table | Text | `/Invoice/cac:TaxRepresentativeParty/cac:PostalAddress/cbc:StreetName` | `AGR/ram:SellerTaxRepresentativeTradeParty/ram:PostalTradeAddress/ram:LineOne` |
| BT-65 | Tax representative address line 2 | `seller_tax_representative.postal_address.address_line_2` | 0..1 | XR table | Text | `/Invoice/cac:TaxRepresentativeParty/cac:PostalAddress/cbc:AdditionalStreetName` | `AGR/ram:SellerTaxRepresentativeTradeParty/ram:PostalTradeAddress/ram:LineTwo` |
| BT-164 | Tax representative address line 3 | `seller_tax_representative.postal_address.address_line_3` | 0..1 | XR table | Text | `/Invoice/cac:TaxRepresentativeParty/cac:PostalAddress/cac:AddressLine/cbc:Line` | `AGR/ram:SellerTaxRepresentativeTradeParty/ram:PostalTradeAddress/ram:LineThree` |
| BT-66 | Tax representative city | `seller_tax_representative.postal_address.city` | 0..1 | XR table | Text | `/Invoice/cac:TaxRepresentativeParty/cac:PostalAddress/cbc:CityName` | `AGR/ram:SellerTaxRepresentativeTradeParty/ram:PostalTradeAddress/ram:CityName` |
| BT-67 | Tax representative post code | `seller_tax_representative.postal_address.post_code` | 0..1 | XR table | Text | `/Invoice/cac:TaxRepresentativeParty/cac:PostalAddress/cbc:PostalZone` | `AGR/ram:SellerTaxRepresentativeTradeParty/ram:PostalTradeAddress/ram:PostcodeCode` |
| BT-68 | Tax representative country subdivision | `seller_tax_representative.postal_address.country_subdivision` | 0..1 | XR table | Text | `/Invoice/cac:TaxRepresentativeParty/cac:PostalAddress/cbc:CountrySubentity` | `AGR/ram:SellerTaxRepresentativeTradeParty/ram:PostalTradeAddress/ram:CountrySubDivisionName` |
| BT-69 | Tax representative country code | `seller_tax_representative.postal_address.country_code` | 1 | CEN BR-20 | Code | `/Invoice/cac:TaxRepresentativeParty/cac:PostalAddress/cac:Country/cbc:IdentificationCode` | `AGR/ram:SellerTaxRepresentativeTradeParty/ram:PostalTradeAddress/ram:CountryID` |
| BG-13 | DELIVERY INFORMATION | `delivery` | 0..1 | XR table | Group | `/Invoice/cac:Delivery` | `DLV (ram:ApplicableHeaderTradeDelivery; BG-14 is under STL)` |
| BT-70 | Deliver to party name | `delivery.deliver_to_party_name` | 0..1 | XR table | Text | `/Invoice/cac:Delivery/cac:DeliveryParty/cac:PartyName/cbc:Name` | `DLV/ram:ShipToTradeParty/ram:Name` |
| BT-71 | Deliver to location identifier | `delivery.deliver_to_location_identifier` | 0..1 | XR table | Identifier | `/Invoice/cac:Delivery/cac:DeliveryLocation/cbc:ID` | `DLV/ram:ShipToTradeParty/ram:ID[empty(following-sibling::ram:GlobalID/@schemeID)]`<br>`DLV/ram:ShipToTradeParty/ram:GlobalID[exists(@schemeID)]` |
| BT-72 | Actual delivery date | `delivery.actual_delivery_date` | 0..1 | XR table | Date | `/Invoice/cac:Delivery/cbc:ActualDeliveryDate` | `DLV/ram:ActualDeliverySupplyChainEvent/ram:OccurrenceDateTime/udt:DateTimeString[@format='102']` |
| BG-14 | INVOICING PERIOD | `delivery.invoicing_period` | 0..1 | XR table | Group | `/Invoice/cac:InvoicePeriod` | `STL/ram:BillingSpecifiedPeriod` |
| BT-73 | Invoicing period start date | `delivery.invoicing_period.start_date` | 0..1 | XR table | Date | `/Invoice/cac:InvoicePeriod/cbc:StartDate` | `STL/ram:BillingSpecifiedPeriod/ram:StartDateTime/udt:DateTimeString[@format='102']` |
| BT-74 | Invoicing period end date | `delivery.invoicing_period.end_date` | 0..1 | XR table | Date | `/Invoice/cac:InvoicePeriod/cbc:EndDate` | `STL/ram:BillingSpecifiedPeriod/ram:EndDateTime/udt:DateTimeString[@format='102']` |
| BG-15 | DELIVER TO ADDRESS | `delivery.deliver_to_address` | 0..1 | XR table | Group | `/Invoice/cac:Delivery/cac:DeliveryLocation/cac:Address` | `DLV/ram:ShipToTradeParty/ram:PostalTradeAddress` |
| BT-75 | Deliver to address line 1 | `delivery.deliver_to_address.address_line_1` | 0..1 | XR table | Text | `/Invoice/cac:Delivery/cac:DeliveryLocation/cac:Address/cbc:StreetName` | `DLV/ram:ShipToTradeParty/ram:PostalTradeAddress/ram:LineOne` |
| BT-76 | Deliver to address line 2 | `delivery.deliver_to_address.address_line_2` | 0..1 | XR table | Text | `/Invoice/cac:Delivery/cac:DeliveryLocation/cac:Address/cbc:AdditionalStreetName` | `DLV/ram:ShipToTradeParty/ram:PostalTradeAddress/ram:LineTwo` |
| BT-165 | Deliver to address line 3 | `delivery.deliver_to_address.address_line_3` | 0..1 | XR table | Text | `/Invoice/cac:Delivery/cac:DeliveryLocation/cac:Address/cac:AddressLine/cbc:Line` | `DLV/ram:ShipToTradeParty/ram:PostalTradeAddress/ram:LineThree` |
| BT-77 | Deliver to city | `delivery.deliver_to_address.city` | 0..1 | XR 1 via BR-DE-10 | Text | `/Invoice/cac:Delivery/cac:DeliveryLocation/cac:Address/cbc:CityName` | `DLV/ram:ShipToTradeParty/ram:PostalTradeAddress/ram:CityName` |
| BT-78 | Deliver to post code | `delivery.deliver_to_address.post_code` | 0..1 | XR 1 via BR-DE-11 | Text | `/Invoice/cac:Delivery/cac:DeliveryLocation/cac:Address/cbc:PostalZone` | `DLV/ram:ShipToTradeParty/ram:PostalTradeAddress/ram:PostcodeCode` |
| BT-79 | Deliver to country subdivision | `delivery.deliver_to_address.country_subdivision` | 0..1 | XR table | Text | `/Invoice/cac:Delivery/cac:DeliveryLocation/cac:Address/cbc:CountrySubentity` | `DLV/ram:ShipToTradeParty/ram:PostalTradeAddress/ram:CountrySubDivisionName` |
| BT-80 | Deliver to country code | `delivery.deliver_to_address.country_code` | 1 | CEN BR-57 | Code | `/Invoice/cac:Delivery/cac:DeliveryLocation/cac:Address/cac:Country/cbc:IdentificationCode` | `DLV/ram:ShipToTradeParty/ram:PostalTradeAddress/ram:CountryID` |
| BG-16 | PAYMENT INSTRUCTIONS | `payment_instructions` | 0..1 | XR 1 via BR-DE-1 | Group | `/Invoice/cac:PaymentMeans` | `STL/ram:SpecifiedTradeSettlementPaymentMeans` |
| BT-81 | Payment means type code | `payment_instructions.payment_means_type_code` | 1 | CEN BR-49 | Code | `/Invoice/cac:PaymentMeans/cbc:PaymentMeansCode` | `STL/ram:SpecifiedTradeSettlementPaymentMeans/ram:TypeCode` |
| BT-82 | Payment means text | `payment_instructions.payment_means_text` | 0..1 | XR table | Text | `/Invoice/cac:PaymentMeans/cbc:PaymentMeansCode/@name` | `STL/ram:SpecifiedTradeSettlementPaymentMeans/ram:Information` |
| BT-83 | Remittance information | `payment_instructions.remittance_information` | 0..1 | XR table | Text | `/Invoice/cac:PaymentMeans/cbc:PaymentID` | `STL/ram:PaymentReference` |
| BG-17 | CREDIT TRANSFER | `payment_instructions.credit_transfers[]` | 0..n | XR table | Group | `/Invoice/cac:PaymentMeans/cac:PayeeFinancialAccount` | `STL/ram:SpecifiedTradeSettlementPaymentMeans/ram:PayeePartyCreditorFinancialAccount` |
| BT-84 | Payment account identifier | `payment_instructions.credit_transfers[].payment_account_identifier` | 1 | CEN BR-50 | Identifier | `/Invoice/cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID` | `STL/ram:SpecifiedTradeSettlementPaymentMeans/ram:PayeePartyCreditorFinancialAccount/ram:ProprietaryID`<br>`STL/ram:SpecifiedTradeSettlementPaymentMeans/ram:PayeePartyCreditorFinancialAccount/ram:IBANID` |
| BT-85 | Payment account name | `payment_instructions.credit_transfers[].payment_account_name` | 0..1 | XR table | Text | `/Invoice/cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:Name` | `STL/ram:SpecifiedTradeSettlementPaymentMeans/ram:PayeePartyCreditorFinancialAccount/ram:AccountName` |
| BT-86 | Payment service provider identifier | `payment_instructions.credit_transfers[].payment_service_provider_identifier` | 0..1 | XR table | Identifier | `/Invoice/cac:PaymentMeans/cac:PayeeFinancialAccount/cac:FinancialInstitutionBranch/cbc:ID` | `STL/ram:SpecifiedTradeSettlementPaymentMeans/ram:PayeeSpecifiedCreditorFinancialInstitution/ram:BICID` |
| BG-18 | PAYMENT CARD INFORMATION | `payment_instructions.payment_card` | 0..1 | XR table; see note N2 | Group | `/Invoice/cac:PaymentMeans/cac:CardAccount` | `STL/ram:SpecifiedTradeSettlementPaymentMeans/ram:ApplicableTradeSettlementFinancialCard` |
| BT-87 | Payment card primary account number | `payment_instructions.payment_card.primary_account_number` | 0..1 | XR 1 and UBL XSD 1, no CEN rule, CII XSD 0..1: decision M2 | Text | `/Invoice/cac:PaymentMeans/cac:CardAccount/cbc:PrimaryAccountNumberID` | `STL/ram:SpecifiedTradeSettlementPaymentMeans/ram:ApplicableTradeSettlementFinancialCard/ram:ID` |
| BT-88 | Payment card holder name | `payment_instructions.payment_card.holder_name` | 0..1 | XR table | Text | `/Invoice/cac:PaymentMeans/cac:CardAccount/cbc:HolderName` | `STL/ram:SpecifiedTradeSettlementPaymentMeans/ram:ApplicableTradeSettlementFinancialCard/ram:CardholderName` |
| BG-19 | DIRECT DEBIT | `payment_instructions.direct_debit` | 0..1 | XR table | Group | `/Invoice/cac:PaymentMeans/cac:PaymentMandate` | `STL (ram:ApplicableHeaderTradeSettlement)` |
| BT-89 | Mandate reference identifier | `payment_instructions.direct_debit.mandate_reference_identifier` | 0..1 | XR 1 (BR-DE-29, XR changelog 2.3.0) | Identifier | `/Invoice/cac:PaymentMeans/cac:PaymentMandate/cbc:ID` | `STL/ram:SpecifiedTradePaymentTerms/ram:DirectDebitMandateID` |
| BT-90 | Bank assigned creditor identifier | `payment_instructions.direct_debit.bank_assigned_creditor_identifier` | 0..1 | XR 1 via BR-DE-30 | Identifier | `/Invoice/cac:PayeeParty/cac:PartyIdentification/cbc:ID[@schemeID='SEPA']`<br>`/Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyIdentification/cbc:ID[@schemeID='SEPA']` | `STL/ram:CreditorReferenceID` |
| BT-91 | Debited account identifier | `payment_instructions.direct_debit.debited_account_identifier` | 0..1 | XR 1 via BR-DE-31 | Identifier | `/Invoice/cac:PaymentMeans/cac:PaymentMandate/cac:PayerFinancialAccount/cbc:ID` | `STL/ram:SpecifiedTradeSettlementPaymentMeans/ram:PayerPartyDebtorFinancialAccount/ram:IBANID` |
| BG-20 | DOCUMENT LEVEL ALLOWANCES | `allowances[]` | 0..n | XR table | Group | `/Invoice/cac:AllowanceCharge[cbc:ChargeIndicator='false']` | `STL/ram:SpecifiedTradeAllowanceCharge[ram:ChargeIndicator/udt:Indicator='false']` |
| BT-92 | Document level allowance amount | `allowances[].amount` | 1 | CEN BR-31 | Amount | `/Invoice/cac:AllowanceCharge/cbc:Amount[preceding-sibling::cbc:ChargeIndicator='false']` | `STL/ram:SpecifiedTradeAllowanceCharge/ram:ActualAmount` |
| BT-93 | Document level allowance base amount | `allowances[].base_amount` | 0..1 | XR table | Amount | `/Invoice/cac:AllowanceCharge/cbc:BaseAmount[preceding-sibling::cbc:ChargeIndicator='false']` | `STL/ram:SpecifiedTradeAllowanceCharge/ram:BasisAmount` |
| BT-94 | Document level allowance percentage | `allowances[].percentage` | 0..1 | XR table | Percentage | `/Invoice/cac:AllowanceCharge/cbc:MultiplierFactorNumeric[preceding-sibling::cbc:ChargeIndicator='false']` | `STL/ram:SpecifiedTradeAllowanceCharge/ram:CalculationPercent` |
| BT-95 | Document level allowance VAT category code | `allowances[].vat_category_code` | 1 | CEN BR-32 | Code | `/Invoice/cac:AllowanceCharge/cac:TaxCategory/cbc:ID[ancestor::cac:AllowanceCharge/cbc:ChargeIndicator='false' and following-sibling::cac:TaxScheme/cbc:ID='VAT']` | `STL/ram:SpecifiedTradeAllowanceCharge/ram:CategoryTradeTax/ram:CategoryCode` |
| BT-96 | Document level allowance VAT rate | `allowances[].vat_rate` | 0..1 | XR table | Percentage | `/Invoice/cac:AllowanceCharge/cac:TaxCategory/cbc:Percent[ancestor::cac:AllowanceCharge/cbc:ChargeIndicator='false']` | `STL/ram:SpecifiedTradeAllowanceCharge/ram:CategoryTradeTax/ram:RateApplicablePercent` |
| BT-97 | Document level allowance reason | `allowances[].reason` | 0..1 | XR table | Text | `/Invoice/cac:AllowanceCharge/cbc:AllowanceChargeReason[preceding-sibling::cbc:ChargeIndicator='false']` | `STL/ram:SpecifiedTradeAllowanceCharge/ram:Reason` |
| BT-98 | Document level allowance reason code | `allowances[].reason_code` | 0..1 | XR table | Code | `/Invoice/cac:AllowanceCharge/cbc:AllowanceChargeReasonCode[preceding-sibling::cbc:ChargeIndicator='false']` | `STL/ram:SpecifiedTradeAllowanceCharge/ram:ReasonCode` |
| BG-21 | DOCUMENT LEVEL CHARGES | `charges[]` | 0..n | XR table | Group | `/Invoice/cac:AllowanceCharge[cbc:ChargeIndicator='true']` | `STL/ram:SpecifiedTradeAllowanceCharge[ram:ChargeIndicator/udt:Indicator='true']` |
| BT-99 | Document level charge amount | `charges[].amount` | 1 | CEN BR-36 | Amount | `/Invoice/cac:AllowanceCharge/cbc:Amount[preceding-sibling::cbc:ChargeIndicator='true']` | `STL/ram:SpecifiedTradeAllowanceCharge/ram:ActualAmount` |
| BT-100 | Document level charge base amount | `charges[].base_amount` | 0..1 | XR table | Amount | `/Invoice/cac:AllowanceCharge/cbc:BaseAmount[preceding-sibling::cbc:ChargeIndicator='true']` | `STL/ram:SpecifiedTradeAllowanceCharge/ram:BasisAmount` |
| BT-101 | Document level charge percentage | `charges[].percentage` | 0..1 | XR table | Percentage | `/Invoice/cac:AllowanceCharge/cbc:MultiplierFactorNumeric[preceding-sibling::cbc:ChargeIndicator='true']` | `STL/ram:SpecifiedTradeAllowanceCharge/ram:CalculationPercent` |
| BT-102 | Document level charge VAT category code | `charges[].vat_category_code` | 1 | CEN BR-37 | Code | `/Invoice/cac:AllowanceCharge/cac:TaxCategory/cbc:ID[ancestor::cac:AllowanceCharge/cbc:ChargeIndicator='true']` | `STL/ram:SpecifiedTradeAllowanceCharge/ram:CategoryTradeTax/ram:CategoryCode` |
| BT-103 | Document level charge VAT rate | `charges[].vat_rate` | 0..1 | XR table | Percentage | `/Invoice/cac:AllowanceCharge/cac:TaxCategory/cbc:Percent[ancestor::cac:AllowanceCharge/cbc:ChargeIndicator='true']` | `STL/ram:SpecifiedTradeAllowanceCharge/ram:CategoryTradeTax/ram:RateApplicablePercent` |
| BT-104 | Document level charge reason | `charges[].reason` | 0..1 | XR table | Text | `/Invoice/cac:AllowanceCharge/cbc:AllowanceChargeReason[preceding-sibling::cbc:ChargeIndicator='true']` | `STL/ram:SpecifiedTradeAllowanceCharge/ram:Reason` |
| BT-105 | Document level charge reason code | `charges[].reason_code` | 0..1 | XR table | Code | `/Invoice/cac:AllowanceCharge/cbc:AllowanceChargeReasonCode[preceding-sibling::cbc:ChargeIndicator='true']` | `STL/ram:SpecifiedTradeAllowanceCharge/ram:ReasonCode` |
| BG-24 | ADDITIONAL SUPPORTING DOCUMENTS | `additional_supporting_documents[]` | 0..n | XR table; see note N1 | Group | `/Invoice/cac:AdditionalDocumentReference` | `AGR/ram:AdditionalReferencedDocument` |
| BT-122 | Supporting document reference | `additional_supporting_documents[].reference` | 1 | CEN BR-52 | Document Reference | `/Invoice/cac:AdditionalDocumentReference/cbc:ID` | `AGR/ram:AdditionalReferencedDocument/ram:IssuerAssignedID[following-sibling::ram:TypeCode='916']` |
| BT-123 | Supporting document description | `additional_supporting_documents[].description` | 0..1 | XR table | Text | `/Invoice/cac:AdditionalDocumentReference/cbc:DocumentDescription` | `AGR/ram:AdditionalReferencedDocument/ram:Name` |
| BT-124 | External document location | `additional_supporting_documents[].external_location` | 0..1 | XR table | Text | `/Invoice/cac:AdditionalDocumentReference/cac:Attachment/cac:ExternalReference/cbc:URI` | `AGR/ram:AdditionalReferencedDocument/ram:URIID` |
| BT-125 | Attached document | `additional_supporting_documents[].attached_document` | 0..1 | XR table; decision M3 | Binary Object | `/Invoice/cac:AdditionalDocumentReference/cac:Attachment/cbc:EmbeddedDocumentBinaryObject` | `AGR/ram:AdditionalReferencedDocument/ram:AttachmentBinaryObject` |
| BG-22 | DOCUMENT TOTALS | `totals` | 1 | UBL XSD cac:LegalMonetaryTotal minOccurs=1 (UBL-Invoice-2.1.xsd:921); CII: BR-CO-15 (fatal, $Invoice context) | Group | `/Invoice/cac:LegalMonetaryTotal` | `STL/ram:SpecifiedTradeSettlementHeaderMonetarySummation` |
| BT-106 | Sum of Invoice line net amount | `totals.sum_of_line_net_amounts` | 1 | CEN BR-12 | Amount | `/Invoice/cac:LegalMonetaryTotal/cbc:LineExtensionAmount` | `STL/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:LineTotalAmount` |
| BT-107 | Sum of allowances on document level | `totals.sum_of_allowances` | 0..1 | XR table | Amount | `/Invoice/cac:LegalMonetaryTotal/cbc:AllowanceTotalAmount` | `STL/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:AllowanceTotalAmount` |
| BT-108 | Sum of charges on document level | `totals.sum_of_charges` | 0..1 | XR table | Amount | `/Invoice/cac:LegalMonetaryTotal/cbc:ChargeTotalAmount` | `STL/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:ChargeTotalAmount` |
| BT-109 | Invoice total amount without VAT | `totals.total_without_vat` | 1 | CEN BR-13 | Amount | `/Invoice/cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount` | `STL/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxBasisTotalAmount` |
| BT-110 | Invoice total VAT amount | `totals.total_vat` | 0..1 | XR table | Amount | `/Invoice/cac:TaxTotal/cbc:TaxAmount[@currencyID=/Invoice/cbc:DocumentCurrencyCode]` | `STL/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxTotalAmount[@currencyID=parent::ram:SpecifiedTradeSettlementHeaderMonetarySummation/preceding-sibling::ram:InvoiceCurrencyCode]` |
| BT-111 | Invoice total VAT amount in accounting currency | `totals.total_vat_in_accounting_currency` | 0..1 | XR table | Amount | `/Invoice/cac:TaxTotal/cbc:TaxAmount[@currencyID=/Invoice/cbc:TaxCurrencyCode]` | `STL/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxTotalAmount[@currencyID=parent::ram:SpecifiedTradeSettlementHeaderMonetarySummation/preceding-sibling::ram:TaxCurrencyCode]` |
| BT-112 | Invoice total amount with VAT | `totals.total_with_vat` | 1 | CEN BR-14 | Amount | `/Invoice/cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount` | `STL/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:GrandTotalAmount` |
| BT-113 | Paid amount | `totals.paid_amount` | 0..1 | XR table | Amount | `/Invoice/cac:LegalMonetaryTotal/cbc:PrepaidAmount` | `STL/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TotalPrepaidAmount` |
| BT-114 | Rounding amount | `totals.rounding_amount` | 0..1 | XR table | Amount | `/Invoice/cac:LegalMonetaryTotal/cbc:PayableRoundingAmount` | `STL/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:RoundingAmount` |
| BT-115 | Amount due for payment | `totals.amount_due` | 1 | CEN BR-15 | Amount | `/Invoice/cac:LegalMonetaryTotal/cbc:PayableAmount` | `STL/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:DuePayableAmount` |
| BG-23 | VAT BREAKDOWN | `vat_breakdown[]` | 1..n | CEN BR-CO-18 | Group | `/Invoice/cac:TaxTotal/cac:TaxSubtotal` | `STL/ram:ApplicableTradeTax` |
| BT-116 | VAT category taxable amount | `vat_breakdown[].taxable_amount` | 1 | CEN BR-45 | Amount | `/Invoice/cac:TaxTotal/cac:TaxSubtotal/cbc:TaxableAmount` | `STL/ram:ApplicableTradeTax/ram:BasisAmount` |
| BT-117 | VAT category tax amount | `vat_breakdown[].tax_amount` | 1 | CEN BR-46 | Amount | `/Invoice/cac:TaxTotal/cac:TaxSubtotal/cbc:TaxAmount` | `STL/ram:ApplicableTradeTax/ram:CalculatedAmount` |
| BT-118 | VAT category code | `vat_breakdown[].category_code` | 1 | CEN BR-47 | Code | `/Invoice/cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:ID[following-sibling::cac:TaxScheme/cbc:ID='VAT']` | `STL/ram:ApplicableTradeTax/ram:CategoryCode` |
| BT-119 | VAT category rate | `vat_breakdown[].rate` | 0..1 | XR 1 via BR-DE-14; EN: BR-48 except category O | Percentage | `/Invoice/cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:Percent` | `STL/ram:ApplicableTradeTax/ram:RateApplicablePercent` |
| BT-120 | VAT exemption reason text | `vat_breakdown[].exemption_reason` | 0..1 | XR table | Text | `/Invoice/cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:TaxExemptionReason` | `STL/ram:ApplicableTradeTax/ram:ExemptionReason` |
| BT-121 | VAT exemption reason code | `vat_breakdown[].exemption_reason_code` | 0..1 | XR table | Code | `/Invoice/cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:TaxExemptionReasonCode` | `STL/ram:ApplicableTradeTax/ram:ExemptionReasonCode` |
| BG-25 | INVOICE LINE | `lines[]` | 1..n | CEN BR-16 | Group | `/Invoice/cac:InvoiceLine` | `/rsm:SupplyChainTradeTransaction/ram:IncludedSupplyChainTradeLineItem` |
| BT-126 | Invoice line identifier | `lines[].identifier` | 1 | CEN BR-21 | Identifier | `cac:InvoiceLine/cbc:ID` | `LINE/ram:AssociatedDocumentLineDocument/ram:LineID` |
| BT-127 | Invoice line note | `lines[].note` | 0..1 | XR table | Text | `cac:InvoiceLine/cbc:Note` | `LINE/ram:AssociatedDocumentLineDocument/ram:IncludedNote/ram:Content` |
| BT-128 | Invoice line object identifier | `lines[].object_identifier` | 0..1 | XR table | Identifier | `cac:InvoiceLine/cac:DocumentReference/cbc:ID[following-sibling::cbc:DocumentTypeCode='130']` | `LINE/ram:SpecifiedLineTradeSettlement/ram:AdditionalReferencedDocument/ram:IssuerAssignedID[following-sibling::ram:TypeCode='130']` |
| BT-129 | Invoiced quantity | `lines[].invoiced_quantity` | 1 | CEN BR-22 | Quantity | `cac:InvoiceLine/cbc:InvoicedQuantity` | `LINE/ram:SpecifiedLineTradeDelivery/ram:BilledQuantity` |
| BT-130 | Invoiced quantity unit of measure code | `lines[].invoiced_quantity_unit_code` | 1 | CEN BR-23 | Code | `cac:InvoiceLine/cbc:InvoicedQuantity/@unitCode` | `LINE/ram:SpecifiedLineTradeDelivery/ram:BilledQuantity/@unitCode` |
| BT-132 | Referenced purchase order line reference | `lines[].purchase_order_line_reference` | 0..1 | XR table | Document Reference | `cac:InvoiceLine/cac:OrderLineReference/cbc:LineID` | `LINE/ram:SpecifiedLineTradeAgreement/ram:BuyerOrderReferencedDocument/ram:LineID` |
| BT-133 | Invoice line Buyer accounting reference | `lines[].buyer_accounting_reference` | 0..1 | XR table | Text | `cac:InvoiceLine/cbc:AccountingCost` | `LINE/ram:SpecifiedLineTradeSettlement/ram:ReceivableSpecifiedTradeAccountingAccount/ram:ID` |
| BG-26 | INVOICE LINE PERIOD | `lines[].period` | 0..1 | XR table | Group | `cac:InvoiceLine/cac:InvoicePeriod` | `LINE/ram:SpecifiedLineTradeSettlement/ram:BillingSpecifiedPeriod` |
| BT-134 | Invoice line period start date | `lines[].period.start_date` | 0..1 | XR table | Date | `cac:InvoiceLine/cac:InvoicePeriod/cbc:StartDate` | `LINE/ram:SpecifiedLineTradeSettlement/ram:BillingSpecifiedPeriod/ram:StartDateTime/udt:DateTimeString[@format='102']` |
| BT-135 | Invoice line period end date | `lines[].period.end_date` | 0..1 | XR table | Date | `cac:InvoiceLine/cac:InvoicePeriod/cbc:EndDate` | `LINE/ram:SpecifiedLineTradeSettlement/ram:BillingSpecifiedPeriod/ram:EndDateTime/udt:DateTimeString[@format='102']` |
| BG-27 | INVOICE LINE ALLOWANCES | `lines[].allowances[]` | 0..n | XR table | Group | `cac:InvoiceLine/cac:AllowanceCharge[cbc:ChargeIndicator='false']` | `LINE/ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeAllowanceCharge[ram:ChargeIndicator/udt:Indicator='false']` |
| BT-136 | Invoice line allowance amount | `lines[].allowances[].amount` | 1 | CEN BR-41 | Amount | `cac:InvoiceLine/cac:AllowanceCharge/cbc:Amount[preceding-sibling::cbc:ChargeIndicator='false']` | `LINE/ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeAllowanceCharge/ram:ActualAmount` |
| BT-137 | Invoice line allowance base amount | `lines[].allowances[].base_amount` | 0..1 | XR table | Amount | `cac:InvoiceLine/cac:AllowanceCharge/cbc:BaseAmount[preceding-sibling::cbc:ChargeIndicator='false']` | `LINE/ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeAllowanceCharge/ram:BasisAmount` |
| BT-138 | Invoice line allowance percentage | `lines[].allowances[].percentage` | 0..1 | XR table | Percentage | `cac:InvoiceLine/cac:AllowanceCharge/cbc:MultiplierFactorNumeric[preceding-sibling::cbc:ChargeIndicator='false']` | `LINE/ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeAllowanceCharge/ram:CalculationPercent` |
| BT-139 | Invoice line allowance reason | `lines[].allowances[].reason` | 0..1 | XR table | Text | `cac:InvoiceLine/cac:AllowanceCharge/cbc:AllowanceChargeReason[preceding-sibling::cbc:ChargeIndicator='false']` | `LINE/ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeAllowanceCharge/ram:Reason` |
| BT-140 | Invoice line allowance reason code | `lines[].allowances[].reason_code` | 0..1 | XR table | Code | `cac:InvoiceLine/cac:AllowanceCharge/cbc:AllowanceChargeReasonCode[preceding-sibling::cbc:ChargeIndicator='false']` | `LINE/ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeAllowanceCharge/ram:ReasonCode` |
| BG-28 | INVOICE LINE CHARGES | `lines[].charges[]` | 0..n | XR table | Group | `cac:InvoiceLine/cac:AllowanceCharge[cbc:ChargeIndicator='true']` | `LINE/ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeAllowanceCharge[ram:ChargeIndicator/udt:Indicator='true']` |
| BT-141 | Invoice line charge amount | `lines[].charges[].amount` | 1 | CEN BR-43 | Amount | `cac:InvoiceLine/cac:AllowanceCharge/cbc:Amount[preceding-sibling::cbc:ChargeIndicator='true']` | `LINE/ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeAllowanceCharge/ram:ActualAmount` |
| BT-142 | Invoice line charge base amount | `lines[].charges[].base_amount` | 0..1 | XR table | Amount | `cac:InvoiceLine/cac:AllowanceCharge/cbc:BaseAmount[preceding-sibling::cbc:ChargeIndicator='true']` | `LINE/ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeAllowanceCharge/ram:BasisAmount` |
| BT-143 | Invoice line charge percentage | `lines[].charges[].percentage` | 0..1 | XR table | Percentage | `cac:InvoiceLine/cac:AllowanceCharge/cbc:MultiplierFactorNumeric[preceding-sibling::cbc:ChargeIndicator='true']` | `LINE/ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeAllowanceCharge/ram:CalculationPercent` |
| BT-144 | Invoice line charge reason | `lines[].charges[].reason` | 0..1 | XR table | Text | `cac:InvoiceLine/cac:AllowanceCharge/cbc:AllowanceChargeReason[preceding-sibling::cbc:ChargeIndicator='true']` | `LINE/ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeAllowanceCharge/ram:Reason` |
| BT-145 | Invoice line charge reason code | `lines[].charges[].reason_code` | 0..1 | XR table | Code | `cac:InvoiceLine/cac:AllowanceCharge/cbc:AllowanceChargeReasonCode[preceding-sibling::cbc:ChargeIndicator='true']` | `LINE/ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeAllowanceCharge/ram:ReasonCode` |
| BG-29 | PRICE DETAILS | `lines[].price_details` | 1 | CEN BR-26 (via BT-146) | Group | `cac:InvoiceLine/cac:Price` | `LINE/ram:SpecifiedLineTradeAgreement` |
| BT-146 | Item net price | `lines[].price_details.item_net_price` | 1 | CEN BR-26 | Unit Price Amount | `cac:InvoiceLine/cac:Price/cbc:PriceAmount` | `LINE/ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount` |
| BT-147 | Item price discount | `lines[].price_details.item_price_discount` | 0..1 | XR table | Unit Price Amount | `cac:InvoiceLine/cac:Price/cac:AllowanceCharge/cbc:Amount[preceding-sibling::cbc:ChargeIndicator='false']` | `LINE/ram:SpecifiedLineTradeAgreement/ram:GrossPriceProductTradePrice/ram:AppliedTradeAllowanceCharge/ram:ActualAmount` |
| BT-148 | Item gross price | `lines[].price_details.item_gross_price` | 0..1 | XR table | Unit Price Amount | `cac:InvoiceLine/cac:Price/cac:AllowanceCharge/cbc:BaseAmount[preceding-sibling::cbc:ChargeIndicator='false']` | `LINE/ram:SpecifiedLineTradeAgreement/ram:GrossPriceProductTradePrice/ram:ChargeAmount` |
| BT-149 | Item price base quantity | `lines[].price_details.base_quantity` | 0..1 | XR table | Quantity | `cac:InvoiceLine/cac:Price/cbc:BaseQuantity` | `LINE/ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:BasisQuantity` |
| BT-150 | Item price base quantity unit of measure code | `lines[].price_details.base_quantity_unit_code` | 0..1 | XR table | Code | `cac:InvoiceLine/cac:Price/cbc:BaseQuantity/@unitCode` | `LINE/ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:BasisQuantity/@unitCode` |
| BG-30 | LINE VAT INFORMATION | `lines[].vat_information` | 1 | CEN BR-CO-04 (via BT-151) | Group | `cac:InvoiceLine/cac:Item/cac:ClassifiedTaxCategory` | `LINE/ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax` |
| BT-151 | Invoiced item VAT category code | `lines[].vat_information.category_code` | 1 | CEN BR-CO-04 | Code | `cac:InvoiceLine/cac:Item/cac:ClassifiedTaxCategory/cbc:ID` | `LINE/ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:CategoryCode` |
| BT-152 | Invoiced item VAT rate | `lines[].vat_information.rate` | 0..1 | XR table | Percentage | `cac:InvoiceLine/cac:Item/cac:ClassifiedTaxCategory/cbc:Percent` | `LINE/ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:RateApplicablePercent` |
| BG-31 | ITEM INFORMATION | `lines[].item` | 1 | CEN BR-25 (via BT-153) | Group | `cac:InvoiceLine/cac:Item` | `LINE/ram:SpecifiedTradeProduct` |
| BT-153 | Item name | `lines[].item.name` | 1 | CEN BR-25 | Text | `cac:InvoiceLine/cac:Item/cbc:Name` | `LINE/ram:SpecifiedTradeProduct/ram:Name` |
| BT-154 | Item description | `lines[].item.description` | 0..1 | XR table | Text | `cac:InvoiceLine/cac:Item/cbc:Description` | `LINE/ram:SpecifiedTradeProduct/ram:Description` |
| BT-155 | Item Sellers identifier | `lines[].item.sellers_identifier` | 0..1 | XR table | Identifier | `cac:InvoiceLine/cac:Item/cac:SellersItemIdentification/cbc:ID` | `LINE/ram:SpecifiedTradeProduct/ram:SellerAssignedID` |
| BT-156 | Item Buyers identifier | `lines[].item.buyers_identifier` | 0..1 | XR table | Identifier | `cac:InvoiceLine/cac:Item/cac:BuyersItemIdentification/cbc:ID` | `LINE/ram:SpecifiedTradeProduct/ram:BuyerAssignedID` |
| BT-157 | Item standard identifier | `lines[].item.standard_identifier` | 0..1 | XR table | Identifier | `cac:InvoiceLine/cac:Item/cac:StandardItemIdentification/cbc:ID` | `LINE/ram:SpecifiedTradeProduct/ram:GlobalID` |
| BT-158 | Item classification identifier | `lines[].item.classification_identifiers[]` | 0..n | XR table | Identifier | `cac:InvoiceLine/cac:Item/cac:CommodityClassification/cbc:ItemClassificationCode` | `LINE/ram:SpecifiedTradeProduct/ram:DesignatedProductClassification/ram:ClassCode` |
| BT-159 | Item country of origin | `lines[].item.country_of_origin` | 0..1 | XR table | Code | `cac:InvoiceLine/cac:Item/cac:OriginCountry/cbc:IdentificationCode` | `LINE/ram:SpecifiedTradeProduct/ram:OriginTradeCountry/ram:ID` |
| BG-32 | ITEM ATTRIBUTES | `lines[].item.attributes[]` | 0..n | XR table | Group | `cac:InvoiceLine/cac:Item/cac:AdditionalItemProperty` | `LINE/ram:SpecifiedTradeProduct/ram:ApplicableProductCharacteristic` |
| BT-160 | Item attribute name | `lines[].item.attributes[].name` | 1 | CEN BR-54 | Text | `cac:InvoiceLine/cac:Item/cac:AdditionalItemProperty/cbc:Name` | `LINE/ram:SpecifiedTradeProduct/ram:ApplicableProductCharacteristic/ram:Description` |
| BT-161 | Item attribute value | `lines[].item.attributes[].value` | 1 | CEN BR-54 | Text | `cac:InvoiceLine/cac:Item/cac:AdditionalItemProperty/cbc:Value` | `LINE/ram:SpecifiedTradeProduct/ram:ApplicableProductCharacteristic/ram:Value` |
| BT-131 | Invoice line net amount | `lines[].net_amount` | 1 | CEN BR-24 | Amount | `cac:InvoiceLine/cbc:LineExtensionAmount` | `LINE/ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount` |

## Notes for the mappers

* **N1 · BG-24 shares its elements.** In UBL, `cac:AdditionalDocumentReference` also carries BT-18
  (`cbc:DocumentTypeCode` 130). In CII, `ram:AdditionalReferencedDocument` also carries BT-17
  (`ram:TypeCode` 50) and BT-18 (130); a BG-24 entry has `ram:TypeCode` 916. The mappers must filter by
  type code.
* **N2 · UBL `cac:CardAccount/cbc:NetworkID`** is mandatory in the UBL 2.1 XSD
  (`UBL-CommonAggregateComponents-2.1.xsd:3122`, `CardAccountType`, minOccurs=1 maxOccurs=1) but carries no
  business term; the CEN rules only forbid its `@schemeID` (UBL-CR-675, warning). The UBL writer (#10)
  writes `NA` whenever BG-18 is present, the example value of the Peppol upstream structure docs
  (peppol-bis-invoice-3 commit 806866b, not a pinned artifact), `structure/syntax/part/card-payment.xml`
  ("Syntax required element not related to a business term"); the reader ignores it.
* **N3 · UBL credit notes.** `CreditNoteType` has neither `cbc:DueDate` nor `cac:ProjectReference`. BT-9 is
  `/CreditNote/cac:PaymentMeans/cbc:PaymentDueDate` and BT-11 is
  `/CreditNote/cac:AdditionalDocumentReference/cbc:ID[following-sibling::cbc:DocumentTypeCode='50']`
  (Peppol upstream structure docs, commit 806866b, `ubl-creditnote.xml`; KoSIT `ubl-creditnote-xr.xsl`;
  CEN UBL-SR-43 allows code 50 only in a credit note). BT-9 in a credit note therefore needs BG-16 (whose
  BT-81 is mandatory, BR-49); the writer refuses it otherwise.
* **N4 · UBL writer fill-ins.** `cac:OrderReference/cbc:ID` is mandatory, so BT-14 without BT-13 writes
  `NA` there (Peppol upstream structure docs, commit 806866b, `ubl-invoice.xml`, BT-13). BT-32 is written
  with `cac:TaxScheme/cbc:ID` `FC`, as in the XRechnung test suite (CEN only requires a value other than
  `VAT`, UBL-SR-13). BT-90 is written under `cac:PayeeParty` when BG-10 is present, else under the Seller.

## Library conventions

* **BG-0.** EN 16931-1 gives the root "INVOICE" no identifier (XR §11.1: "besitzt … keine eigene
  Kennung"). The library calls it `BG-0` (plan §4, issue #8), so that every node of the tree has an id.
  It is the only id in this table that no source defines.
* **BG-14 and BG-15 sit under BG-13** in the model, as in the semantic tree (XR §11.7, §11.18), although
  UBL and CII write the invoicing period at document level.
* **BT-130 and BT-150** are separate fields although both syntaxes write them as the `unitCode`
  attribute of the quantity.

## Decisions (permissive per D8)

Where XR and a syntax disagree and no CEN rule decides, the model takes the most permissive structurally
valid option, so it never refuses an invoice the official CEN Schematron accepts (D8). The stricter
syntax's writer reports the gap.

* **M1 · BT-22 Invoice note is optional in BG-1.** XR gives `1`, but no CEN rule requires it and the CII
  XSD allows `ram:IncludedNote` with only a `ram:SubjectCode`.
* **M2 · BT-87 Payment card primary account number is optional in BG-18.** XR gives `1` and the UBL XSD
  requires `cbc:PrimaryAccountNumberID`, but no CEN rule requires it and the CII XSD makes
  `ram:ApplicableTradeSettlementFinancialCard/ram:ID` optional. The UBL writer must report its absence.
* **M3 · BT-125 mime code and filename are optional.** XR gives both `1` and UBL enforces them
  (UBL-DT-06/07, fatal), but the CEN CII rules and the CII XSD do not. The UBL writer must report their
  absence.
* **BT-21 in UBL** is bound by CEN UBL BR-CL-08 (`UBL/EN16931-UBL-model.sch`, fatal, context
  `cbc:Note`): the code is the text between a leading `#…#` (e.g. `#ADU#text`, as in the XRechnung test
  suite).
* **BT-8 in CII.** The model stores UNTDID 2005 codes (3, 35, 432); CII requires UNTDID 2475 codes
  (5, 29, 72). The correspondence 3 = 5, 35 = 29, 432 = 72 is the European Commission's "EN16931 code
  lists values v17b - used from 2026-05-15" (ec.europa.eu, Registry of supporting artefacts to implement
  EN16931), sheet "Time"; `euinvoice/syntax/cii/_build.py` encodes it.
* **CII gap · more than one BG-3.** The model allows 0..n preceding invoice references (XR table), but
  `ram:HeaderTradeSettlementType` declares `ram:InvoiceReferencedDocument` with `minOccurs="0"` and the
  default `maxOccurs` 1 (D16B `CrossIndustryInvoice_ReusableAggregateBusinessInformationEntity_100pD16B.xsd`).
  The CII writer raises `ModelError` for a second one.
* **CII gap · BT-150 without BT-149.** CII writes BT-150 as the `@unitCode` of `ram:BasisQuantity` (BT-149),
  a `udt:QuantityType` whose content is an `xs:decimal` (D16B `..._UnqualifiedDataType_100pD16B.xsd`), so a
  unit without a quantity has no element to sit on. The CII writer raises `ModelError`.
* **CII gap · BT-111 without BT-6.** BT-111's only binding is
  `ram:TaxTotalAmount[@currencyID = ../../ram:TaxCurrencyCode]` (KoSIT binding, BR-53, BR-DEC-15); without
  BT-6 the amount has no currency to carry. The CII writer raises `ModelError`.
* **Gap in both syntaxes · BT-6 = BT-5 with BT-111.** BT-110 and BT-111 are told apart only by `@currencyID`, so
  equal currencies give two amounts in BT-5 that no reader can tell apart, and the CEN Schematron rejects every
  such document: CII BR-53 requires `ram:TaxCurrencyCode` to differ from `ram:InvoiceCurrencyCode`, UBL BR-CO-15
  requires exactly one `cbc:TaxAmount` in BT-5. Both writers raise `ModelError` (#71). Without BT-111 both write
  BT-6 = BT-5, which fails CII BR-53 only.

## Normalizations

A writer may add a value the model leaves out when a syntax requires it and the value follows from other
terms. A model → syntax → model round trip then gains that value.

* **BT-148 derived from BT-146 + BT-147 in CII.** CII writes the item price discount BT-147 as an
  allowance on `ram:GrossPriceProductTradePrice`, whose `ram:ChargeAmount` (BT-148) the D16B XSD requires
  (`TradePriceType`, minOccurs 1). When BT-147 is set without BT-148, the CII writer writes
  BT-148 = BT-146 + BT-147 (the identity BT-146 = BT-148 − BT-147 of PEPPOL-EN16931-R046), with BT-149/BT-150
  as the gross price's `ram:BasisQuantity` (written on every gross price, as in the CEN examples). CEN does the same for its TOSL108 invoice:
  `ubl-tc434-example2.xml` carries BT-147 only and `CII_example2.xml` writes gross 1498 = net 1273 +
  allowance 225. A derived BT-148 below zero would break BR-28 (fatal), so the writer raises `ModelError`
  then and asks for an explicit BT-148.
* **BT-147 derived from BT-148 − BT-146 in UBL.** UBL writes BT-147 and BT-148 as `cbc:Amount` and
  `cbc:BaseAmount` of `cac:Price/cac:AllowanceCharge`, and `cbc:Amount` is mandatory there (UBL 2.1 XSD
  `AllowanceChargeType`). When BT-148 is set without BT-147, the UBL writer writes BT-147 = BT-148 − BT-146
  (`0.00` when they are equal), the identity of PEPPOL-EN16931-R046 (`rules/sch/PEPPOL-EN16931-UBL.sch:363`);
  the same TOSL108 pair shows the binding. A BT-148 below BT-146 would need a negative discount, i.e. a
  price-level charge, which PEPPOL-EN16931-R044 forbids, so the writer raises `ModelError` then.
* **Code 81 written as a UBL `CreditNote`.** BT-3 = 81 is in both CEN UBL lists (BR-CL-01); the UBL writer
  always writes it as `CreditNote` (Peppol accepts it only there, P0101; issue #10), so a UBL `Invoice` with
  code 81 is read back and written again as a `CreditNote`. The model stores no root hint (D4).
* **Empty groups are not written in CII.** The CII writer skips a BG-1 note with neither BT-21 nor BT-22, a BG-13
  whose terms (including BG-14) are all absent and a BG-19 whose BT-89, BT-90 and BT-91 are all absent, so a
  model → CII → model round trip drops them. It writes BT-29 identifiers without a scheme first (`ram:ID` precedes
  `ram:GlobalID` in the D16B `TradePartyType` sequence), so their order may change.
* **Empty groups and notes are not written in UBL.** The UBL writer writes nothing for a BG-1 note with neither
  BT-21 nor BT-22, a BG-13 with no term set, a BG-19 with none of BT-89..BT-91, and an empty `cac:InvoicePeriod` for
  a BG-14 / BG-26 without dates reads back as absent; a model → UBL → model round trip drops such empty groups. A
  BT-21 note whose BT-22 is empty is written `#CODE#` and reads back with no BT-22.

### The CII reader (#14)

The reader (`euinvoice.syntax.cii.read`) is the inverse of the writer. Anything it cannot map to a business term is
listed in `ParseResult.unmapped` (XPaths), never dropped and never an error:

* Dates are read only with `@format='102'` (CCYYMMDD); another format, or an invalid date, is a `ParseError` (binding
  note on #13). BT-8 is mapped back from UNTDID 2475 (5, 29, 72) to 2005 (3, 35, 432); another code is a
  `ParseError` (CII BR-CL-06).
* BT-7 and BT-8 are read from whichever `ram:ApplicableTradeTax` carries them (CII-SR-461: at most one
  `ram:TaxPointDate` per breakdown; CII-SR-462: one distinct `ram:DueDateTypeCode`); a later different value is unmapped.
* BT-84 is `ram:IBANID`, else `ram:ProprietaryID`. BT-81 and BT-82 are the first `ram:TypeCode` and the first
  `ram:Information` across the payment means; as in CII-SR-467/468, a means whose own `ram:TypeCode` /
  `ram:Information` is absent or equal under `normalize-space` belongs to the same BG-16 and adds its account as a
  BG-17, and a means with a different one is unmapped. BT-83, BT-89 and BT-90 without any payment means are unmapped
  (BG-16 needs BT-81, BR-49). BT-91 is `ram:IBANID` only (CII-SR-444 warns that `ram:ProprietaryID` should not be
  there; one is unmapped).
* An allowance or charge (BG-20, BG-21, BG-27, BG-28) whose `ram:ChargeIndicator/udt:Indicator` is missing or not an
  `xs:boolean` is unmapped: the D16B XSD makes the indicator optional and the CEN rules select the groups by it.
  BT-147 is the first gross price `ram:AppliedTradeAllowanceCharge` with indicator false; a charge, one without an
  indicator (CII-SR-119 accepts it without amount) and any later allowance are unmapped.
* BT-41 / BT-56 is `ram:PersonName`, else `ram:DepartmentName`. A party identifier is `ram:ID` or `ram:GlobalID`, each
  with its `@schemeID` if present.
* `ram:TaxTotalAmount` is BT-110 or BT-111 by its `@currencyID` (BT-5 or BT-6); one with neither is unmapped.
* Consumed without a business term, and only with exactly the value the writer itself writes (any other value is
  unmapped): `ram:SpecifiedProcuringProject/ram:Name` equal to "Project reference" (`PROJECT_NAME`), a gross price
  `ram:BasisQuantity` equal to the net one, the `ram:TypeCode` `VAT` of taxes and 916 / 50 / 130 of BG-24 / BT-17 /
  BT-18 documents, empty `ram:IncludedNote` elements (no child, no text), and `@format='102'` of dates.
* Content the model cannot hold (e.g. a line-level `ram:ExemptionReason`, Factur-X EXTENDED elements, a second card)
  is unmapped. A model that cannot be built (a missing required term, a code outside its list) is a `ParseError`
  naming the BT/BG and located at the element being read; Factur-X MINIMUM / BASIC WL subsets are #22's job.


### The UBL reader (#11)

The reader (`euinvoice.syntax.ubl.read`) is the inverse of the writer and accepts both roots (`Invoice`,
`CreditNote` with `cac:CreditNoteLine` / `cbc:CreditedQuantity`). Anything it cannot map to a business term is
listed in `ParseResult.unmapped` (XPaths), never dropped and never an error:

* **BT-21** is taken only from a leading `#CODE#` whose CODE has exactly three characters and is in UNTDID 4451; the
  rest is BT-22. Any other note is BT-22 verbatim (issue #11; CEN BR-CL-08 accepts more, so nothing it accepts is
  refused). A BT-22 without BT-21 that itself starts with such a pair reads back as BT-21 + BT-22. An empty
  `cbc:Note` is unmapped.
* **BT-13**: `cac:OrderReference/cbc:ID` `NA` next to a `cbc:SalesOrderID` is the writer's placeholder and reads as
  no BT-13. Known ambiguity: a genuine purchase order reference "NA" together with a BT-14 cannot be told apart.
* **Credit notes**: BT-9 is `cac:PaymentMeans/cbc:PaymentDueDate` (in an `Invoice` that element is unmapped), BT-11
  is `cac:AdditionalDocumentReference` with `cbc:DocumentTypeCode` 50 (in an `Invoice` such a reference is unmapped,
  CEN UBL-SR-43). An `Invoice` with BT-3 = 81 reads like a `CreditNote` (see the code 81 normalization).
* `cac:AdditionalDocumentReference` is BT-18 (code 130, the first), BT-11 (code 50, credit note) or BG-24 (no code);
  any other is unmapped. A line `cac:DocumentReference` is BT-128 only with code 130 (the table's binding; CEN
  BR-CL-07 is checked in the context `cac:DocumentReference[cbc:DocumentTypeCode = '130']/cbc:ID[@schemeID]`,
  `codelist/EN16931-UBL-codes.sch:43`;
  Peppol PEPPOL-EN16931-R101); one without a code, as in CEN `ubl-tc434-example5.xml`, is unmapped.
* **BT-90** is `cac:PartyIdentification/cbc:ID[@schemeID='SEPA']` of the Payee, else of the Seller (issue #10); a
  copy with the same value under the other party is taken too, a different one is unmapped, and so is a SEPA id
  when there is no `cac:PaymentMeans` (BG-16 needs BT-81, BR-49).
* **BG-16 / BG-17**: every `cac:PaymentMeans/cac:PayeeFinancialAccount` is a BG-17. BT-81, BT-82, BT-83 and the
  credit note BT-9 come from their first occurrence; a repeat equal to it (codes and dates under
  `normalize-space`, BT-83 exactly, as UBL-SR-44) or absent is taken, a different one is unmapped (UBL-SR-44..47).
  The first `cac:CardAccount` and `cac:PaymentMandate` are BG-18 and BG-19.
* **BT-110 / BT-111** are the `cac:TaxTotal/cbc:TaxAmount` whose `@currencyID` is BT-5 / BT-6; BG-23 is read from
  the BT-110 `cac:TaxTotal` only; another `cac:TaxTotal` is unmapped. Every other amount's `@currencyID` is taken
  only when it is BT-5; another currency is unmapped.
* Consumed without a business term, and only with exactly the value the writer itself writes (any other value is
  unmapped): `cac:CardAccount/cbc:NetworkID` `NA` (note N2), the `cac:TaxScheme/cbc:ID` `FC` of BT-32, and
  `VAT` (under `normalize-space`, upper-cased, as the CEN rules select it) of VAT identifiers and categories.
* Dates are `xs:date` (surrounding whitespace allowed). A time zone (`2013-04-10Z`, `2013-04-10+01:00`) is valid
  `xs:date` and no CEN rule restricts it, so the calendar date is read and the zone, which the model cannot hold, is
  reported as `<element path>/text()` in `unmapped`: a `/text()` suffix means part of that element's text was not
  mapped. Text that is not an `xs:date` (with a four-digit year) or not a calendar date is a `ParseError`
  (`BT-n: cannot interpret the date …`). An invalid `cbc:ChargeIndicator` is a `ParseError` naming BG-20/BG-21,
  BG-27/BG-28 or BT-147: it is typed `xs:boolean`, so the UBL XSD rejects the document anyway. A model that
  cannot be built (a missing required term, a code outside its list) is a `ParseError` naming the BT/BG and located
  at the element being read.
