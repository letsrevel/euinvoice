"""Syntax-neutral synthetic invoices for the writer and reader tests (CLAUDE.md fixtures rule).

Fake parties, ``example.com`` addresses, placeholder tax ids and the test IBAN only. :func:`minimal_invoice` and
:func:`full_invoice` are arithmetically consistent and pass the CEN EN 16931 rules, so a writer's conformance
tests can demand zero findings. The part builders take keyword overrides, so a test changes one term without
restating the rest. Syntax-specific bases (for example a writer's all-terms coverage invoice) live next to that
writer's tests and build on these. ``tests/conftest.py`` belongs to the model tests and is separate.
"""

import datetime
import typing as t
from decimal import Decimal

from euinvoice.model import (
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
    Invoice,
    InvoiceLine,
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

TEST_IBAN: t.Final = "DE02120300000000202051"
"""The well-known German test IBAN (valid check digits, no real account)."""
CEN: t.Final = "urn:cen.eu:en16931:2017"
"""BT-24 of the EN 16931 core."""


def rebuild[M: (Invoice, InvoiceLine)](model: M, **changes: t.Any) -> M:
    """A validated copy of ``model`` with top-level ``changes`` (``model_copy`` would skip validation)."""
    return type(model).model_validate({**dict(model), **changes})


def seller(**changes: t.Any) -> Seller:
    """A Seller (BG-4) with every term set."""
    data: dict[str, t.Any] = {
        "name": "Seller Example GmbH",
        "trading_name": "Seller Example",
        "identifiers": (Identifier(value="SELLER-1"), Identifier(value="4000001000005", scheme_id="0088")),
        "legal_registration_identifier": Identifier(value="HRB 00000", scheme_id="0002"),
        "vat_identifier": "DE000000000",
        "tax_registration_identifier": "000/000/00000",
        "additional_legal_information": "Share capital 25 000 EUR",
        "electronic_address": Identifier(value="seller@example.com", scheme_id="EM"),
        "postal_address": SellerPostalAddress(
            address_line_1="Example Street 1",
            address_line_2="Building A",
            address_line_3="Floor 2",
            city="Example City",
            post_code="10000",
            country_subdivision="Example State",
            country_code="DE",
        ),
        "contact": SellerContact(contact_point="Sales", telephone="+49 000 000000", email="sales@example.com"),
    }
    return Seller(**{**data, **changes})


def buyer(**changes: t.Any) -> Buyer:
    """A Buyer (BG-7) with every term set."""
    data: dict[str, t.Any] = {
        "name": "Buyer Example AG",
        "trading_name": "Buyer Example",
        "identifier": Identifier(value="4000001000036", scheme_id="0088"),
        "legal_registration_identifier": Identifier(value="CHE-000.000.000", scheme_id="0183"),
        "vat_identifier": "ATU00000000",
        "electronic_address": Identifier(value="buyer@example.com", scheme_id="EM"),
        "postal_address": BuyerPostalAddress(
            address_line_1="Sample Road 2",
            address_line_2="Unit 3",
            address_line_3="Back office",
            city="Sample Town",
            post_code="1010",
            country_subdivision="Sample Region",
            country_code="AT",
        ),
        "contact": BuyerContact(contact_point="Accounts payable", telephone="+43 0 000000", email="ap@example.com"),
    }
    return Buyer(**{**data, **changes})


def price(**changes: t.Any) -> PriceDetails:
    """PRICE DETAILS (BG-29): net 50.0000 = gross 50.5 less discount 0.5, per 1 C62."""
    data: dict[str, t.Any] = {
        "item_net_price": Decimal("50.0000"),
        "item_price_discount": Decimal("0.5"),
        "item_gross_price": Decimal("50.5"),
        "base_quantity": Decimal("1"),
        "base_quantity_unit_code": "C62",
    }
    return PriceDetails(**{**data, **changes})


def item(**changes: t.Any) -> ItemInformation:
    """ITEM INFORMATION (BG-31) with every term set."""
    data: dict[str, t.Any] = {
        "name": "Widget",
        "description": "A synthetic widget",
        "sellers_identifier": "SKU-1",
        "buyers_identifier": "BUY-SKU-1",
        "standard_identifier": Identifier(value="4000001000029", scheme_id="0160"),
        "classification_identifiers": (
            ItemClassificationIdentifier(value="43211503", scheme_id="STI", scheme_version_id="19.0501"),
        ),
        "country_of_origin": "DE",
        "attributes": (ItemAttribute(name="Colour", value="Blue"),),
    }
    return ItemInformation(**{**data, **changes})


def line(**changes: t.Any) -> InvoiceLine:
    """INVOICE LINE (BG-25) with every term set: 2 x 50.00, allowance 5.00 and charge 5.00, net 100.00 at S 19 %."""
    data: dict[str, t.Any] = {
        "identifier": "1",
        "note": "Line note",
        "object_identifier": Identifier(value="LINE-OBJ-1", scheme_id="AAA"),
        "invoiced_quantity": Decimal("2"),
        "invoiced_quantity_unit_code": "C62",
        "net_amount": Decimal("100.00"),
        "purchase_order_line_reference": "PO-1-10",
        "buyer_accounting_reference": "ACC-LINE-1",
        "period": InvoiceLinePeriod(start_date=datetime.date(2026, 1, 1), end_date=datetime.date(2026, 1, 31)),
        "allowances": (
            InvoiceLineAllowance(
                amount=Decimal("5.00"),
                base_amount=Decimal("100.00"),
                percentage=Decimal("5"),
                reason="Line discount",
                reason_code="95",
            ),
        ),
        "charges": (
            InvoiceLineCharge(
                amount=Decimal("5.00"),
                base_amount=Decimal("100.00"),
                percentage=Decimal("5"),
                reason="Packing",
                reason_code="ABL",
            ),
        ),
        "price_details": price(),
        "vat_information": LineVatInformation(category_code="S", rate=Decimal("19")),
        "item": item(),
    }
    return InvoiceLine(**{**data, **changes})


def simple_line(**changes: t.Any) -> InvoiceLine:
    """A line with only the mandatory terms: 2 x 50, net 100.00 at S 19 %."""
    data: dict[str, t.Any] = {
        "identifier": "1",
        "invoiced_quantity": Decimal("2"),
        "invoiced_quantity_unit_code": "C62",
        "net_amount": Decimal("100.00"),
        "price_details": PriceDetails(item_net_price=Decimal("50")),
        "vat_information": LineVatInformation(category_code="S", rate=Decimal("19")),
        "item": ItemInformation(name="Widget"),
    }
    return InvoiceLine(**{**data, **changes})


def payment(**changes: t.Any) -> PaymentInstructions:
    """PAYMENT INSTRUCTIONS (BG-16) with a SEPA credit transfer, a card and a direct debit (every term set)."""
    data: dict[str, t.Any] = {
        "payment_means_type_code": "58",
        "payment_means_text": "SEPA credit transfer",
        "remittance_information": "INV-2026-0001",
        "credit_transfers": (
            CreditTransfer(
                payment_account_identifier=TEST_IBAN,
                payment_account_name="Seller Example GmbH",
                payment_service_provider_identifier="EXAMPLEXXXX",
            ),
        ),
        # BR-51: at most the first 6 and last 4 digits of the card number (10 characters).
        "payment_card": PaymentCardInformation(primary_account_number="0000000000", holder_name="A. Holder"),
        "direct_debit": DirectDebit(
            mandate_reference_identifier="MANDATE-1",
            bank_assigned_creditor_identifier="DE98ZZZ09999999999",
            debited_account_identifier=TEST_IBAN,
        ),
    }
    return PaymentInstructions(**{**data, **changes})


def totals(**changes: t.Any) -> DocumentTotals:
    """DOCUMENT TOTALS (BG-22) of :func:`full_invoice`, every term set."""
    data: dict[str, t.Any] = {
        "sum_of_line_net_amounts": Decimal("150.00"),
        "sum_of_allowances": Decimal("10.00"),
        "sum_of_charges": Decimal("10.00"),
        "total_without_vat": Decimal("150.00"),
        "total_vat": Decimal("19.00"),
        "total_vat_in_accounting_currency": Decimal("210.00"),
        "total_with_vat": Decimal("169.00"),
        "paid_amount": Decimal("0.00"),
        "rounding_amount": Decimal("0.00"),
        "amount_due": Decimal("169.00"),
    }
    return DocumentTotals(**{**data, **changes})


def minimal_invoice(**changes: t.Any) -> Invoice:
    """The smallest CEN-valid invoice: the mandatory terms, BT-110 and the Seller VAT id BR-S-02 needs."""
    data: dict[str, t.Any] = {
        "number": "INV-1",
        "issue_date": datetime.date(2026, 1, 15),
        "type_code": "380",
        "currency_code": "EUR",
        "process_control": ProcessControl(specification_identifier=CEN),
        "seller": Seller(
            name="Seller Example GmbH",
            vat_identifier="DE000000000",
            postal_address=SellerPostalAddress(country_code="DE"),
        ),
        "buyer": Buyer(name="Buyer Example AG", postal_address=BuyerPostalAddress(country_code="DE")),
        "totals": DocumentTotals(
            sum_of_line_net_amounts=Decimal("100.00"),
            total_without_vat=Decimal("100.00"),
            total_vat=Decimal("19.00"),
            total_with_vat=Decimal("119.00"),
            amount_due=Decimal("119.00"),
        ),
        "vat_breakdown": (
            VatBreakdown(
                taxable_amount=Decimal("100.00"), tax_amount=Decimal("19.00"), category_code="S", rate=Decimal("19")
            ),
        ),
        "lines": (simple_line(),),
    }
    return Invoice(**{**data, **changes})


def full_invoice(**changes: t.Any) -> Invoice:
    """A CEN-valid invoice setting every business term except BT-7, which excludes BT-8 (BR-CO-03).

    Two lines: :func:`line` (S 19 %) and an exempt one, so the VAT breakdown has two categories.
    """
    data: dict[str, t.Any] = {
        "number": "INV-2026-0001",
        "issue_date": datetime.date(2026, 1, 15),
        "type_code": "380",
        "currency_code": "EUR",
        "vat_accounting_currency_code": "SEK",
        "vat_point_date_code": "35",
        "payment_due_date": datetime.date(2026, 2, 14),
        "buyer_reference": "BUYER-REF-1",
        "project_reference": "PROJ-1",
        "contract_reference": "CONTRACT-1",
        "purchase_order_reference": "PO-1",
        "sales_order_reference": "SO-1",
        "receiving_advice_reference": "RA-1",
        "despatch_advice_reference": "DA-1",
        "tender_or_lot_reference": "LOT-1",
        "invoiced_object_identifier": Identifier(value="OBJ-1", scheme_id="AAA"),
        "buyer_accounting_reference": "ACC-1",
        "payment_terms": "30 days net",
        "notes": (InvoiceNote(subject_code="AAI", note="Synthetic test invoice."),),
        "process_control": ProcessControl(
            business_process_type="urn:example.com:process:01", specification_identifier=CEN
        ),
        "preceding_invoice_references": (
            PrecedingInvoiceReference(reference="INV-2025-0099", issue_date=datetime.date(2025, 12, 1)),
        ),
        "seller": seller(),
        "buyer": buyer(),
        "payee": Payee(
            name="Payee Example Ltd",
            identifier=Identifier(value="PAYEE-1"),
            legal_registration_identifier=Identifier(value="00000000", scheme_id="0002"),
        ),
        "seller_tax_representative": SellerTaxRepresentative(
            name="Tax Rep Example SARL",
            vat_identifier="FR00000000000",
            postal_address=TaxRepresentativePostalAddress(
                address_line_1="Rue Exemple 3",
                address_line_2="Batiment B",
                address_line_3="Etage 1",
                city="Exempleville",
                post_code="75000",
                country_subdivision="Exemple",
                country_code="FR",
            ),
        ),
        "delivery": DeliveryInformation(
            deliver_to_party_name="Warehouse Example",
            deliver_to_location_identifier=Identifier(value="4000001000012", scheme_id="0088"),
            actual_delivery_date=datetime.date(2026, 1, 10),
            invoicing_period=InvoicingPeriod(start_date=datetime.date(2026, 1, 1), end_date=datetime.date(2026, 1, 31)),
            deliver_to_address=DeliverToAddress(
                address_line_1="Dock Lane 4",
                address_line_2="Gate 5",
                address_line_3="Bay 6",
                city="Harbour Town",
                post_code="20000",
                country_subdivision="Harbour State",
                country_code="DE",
            ),
        ),
        "payment_instructions": payment(),
        "allowances": (
            DocumentLevelAllowance(
                amount=Decimal("10.00"),
                base_amount=Decimal("100.00"),
                percentage=Decimal("10"),
                vat_category_code="S",
                vat_rate=Decimal("19"),
                reason="Loyalty discount",
                reason_code="95",
            ),
        ),
        "charges": (
            DocumentLevelCharge(
                amount=Decimal("10.00"),
                base_amount=Decimal("100.00"),
                percentage=Decimal("10"),
                vat_category_code="S",
                vat_rate=Decimal("19"),
                reason="Freight",
                reason_code="FC",
            ),
        ),
        "additional_supporting_documents": (
            AdditionalSupportingDocument(
                reference="TIMESHEET-1",
                description="Timesheet",
                external_location="https://example.com/timesheet.pdf",
                attached_document=BinaryObject(
                    content=b"%PDF-1.7\n\x00\xff", mime_code="application/pdf", filename="timesheet.pdf"
                ),
            ),
        ),
        "totals": totals(),
        "vat_breakdown": (
            VatBreakdown(
                taxable_amount=Decimal("100.00"), tax_amount=Decimal("19.00"), category_code="S", rate=Decimal("19")
            ),
            VatBreakdown(
                taxable_amount=Decimal("50.00"),
                tax_amount=Decimal("0.00"),
                category_code="E",
                rate=Decimal("0"),
                exemption_reason="Exempt",
                exemption_reason_code="VATEX-EU-132",
            ),
        ),
        "lines": (
            line(),
            simple_line(
                identifier="2",
                invoiced_quantity=Decimal("1"),
                net_amount=Decimal("50.00"),
                vat_information=LineVatInformation(category_code="E", rate=Decimal("0")),
                item=ItemInformation(name="Exempt service"),
            ),
        ),
    }
    return Invoice(**{**data, **changes})


def peppol_invoice(**changes: t.Any) -> Invoice:
    """:func:`minimal_invoice` plus what Peppol BIS requires; valid under ``profiles.PEPPOL`` in UBL and CII.

    BT-10 (PEPPOL-EN16931-R003), GLN electronic addresses (R010, R020; EAS ``0088`` passes
    PEPPOL-COMMON-R040) and Austrian parties (no Peppol national rule set applies to AT). BT-23 and BT-24
    are the Peppol ones, as ``PEPPOL.prepare()`` sets them.
    """
    data: dict[str, t.Any] = {
        "buyer_reference": "BUYER-REF-1",
        "process_control": ProcessControl(
            business_process_type="urn:fdc:peppol.eu:2017:poacc:billing:01:1.0",
            specification_identifier="urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0",
        ),
        "seller": Seller(
            name="Seller Example GmbH",
            vat_identifier="ATU00000000",
            electronic_address=Identifier(value="4000001000005", scheme_id="0088"),
            postal_address=SellerPostalAddress(country_code="AT"),
        ),
        "buyer": Buyer(
            name="Buyer Example AG",
            electronic_address=Identifier(value="4000001000036", scheme_id="0088"),
            postal_address=BuyerPostalAddress(country_code="AT"),
        ),
    }
    return minimal_invoice(**{**data, **changes})
