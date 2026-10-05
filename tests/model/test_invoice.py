"""The Invoice root: immutability, value semantics, cardinalities, Decimal-only boundaries, JSON round-trip."""

import datetime
from collections.abc import Callable
from decimal import Decimal

import pydantic
import pytest

from euinvoice.model import DocumentTotals, Invoice, InvoiceLine, InvoiceNote, VatBreakdown
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
