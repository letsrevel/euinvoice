"""What the FPR12 writer refuses instead of dropping or altering (#119; plan §1, #115 decision 5)."""

import datetime
import typing as t
from decimal import Decimal

import pytest

from _fatturapa_write import (
    OPTIONS,
    TEST_IBAN,
    buyer,
    it_invoice,
    it_line,
    italian,
    samples,
    seller,
)
from euinvoice import calc
from euinvoice.errors import ModelError
from euinvoice.model import (
    AdditionalSupportingDocument,
    BuyerContact,
    BuyerPostalAddress,
    CreditTransfer,
    DeliveryInformation,
    DocumentLevelAllowance,
    DocumentLevelCharge,
    Identifier,
    Invoice,
    InvoiceLineAllowance,
    InvoiceLineCharge,
    InvoiceNote,
    ItemAttribute,
    ItemInformation,
    PaymentCardInformation,
    PaymentInstructions,
    PriceDetails,
    ProcessControl,
    SellerContact,
    SellerPostalAddress,
    SellerTaxRepresentative,
    TaxRepresentativePostalAddress,
    VatBreakdown,
)
from euinvoice.model.it import (
    CondizioniPagamento,
    EsigibilitaIVA,
    ItalianPayment,
    ItalianVatSummary,
    ModalitaPagamento,
    Natura,
    TipoDocumento,
)
from euinvoice.syntax.fatturapa import write
from euinvoice.syntax.fatturapa._write_refuse import WRITTEN


def _refused(invoice: Invoice, match: str) -> None:
    with pytest.raises(ModelError, match=match):
        write(invoice, OPTIONS)


UNWRITTEN: t.Final[dict[str, tuple[dict[str, t.Any], str]]] = {
    "BT-7": ({"vat_point_date": datetime.date(2026, 1, 15)}, r"BT-7 \(vat_point_date\)"),
    "BT-10": ({"buyer_reference": "REF"}, r"BT-10 \(buyer_reference\)"),
    "BT-11": ({"project_reference": "P"}, r"BT-11 \(project_reference\)"),
    "BT-14": ({"sales_order_reference": "S"}, r"BT-14 \(sales_order_reference\)"),
    "BT-16": ({"despatch_advice_reference": "D"}, r"BT-16 \(despatch_advice_reference\)"),
    "BT-21": ({"notes": (InvoiceNote(subject_code="AAI", note="x"),)}, r"BT-21 \(notes\[0\]\.subject_code\)"),
    "BT-23": (
        {"process_control": ProcessControl(business_process_type="P1", specification_identifier="urn:x")},
        r"BT-23 \(process_control\.business_process_type\).*: App\. 4\.1 maps no FatturaPA element",
    ),
    "BT-28": ({"seller": seller(trading_name="Brand")}, r"BT-28 \(seller\.trading_name\)"),
    "BT-34": (
        {"seller": seller(electronic_address=Identifier(value="x@example.com", scheme_id="EM"))},
        r"BT-34 \(seller\.electronic_address\)",
    ),
    "BT-41": (
        {"seller": seller(contact=SellerContact(contact_point="Desk"))},
        r"BT-41 \(seller\.contact\.contact_point\)",
    ),
    "BT-49": (
        {"buyer": buyer(electronic_address=Identifier(value="ABCDEF1", scheme_id="0205"))},
        r"BT-49 \(buyer\.electronic_address\) cannot be written in FatturaPA: the SdI routing .* WriterOptions",
    ),
    "BG-9": ({"buyer": buyer(contact=BuyerContact(email="b@example.com"))}, r"BG-9 \(buyer\.contact\)"),
    "BG-11": (
        {
            "seller_tax_representative": SellerTaxRepresentative(
                name="Rep",
                vat_identifier="IT00000000009",
                postal_address=TaxRepresentativePostalAddress(country_code="IT"),
            )
        },
        r"BG-11 \(seller_tax_representative\).*: 1\.3 RappresentanteFiscale has no address",
    ),
    "BG-13": ({"delivery": DeliveryInformation(deliver_to_party_name="X")}, r"BG-13 \(delivery\)"),
    "BG-24": ({"additional_supporting_documents": (AdditionalSupportingDocument(reference="A"),)}, r"BG-24"),
    "BG-18": (
        {
            "payment_instructions": PaymentInstructions(
                payment_means_type_code="48", payment_card=PaymentCardInformation(primary_account_number="1234")
            ),
            "it": italian(payment=ItalianPayment(conditions=CondizioniPagamento.TP02)),
        },
        r"BG-18 \(payment_instructions\.payment_card\)",
    ),
    "BT-85": (
        {
            "payment_instructions": PaymentInstructions(
                payment_means_type_code="58",
                credit_transfers=(CreditTransfer(payment_account_identifier=TEST_IBAN, payment_account_name="N"),),
            ),
            "it": italian(payment=ItalianPayment(conditions=CondizioniPagamento.TP02)),
        },
        r"BT-85 \(payment_instructions\.credit_transfers\[0\]\.payment_account_name\)",
    ),
    "BT-127": ({"lines": (it_line(note="n"),)}, r"BT-127 \(lines\[0\]\.note\)"),
    "BT-154": (
        {"lines": (it_line(item=ItemInformation(name="A", description="B")),)},
        r"BT-154 \(lines\[0\]\.item\.description\) cannot be written in FatturaPA: App\. 4\.1 concatenates",
    ),
    "BG-32": (
        {"lines": (it_line(item=ItemInformation(name="A", attributes=(ItemAttribute(name="N", value="V"),))),)},
        r"BG-32 \(lines\[0\]\.item\.attributes\)",
    ),
    "BG-27": (
        {"lines": (it_line(allowances=(InvoiceLineAllowance(amount=Decimal(1), reason="Promo"),)),)},
        r"BG-27 \(lines\[0\]\.allowances\).*: 2\.2\.1\.10 ScontoMaggiorazione has no place for the reason",
    ),
    "BG-28": (
        {"lines": (it_line(charges=(InvoiceLineCharge(amount=Decimal(1), reason="Fee"),)),)},
        r"BG-28 \(lines\[0\]\.charges\)",
    ),
    "BT-149": (
        {"lines": (it_line(price_details=PriceDetails(item_net_price=Decimal(50), base_quantity=Decimal(1))),)},
        r"BT-149 \(lines\[0\]\.price_details\.base_quantity\)",
    ),
    "BT-162": (
        {
            "seller": seller(
                postal_address=SellerPostalAddress(
                    address_line_1="A", address_line_3="C", city="Roma", post_code="00100", country_code="IT"
                )
            )
        },
        r"BT-162 \(seller\.postal_address\.address_line_3\)",
    ),
}


