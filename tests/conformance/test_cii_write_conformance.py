"""The CII writer's output against the pinned D16B XSD and the CEN EN 16931 CII Schematron (``make conformance``)."""

import datetime
import typing as t

import pytest
from hypothesis import HealthCheck, given, settings

from _invoices import TEST_IBAN, full_invoice, line, minimal_invoice, payment, price, rebuild
from _strategies import cii_invoices
from euinvoice import _xml
from euinvoice.model import CreditTransfer, Invoice
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


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(cii_invoices)
def test_random_invoices_are_xsd_valid(invoice: Invoice) -> None:
    assert xsd.validate(_xml.parse(cii.write(invoice))) == ()
