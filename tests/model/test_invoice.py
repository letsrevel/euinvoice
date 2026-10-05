"""The Invoice root: immutability, value semantics, cardinalities, Decimal-only boundaries, JSON round-trip."""

import datetime
import typing as t
from collections.abc import Callable
from decimal import Decimal

import pydantic
import pytest

from euinvoice.model import (
    BT_INDEX,
    Buyer,
    BuyerPostalAddress,
    DeliverToAddress,
    DeliveryInformation,
    DocumentTotals,
    Identifier,
    Invoice,
    InvoiceDraft,
    InvoiceLine,
    InvoiceNote,
    LineDraft,
    Seller,
    SellerPostalAddress,
    VatBreakdown,
)
from euinvoice.model._base import bt_id
from euinvoice.model.bt_index import build_index
from euinvoice.model.codes import UNTDID_1001_INVOICE_TYPE_UBL, DocumentType

MakeInvoice = Callable[..., Invoice]


class TestValueSemantics:
    def test_is_frozen_down_to_the_leaves(self, invoice: Invoice) -> None:
        with pytest.raises(pydantic.ValidationError, match="frozen"):
            invoice.number = "X"  # type: ignore[misc]  # assigning to a frozen field is the point
        with pytest.raises(pydantic.ValidationError, match="frozen"):
            invoice.seller.postal_address.city = "X"  # type: ignore[misc]  # same, nested
        assert isinstance(invoice.lines, tuple)

    def test_equal_invoices_compare_and_hash_equal(self, invoice: Invoice, make_full_invoice: MakeInvoice) -> None:
        other = make_full_invoice()
        assert other is not invoice
        assert invoice == other
        assert hash(invoice) == hash(other)
        assert len({invoice, other}) == 1

    def test_a_changed_term_makes_a_different_invoice(self, invoice: Invoice) -> None:
        changed = invoice.model_copy(update={"number": "INV-2"})
        assert changed != invoice
        assert invoice.number == "INV-2026-0001"

    def test_unknown_fields_are_refused(self, make_invoice: MakeInvoice) -> None:
        with pytest.raises(pydantic.ValidationError, match="extra"):
            make_invoice(nickname="x")


class TestJsonRoundTrip:
    def test_full_invoice_round_trips_exactly(self, invoice: Invoice) -> None:
        assert Invoice.model_validate_json(invoice.model_dump_json()) == invoice

    def test_python_dump_round_trips(self, invoice: Invoice) -> None:
        assert Invoice.model_validate(invoice.model_dump()) == invoice

    def test_numbers_are_fixed_point_strings_in_json(self, invoice: Invoice) -> None:
        text = invoice.model_dump_json()
        assert '"item_net_price":"50.0000"' in text
        assert '"amount_due":"119.00"' in text

    def test_json_schema_carries_the_ids(self) -> None:
        schema = Invoice.model_json_schema()
        assert schema["properties"]["number"]["bt"] == "BT-1"
        assert schema["properties"]["lines"]["bt"] == "BG-25"
        assert schema["$defs"]["Seller"]["properties"]["vat_identifier"]["bt"] == "BT-31"


class TestDocumentType:
    def test_bt3_388_regression_constructs_and_round_trips(self, make_invoice: MakeInvoice) -> None:
        # 388 is valid for CEN BR-CL-01 (and Peppol P0100) but is not a DocumentType member.
        assert "388" not in {member.value for member in DocumentType}
        assert "388" in UNTDID_1001_INVOICE_TYPE_UBL
        invoice = make_invoice(type_code="388")
        assert invoice.type_code == "388"
        assert Invoice.model_validate_json(invoice.model_dump_json()) == invoice

    def test_credit_note_uses_the_same_model(self, make_invoice: MakeInvoice) -> None:
        assert make_invoice(type_code=DocumentType.CREDIT_NOTE).type_code == "381"

    def test_unknown_type_code_is_refused(self, make_invoice: MakeInvoice) -> None:
        with pytest.raises(pydantic.ValidationError, match="BR-CL-01"):
            make_invoice(type_code="999")


