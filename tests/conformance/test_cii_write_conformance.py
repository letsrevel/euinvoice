"""The CII writer's output against the pinned D16B XSD and the CEN EN 16931 CII Schematron (``make conformance``)."""

import datetime
import typing as t

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from _invoices import TEST_IBAN, full_invoice, line, minimal_invoice, payment, price, rebuild
from euinvoice import _xml
from euinvoice.model import (
    Buyer,
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
    ItemInformation,
    LineVatInformation,
    PaymentCardInformation,
    PaymentInstructions,
    PrecedingInvoiceReference,
    PriceDetails,
    ProcessControl,
    Seller,
    SellerPostalAddress,
    VatBreakdown,
)
from euinvoice.syntax import cii
from euinvoice.validate import schematron, xsd

pytestmark = pytest.mark.conformance

INVOICES: t.Final[dict[str, t.Callable[[], Invoice]]] = {
    "minimal": minimal_invoice,
    "credit-note": lambda: minimal_invoice(type_code="381"),
    "full": full_invoice,
    # BT-7 instead of BT-8 (BR-CO-03 makes them mutually exclusive).
    "full-tax-point-date": lambda: full_invoice(vat_point_date_code=None, vat_point_date=datetime.date(2026, 1, 10)),
    # Two credit transfers: two payment means with the same BT-81 / BT-82 (CII-SR-467, CII-SR-468), each with an
    # account (BR-61), one IBANID and one ProprietaryID.
    "two-transfers": lambda: full_invoice(
        payment_instructions=payment(
            payment_card=None,
            direct_debit=None,
            credit_transfers=(
                CreditTransfer(payment_account_identifier=TEST_IBAN, payment_account_name="Main account"),
                CreditTransfer(
                    payment_account_identifier="ACCOUNT-2", payment_service_provider_identifier="EXAMPLEXXXX"
                ),
            ),
        )
    ),
    # BT-147 without BT-148 on line 1: the writer derives the gross price as BT-146 + BT-147.
    "derived-gross-price": lambda: full_invoice(
        lines=(rebuild(line(), price_details=price(item_gross_price=None)), *full_invoice().lines[1:])
    ),
}


@pytest.mark.parametrize("name", INVOICES)
def test_output_is_xsd_valid(name: str) -> None:
    assert xsd.validate(_xml.parse(cii.write(INVOICES[name]()))) == ()


@pytest.mark.parametrize("name", INVOICES)
def test_output_has_no_cen_findings(name: str) -> None:
    # Not even warnings or information: the invoices are built to satisfy every CEN CII rule.
    assert schematron.run(schematron.CEN_CII, cii.write(INVOICES[name]())) == ()


# XML-compatible characters only (no surrogates, controls or noncharacters such as U+FFFE), and not blank:
# the model rejects whitespace-only mandatory text (normalize-space(.) != '').
_text = st.text(
    alphabet=st.characters(codec="utf-8", exclude_categories=("Cs", "Cc", "Cn")), min_size=1, max_size=12
).filter(lambda s: s.strip(" \t\r\n") != "")
_amount = st.decimals(min_value=-(10**6), max_value=10**6, places=2)
_price = st.decimals(min_value=0, max_value=10**6, places=4)
_date = st.dates(min_value=datetime.date(1900, 1, 1), max_value=datetime.date(2999, 12, 31))
_category = st.sampled_from(["S", "Z", "E", "AE", "K", "G", "O", "L", "M"])
_identifier = st.builds(Identifier, value=_text, scheme_id=st.none() | st.just("0088"))
_account = st.sampled_from([TEST_IBAN, "ACCOUNT-1"])
_period_dates = {"start_date": st.none() | _date, "end_date": st.none() | _date}


@st.composite
def _price_details(draw: st.DrawFn) -> PriceDetails:
    base_quantity = draw(st.none() | _price)
    unit = None if base_quantity is None else draw(st.none() | st.just("C62"))
    return PriceDetails(
        item_net_price=draw(_price),
        # Every combination of BT-148 and BT-147, including BT-147 alone (gross price derived by the writer).
        item_gross_price=draw(st.none() | _price),
        item_price_discount=draw(st.none() | _price),
        base_quantity=base_quantity,
        base_quantity_unit_code=unit,
    )


