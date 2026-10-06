"""Hypothesis strategies of random model invoices, shared by the writer and reader tests.

:data:`invoices` are random, structurally valid models, not arithmetically consistent ones (``calc`` is not
involved). They draw every field of the model, each optional one both set and unset (``tests/test_strategies.py``
checks it, #89), and may hold what a syntax cannot express; each syntax maps them onto what its writer accepts
before use: :func:`cii_expressible` here, ``ubl_expressible`` in ``tests/syntax/_ubl_strategies.py``. Those filters
are the only places where documented gaps are taken out. The results feed the writers' XSD property tests and the
readers' round-trip property tests; :func:`cii_normalized` is what a CII round trip gives back.
"""

import datetime
import typing as t

from hypothesis import strategies as st

from _invoices import TEST_IBAN, rebuild
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


def text(*, max_codepoint: int = 0x10FFFF, include_characters: str = "") -> st.SearchStrategy[str]:
    """Short non-blank text of XML-compatible characters.

    No surrogates, controls or noncharacters such as U+FFFE, except ``include_characters``; not blank, because
    the model rejects whitespace-only mandatory text (``normalize-space(.) != ''``).
    """
    alphabet = st.characters(
        codec="utf-8",
        max_codepoint=max_codepoint,
        exclude_categories=("Cs", "Cc", "Cn"),
        include_characters=include_characters,
    )
    return st.text(alphabet=alphabet, min_size=1, max_size=12).filter(lambda s: s.strip(" \t\r\n") != "")


def _opt[T](strategy: st.SearchStrategy[T]) -> st.SearchStrategy[T | None]:
    return st.none() | strategy


def _tuples[T](strategy: st.SearchStrategy[T], *, min_size: int = 0, max_size: int = 2) -> st.SearchStrategy[t.Any]:
    return st.lists(strategy, min_size=min_size, max_size=max_size).map(tuple)


_text = text()
# Optional Text admits "" (bt-mapping.md, "Empty text is kept", #79).
_opt_text = st.none() | _text | st.just("")
_amount = st.decimals(min_value=-(10**6), max_value=10**6, places=2)
_price = st.decimals(min_value=0, max_value=10**6, places=4)
_date = st.dates(min_value=datetime.date(1900, 1, 1), max_value=datetime.date(2999, 12, 31))
_category = st.sampled_from(["S", "Z", "E", "AE", "K", "G", "O", "L", "M"])
_account = st.sampled_from([TEST_IBAN, "ACCOUNT-1"])
_period_dates = {"start_date": _opt(_date), "end_date": _opt(_date)}


def _identifier(schemes: list[str], *, required: bool = False) -> st.SearchStrategy[Identifier]:
    """An identifier whose scheme comes from ``schemes``: ICD 0088/0002, EAS 0088/EM, UNTDID 1153 AAA/ABZ."""
    scheme = st.sampled_from(schemes)
    return st.builds(Identifier, value=_text, scheme_id=scheme if required else _opt(scheme))


_icd = _identifier(["0088", "0002"])
_eas = _identifier(["0088", "EM"], required=True)
_object = _identifier(["AAA", "ABZ"])


def _address[A](cls: type[A], country: str) -> st.SearchStrategy[A]:
    """A postal address (BG-5, BG-8, BG-12, BG-15) with every term drawn; the fields share their names."""
    return st.builds(
        cls,
        address_line_1=_opt_text,
        address_line_2=_opt_text,
        address_line_3=_opt_text,
        city=_opt_text,
        post_code=_opt_text,
        country_subdivision=_opt_text,
        country_code=st.just(country),
    )


def _contact[C](cls: type[C]) -> st.SearchStrategy[C | None]:
    """An optional contact (BG-6, BG-9)."""
    return _opt(st.builds(cls, contact_point=_opt_text, telephone=_opt_text, email=_opt_text))


