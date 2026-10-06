"""Synthetic invoices shared by the test suite (fake parties, example.com, test IBAN; CLAUDE.md fixtures rule)."""

import datetime
import os
import typing as t
from collections.abc import Callable
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, settings

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
from euinvoice.model.codes import VatCategory

# Hypothesis profiles (CLAUDE.md "Testing"). No wall-clock deadline and no too_slow health check: under a loaded
# host or parallel xdist workers they fail correct tests (DeadlineExceeded, FlakyFailure) without testing anything
# about the library. They are runtime knobs only; what each property asserts is unchanged. "default" keeps
# Hypothesis' 100 examples; "ci" (HYPOTHESIS_PROFILE=ci) runs more for a deeper search. Explicit @settings on a
# test override only the fields they name.
settings.register_profile("default", deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.register_profile("ci", settings.get_profile("default"), max_examples=500)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))

TEST_IBAN: t.Final = "DE02120300000000202051"


def _line(identifier: str = "1") -> InvoiceLine:
    return InvoiceLine(
        identifier=identifier,
        invoiced_quantity=Decimal("2"),
        invoiced_quantity_unit_code="C62",
        net_amount=Decimal("100.00"),
        price_details=PriceDetails(item_net_price=Decimal("50")),
        vat_information=LineVatInformation(category_code=VatCategory.STANDARD_RATED, rate=Decimal("19")),
        item=ItemInformation(name="Widget"),
    )


def minimal_invoice(**changes: t.Any) -> Invoice:
    """The smallest invoice the model accepts: only the terms the CEN rules make mandatory."""
    data: dict[str, t.Any] = {
        "number": "INV-1",
        "issue_date": datetime.date(2026, 1, 15),
        "type_code": "380",
        "currency_code": "EUR",
        "process_control": ProcessControl(specification_identifier="urn:cen.eu:en16931:2017"),
        "seller": Seller(name="Seller Example GmbH", postal_address=SellerPostalAddress(country_code="DE")),
        "buyer": Buyer(name="Buyer Example AG", postal_address=BuyerPostalAddress(country_code="DE")),
        "totals": DocumentTotals(
            sum_of_line_net_amounts=Decimal("100.00"),
            total_without_vat=Decimal("100.00"),
            total_with_vat=Decimal("119.00"),
            amount_due=Decimal("119.00"),
        ),
        "vat_breakdown": (
            VatBreakdown(
                taxable_amount=Decimal("100.00"),
                tax_amount=Decimal("19.00"),
                category_code="S",
                rate=Decimal("19"),
            ),
        ),
        "lines": (_line(),),
    }
    data.update(changes)
    return Invoice(**data)


