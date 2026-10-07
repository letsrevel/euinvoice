"""What FPR12 cannot express, reported by the pre-flight and refused by write() (#119; plan §1, #133)."""

import datetime
import re
import typing as t
from decimal import Decimal

import pytest

from _fatturapa_write import (
    GOODS,
    TEST_IBAN,
    TRANSMISSION,
    buyer,
    it_draft,
    it_invoice,
    it_line,
    italian,
    samples,
    seller,
    written,
)
from euinvoice import calc
from euinvoice.errors import ModelError
from euinvoice.model import (
    AdditionalSupportingDocument,
    BuyerContact,
    CreditTransfer,
    DeliveryInformation,
    DocumentLevelAllowance,
    DocumentLevelCharge,
    DocumentTotals,
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
from euinvoice.report import Severity
from euinvoice.syntax.fatturapa import preflight, write
from euinvoice.syntax.fatturapa._write_refuse import WRITTEN
from euinvoice.syntax.fatturapa._write_rules import (
    ALLOWANCE_CHARGE,
    CATEGORY,
    PAYMENT,
    SUMMARY,
    TOTALS,
    UNWRITTEN,
)


def _reported(invoice: Invoice, rule: str, location: str, match: str) -> None:
    """``preflight`` reports exactly one error for ``location``, and ``write`` refuses with it."""
    errors = [f for f in preflight(invoice) if f.severity is Severity.ERROR]
    assert [(f.rule_id, f.location) for f in errors if f.location == location] == [(rule, location)], errors
    (found,) = (f for f in errors if f.location == location)
    assert re.search(match, found.message), found.message
    with pytest.raises(ModelError, match=f"FatturaPA pre-flight: .*{rule} at {re.escape(location)}"):
        write(invoice, TRANSMISSION)


UNWRITTEN_TERMS: t.Final[dict[str, tuple[dict[str, t.Any], str, str]]] = {
    "BT-7": ({"vat_point_date": datetime.date(2026, 1, 15)}, "vat_point_date", r"^BT-7 cannot be written"),
    "BT-10": ({"buyer_reference": "REF"}, "buyer_reference", r"^BT-10 cannot be written"),
    "BT-11": ({"project_reference": "P"}, "project_reference", r"^BT-11 "),
    "BT-14": ({"sales_order_reference": "S"}, "sales_order_reference", r"^BT-14 "),
    "BT-16": ({"despatch_advice_reference": "D"}, "despatch_advice_reference", r"^BT-16 "),
    "BT-21": ({"notes": (InvoiceNote(subject_code="AAI", note="x"),)}, "notes[0].subject_code", r"^BT-21 "),
    "BT-23": (
        {"process_control": ProcessControl(business_process_type="P1", specification_identifier="urn:x")},
        "process_control.business_process_type",
        r"^BT-23 cannot be written in FatturaPA: App\. 4\.1 maps no FatturaPA element",
    ),
    "BT-28": ({"seller": seller(trading_name="Brand")}, "seller.trading_name", r"^BT-28 "),
    "BT-34": (
        {"seller": seller(electronic_address=Identifier(value="x@example.com", scheme_id="EM"))},
        "seller.electronic_address",
        r"^BT-34 ",
    ),
    "BT-41": ({"seller": seller(contact=SellerContact(contact_point="Desk"))}, "seller.contact.contact_point", "BT-41"),
    "BT-49": (
        {"buyer": buyer(electronic_address=Identifier(value="ABCDEF1", scheme_id="0205"))},
        "buyer.electronic_address",
        r"the SdI routing .* Transmission.*BR-IT-190/200",
    ),
    "BG-9": ({"buyer": buyer(contact=BuyerContact(email="b@example.com"))}, "buyer.contact", r"^BG-9 "),
    "BG-11": (
        {
            "seller_tax_representative": SellerTaxRepresentative(
                name="Rep",
                vat_identifier="IT00000000009",
                postal_address=TaxRepresentativePostalAddress(country_code="IT"),
            )
        },
        "seller_tax_representative",
        r"1\.3 RappresentanteFiscale has no address",
    ),
    "BG-13": ({"delivery": DeliveryInformation(deliver_to_party_name="X")}, "delivery", r"^BG-13 "),
    "BG-24": (
        {"additional_supporting_documents": (AdditionalSupportingDocument(reference="A"),)},
        "additional_supporting_documents",
        r"^BG-24 ",
    ),
    "BG-18": (
        {
            "payment_instructions": PaymentInstructions(
                payment_means_type_code="48", payment_card=PaymentCardInformation(primary_account_number="1234")
            ),
            "it": italian(payment=ItalianPayment(conditions=CondizioniPagamento.TP02)),
        },
        "payment_instructions.payment_card",
        r"^BG-18 ",
    ),
    "BT-85": (
        {
            "payment_instructions": PaymentInstructions(
                payment_means_type_code="58",
                credit_transfers=(CreditTransfer(payment_account_identifier=TEST_IBAN, payment_account_name="N"),),
            ),
            "it": italian(payment=ItalianPayment(conditions=CondizioniPagamento.TP02)),
        },
        "payment_instructions.credit_transfers[0].payment_account_name",
        r"^BT-85 ",
    ),
    "BT-127": ({"lines": (it_line(note="n"),)}, "lines[0].note", r"^BT-127 "),
    "BT-154": (
        {"lines": (it_line(item=ItemInformation(name="A", description="B")),)},
        "lines[0].item.description",
        r"App\. 4\.1 concatenates",
    ),
    "BG-32": (
        {"lines": (it_line(item=ItemInformation(name="A", attributes=(ItemAttribute(name="N", value="V"),))),)},
        "lines[0].item.attributes",
        r"^BG-32 ",
    ),
    "BG-27": (
        {"lines": (it_line(allowances=(InvoiceLineAllowance(amount=Decimal(1), reason="Promo"),)),)},
        "lines[0].allowances",
        r"no place for the reason \(BT-139/BT-140, BR-42\)",
    ),
    "BG-28": (
        {"lines": (it_line(charges=(InvoiceLineCharge(amount=Decimal(1), reason="Fee"),)),)},
        "lines[0].charges",
        r"BR-44",
    ),
    "BT-149": (
        {"lines": (it_line(price_details=PriceDetails(item_net_price=Decimal(50), base_quantity=Decimal(1))),)},
        "lines[0].price_details.base_quantity",
        r"^BT-149 ",
    ),
    "BT-162": (
        {
            "seller": seller(
                postal_address=SellerPostalAddress(
                    address_line_1="A", address_line_3="C", city="Roma", post_code="00100", country_code="IT"
                )
            )
        },
        "seller.postal_address.address_line_3",
        r"^BT-162 ",
    ),
    "BT-30 scheme": (
        {"seller": seller(legal_registration_identifier=Identifier(value="X", scheme_id="0088"))},
        "seller.legal_registration_identifier",
        r"^BT-30 .*scheme 0210",
    ),
    "BT-147 without BT-148": (
        {"lines": (it_line(price_details=PriceDetails(item_net_price=Decimal(50), item_price_discount=Decimal(1))),)},
        "lines[0].price_details.item_price_discount",
        r"^BT-147 .*without a gross price",
    ),
    "BG-17 twice": (
        {
            "payment_instructions": PaymentInstructions(
                payment_means_type_code="58",
                credit_transfers=(
                    CreditTransfer(payment_account_identifier=TEST_IBAN),
                    CreditTransfer(payment_account_identifier=TEST_IBAN),
                ),
            ),
            "it": italian(payment=ItalianPayment(conditions=CondizioniPagamento.TP02)),
        },
        "payment_instructions.credit_transfers",
        r"^BG-17 .*one IBAN",
    ),
}


@pytest.mark.parametrize(("changes", "location", "match"), UNWRITTEN_TERMS.values(), ids=UNWRITTEN_TERMS.keys())
def test_terms_without_a_fatturapa_element_are_reported(changes: dict[str, t.Any], location: str, match: str) -> None:
    _reported(it_invoice(**changes), UNWRITTEN, location, match)


def test_vat_accounting_currency_has_no_place() -> None:
    invoice = it_invoice().model_copy(update={"vat_accounting_currency_code": "USD"})
    _reported(invoice, UNWRITTEN, "vat_accounting_currency_code", r"FatturaPA has one currency")


def test_every_unwritten_term_is_reported_at_once() -> None:
    errors = [f.location for f in preflight(it_invoice(buyer_reference="R", project_reference="P"))]

    assert errors == ["buyer_reference", "project_reference"]


def test_paid_amount_has_no_place() -> None:
    _reported(calc.complete(it_draft(), paid_amount=Decimal(10)), UNWRITTEN, "totals.paid_amount", r"^BT-113 ")


def test_written_ids_are_business_terms_or_groups() -> None:
    assert all(i.startswith(("BT-", "BG-")) for i in WRITTEN)


def _charge(amount: str = "0", reason: str | None = None, code: str = "SAE") -> DocumentLevelCharge:
    return DocumentLevelCharge(
        amount=Decimal(amount), vat_category_code="Z", vat_rate=Decimal(0), reason=reason, reason_code=code
    )


@pytest.mark.parametrize(
    ("changes", "location", "match"),
    [
        (
            {
                "allowances": (
                    DocumentLevelAllowance(
                        amount=Decimal(1), vat_category_code="S", vat_rate=Decimal(22), reason="Promo"
                    ),
                )
            },
            "allowances[0]",
            r"^BG-20 cannot be written in FatturaPA: only the stamp duty",
        ),
        (
            {
                "charges": (
                    DocumentLevelCharge(amount=Decimal(1), vat_category_code="S", vat_rate=Decimal(22), reason="Fee"),
                )
            },
            "charges[0]",
            r"^BG-21 cannot be written in FatturaPA: only the stamp duty",
        ),
        (
            {
                "allowances": (
                    DocumentLevelAllowance(
                        amount=Decimal(0), vat_category_code="Z", vat_rate=Decimal(0), reason_code="95"
                    ),
                )
            },
            "allowances[0]",
            r"only the stamp",
        ),
        (
            {"charges": (_charge(),), "type_code": "381", "it": italian(document_type=TipoDocumento.TD04)},
            "charges[0]",
            r"only the stamp",
        ),
        ({"charges": (_charge(), _charge())}, "charges[1]", r"DatiBollo occurs at most once"),
        ({"charges": (_charge(reason="Altro"),)}, "charges[0].reason", r"^BT-104: 2\.1\.1\.6 DatiBollo has no reason"),
    ],
    ids=[
        "generic allowance",
        "generic charge",
        "allowance 95 on an invoice",
        "SAE on a credit note",
        "twice",
        "reason",
    ],
)
def test_allowances_and_charges_other_than_a_zero_stamp_duty(
    changes: dict[str, t.Any], location: str, match: str
) -> None:
    _reported(it_invoice(**changes), ALLOWANCE_CHARGE, location, match)


def test_stamp_duty_charged_to_the_buyer_is_reported() -> None:
    line = it_line(category="E", rate="0", nature=Natura.N4)
    _reported(it_invoice(line, charges=(_charge("2"),)), ALLOWANCE_CHARGE, "charges[0].amount", r"charged to the buyer")


@pytest.mark.parametrize("category", ["O", "L", "M"])
def test_vat_categories_without_natura_are_reported(category: str) -> None:
    rate = None if category == "O" else "7"
    _reported(
        it_invoice(it_line(category=category, rate=rate)),
        CATEGORY,
        "lines[0].vat_information.category_code",
        rf"^BT-151 VAT category {category} has no Natura",
    )


def test_an_o_breakdown_is_reported() -> None:
    invoice = it_invoice()
    extra = VatBreakdown(taxable_amount=Decimal(0), tax_amount=Decimal(0), category_code="O")
    invoice = invoice.model_copy(update={"vat_breakdown": (*invoice.vat_breakdown, extra)})
    _reported(invoice, CATEGORY, "vat_breakdown[1].category_code", r"^BT-118 VAT category O")


def _with_group(invoice: Invoice, index: int, **changes: Decimal) -> Invoice:
    groups = list(invoice.vat_breakdown)
    groups[index] = groups[index].model_copy(update=changes)
    return invoice.model_copy(update={"vat_breakdown": tuple(groups)})


def test_breakdown_must_equal_its_lines() -> None:
    invoice = _with_group(it_invoice(), 0, taxable_amount=Decimal("101.00"))
    _reported(invoice, SUMMARY, "vat_breakdown[0].taxable_amount", r"BT-116 101.00 differs from .* BT-131, 100.00")


def test_breakdown_split_by_natura_must_have_their_tax() -> None:
    invoice = samples()["TD01 exempt and split payment"].invoice
    index = next(i for i, g in enumerate(invoice.vat_breakdown) if g.category_code == "E")
    invoice = _with_group(invoice, index, tax_amount=Decimal("0.01"))
    _reported(invoice, SUMMARY, f"vat_breakdown[{index}].tax_amount", r"BT-117 0.01 differs from the Imposta of its 2")


@pytest.mark.parametrize("taxable", ["5", "0"])
def test_breakdown_without_lines_is_reported(taxable: str) -> None:
    invoice = it_invoice()
    extra = VatBreakdown(taxable_amount=Decimal(taxable), tax_amount=Decimal(0), category_code="Z", rate=Decimal(0))
    invoice = invoice.model_copy(update={"vat_breakdown": (*invoice.vat_breakdown, extra)})
    _reported(invoice, SUMMARY, "vat_breakdown[1]", r"BG-23 of category Z has no line")


def test_lines_without_a_breakdown_are_reported() -> None:
    invoice = it_invoice().model_copy(update={"vat_breakdown": ()})
    _reported(invoice, SUMMARY, "vat_breakdown", r"no VAT BREAKDOWN of category S at rate 22")


@pytest.mark.parametrize(
    "summary",
    [
        ItalianVatSummary(rate=Decimal(10)),
        ItalianVatSummary(rate=Decimal(22), vat_chargeability=EsigibilitaIVA.S),
        ItalianVatSummary(rate=Decimal(22), nature=Natura.N4),
    ],
    ids=["rate without lines", "split payment without category B", "Natura without lines"],
)
def test_orphan_vat_summaries_are_reported(summary: ItalianVatSummary) -> None:
    invoice = it_invoice(it=italian(vat_summaries=(summary,)))
    _reported(invoice, SUMMARY, "it.vat_summaries[0]", r"^it\.vat_summaries\[0\] cannot be written")


def test_vat_point_date_code_conflicting_with_a_summary() -> None:
    summary = ItalianVatSummary(rate=Decimal(22), vat_chargeability=EsigibilitaIVA.I)
    invoice = it_invoice(vat_point_date_code="432", it=italian(vat_summaries=(summary,)))
    _reported(invoice, SUMMARY, "vat_point_date_code", r"^BT-8 gives EsigibilitaIVA D")


def test_vat_point_date_code_with_only_split_payment() -> None:
    invoice = it_invoice(it_line(category="B"), vat_point_date_code="3")
    _reported(invoice, SUMMARY, "vat_point_date_code", r"^BT-8: every DatiRiepilogo is split")


@pytest.mark.parametrize(
    ("means", "method", "match"),
    [
        ("58", ModalitaPagamento.MP08, r"App\. 5\.6 gives BT-81 58 ModalitaPagamento MP05, but it\.payment\.method"),
        ("69", ModalitaPagamento.MP01, r"BT-81 69 no ModalitaPagamento"),
    ],
)
def test_bt_81_conflicting_with_the_method(means: str, method: ModalitaPagamento, match: str) -> None:
    invoice = it_invoice(
        it=italian(payment=ItalianPayment(conditions=CondizioniPagamento.TP02, method=method)),
        payment_instructions=PaymentInstructions(payment_means_type_code=means),
    )
    _reported(invoice, PAYMENT, "payment_instructions.payment_means_type_code", match)


def _with_totals(invoice: Invoice, **changes: Decimal | None) -> Invoice:
    totals = DocumentTotals.model_validate({**dict(invoice.totals), **changes})
    return invoice.model_copy(update={"totals": totals})


@pytest.mark.parametrize(
    ("changes", "location", "match"),
    [
        ({"total_with_vat": Decimal("999.00")}, "totals.total_with_vat", r"BT-112 is 999.00, .* = 122.00"),
        ({"amount_due": Decimal("5.00")}, "totals.amount_due", r"BT-115 is 5.00, .*ImportoPagamento.* = 122.00"),
        ({"total_vat": Decimal("1.00")}, "totals.total_vat", r"BT-110 is 1.00, .*Σ Imposta = 22.00"),
        ({"total_vat": None}, "totals.total_vat", r"BT-110 is 0, .*Σ Imposta = 22.00"),
        ({"total_without_vat": Decimal("90.00")}, "totals.total_without_vat", r"BT-109 is 90.00"),
        ({"sum_of_line_net_amounts": Decimal("90.00")}, "totals.sum_of_line_net_amounts", r"BT-106 is 90.00"),
        ({"sum_of_allowances": Decimal("1.00")}, "totals.sum_of_allowances", r"BT-107 is 1.00"),
        ({"sum_of_charges": Decimal("1.00")}, "totals.sum_of_charges", r"BT-108 is 1.00"),
    ],
    ids=["BT-112", "BT-115", "BT-110", "BT-110 missing", "BT-109", "BT-106", "BT-107", "BT-108"],
)
def test_totals_must_agree_with_the_summaries(changes: dict[str, Decimal | None], location: str, match: str) -> None:
    _reported(_with_totals(it_invoice(), **changes), TOTALS, location, match)


def test_amount_due_includes_the_rounding() -> None:
    invoice = calc.complete(it_draft(), rounding_amount=Decimal("0.01"))

    assert [f for f in preflight(invoice) if f.rule_id == TOTALS] == []
    _reported(_with_totals(invoice, amount_due=Decimal("122.00")), TOTALS, "totals.amount_due", r"= 122.01")


def test_totals_are_compared_only_once_the_summaries_are_built() -> None:
    invoice = _with_totals(_with_group(it_invoice(), 0, taxable_amount=Decimal(1)), total_with_vat=Decimal(1))

    assert {f.rule_id for f in preflight(invoice)} == {SUMMARY}


def test_payment_terms_text_is_reported() -> None:
    _reported(it_invoice(payment_terms="30 giorni"), UNWRITTEN, "payment_terms", r"^BT-20 cannot be written .*#133")


def _exempt(*natures: Natura, reason: calc.ExemptionReason, **changes: t.Any) -> Invoice:
    lines = [it_line(str(i), "1", "10", "E", "0", nature=n) for i, n in enumerate(natures, 1)]
    return it_invoice(*lines, exemption_reasons={"E": reason}, **changes)


def _riferimento(invoice: Invoice) -> list[str | None]:
    return [s.findtext("RiferimentoNormativo") for s in written(invoice).findall(f"{GOODS}/DatiRiepilogo")]


def test_exemption_reason_is_written_as_riferimento_normativo() -> None:
    invoice = _exempt(Natura.N4, reason=calc.ExemptionReason(text="Art. 10 DPR 633/72"))

    assert preflight(invoice) == ()
    assert _riferimento(invoice) == ["Art. 10 DPR 633/72"]


def test_exemption_reason_equal_to_the_legal_reference_is_written_once() -> None:
    summary = ItalianVatSummary(rate=Decimal(0), nature=Natura.N4, legal_reference="Art. 10")
    invoice = _exempt(Natura.N4, reason=calc.ExemptionReason(text="Art. 10"), it=italian(vat_summaries=(summary,)))

    assert preflight(invoice) == ()
    assert _riferimento(invoice) == ["Art. 10"]


@pytest.mark.parametrize(
    ("natures", "summaries", "text", "match"),
    [
        ((Natura.N4,), (ItalianVatSummary(rate=Decimal(0), nature=Natura.N4, legal_reference="A"),), "B", "sets"),
        ((Natura.N4, Natura.N2_1), (), "A", "has 2 DatiRiepilogo, not one"),
        ((Natura.N4,), (), "x" * 101, "String100LatinType"),
        ((Natura.N4,), (), "€", "String100LatinType"),
    ],
    ids=["other legal reference", "several summaries", "too long", "not Latin-1"],
)
def test_exemption_reason_that_cannot_be_written(
    natures: tuple[Natura, ...], summaries: tuple[ItalianVatSummary, ...], text: str, match: str
) -> None:
    invoice = _exempt(*natures, reason=calc.ExemptionReason(text=text), it=italian(vat_summaries=summaries))
    _reported(invoice, SUMMARY, "vat_breakdown[0].exemption_reason", rf"^BT-120 cannot be written.*{match}")


@pytest.mark.parametrize(
    ("natures", "category", "code"),
    [
        ((Natura.N4, Natura.N2_1, Natura.N5), "E", "VATEX-EU-132"),
        ((Natura.N3_1, Natura.N3_4), "G", "VATEX-EU-G"),
        ((Natura.N3_2,), "K", "VATEX-EU-IC"),
        ((Natura.N7,), "K", "VATEX-EU-151"),
        ((Natura.N6_1, Natura.N6_9), "AE", "VATEX-EU-AE"),
    ],
)
def test_exemption_reason_code_carried_by_natura(natures: tuple[Natura, ...], category: str, code: str) -> None:
    lines = [it_line(str(i), "1", "10", category, "0", nature=n) for i, n in enumerate(natures, 1)]
    invoice = it_invoice(*lines, exemption_reasons={category: calc.ExemptionReason(code=code)})

    assert preflight(invoice) == ()
    write(invoice, TRANSMISSION)


@pytest.mark.parametrize(
    ("natures", "category", "code"),
    [((Natura.N4,), "E", "VATEX-EU-79-C"), ((Natura.N3_2, Natura.N7), "K", "VATEX-EU-IC")],
    ids=["other code", "two codes in one group"],
)
def test_exemption_reason_code_not_carried_by_natura(natures: tuple[Natura, ...], category: str, code: str) -> None:
    lines = [it_line(str(i), "1", "10", category, "0", nature=n) for i, n in enumerate(natures, 1)]
    invoice = it_invoice(*lines, exemption_reasons={category: calc.ExemptionReason(code=code)})
    _reported(invoice, SUMMARY, "vat_breakdown[0].exemption_reason_code", rf"^BT-121 {code} cannot be written")