@st.composite
def _with_reason[M](
    draw: st.DrawFn, /, cls: t.Callable[..., M], codes: list[str], **fields: st.SearchStrategy[t.Any]
) -> M:
    """An allowance or charge with a reason, a reason code or both (BR-33, BR-38, BR-42, BR-44)."""
    reason, code = draw(
        st.tuples(_text | st.just(""), _opt(st.sampled_from(codes))) | st.tuples(st.none(), st.sampled_from(codes))
    )
    return cls(**{name: draw(value) for name, value in fields.items()}, reason=reason, reason_code=code)


_allowance_reasons = ["95", "100"]  # UNTDID 5189 (BR-CL-19)
_charge_reasons = ["ABL", "FC"]  # UNTDID 7161 (BR-CL-20)
_rate = _opt(_price)


@st.composite
def _price_details(draw: st.DrawFn) -> PriceDetails:
    base_quantity = draw(_opt(_price))
    unit = None if base_quantity is None else draw(_opt(st.just("C62")))
    return PriceDetails(
        item_net_price=draw(_price),
        # Every combination of BT-148 and BT-147, including BT-147 alone (gross price derived by the writer).
        item_gross_price=draw(_opt(_price)),
        item_price_discount=draw(_opt(_price)),
        base_quantity=base_quantity,
        base_quantity_unit_code=unit,
    )


_item = st.builds(
    ItemInformation,
    name=_text,
    description=_opt_text,
    sellers_identifier=_opt_text,
    buyers_identifier=_opt_text,
    standard_identifier=_opt(_identifier(["0160", "0088"], required=True)),
    classification_identifiers=_tuples(
        st.builds(
            ItemClassificationIdentifier,
            value=_text,
            scheme_id=st.sampled_from(["STI", "CV"]),  # UNTDID 7143 (BR-CL-13)
            scheme_version_id=_opt_text,
        )
    ),
    country_of_origin=_opt(st.sampled_from(["CN", "DE"])),
    attributes=_tuples(st.builds(ItemAttribute, name=_text, value=_text | st.just(""))),
)

_line = st.builds(
    InvoiceLine,
    identifier=_text,
    note=_opt_text,
    object_identifier=_opt(_object),
    invoiced_quantity=_price,
    invoiced_quantity_unit_code=st.sampled_from(["C62", "HUR", "KGM"]),
    net_amount=_amount,
    purchase_order_line_reference=_opt_text,
    buyer_accounting_reference=_opt_text,
    period=_opt(st.builds(InvoiceLinePeriod, **_period_dates)),
    allowances=_tuples(
        _with_reason(
            InvoiceLineAllowance, _allowance_reasons, amount=_amount, base_amount=_opt(_amount), percentage=_rate
        )
    ),
    charges=_tuples(
        _with_reason(InvoiceLineCharge, _charge_reasons, amount=_amount, base_amount=_opt(_amount), percentage=_rate)
    ),
    price_details=_price_details(),
    vat_information=st.builds(LineVatInformation, category_code=_category, rate=_rate),
    item=_item,
)

_payment = st.builds(
    PaymentInstructions,
    payment_means_type_code=st.sampled_from(["30", "48", "58", "59"]),
    payment_means_text=_opt_text,
    remittance_information=_opt_text,
    credit_transfers=_tuples(
        st.builds(
            CreditTransfer,
            payment_account_identifier=_account,
            payment_account_name=_opt_text,
            payment_service_provider_identifier=_opt_text,
        ),
        max_size=3,
    ),
    payment_card=_opt(st.builds(PaymentCardInformation, primary_account_number=_opt_text, holder_name=_opt_text)),
    direct_debit=_opt(
        st.builds(
            DirectDebit,
            mandate_reference_identifier=_opt_text,
            bank_assigned_creditor_identifier=_opt_text,
            debited_account_identifier=_opt(_account),
        )
    ),
)

_delivery = st.builds(
    DeliveryInformation,
    deliver_to_party_name=_opt_text,
    deliver_to_location_identifier=_opt(_icd),
    actual_delivery_date=_opt(_date),
    invoicing_period=_opt(st.builds(InvoicingPeriod, **_period_dates)),
    deliver_to_address=_opt(_address(DeliverToAddress, "NL")),
)

