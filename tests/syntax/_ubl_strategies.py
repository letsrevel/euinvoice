"""Hypothesis strategy of random model invoices the UBL writer can express, for the reader's round-trip test.

ponytail: modelled on ``cii_invoices`` of ``tests/_strategies.py`` (PR #63, not on main yet); once it lands, build
this on it and keep only the UBL constraints below.

Left out on purpose, each covered by its own example test in ``test_ubl_read.py``: what the UBL writer refuses
(BT-110 missing, BT-111 without BT-6, BT-87 missing, a credit note's BT-9 without BG-16, BT-148 below BT-146) and
the documented normalizations of ``docs/reference/bt-mapping.md`` (BT-148 without BT-147, groups with no term set,
an empty note, a BT-22 that starts like a BT-21 code).
"""

import datetime
import re
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
    VatBreakdown,
)
from euinvoice.model.codes import UNTDID_1001_CREDIT_NOTE_TYPE_UBL
from euinvoice.syntax.ubl._write import is_credit_note

_text = st.text(
    alphabet=st.characters(codec="utf-8", exclude_categories=("Cs", "Cc", "Cn")), min_size=1, max_size=12
).filter(lambda s: s.strip(" \t\r\n") != "")
_LEADING_CODE: t.Final = re.compile(r"#...#", re.S)
_note_text = _text.filter(lambda s: not _LEADING_CODE.match(s))  # would read back as BT-21 + BT-22
_amount = st.decimals(min_value=-(10**6), max_value=10**6, places=2)
_price = st.decimals(min_value=0, max_value=10**6, places=4)
_date = st.dates(min_value=datetime.date(1900, 1, 1), max_value=datetime.date(2999, 12, 31))
_category = st.sampled_from(["S", "Z", "E", "AE", "K", "G", "O", "L", "M"])
_identifier = st.builds(Identifier, value=_text, scheme_id=st.none() | st.just("0088"))
_account = st.sampled_from([TEST_IBAN, "ACCOUNT-1"])


def _dated[P: (InvoicingPeriod, InvoiceLinePeriod)](model: type[P]) -> st.SearchStrategy[P]:
    """A period with at least one date (an empty one reads back as absent)."""
    return st.builds(model, start_date=st.none() | _date, end_date=st.none() | _date).filter(
        lambda p: p.start_date is not None or p.end_date is not None
    )


@st.composite
def _price_details(draw: st.DrawFn) -> PriceDetails:
    net = draw(_price)
    gross = draw(st.none() | st.decimals(min_value=net, max_value=net + 1000, places=4))
    base_quantity = draw(st.none() | _price)
    return PriceDetails(
        item_net_price=net,
        item_gross_price=gross,
        # BT-147 alone, or the one consistent with BT-148 (BT-148 alone gains it: a documented normalization).
        item_price_discount=draw(st.none() | _price) if gross is None else gross - net,
        base_quantity=base_quantity,
        base_quantity_unit_code=None if base_quantity is None else draw(st.none() | st.just("C62")),
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
    period=st.none() | _dated(InvoiceLinePeriod),
    allowances=st.lists(st.builds(InvoiceLineAllowance, amount=_amount, reason=_text), max_size=2).map(tuple),
    charges=st.lists(
        st.builds(InvoiceLineCharge, amount=_amount, base_amount=st.none() | _amount, reason_code=st.just("ABL")),
        max_size=2,
    ).map(tuple),
    price_details=_price_details(),
    vat_information=st.builds(LineVatInformation, category_code=_category, rate=st.none() | _price),
    item=st.builds(ItemInformation, name=_text, description=st.none() | _text),
)

_debit = st.builds(
    DirectDebit,
    mandate_reference_identifier=st.none() | _text,
    bank_assigned_creditor_identifier=st.none() | _text,
    debited_account_identifier=st.none() | _account,
).filter(lambda d: d != DirectDebit())

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
    payment_card=st.none() | st.builds(PaymentCardInformation, primary_account_number=_text),
    direct_debit=st.none() | _debit,
)

