"""Hypothesis strategies of random model invoices, shared by the writer and reader tests.

:data:`invoices` are random, structurally valid models, not arithmetically consistent ones (``calc`` is not
involved). They may hold what a syntax cannot express; each syntax maps them onto what its writer accepts before
use: :func:`cii_expressible` here, ``ubl_expressible`` in ``tests/syntax/_ubl_strategies.py``. The results feed the
writers' XSD property tests and the readers' round-trip property tests.
"""

import datetime
import typing as t

from hypothesis import strategies as st

from _invoices import TEST_IBAN
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
    Payee,
    PaymentCardInformation,
    PaymentInstructions,
    PrecedingInvoiceReference,
    PriceDetails,
    ProcessControl,
    Seller,
    SellerPostalAddress,
    SellerTaxRepresentative,
    TaxRepresentativePostalAddress,
    VatBreakdown,
)

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

invoices: t.Final = st.builds(
    Invoice,
    number=_text,
    issue_date=_date,
    type_code=st.sampled_from(["380", "381", "384", "389", "751"]),
    currency_code=st.sampled_from(["EUR", "SEK", "CHF"]),
    # BT-6 may equal BT-5 (UBL refuses that together with BT-111) and BT-111 may come without BT-6 (both refuse).
    vat_accounting_currency_code=st.none() | st.sampled_from(["EUR", "SEK", "NOK"]),
    vat_point_date=st.none() | _date,
    payment_due_date=st.none() | _date,
    vat_point_date_code=st.none() | st.sampled_from(["3", "35", "432"]),
    payment_terms=st.none() | _text,
    notes=st.lists(
        st.builds(InvoiceNote, subject_code=st.none() | st.sampled_from(["AAI", "SUR"]), note=st.none() | _text),
        max_size=2,
    ).map(tuple),
    purchase_order_reference=st.none() | _text | st.just("NA"),
    sales_order_reference=st.none() | _text,
    process_control=st.builds(ProcessControl, specification_identifier=_text),
    preceding_invoice_references=st.lists(
        st.builds(PrecedingInvoiceReference, reference=_text, issue_date=st.none() | _date), max_size=1
    ).map(tuple),
    seller=st.builds(
        Seller,
        name=_text,
        identifiers=st.lists(_identifier, max_size=2).map(tuple),
        vat_identifier=st.none() | _text,
        tax_registration_identifier=st.none() | _text,
        postal_address=st.builds(SellerPostalAddress, city=st.none() | _text, country_code=st.just("DE")),
    ),
    payee=st.none() | st.builds(Payee, name=_text, identifier=st.none() | _identifier),
    seller_tax_representative=st.none()
    | st.builds(
        SellerTaxRepresentative,
        name=_text,
        vat_identifier=_text,
        postal_address=st.builds(TaxRepresentativePostalAddress, country_code=st.just("AT")),
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
        total_vat_in_accounting_currency=st.none() | _amount,
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
"""Random invoices and credit notes (see the module docstring)."""


def cii_expressible(invoice: Invoice) -> Invoice:
    """``invoice`` without BT-111 where CII cannot carry it unambiguously.

    The CII writer refuses BT-111 without BT-6 (bt-mapping.md, "CII gap") and BT-111 with BT-6 equal to BT-5: two
    ``ram:TaxTotalAmount`` in one currency, which CEN CII BR-53 and BR-CO-15 reject (#71), as the UBL writer
    refuses it (BR-CO-15).

    Args:
        invoice: A random invoice.

    Returns:
        The invoice the CII writer accepts.
    """
    totals = invoice.totals
    if invoice.vat_accounting_currency_code in (None, invoice.currency_code):
        totals = totals.model_validate({**dict(totals), "total_vat_in_accounting_currency": None})
    return Invoice.model_validate({**dict(invoice), "totals": totals})
