"""The CII writer's output against the pinned D16B XSD and the CEN EN 16931 CII Schematron (``make conformance``)."""

import datetime
import sys
import typing as t
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from euinvoice import _xml
from euinvoice.model import (
    Buyer,
    BuyerPostalAddress,
    DocumentLevelAllowance,
    DocumentTotals,
    Identifier,
    Invoice,
    InvoiceLine,
    InvoiceNote,
    ItemInformation,
    LineVatInformation,
    PriceDetails,
    ProcessControl,
    Seller,
    SellerPostalAddress,
    VatBreakdown,
)
from euinvoice.syntax import cii
from euinvoice.validate import schematron, xsd
from euinvoice.validate.report import Severity

sys.path.insert(0, str(Path(__file__).parent.parent / "syntax"))
from _cii_invoices import full_invoice, minimal_invoice

pytestmark = pytest.mark.conformance

BLOCKING: t.Final = {Severity.FATAL, Severity.ERROR}

INVOICES: t.Final[dict[str, t.Callable[[], Invoice]]] = {
    "minimal": minimal_invoice,
    "credit-note": lambda: minimal_invoice(type_code="381"),
    "full": full_invoice,
    # BT-7 instead of BT-8 (BR-CO-03 makes them mutually exclusive).
    "full-tax-point-date": lambda: full_invoice(vat_point_date_code=None, vat_point_date=datetime.date(2026, 1, 10)),
}


@pytest.mark.parametrize("name", INVOICES)
def test_output_is_xsd_valid(name: str) -> None:
    assert xsd.validate(_xml.parse(cii.write(INVOICES[name]()))) == ()


@pytest.mark.parametrize("name", INVOICES)
def test_output_passes_the_cen_rules(name: str) -> None:
    findings = schematron.run(schematron.CEN_CII, cii.write(INVOICES[name]()))
    assert [f for f in findings if f.severity in BLOCKING] == []


_text = st.text(alphabet=st.characters(codec="utf-8", exclude_categories=("Cs", "Cc")), min_size=1, max_size=12)
_amount = st.decimals(min_value=-(10**6), max_value=10**6, places=2)
_price = st.decimals(min_value=0, max_value=10**6, places=4)
_date = st.dates(min_value=datetime.date(1900, 1, 1), max_value=datetime.date(2999, 12, 31))
_category = st.sampled_from(["S", "Z", "E", "AE", "K", "G", "O", "L", "M"])

_line = st.builds(
    InvoiceLine,
    identifier=_text,
    note=st.none() | _text,
    invoiced_quantity=_price,
    invoiced_quantity_unit_code=st.sampled_from(["C62", "HUR", "KGM"]),
    net_amount=_amount,
    price_details=st.builds(
        PriceDetails,
        item_net_price=_price,
        item_gross_price=st.none() | _price,
        base_quantity=st.none() | _price,
    ),
    vat_information=st.builds(LineVatInformation, category_code=_category, rate=st.none() | _price),
    item=st.builds(ItemInformation, name=_text, description=st.none() | _text),
)

_invoice = st.builds(
    Invoice,
    number=_text,
    issue_date=_date,
    type_code=st.sampled_from(["380", "381", "384", "389", "751"]),
    currency_code=st.sampled_from(["EUR", "SEK", "CHF"]),
    payment_due_date=st.none() | _date,
    vat_point_date_code=st.none() | st.sampled_from(["3", "35", "432"]),
    notes=st.lists(st.builds(InvoiceNote, note=st.none() | _text), max_size=2).map(tuple),
    process_control=st.builds(ProcessControl, specification_identifier=_text),
    seller=st.builds(
        Seller,
        name=_text,
        identifiers=st.lists(st.builds(Identifier, value=_text, scheme_id=st.none() | st.just("0088")), max_size=2).map(
            tuple
        ),
        vat_identifier=st.none() | _text,
        postal_address=st.builds(SellerPostalAddress, city=st.none() | _text, country_code=st.just("DE")),
    ),
    buyer=st.builds(Buyer, name=_text, postal_address=st.builds(BuyerPostalAddress, country_code=st.just("FR"))),
    allowances=st.lists(
        st.builds(DocumentLevelAllowance, amount=_amount, vat_category_code=_category, reason=_text), max_size=2
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