class TestCardinalities:
    def test_mandatory_term_is_required(self, make_invoice: MakeInvoice) -> None:
        data = make_invoice().model_dump()
        del data["number"]
        with pytest.raises(pydantic.ValidationError, match="number"):
            Invoice.model_validate(data)

    def test_optional_term_defaults_to_none(self, make_invoice: MakeInvoice) -> None:
        invoice = make_invoice()
        assert invoice.payee is None
        assert invoice.seller.contact is None

    def test_repeated_term_defaults_to_empty_tuple_and_takes_a_list(self, make_invoice: MakeInvoice) -> None:
        assert make_invoice().notes == ()
        notes = make_invoice(notes=[InvoiceNote(note="a"), InvoiceNote(subject_code="AAI")]).notes
        assert notes == (InvoiceNote(note="a"), InvoiceNote(subject_code="AAI"))

    def test_at_least_one_line(self, make_invoice: MakeInvoice) -> None:
        with pytest.raises(pydantic.ValidationError, match="BR-16"):
            make_invoice(lines=())

    def test_at_least_one_vat_breakdown(self, make_invoice: MakeInvoice) -> None:
        with pytest.raises(pydantic.ValidationError, match="BR-CO-18"):
            make_invoice(vat_breakdown=[])

    def test_mandatory_text_must_not_be_blank(self, make_invoice: MakeInvoice) -> None:
        with pytest.raises(pydantic.ValidationError, match="must not be empty"):
            make_invoice(number="  ")

    def test_minimal_invoice_holds_only_the_mandatory_terms(self, make_invoice: MakeInvoice) -> None:
        invoice = make_invoice()
        assert invoice.issue_date == datetime.date(2026, 1, 15)
        assert invoice.payment_instructions is None
        assert invoice.delivery is None


class TestDecimalOnly:
    def test_float_amount_is_refused(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="float is not accepted"):
            DocumentTotals(
                sum_of_line_net_amounts=100.0,  # type: ignore[arg-type]  # refusing float is the point
                total_without_vat=Decimal("100"),
                total_with_vat=Decimal("100"),
                amount_due=Decimal("100"),
            )

    def test_float_rate_is_refused(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="float is not accepted"):
            VatBreakdown(
                taxable_amount=Decimal("1"),
                tax_amount=Decimal("0"),
                category_code="S",
                rate=19.0,  # type: ignore[arg-type]  # refusing float is the point
            )

    def test_amount_with_three_decimals_is_refused(self, make_invoice: MakeInvoice) -> None:
        line = make_invoice().lines[0].model_dump()
        line["net_amount"] = "100.001"
        with pytest.raises(pydantic.ValidationError, match="BR-DEC"):
            InvoiceLine.model_validate(line)

    def test_strings_are_exact_decimals(self, make_invoice: MakeInvoice) -> None:
        line = make_invoice().lines[0].model_dump()
        line["invoiced_quantity"] = "0.3333333333333333333"
        assert InvoiceLine.model_validate(line).invoiced_quantity == Decimal("0.3333333333333333333")


def _scheme(value: str) -> Identifier:
    return Identifier(value="ID-1", scheme_id=value)


Build = Callable[[MakeInvoice, str], t.Any]
Read = Callable[[t.Any], t.Any]

# (business term, rule, invalid value, padded valid value, stored value, build, read back)
_CODE_CASES: list[tuple[str, str, str, str, str, Build, Read]] = [
    ("BT-5", "BR-CL-04", "EURO", " EUR\n", "EUR", lambda make, v: make(currency_code=v), lambda i: i.currency_code),
    (
        "BT-6",
        "BR-CL-05",
        "XYZ",
        "\tSEK ",
        "SEK",
        lambda make, v: make(vat_accounting_currency_code=v),
        lambda i: i.vat_accounting_currency_code,
    ),
    # "5" is the CII (UNTDID 2475) code; the model stores the semantic UNTDID 2005 code.
    (
        "BT-8",
        "BR-CL-06",
        "5",
        " 35 ",
        "35",
        lambda make, v: make(vat_point_date_code=v),
        lambda i: i.vat_point_date_code,
    ),
    ("BT-21", "BR-CL-08", "XXX", " AAI ", "AAI", lambda _, v: InvoiceNote(subject_code=v), lambda n: n.subject_code),
    (
        "BT-18",
        "BR-CL-07",
        "ZZZZ",
        " AAA ",
        "AAA",
        lambda make, v: make(invoiced_object_identifier=_scheme(v)),
        lambda i: i.invoiced_object_identifier.scheme_id,
    ),
    (
        "BT-30",
        "BR-CL-11",
        "NOPE",
        " 0002 ",
        "0002",
        lambda _, v: Seller(
            name="S", postal_address=SellerPostalAddress(country_code="DE"), legal_registration_identifier=_scheme(v)
        ),
        lambda s: s.legal_registration_identifier.scheme_id,
    ),
    (
        "BT-47",
        "BR-CL-11",
        "NOPE",
        "\n0002",
        "0002",
        lambda _, v: Buyer(
            name="B", postal_address=BuyerPostalAddress(country_code="DE"), legal_registration_identifier=_scheme(v)
        ),
        lambda b: b.legal_registration_identifier.scheme_id,
    ),
    (
        "BT-71",
        "BR-CL-26",
        "NOPE",
        " 0088 ",
        "0088",
        lambda _, v: DeliveryInformation(deliver_to_location_identifier=_scheme(v)),
        lambda d: d.deliver_to_location_identifier.scheme_id,
    ),
]