@pytest.mark.parametrize(("changes", "match"), UNWRITTEN.values(), ids=UNWRITTEN.keys())
def test_terms_without_a_fatturapa_element_are_refused(changes: dict[str, t.Any], match: str) -> None:
    _refused(it_invoice(**changes), match)


def test_vat_accounting_currency_has_no_place() -> None:
    invoice = it_invoice().model_copy(update={"vat_accounting_currency_code": "USD"})
    _refused(invoice, r"BT-6 \(vat_accounting_currency_code\) cannot be written in FatturaPA: FatturaPA has one")


def test_every_unwritten_term_is_named_at_once() -> None:
    invoice = it_invoice(buyer_reference="R", project_reference="P")

    _refused(invoice, r"BT-10 \(buyer_reference\).*; BT-11 \(project_reference\)")


def test_paid_amount_has_no_place() -> None:
    from _fatturapa_write import it_draft

    _refused(calc.complete(it_draft(), paid_amount=Decimal(10)), r"BT-113 \(totals\.paid_amount\)")


def test_written_ids_are_business_terms_or_groups() -> None:
    assert all(i.startswith(("BT-", "BG-")) for i in WRITTEN)


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        (
            {
                "allowances": (
                    DocumentLevelAllowance(
                        amount=Decimal(1), vat_category_code="S", vat_rate=Decimal(22), reason="Promo"
                    ),
                )
            },
            r"BG-20 \(allowances\[0\]\) cannot be written in FatturaPA: only the stamp duty",
        ),
        (
            {
                "charges": (
                    DocumentLevelCharge(amount=Decimal(1), vat_category_code="S", vat_rate=Decimal(22), reason="Fee"),
                )
            },
            r"BG-21 \(charges\[0\]\) cannot be written in FatturaPA: only the stamp duty",
        ),
        (
            {
                "allowances": (
                    DocumentLevelAllowance(
                        amount=Decimal(0), vat_category_code="Z", vat_rate=Decimal(0), reason_code="95"
                    ),
                )
            },
            r"BG-20 \(allowances\[0\]\) cannot be written in FatturaPA: only the stamp",
        ),
        (
            {
                "charges": (
                    DocumentLevelCharge(
                        amount=Decimal(0), vat_category_code="Z", vat_rate=Decimal(0), reason_code="SAE"
                    ),
                ),
                "type_code": "381",
                "it": italian(document_type=TipoDocumento.TD04),
            },
            r"BG-21 \(charges\[0\]\)",
        ),
    ],
    ids=["generic allowance", "generic charge", "allowance 95 on an invoice", "SAE on a credit note"],
)
def test_document_level_allowances_and_charges_other_than_stamp_duty(changes: dict[str, t.Any], match: str) -> None:
    _refused(it_invoice(**changes), match)


