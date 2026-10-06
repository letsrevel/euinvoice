"""UBL writer output against the official UBL 2.1 XSD and CEN EN 16931 UBL Schematron (``make artifacts``)."""

import datetime
import typing as t
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from _calc_drafts import not_subject_to_vat, with_totals
from _invoices import TEST_IBAN, full_invoice, minimal_invoice, simple_line
from euinvoice import _xml
from euinvoice.model import (
    CreditTransfer,
    DeliveryInformation,
    Identifier,
    Invoice,
    InvoiceLine,
    InvoiceNote,
    InvoicingPeriod,
    ItemInformation,
    LineVatInformation,
    PaymentInstructions,
    PriceDetails,
)
from euinvoice.model.codes import UNTDID_1001_CREDIT_NOTE_TYPE_UBL, UNTDID_1001_INVOICE_TYPE_UBL
from euinvoice.report import Severity
from euinvoice.syntax import cii, ubl
from euinvoice.validation import artifacts, schematron, xsd

pytestmark = pytest.mark.conformance

_BLOCKING = {Severity.FATAL, Severity.ERROR}

INVOICES: t.Final = {
    "minimal-invoice": minimal_invoice,
    "minimal-credit-note": lambda: minimal_invoice(type_code="381"),
    "full-invoice": full_invoice,
    # 381 credit note: BT-9 in cac:PaymentMeans, BT-11 as DocumentTypeCode 50, BT-17 after the ADRs.
    "full-credit-note": lambda: full_invoice(type_code="381"),
    "credit-note-code-81": lambda: full_invoice(type_code="81"),
    # The shared full invoice carries BT-8; this variant carries BT-7 instead (BR-CO-03 forbids both).
    "vat-point-date": lambda: full_invoice(vat_point_date=datetime.date(2026, 1, 10), vat_point_date_code=None),
    # bt-mapping.md "Normalizations": BT-148 without BT-147 writes cbc:Amount = BT-148 - BT-146.
    "gross-equals-net": lambda: _gross_only(Decimal("50"), Decimal("50")),
    "gross-above-net": lambda: _gross_only(Decimal("50"), Decimal("50.75")),
    # bt-mapping.md "Normalizations": BT-110 absent, BT-112 = BT-109 and Σ BT-117 = 0 write cbc:TaxAmount 0.00.
    "bt110-absent-no-vat": lambda: with_totals(not_subject_to_vat(), total_vat=None),
}

NO_VAT_TWINS: t.Final = {
    # CII omits BT-110, its UBL twin writes 0: CEN TOSL110 (example7) and the KoSIT minimal O-category case.
    "cen-example7": (("cen-cii", "examples/CII_example7.xml"), ("cen-ubl", "examples/ubl-tc434-example7.xml")),
    "kosit-01.05-minimal": (
        ("xrechnung-testsuite", "instances/technical-cases/cius/01.05_minimal_test_uncefact.xml"),
        ("xrechnung-testsuite", "instances/technical-cases/cius/01.05_minimal_test_ubl.xml"),
    ),
}


def _gross_only(net: Decimal, gross: Decimal) -> Invoice:
    details = PriceDetails(item_net_price=net, item_gross_price=gross)
    return minimal_invoice(lines=(simple_line(price_details=details),))


@pytest.mark.parametrize("build", [INVOICES["gross-equals-net"], INVOICES["gross-above-net"]], ids=["equal", "above"])
def test_implied_price_discount_satisfies_peppol_price_rules(build: t.Callable[[], Invoice]) -> None:
    # PEPPOL-EN16931-R046: net = gross - allowance; R044: price level allowance only (ChargeIndicator false).
    rule_ids = {f.rule_id for f in schematron.run(schematron.PEPPOL_UBL, ubl.write(build()))}
    assert not rule_ids & {"PEPPOL-EN16931-R044", "PEPPOL-EN16931-R046"}


def test_wrong_price_discount_fires_peppol_r046() -> None:
    # Guard for the test above: a discount that does not match gross - net is caught.
    details = PriceDetails(
        item_net_price=Decimal("50"), item_price_discount=Decimal("1"), item_gross_price=Decimal("50")
    )
    wrong = minimal_invoice(lines=(simple_line(price_details=details),))
    rule_ids = {f.rule_id for f in schematron.run(schematron.PEPPOL_UBL, ubl.write(wrong))}
    assert "PEPPOL-EN16931-R046" in rule_ids


@pytest.mark.parametrize("build", INVOICES.values(), ids=INVOICES.keys())
def test_output_is_schema_valid(build: t.Callable[[], Invoice]) -> None:
    assert xsd.validate(_xml.parse(ubl.write(build()))) == ()


@pytest.mark.parametrize("build", INVOICES.values(), ids=INVOICES.keys())
def test_output_passes_cen_ubl_schematron(build: t.Callable[[], Invoice]) -> None:
    findings = schematron.run(schematron.CEN_UBL, ubl.write(build()))
    assert [f for f in findings if f.severity in _BLOCKING] == []