@pytest.mark.parametrize(
    ("term", "rule", "invalid", "padded", "stored", "build", "read"), _CODE_CASES, ids=[case[0] for case in _CODE_CASES]
)
class TestCodeListRules:
    def test_invalid_value_names_the_rule(
        self,
        make_invoice: MakeInvoice,
        term: str,
        rule: str,
        invalid: str,
        padded: str,
        stored: str,
        build: Build,
        read: Read,
    ) -> None:
        with pytest.raises(pydantic.ValidationError, match=rule):
            build(make_invoice, invalid)

    def test_padded_valid_value_is_stored_stripped(
        self,
        make_invoice: MakeInvoice,
        term: str,
        rule: str,
        invalid: str,
        padded: str,
        stored: str,
        build: Build,
        read: Read,
    ) -> None:
        assert read(build(make_invoice, padded)) == stored


def test_postal_address_classes_are_interchangeable(invoice: Invoice) -> None:
    # Same field names across BG-5/8/12/15, so one address converts into another by value.
    seller_address = invoice.seller.postal_address
    as_buyer = BuyerPostalAddress.model_validate(seller_address.model_dump())
    assert as_buyer.model_dump() == seller_address.model_dump()
    assert DeliverToAddress.model_validate(seller_address.model_dump()).city == seller_address.city


class TestDrafts:
    def test_draft_fields_are_the_invoice_fields_minus_the_derived_ones(self) -> None:
        assert set(Invoice.model_fields) - set(InvoiceDraft.model_fields) == {"totals", "vat_breakdown"}
        assert set(InvoiceDraft.model_fields) <= set(Invoice.model_fields)
        assert set(InvoiceLine.model_fields) - set(LineDraft.model_fields) == {"net_amount"}
        assert set(LineDraft.model_fields) <= set(InvoiceLine.model_fields)

    def test_shared_fields_have_the_same_ids_and_types(self) -> None:
        for draft, final in ((InvoiceDraft, Invoice), (LineDraft, InvoiceLine)):
            for name, field in draft.model_fields.items():
                assert bt_id(draft, name) == bt_id(final, name), name
                if name != "lines":
                    assert field.annotation == final.model_fields[name].annotation, name

    def test_draft_builds_from_an_invoice_without_derived_terms(self, invoice: Invoice) -> None:
        data = invoice.model_dump(exclude={"totals": True, "vat_breakdown": True, "lines": {"__all__": {"net_amount"}}})
        draft = InvoiceDraft.model_validate(data)
        assert draft.lines[0] == LineDraft.model_validate(data["lines"][0])
        assert draft.number == invoice.number

    def test_draft_still_needs_a_line(self, invoice: Invoice) -> None:
        data = invoice.model_dump(exclude={"totals", "vat_breakdown"})
        data["lines"] = []
        with pytest.raises(pydantic.ValidationError, match="BR-16"):
            InvoiceDraft.model_validate(data)

    def test_the_draft_index_has_no_duplicates_and_lacks_only_the_derived_terms(self) -> None:
        derived = {ident for ident, path in BT_INDEX.items() if path.startswith(("totals", "vat_breakdown"))}
        assert set(BT_INDEX) - set(build_index(InvoiceDraft)) == derived | {"BT-131"}


def test_json_mode_dump_validates_back(invoice: Invoice) -> None:
    # Dates come back from ISO strings; attachment bytes need model_validate_json (see BinaryObject).
    without_attachment = invoice.model_copy(update={"additional_supporting_documents": ()})
    assert Invoice.model_validate(without_attachment.model_dump(mode="json")) == without_attachment