def _stamp_duty(amount: str = "0", reason: str | None = None) -> DocumentLevelCharge:
    return DocumentLevelCharge(
        amount=Decimal(amount), vat_category_code="Z", vat_rate=Decimal(0), reason=reason, reason_code="SAE"
    )


def test_stamp_duty_at_most_once() -> None:
    _refused(
        it_invoice(charges=(_stamp_duty(), _stamp_duty())),
        r"BG-21 \(charges\[1\]\) cannot be written in FatturaPA: 2\.1\.1\.6 DatiBollo",
    )


def test_stamp_duty_charged_to_the_buyer_is_refused() -> None:
    line = it_line(category="E", rate="0", nature=Natura.N4)
    _refused(
        it_invoice(line, charges=(_stamp_duty("2"),)),
        r"BG-21 \(charges\[0\]\.amount\) cannot be written in FatturaPA: a stamp duty charged",
    )


def test_stamp_duty_reason_other_than_bollo_is_refused() -> None:
    _refused(it_invoice(charges=(_stamp_duty(reason="Altro"),)), r"BT-104 \(charges\[0\]\.reason\)")


@pytest.mark.parametrize("category", ["O", "L", "M"])
def test_vat_categories_without_natura_are_refused(category: str) -> None:
    rate = None if category == "O" else "7"
    _refused(it_invoice(it_line(category=category, rate=rate)), r"BT-151 \(lines\[0\]\.vat_information")


def test_an_o_breakdown_is_refused() -> None:
    invoice = it_invoice()
    extra = VatBreakdown(taxable_amount=Decimal(0), tax_amount=Decimal(0), category_code="O")
    _refused(
        invoice.model_copy(update={"vat_breakdown": (*invoice.vat_breakdown, extra)}),
        r"BG-23 \(vat_breakdown\[1\]\) cannot be written in FatturaPA: VAT category O",
    )


def _with_group(invoice: Invoice, index: int, **changes: Decimal) -> Invoice:
    groups = list(invoice.vat_breakdown)
    groups[index] = groups[index].model_copy(update=changes)
    return invoice.model_copy(update={"vat_breakdown": tuple(groups)})


def test_breakdown_must_equal_its_lines() -> None:
    invoice = _with_group(it_invoice(), 0, taxable_amount=Decimal("101.00"))
    _refused(
        invoice,
        r"BG-23 \(vat_breakdown\[0\]\).*: BT-116 101.00 differs from the sum of its lines' BT-131, 100.00",
    )


def test_breakdown_split_by_natura_must_have_their_tax() -> None:
    invoice = samples()["TD01 exempt and split payment"].invoice
    index = next(i for i, g in enumerate(invoice.vat_breakdown) if g.category_code == "E")
    _refused(_with_group(invoice, index, tax_amount=Decimal("0.01")), r"BT-117 0.01 differs from the Imposta of its 2")


def test_breakdown_without_lines_must_be_zero() -> None:
    invoice = it_invoice()
    extra = VatBreakdown(taxable_amount=Decimal(5), tax_amount=Decimal(0), category_code="Z", rate=Decimal(0))
    _refused(invoice.model_copy(update={"vat_breakdown": (*invoice.vat_breakdown, extra)}), r"BT-116 5 differs")