def full_invoice() -> Invoice:
    """An invoice that sets every business term of the model at least once."""
    return Invoice(
        number="INV-2026-0001",
        issue_date=datetime.date(2026, 1, 15),
        type_code="380",
        currency_code="EUR",
        vat_accounting_currency_code="SEK",
        vat_point_date=datetime.date(2026, 1, 10),
        vat_point_date_code="35",
        payment_due_date=datetime.date(2026, 2, 14),
        buyer_reference="BUYER-REF-1",
        project_reference="PROJ-1",
        contract_reference="CONTRACT-1",
        purchase_order_reference="PO-1",
        sales_order_reference="SO-1",
        receiving_advice_reference="RA-1",
        despatch_advice_reference="DA-1",
        tender_or_lot_reference="LOT-1",
        invoiced_object_identifier=Identifier(value="OBJ-1", scheme_id="AAA"),
        buyer_accounting_reference="ACC-1",
        payment_terms="30 days net",
        notes=(InvoiceNote(subject_code="AAI", note="Synthetic test invoice."),),
        process_control=ProcessControl(
            business_process_type="urn:example.com:process:01",
            specification_identifier="urn:cen.eu:en16931:2017",
        ),
        preceding_invoice_references=(
            PrecedingInvoiceReference(reference="INV-2025-0099", issue_date=datetime.date(2025, 12, 1)),
        ),
        seller=Seller(
            name="Seller Example GmbH",
            trading_name="Seller Example",
            identifiers=(Identifier(value="SELLER-1"), Identifier(value="4000001000005", scheme_id="0088")),
            legal_registration_identifier=Identifier(value="HRB 00000", scheme_id="0002"),
            vat_identifier="DE123456789",
            tax_registration_identifier="000/000/00000",
            additional_legal_information="Share capital 25 000 EUR",
            electronic_address=Identifier(value="seller@example.com", scheme_id="EM"),
            postal_address=SellerPostalAddress(
                address_line_1="Example Street 1",
                address_line_2="Building A",
                address_line_3="Floor 2",
                city="Example City",
                post_code="10000",
                country_subdivision="Example State",
                country_code="DE",
            ),
            contact=SellerContact(contact_point="Sales", telephone="+49 000 000000", email="sales@example.com"),
        ),
        buyer=Buyer(
            name="Buyer Example AG",
            trading_name="Buyer Example",
            identifier=Identifier(value="BUYER-1", scheme_id="0088"),
            legal_registration_identifier=Identifier(value="CHE-000.000.000", scheme_id="0183"),
            vat_identifier="ATU00000000",
            electronic_address=Identifier(value="buyer@example.com", scheme_id="EM"),
            postal_address=BuyerPostalAddress(
                address_line_1="Sample Road 2",
                address_line_2="Unit 3",
                address_line_3="Back office",
                city="Sample Town",
                post_code="1010",
                country_subdivision="Sample Region",
                country_code="AT",
            ),
            contact=BuyerContact(contact_point="Accounts payable", telephone="+43 0 000000", email="ap@example.com"),
        ),
        payee=Payee(
            name="Payee Example Ltd",
            identifier=Identifier(value="PAYEE-1", scheme_id="0088"),
            legal_registration_identifier=Identifier(value="00000000", scheme_id="0002"),
        ),
        seller_tax_representative=SellerTaxRepresentative(
            name="Tax Rep Example SARL",
            vat_identifier="FR00000000000",
            postal_address=TaxRepresentativePostalAddress(
                address_line_1="Rue Exemple 3",
                address_line_2="Bâtiment B",
                address_line_3="Étage 1",
                city="Exempleville",
                post_code="75000",
                country_subdivision="Exemple",
                country_code="FR",
            ),
        ),
        delivery=DeliveryInformation(
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
        payment_instructions=PaymentInstructions(
            payment_means_type_code="58",
            payment_means_text="SEPA credit transfer",
            remittance_information="INV-2026-0001",
            credit_transfers=(
                CreditTransfer(
                    payment_account_identifier=TEST_IBAN,
                    payment_account_name="Seller Example GmbH",
                    payment_service_provider_identifier="EXAMPLEXXXX",
                ),
            ),
            payment_card=PaymentCardInformation(primary_account_number="000000******0000", holder_name="A. Holder"),
            direct_debit=DirectDebit(
                mandate_reference_identifier="MANDATE-1",
                bank_assigned_creditor_identifier="DE98ZZZ09999999999",
                debited_account_identifier=TEST_IBAN,
            ),
        ),
        allowances=(
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
        charges=(
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
        totals=DocumentTotals(
            sum_of_line_net_amounts=Decimal("100.00"),
            sum_of_allowances=Decimal("10.00"),
            sum_of_charges=Decimal("10.00"),
            total_without_vat=Decimal("100.00"),
            total_vat=Decimal("19.00"),
            total_vat_in_accounting_currency=Decimal("210.00"),
            total_with_vat=Decimal("119.00"),
            paid_amount=Decimal("0.00"),
            rounding_amount=Decimal("0.00"),
            amount_due=Decimal("119.00"),
        ),
        vat_breakdown=(
            VatBreakdown(
                taxable_amount=Decimal("100.00"), tax_amount=Decimal("19.00"), category_code="S", rate=Decimal("19")
            ),
            VatBreakdown(
                taxable_amount=Decimal("0.00"),
                tax_amount=Decimal("0.00"),
                category_code="E",
                rate=Decimal("0"),
                exemption_reason="Exempt",
                exemption_reason_code="VATEX-EU-132",
            ),
        ),
        additional_supporting_documents=(
            AdditionalSupportingDocument(
                reference="TIMESHEET-1",
                description="Timesheet",
                external_location="https://example.com/timesheet.pdf",
                attached_document=BinaryObject(
                    content=b"%PDF-1.7\n\x00\xff", mime_code="application/pdf", filename="timesheet.pdf"
                ),
            ),
        ),
        lines=(
            InvoiceLine(
                identifier="1",
                note="Line note",
                object_identifier=Identifier(value="LINE-OBJ-1", scheme_id="AAA"),
                invoiced_quantity=Decimal("2"),
                invoiced_quantity_unit_code="C62",
                net_amount=Decimal("100.00"),
                purchase_order_line_reference="PO-1-10",
                buyer_accounting_reference="ACC-LINE-1",
                period=InvoiceLinePeriod(start_date=datetime.date(2026, 1, 1), end_date=datetime.date(2026, 1, 31)),
                allowances=(
                    InvoiceLineAllowance(
                        amount=Decimal("5.00"),
                        base_amount=Decimal("100.00"),
                        percentage=Decimal("5"),
                        reason="Line discount",
                        reason_code="95",
                    ),
                ),
                charges=(
                    InvoiceLineCharge(
                        amount=Decimal("5.00"),
                        base_amount=Decimal("100.00"),
                        percentage=Decimal("5"),
                        reason="Packing",
                        reason_code="ABL",
                    ),
                ),
                price_details=PriceDetails(
                    item_net_price=Decimal("50.0000"),
                    item_price_discount=Decimal("0.5"),
                    item_gross_price=Decimal("50.5"),
                    base_quantity=Decimal("1"),
                    base_quantity_unit_code="C62",
                ),
                vat_information=LineVatInformation(category_code="S", rate=Decimal("19")),
                item=ItemInformation(
                    name="Widget",
                    description="A synthetic widget",
                    sellers_identifier="SKU-1",
                    buyers_identifier="BUY-SKU-1",
                    standard_identifier=Identifier(value="4000001000029", scheme_id="0160"),
                    classification_identifiers=(
                        ItemClassificationIdentifier(value="43211503", scheme_id="STI", scheme_version_id="19.0501"),
                    ),
                    country_of_origin="DE",
                    attributes=(ItemAttribute(name="Colour", value="Blue"),),
                ),
            ),
        ),
    )


@pytest.fixture
def invoice() -> Invoice:
    """A full synthetic invoice (every business term set)."""
    return full_invoice()


@pytest.fixture
def make_invoice() -> Callable[..., Invoice]:
    """Build a minimal invoice, with keyword changes applied on top."""
    return minimal_invoice


@pytest.fixture
def make_full_invoice() -> Callable[[], Invoice]:
    """Build a new full invoice (every business term set)."""
    return full_invoice