def _upstream(source: artifacts.SourceName, path: str) -> bytes:
    return (artifacts.source_dir(source) / path).read_bytes()


@pytest.mark.parametrize("pair", NO_VAT_TWINS.values(), ids=NO_VAT_TWINS.keys())
def test_absent_bt110_is_written_like_the_upstream_ubl_twin(
    pair: tuple[tuple[artifacts.SourceName, str], tuple[artifacts.SourceName, str]],
) -> None:
    (cii_source, cii_path), (ubl_source, ubl_path) = pair
    invoice = cii.read(_xml.parse(_upstream(cii_source, cii_path))).invoice
    assert invoice.totals.total_vat is None
    document = ubl.write(invoice)
    twin = ubl.read(_xml.parse(_upstream(ubl_source, ubl_path))).invoice
    assert ubl.read(_xml.parse(document)).invoice.totals.total_vat == twin.totals.total_vat == 0
    rule_ids = {f.rule_id for f in schematron.run(schematron.CEN_UBL, document)}
    assert not rule_ids & {"BR-CO-14", "BR-CO-15"}


# Narrow strategies: XML-safe text (no control, surrogate or unassigned code points, which XML 1.0 forbids).
_TEXT = st.text(st.characters(exclude_categories=("Cc", "Cs", "Cn", "Co")), min_size=1, max_size=20)
_NAME = st.from_regex(r"[A-Za-z][A-Za-z0-9 .-]{0,15}", fullmatch=True)
_AMOUNT = st.decimals(min_value=0, max_value=10**9, places=2, allow_nan=False, allow_infinity=False)
_QUANTITY = st.decimals(min_value=0, max_value=10**6, places=4, allow_nan=False, allow_infinity=False)
_DATE = st.dates(min_value=datetime.date(2000, 1, 1), max_value=datetime.date(2099, 12, 31))
_TYPE_CODE = st.sampled_from(sorted(UNTDID_1001_INVOICE_TYPE_UBL | UNTDID_1001_CREDIT_NOTE_TYPE_UBL))


@st.composite
def _lines(draw: st.DrawFn) -> tuple[InvoiceLine, ...]:
    count = draw(st.integers(min_value=1, max_value=3))
    return tuple(
        InvoiceLine(
            identifier=str(index),
            note=draw(st.none() | _TEXT),
            invoiced_quantity=draw(_QUANTITY),
            invoiced_quantity_unit_code=draw(st.sampled_from(["C62", "HUR", "KGM"])),
            net_amount=draw(_AMOUNT),
            price_details=PriceDetails(item_net_price=draw(_QUANTITY), base_quantity=draw(st.none() | _QUANTITY)),
            vat_information=LineVatInformation(
                category_code=draw(st.sampled_from(["S", "Z", "E"])), rate=Decimal("19")
            ),
            item=ItemInformation(name=draw(_NAME), description=draw(st.none() | _TEXT)),
        )
        for index in range(1, count + 1)
    )


@st.composite
def _invoices(draw: st.DrawFn) -> Invoice:
    type_code = draw(_TYPE_CODE)
    payment = draw(
        st.none()
        | st.builds(
            PaymentInstructions,
            payment_means_type_code=st.sampled_from(["30", "58", "1"]),
            payment_means_text=st.none() | _TEXT,
            credit_transfers=st.lists(
                st.builds(CreditTransfer, payment_account_identifier=st.just(TEST_IBAN)), max_size=2
            ).map(tuple),
        )
    )
    due = draw(st.none() | _DATE)
    if type_code in UNTDID_1001_CREDIT_NOTE_TYPE_UBL and payment is None:
        due = None  # a credit note carries BT-9 only in cac:PaymentMeans (the writer refuses it otherwise)
    return minimal_invoice(
        number=draw(_NAME),
        issue_date=draw(_DATE),
        type_code=type_code,
        payment_due_date=due,
        vat_point_date=draw(st.none() | _DATE),
        buyer_reference=draw(st.none() | _TEXT),
        project_reference=draw(st.none() | _NAME),
        sales_order_reference=draw(st.none() | _NAME),
        tender_or_lot_reference=draw(st.none() | _NAME),
        invoiced_object_identifier=draw(st.none() | st.builds(Identifier, value=_NAME)),
        notes=tuple(
            draw(
                st.lists(
                    st.builds(InvoiceNote, subject_code=st.none() | st.just("AAI"), note=st.none() | _TEXT), max_size=2
                )
            )
        ),
        delivery=draw(
            st.none() | st.builds(DeliveryInformation, invoicing_period=st.builds(InvoicingPeriod, start_date=_DATE))
        ),
        payment_instructions=payment,
        lines=draw(_lines()),
    )


@settings(max_examples=50)
@given(_invoices())
def test_random_invoices_are_schema_valid(document: Invoice) -> None:
    assert xsd.validate(_xml.parse(ubl.write(document))) == ()