def test_lines_without_a_breakdown_are_refused() -> None:
    invoice = it_invoice()
    _refused(invoice.model_copy(update={"vat_breakdown": ()}), r"no VAT BREAKDOWN of category S at rate 22")


@pytest.mark.parametrize(
    "summary",
    [
        ItalianVatSummary(rate=Decimal(10)),
        ItalianVatSummary(rate=Decimal(22), vat_chargeability=EsigibilitaIVA.S),
        ItalianVatSummary(rate=Decimal(22), nature=Natura.N4),
    ],
    ids=["rate without lines", "split payment without category B", "Natura without lines"],
)
def test_orphan_vat_summaries_are_refused(summary: ItalianVatSummary) -> None:
    _refused(it_invoice(it=italian(vat_summaries=(summary,))), r"it\.vat_summaries\[0\] cannot be written")


def test_vat_point_date_code_conflicting_with_a_summary() -> None:
    summary = ItalianVatSummary(rate=Decimal(22), vat_chargeability=EsigibilitaIVA.I)
    invoice = it_invoice(vat_point_date_code="432", it=italian(vat_summaries=(summary,)))
    _refused(invoice, r"BT-8 \(vat_point_date_code\) cannot be written in FatturaPA: it gives EsigibilitaIVA D")


def test_vat_point_date_code_with_only_split_payment() -> None:
    _refused(it_invoice(it_line(category="B"), vat_point_date_code="3"), r"BT-8 .*every DatiRiepilogo is split")


@pytest.mark.parametrize("identifier", ["01", "0", "10000", "A1", "\u0661"])
def test_line_number_must_be_a_canonical_integer(identifier: str) -> None:
    _refused(it_invoice(it_line(identifier)), r"BT-126 \(lines\[0\]\.identifier\)")


def test_price_discount_needs_a_gross_price() -> None:
    line = it_line(price_details=PriceDetails(item_net_price=Decimal(50), item_price_discount=Decimal(1)))
    _refused(it_invoice(line), r"BT-147 .*without a gross price")


def test_zero_price_discount_is_neither_sc_nor_mg() -> None:
    line = it_line(
        price_details=PriceDetails(
            item_net_price=Decimal(50), item_gross_price=Decimal(50), item_price_discount=Decimal(0)
        )
    )
    _refused(it_invoice(line), r"BT-147 .*zero is neither")


def test_negative_quantity_is_refused() -> None:
    _refused(it_invoice(it_line(quantity="-1")), r"BT-129 .*Quantita \(QuantitaType\) is unsigned")


def test_unit_price_beyond_eight_decimals_is_refused() -> None:
    _refused(it_invoice(it_line(price="0.123456789")), r"BT-146 .*at most 8 decimals")