_delivery = st.builds(
    DeliveryInformation,
    deliver_to_party_name=st.none() | _text,
    deliver_to_location_identifier=st.none() | _identifier,
    actual_delivery_date=st.none() | _date,
    invoicing_period=st.none() | _dated(InvoicingPeriod),
    deliver_to_address=st.none() | st.builds(DeliverToAddress, city=st.none() | _text, country_code=st.just("NL")),
).filter(lambda d: d != DeliveryInformation())

_note = st.one_of(
    st.builds(InvoiceNote, note=_note_text),
    st.builds(InvoiceNote, subject_code=st.just("AAI"), note=st.none() | _text),
)


@st.composite
def ubl_invoices(draw: st.DrawFn) -> Invoice:
    """A random invoice or credit note the UBL writer accepts and the reader must give back unchanged."""
    type_code = draw(st.sampled_from(["380", "384", "389", "751", *sorted(UNTDID_1001_CREDIT_NOTE_TYPE_UBL)]))
    instructions = draw(st.none() | _payment)
    due_date = draw(st.none() | _date)
    if is_credit_note(type_code) and instructions is None:
        due_date = None  # a CreditNote carries BT-9 only in cac:PaymentMeans
    accounting_vat = draw(st.none() | _amount)
    return Invoice(
        number=draw(_text),
        issue_date=draw(_date),
        type_code=type_code,
        currency_code=draw(st.sampled_from(["EUR", "CHF"])),
        vat_accounting_currency_code=None if accounting_vat is None else "SEK",
        vat_point_date=draw(st.none() | _date),
        vat_point_date_code=draw(st.none() | st.sampled_from(["3", "35", "432"])),
        payment_due_date=due_date,
        buyer_reference=draw(st.none() | _text),
        project_reference=draw(st.none() | _text),
        purchase_order_reference=draw(st.none() | _text),
        sales_order_reference=draw(st.none() | _text),
        tender_or_lot_reference=draw(st.none() | _text),
        invoiced_object_identifier=draw(st.none() | st.builds(Identifier, value=_text)),
        payment_terms=draw(st.none() | _text),
        notes=tuple(draw(st.lists(_note, max_size=2))),
        process_control=draw(st.builds(ProcessControl, specification_identifier=_text)),
        preceding_invoice_references=tuple(
            draw(
                st.lists(
                    st.builds(PrecedingInvoiceReference, reference=_text, issue_date=st.none() | _date), max_size=2
                )
            )
        ),
        seller=draw(
            st.builds(
                Seller,
                name=_text,
                identifiers=st.lists(_identifier, max_size=2).map(tuple),
                vat_identifier=st.none() | _text,
                tax_registration_identifier=st.none() | _text,
                postal_address=st.builds(SellerPostalAddress, city=st.none() | _text, country_code=st.just("DE")),
            )
        ),
        buyer=draw(
            st.builds(
                Buyer,
                name=_text,
                identifier=st.none() | _identifier,
                postal_address=st.builds(BuyerPostalAddress, country_code=st.just("FR")),
            )
        ),
        payee=draw(st.none() | st.builds(Payee, name=_text, identifier=st.none() | _identifier)),
        delivery=draw(st.none() | _delivery),
        payment_instructions=instructions,
        allowances=tuple(
            draw(
                st.lists(
                    st.builds(DocumentLevelAllowance, amount=_amount, vat_category_code=_category, reason=_text),
                    max_size=2,
                )
            )
        ),
        charges=tuple(
            draw(
                st.lists(
                    st.builds(
                        DocumentLevelCharge, amount=_amount, vat_category_code=_category, reason_code=st.just("FC")
                    ),
                    max_size=2,
                )
            )
        ),
        totals=draw(
            st.builds(
                DocumentTotals,
                sum_of_line_net_amounts=_amount,
                total_without_vat=_amount,
                total_vat=_amount,
                total_vat_in_accounting_currency=st.just(accounting_vat),
                total_with_vat=_amount,
                amount_due=_amount,
            )
        ),
        vat_breakdown=tuple(
            draw(
                st.lists(
                    st.builds(VatBreakdown, taxable_amount=_amount, tax_amount=_amount, category_code=_category),
                    min_size=1,
                    max_size=3,
                )
            )
        ),
        lines=tuple(draw(st.lists(_line, min_size=1, max_size=3))),
    )