_line = st.builds(
    InvoiceLine,
    identifier=_text,
    note=st.none() | _text,
    object_identifier=st.none() | st.builds(Identifier, value=_text, scheme_id=st.none() | st.just("AAA")),
    invoiced_quantity=_price,
    invoiced_quantity_unit_code=st.sampled_from(["C62", "HUR", "KGM"]),
    net_amount=_amount,
    purchase_order_line_reference=st.none() | _text,
    buyer_accounting_reference=st.none() | _text,
    period=st.none() | st.builds(InvoiceLinePeriod, **_period_dates),
    allowances=st.lists(st.builds(InvoiceLineAllowance, amount=_amount, reason=_text), max_size=2).map(tuple),
    charges=st.lists(
        st.builds(InvoiceLineCharge, amount=_amount, base_amount=st.none() | _amount, reason_code=st.just("ABL")),
        max_size=2,
    ).map(tuple),
    price_details=_price_details(),
    vat_information=st.builds(LineVatInformation, category_code=_category, rate=st.none() | _price),
    item=st.builds(ItemInformation, name=_text, description=st.none() | _text),
)

_payment = st.builds(
    PaymentInstructions,
    payment_means_type_code=st.sampled_from(["30", "48", "58", "59"]),
    payment_means_text=st.none() | _text,
    remittance_information=st.none() | _text,
    credit_transfers=st.lists(
        st.builds(
            CreditTransfer,
            payment_account_identifier=_account,
            payment_account_name=st.none() | _text,
            payment_service_provider_identifier=st.none() | _text,
        ),
        max_size=3,
    ).map(tuple),
    payment_card=st.none() | st.builds(PaymentCardInformation, primary_account_number=st.none() | _text),
    direct_debit=st.none()
    | st.builds(
        DirectDebit,
        mandate_reference_identifier=st.none() | _text,
        bank_assigned_creditor_identifier=st.none() | _text,
        debited_account_identifier=st.none() | _account,
    ),
)

_delivery = st.builds(
    DeliveryInformation,
    deliver_to_party_name=st.none() | _text,
    deliver_to_location_identifier=st.none() | _identifier,
    actual_delivery_date=st.none() | _date,
    invoicing_period=st.none() | st.builds(InvoicingPeriod, **_period_dates),
    deliver_to_address=st.none() | st.builds(DeliverToAddress, city=st.none() | _text, country_code=st.just("NL")),
)

_invoice = st.builds(
    Invoice,
    number=_text,
    issue_date=_date,
    type_code=st.sampled_from(["380", "381", "384", "389", "751"]),
    currency_code=st.sampled_from(["EUR", "SEK", "CHF"]),
    vat_point_date=st.none() | _date,
    payment_due_date=st.none() | _date,
    vat_point_date_code=st.none() | st.sampled_from(["3", "35", "432"]),
    payment_terms=st.none() | _text,
    notes=st.lists(st.builds(InvoiceNote, note=st.none() | _text), max_size=2).map(tuple),
    process_control=st.builds(ProcessControl, specification_identifier=_text),
    preceding_invoice_references=st.lists(
        st.builds(PrecedingInvoiceReference, reference=_text, issue_date=st.none() | _date), max_size=1
    ).map(tuple),
    seller=st.builds(
        Seller,
        name=_text,
        identifiers=st.lists(_identifier, max_size=2).map(tuple),
        vat_identifier=st.none() | _text,
        postal_address=st.builds(SellerPostalAddress, city=st.none() | _text, country_code=st.just("DE")),
    ),
    buyer=st.builds(
        Buyer,
        name=_text,
        identifier=st.none() | _identifier,
        postal_address=st.builds(BuyerPostalAddress, country_code=st.just("FR")),
    ),
    delivery=st.none() | _delivery,
    payment_instructions=st.none() | _payment,
    allowances=st.lists(
        st.builds(DocumentLevelAllowance, amount=_amount, vat_category_code=_category, reason=_text), max_size=2
    ).map(tuple),
    charges=st.lists(
        st.builds(DocumentLevelCharge, amount=_amount, vat_category_code=_category, reason_code=st.just("FC")),
        max_size=2,
    ).map(tuple),
    totals=st.builds(
        DocumentTotals,
        sum_of_line_net_amounts=_amount,
        total_without_vat=_amount,
        total_vat=st.none() | _amount,
        total_with_vat=_amount,
        amount_due=_amount,
    ),
    vat_breakdown=st.lists(
        st.builds(VatBreakdown, taxable_amount=_amount, tax_amount=_amount, category_code=_category),
        min_size=1,
        max_size=3,
    ).map(tuple),
    lines=st.lists(_line, min_size=1, max_size=3).map(tuple),
)


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(_invoice)
def test_random_invoices_are_xsd_valid(invoice: Invoice) -> None:
    assert xsd.validate(_xml.parse(cii.write(invoice))) == ()