def test_rate_beyond_two_decimals_is_refused() -> None:
    _refused(it_invoice(it_line(rate="7.125")), r"BT-152 .*at most 2 decimals")


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"seller": seller(legal_registration_identifier=Identifier(value="X", scheme_id="0088"))}, r"BT-30 .*0210"),
        ({"seller": seller(vat_identifier="1T00000000001")}, r"BT-31 .*IdPaese"),
        ({"seller": seller(vat_identifier="IT" + "0" * 29)}, r"BT-31 .*1 to 28"),
        ({"seller": seller(vat_identifier="IT")}, r"BT-31 .*1 to 28"),
        ({"buyer": buyer(legal_registration_identifier=Identifier(value="abc", scheme_id="0210"))}, r"BT-47 .*CodiceF"),
        (
            {
                "buyer": buyer(
                    postal_address=BuyerPostalAddress(
                        address_line_1="A", city="London", post_code="SW1A 1AA", country_code="GB"
                    )
                )
            },
            r"BT-53 .*CAP",
        ),
        (
            {
                "buyer": buyer(
                    postal_address=BuyerPostalAddress(
                        address_line_1="A", city="Wien", post_code="10100", country_subdivision="W", country_code="AT"
                    )
                )
            },
            r"BT-54 .*only for an address in Italy",
        ),
        (
            {
                "seller": seller(
                    postal_address=SellerPostalAddress(
                        address_line_1="A",
                        city="Roma",
                        post_code="00100",
                        country_subdivision="Roma",
                        country_code="IT",
                    )
                )
            },
            r"BT-39 .*ProvinciaType",
        ),
        (
            {
                "seller": seller(
                    postal_address=SellerPostalAddress(
                        address_line_1="A",
                        address_line_2="123456789",
                        city="Roma",
                        post_code="00100",
                        country_code="IT",
                    )
                )
            },
            r"BT-36 .*1 to 8",
        ),
        (
            {
                "seller": seller(
                    postal_address=SellerPostalAddress(
                        address_line_1="A", city="Roma", post_code="00100", country_code="1A"
                    )
                )
            },
            r"BT-40 .*NazioneType",
        ),
        ({"seller": seller(contact=SellerContact(telephone="123"))}, r"BT-42 .*5 to 12"),
        ({"seller": seller(contact=SellerContact(email="nobody"))}, r"BT-43 .*EmailContattiType"),
        ({"seller": seller(name="Caffè €uro")}, r"BT-27 .*'€' at position 6"),
        ({"notes": (InvoiceNote(note="a\nb"),)}, r"BT-22 .*without tab or line break"),
        ({"notes": (InvoiceNote(note="x" * 201),)}, r"BT-22 .*1 to 200 characters, got 201"),
        ({"number": "FT-è"}, r"BT-1 .*Basic Latin"),
        ({"number": "F" * 21}, r"BT-1 .*1 to 20"),
        ({"buyer_accounting_reference": "R" * 21}, r"BT-19 "),
        ({"issue_date": datetime.date(1969, 12, 31)}, r"BT-2 .*1970-01-01"),
        ({"currency_code": "EUR"}, None),
    ],
)
def test_values_that_do_not_fit_their_xsd_type_are_refused(changes: dict[str, t.Any], match: str | None) -> None:
    invoice = it_invoice(**changes)
    if match is None:
        write(invoice, OPTIONS)
    else:
        _refused(invoice, match)


def test_amounts_beyond_eleven_integer_digits_are_refused() -> None:
    _refused(it_invoice(it_line(quantity="1", price="100000000000")), r"BT-112 .*at most 11 integer digits")


def _with_payment(**changes: t.Any) -> Invoice:
    payment = ItalianPayment(conditions=CondizioniPagamento.TP02, method=changes.pop("method", None))
    return it_invoice(it=italian(payment=payment), **changes)


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        (
            {
                "payment_instructions": PaymentInstructions(
                    payment_means_type_code="58",
                    credit_transfers=(
                        CreditTransfer(payment_account_identifier=TEST_IBAN),
                        CreditTransfer(payment_account_identifier=TEST_IBAN),
                    ),
                )
            },
            r"BG-17 .*one IBAN",
        ),
        (
            {
                "payment_instructions": PaymentInstructions(
                    payment_means_type_code="58", credit_transfers=(CreditTransfer(payment_account_identifier="12345"),)
                )
            },
            r"BT-84 .*IBANType",
        ),
        (
            {
                "payment_instructions": PaymentInstructions(
                    payment_means_type_code="58",
                    credit_transfers=(
                        CreditTransfer(payment_account_identifier=TEST_IBAN, payment_service_provider_identifier="BIC"),
                    ),
                )
            },
            r"BT-86 .*BICType",
        ),
        (
            {
                "payment_instructions": PaymentInstructions(payment_means_type_code="58"),
                "method": ModalitaPagamento.MP08,
            },
            r"BT-81 .*App\. 5\.6 gives BT-81 58 ModalitaPagamento MP05, but it\.payment\.method is MP08",
        ),
        (
            {
                "payment_instructions": PaymentInstructions(payment_means_type_code="69"),
                "method": ModalitaPagamento.MP01,
            },
            r"BT-81 .*69 no ModalitaPagamento",
        ),
        (
            {
                "payment_instructions": PaymentInstructions(payment_means_type_code="58", remittance_information="è"),
                "method": None,
            },
            r"BT-83 ",
        ),
    ],
)
def test_payment_values_that_cannot_be_written(changes: dict[str, t.Any], match: str) -> None:
    _refused(_with_payment(**changes), match)


def test_preflight_errors_block_write() -> None:
    _refused(it_invoice(it=None), r"FatturaPA pre-flight: EUINVOICE-FATTURAPA-EXTENSION at it")