_document = st.builds(
    AdditionalSupportingDocument,
    reference=_text,
    description=_opt_text,
    external_location=_opt(st.just("https://example.com/doc")),
    attached_document=_opt(
        st.builds(
            BinaryObject,
            content=st.binary(max_size=16),
            mime_code=_opt(st.sampled_from(["application/pdf", "text/csv"])),  # BR-CL-24
            filename=_opt(st.just("doc.pdf")),
        )
    ),
)

invoices: t.Final = st.builds(
    Invoice,
    number=_text,
    issue_date=_date,
    type_code=st.sampled_from(["380", "381", "384", "389", "751"]),
    currency_code=st.sampled_from(["EUR", "SEK", "CHF"]),
    # BT-6 may equal BT-5 (UBL refuses that together with BT-111) and BT-111 may come without BT-6 (both refuse).
    vat_accounting_currency_code=_opt(st.sampled_from(["EUR", "SEK", "NOK"])),
    vat_point_date=_opt(_date),
    vat_point_date_code=_opt(st.sampled_from(["3", "35", "432"])),
    payment_due_date=_opt(_date),
    buyer_reference=_opt_text,
    project_reference=_opt_text,
    contract_reference=_opt_text,
    purchase_order_reference=_opt_text | st.just("NA"),
    sales_order_reference=_opt_text,
    receiving_advice_reference=_opt_text,
    despatch_advice_reference=_opt_text,
    tender_or_lot_reference=_opt_text,
    invoiced_object_identifier=_opt(_object),
    buyer_accounting_reference=_opt_text,
    payment_terms=_opt_text,
    notes=_tuples(st.builds(InvoiceNote, subject_code=_opt(st.sampled_from(["AAI", "SUR"])), note=_opt_text)),
    process_control=st.builds(ProcessControl, business_process_type=_opt_text, specification_identifier=_text),
    preceding_invoice_references=_tuples(st.builds(PrecedingInvoiceReference, reference=_text, issue_date=_opt(_date))),
    seller=st.builds(
        Seller,
        name=_text,
        trading_name=_opt_text,
        identifiers=_tuples(_icd),
        legal_registration_identifier=_opt(_icd),
        vat_identifier=_opt_text,
        tax_registration_identifier=_opt_text,
        additional_legal_information=_opt_text,
        electronic_address=_opt(_eas),
        postal_address=_address(SellerPostalAddress, "DE"),
        contact=_contact(SellerContact),
    ),
    buyer=st.builds(
        Buyer,
        name=_text,
        trading_name=_opt_text,
        identifier=_opt(_icd),
        legal_registration_identifier=_opt(_icd),
        vat_identifier=_opt_text,
        electronic_address=_opt(_eas),
        postal_address=_address(BuyerPostalAddress, "FR"),
        contact=_contact(BuyerContact),
    ),
    payee=_opt(st.builds(Payee, name=_text, identifier=_opt(_icd), legal_registration_identifier=_opt(_icd))),
    seller_tax_representative=_opt(
        st.builds(
            SellerTaxRepresentative,
            name=_text,
            vat_identifier=_text,
            postal_address=_address(TaxRepresentativePostalAddress, "AT"),
        )
    ),
    delivery=_opt(_delivery),
    payment_instructions=_opt(_payment),
    allowances=_tuples(
        _with_reason(
            DocumentLevelAllowance,
            _allowance_reasons,
            amount=_amount,
            base_amount=_opt(_amount),
            percentage=_rate,
            vat_category_code=_category,
            vat_rate=_rate,
        )
    ),
    charges=_tuples(
        _with_reason(
            DocumentLevelCharge,
            _charge_reasons,
            amount=_amount,
            base_amount=_opt(_amount),
            percentage=_rate,
            vat_category_code=_category,
            vat_rate=_rate,
        )
    ),
    additional_supporting_documents=_tuples(_document),
    totals=st.builds(
        DocumentTotals,
        sum_of_line_net_amounts=_amount,
        sum_of_allowances=_opt(_amount),
        sum_of_charges=_opt(_amount),
        total_without_vat=_amount,
        total_vat=_opt(_amount),
        total_vat_in_accounting_currency=_opt(_amount),
        total_with_vat=_amount,
        paid_amount=_opt(_amount),
        rounding_amount=_opt(_amount),
        amount_due=_amount,
    ),
    vat_breakdown=_tuples(
        st.builds(
            VatBreakdown,
            taxable_amount=_amount,
            tax_amount=_amount,
            category_code=_category,
            rate=_rate,
            exemption_reason=_opt_text,
            exemption_reason_code=_opt(st.sampled_from(["VATEX-EU-AE", "VATEX-EU-132"])),  # CEF VATEX (BR-CL-22)
        ),
        min_size=1,
        max_size=3,
    ),
    lines=_tuples(_line, min_size=1, max_size=3),
)
"""Random invoices and credit notes (see the module docstring)."""


def cii_expressible(invoice: Invoice) -> Invoice:
    """``invoice`` without what CII cannot carry, each a gap of ``docs/reference/bt-mapping.md``.

    * BT-111 without BT-6 ("CII gap · BT-111 without BT-6") and BT-111 with BT-6 equal to BT-5 ("Gap in both
      syntaxes · BT-6 = BT-5 with BT-111"): two ``ram:TaxTotalAmount`` in one currency, which CEN CII BR-53 and
      BR-CO-15 reject (#71);
    * a second BG-3 ("CII gap · more than one BG-3"): ``ram:InvoiceReferencedDocument`` occurs at most once.

    Args:
        invoice: A random invoice.

    Returns:
        The invoice the CII writer accepts.
    """
    totals = invoice.totals
    if invoice.vat_accounting_currency_code in (None, invoice.currency_code):
        totals = totals.model_validate({**dict(totals), "total_vat_in_accounting_currency": None})
    return Invoice.model_validate(
        {
            **dict(invoice),
            "totals": totals,
            "preceding_invoice_references": invoice.preceding_invoice_references[:1],
        }
    )


def cii_normalized(invoice: Invoice) -> Invoice:
    """What a CII round trip of ``invoice`` returns: the model with the CII writer's normalizations applied.

    See ``docs/reference/bt-mapping.md`` "Normalizations": empty BG-1, BG-13 and BG-19 are not written; BT-29
    identifiers without a scheme come first (``ram:ID`` precedes ``ram:GlobalID`` in the XSD); a BT-147 without
    BT-148 gains BT-148 = BT-146 + BT-147.
    """
    delivery = invoice.delivery
    if delivery is not None and all(v is None for v in dict(delivery).values()):
        delivery = None
    payment_instructions = invoice.payment_instructions
    debit = None if payment_instructions is None else payment_instructions.direct_debit
    if payment_instructions is not None and debit is not None and all(v is None for v in dict(debit).values()):
        payment_instructions = payment_instructions.model_copy(update={"direct_debit": None})
    lines: list[InvoiceLine] = []
    for item in invoice.lines:
        prices = item.price_details
        if prices.item_gross_price is None and prices.item_price_discount is not None:
            gross = prices.item_net_price + prices.item_price_discount
            prices = PriceDetails.model_validate({**dict(prices), "item_gross_price": gross})
        lines.append(rebuild(item, price_details=prices))
    seller = invoice.seller.model_copy(
        update={"identifiers": tuple(sorted(invoice.seller.identifiers, key=lambda i: i.scheme_id is not None))}
    )
    return rebuild(
        invoice,
        notes=tuple(n for n in invoice.notes if (n.note, n.subject_code) != (None, None)),
        delivery=delivery,
        payment_instructions=payment_instructions,
        lines=tuple(lines),
        seller=seller,
    )
