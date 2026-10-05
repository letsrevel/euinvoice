"""EN 16931 data types: code lists (with normalisation), identifiers and schemes, text, dates, binary objects."""

import datetime
import typing as t
from decimal import Decimal

import pydantic
import pytest

from euinvoice.model import (
    BinaryObject,
    Buyer,
    BuyerPostalAddress,
    DocumentLevelAllowance,
    DocumentLevelCharge,
    Identifier,
    InvoiceLineAllowance,
    InvoiceLineCharge,
    ItemClassificationIdentifier,
    ItemInformation,
    PriceDetails,
    Seller,
    SellerPostalAddress,
    VatBreakdown,
)
from euinvoice.model.codes import VatCategory
from euinvoice.model.datatypes import Date, NonBlankText, Text

NBSP = "\N{NO-BREAK SPACE}"  # not XML whitespace: normalize-space keeps it


class _Holder(pydantic.BaseModel):
    text: Text = ""
    non_blank: NonBlankText = "x"
    date: Date = datetime.date(2026, 1, 1)


def _vat(**changes: t.Any) -> VatBreakdown:
    data: dict[str, t.Any] = {
        "taxable_amount": Decimal("100.00"),
        "tax_amount": Decimal("0.00"),
        "category_code": "E",
    }
    data.update(changes)
    return VatBreakdown(**data)


class TestCodes:
    def test_str_enum_member_is_stored_as_its_plain_code(self) -> None:
        vat = _vat(category_code=VatCategory.EXEMPT)
        assert vat.category_code == "E"
        assert type(vat.category_code) is str

    def test_xml_whitespace_is_stripped_like_normalize_space(self) -> None:
        assert _vat(category_code=" \tE\r\n").category_code == "E"

    def test_non_xml_whitespace_is_not_stripped(self) -> None:
        # normalize-space strips only #x20 #x9 #xD #xA; str.strip() would also strip U+00A0.
        with pytest.raises(pydantic.ValidationError, match="BR-CL-17/BR-CL-18"):
            _vat(category_code=NBSP + "E")

    def test_unknown_code_names_the_rule(self) -> None:
        with pytest.raises(pydantic.ValidationError, match=r"'X' is not in the UNTDID 5305 VAT category list"):
            _vat(category_code="X")

    def test_vatex_is_upper_cased_as_br_cl_22_compares_it(self) -> None:
        vat = _vat(exemption_reason_code=" vatex-eu-132 ")
        assert vat.exemption_reason_code == "VATEX-EU-132"

    def test_unknown_vatex_is_refused(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="BR-CL-22"):
            _vat(exemption_reason_code="VATEX-EU-NOPE")

    @pytest.mark.parametrize("country", ["AN", "SS", "DE"])
    def test_countries_accept_the_union_of_the_ubl_and_cii_lists(self, country: str) -> None:
        assert SellerPostalAddress(country_code=country).country_code == country

    def test_unknown_country_is_refused(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="BR-CL-14/BR-CL-15"):
            BuyerPostalAddress(country_code="XX")

    def test_code_must_be_text(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            _vat(category_code=5)


class TestText:
    def test_text_does_not_coerce(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            _Holder(text=b"bytes")  # type: ignore[arg-type]  # refusing bytes is the point
        with pytest.raises(pydantic.ValidationError):
            _Holder(text=3)  # type: ignore[arg-type]  # refusing numbers is the point

    def test_text_may_be_empty(self) -> None:
        assert _Holder(text="").text == ""

    @pytest.mark.parametrize("value", ["", " ", " \t\r\n"])
    def test_non_blank_text_refuses_what_normalize_space_empties(self, value: str) -> None:
        with pytest.raises(pydantic.ValidationError, match="must not be empty"):
            _Holder(non_blank=value)

    def test_non_blank_text_keeps_other_whitespace_and_the_value(self) -> None:
        assert _Holder(non_blank=NBSP).non_blank == NBSP
        assert _Holder(non_blank=" INV-1 ").non_blank == " INV-1 "


class TestDate:
    def test_a_date_is_accepted(self) -> None:
        assert _Holder(date=datetime.date(2026, 2, 1)).date == datetime.date(2026, 2, 1)

    def test_an_iso_string_is_accepted(self) -> None:
        assert _Holder(date="2026-02-01").date == datetime.date(2026, 2, 1)  # type: ignore[arg-type]  # lax on purpose

    @pytest.mark.parametrize(
        "value", [datetime.datetime(2026, 2, 1, 12, 30), datetime.datetime(2026, 2, 1), 0, 1.5, True]
    )
    def test_datetimes_and_numbers_are_refused(self, value: object) -> None:
        with pytest.raises(pydantic.ValidationError, match=r"expected a datetime\.date"):
            _Holder(date=value)  # type: ignore[arg-type]  # refusing these is the point

    def test_json_uses_iso_dates(self) -> None:
        assert _Holder.model_validate_json('{"date": "2026-02-01"}').date == datetime.date(2026, 2, 1)


class TestIdentifierSchemes:
    def test_identifier_without_scheme_where_optional(self) -> None:
        seller = Seller(
            name="S",
            postal_address=SellerPostalAddress(country_code="DE"),
            identifiers=(Identifier(value="X"),),
        )
        assert seller.identifiers == (Identifier(value="X"),)

    def test_icd_scheme_is_checked_and_stored_stripped(self) -> None:
        seller = Seller(
            name="S",
            postal_address=SellerPostalAddress(country_code="DE"),
            legal_registration_identifier=Identifier(value="X", scheme_id=" 0002\n"),
        )
        assert seller.legal_registration_identifier == Identifier(value="X", scheme_id="0002")

    def test_unknown_icd_scheme_is_refused(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="BR-CL-10"):
            Seller(
                name="S",
                postal_address=SellerPostalAddress(country_code="DE"),
                identifiers=(Identifier(value="X", scheme_id="NOPE"),),
            )

    @pytest.mark.parametrize("party", [Seller, Buyer])
    def test_electronic_address_needs_an_eas_scheme(self, party: type[Seller] | type[Buyer]) -> None:
        address = {"country_code": "DE"}
        with pytest.raises(pydantic.ValidationError, match="BR-62/BR-63"):
            party(
                name="P",
                postal_address=address,  # type: ignore[arg-type]  # validated from a dict
                electronic_address=Identifier(value="a@example.com"),
            )
        with pytest.raises(pydantic.ValidationError, match="BR-CL-25"):
            party(
                name="P",
                postal_address=address,  # type: ignore[arg-type]  # validated from a dict
                electronic_address=Identifier(value="a@example.com", scheme_id="NOPE"),
            )

    def test_item_standard_identifier_needs_a_scheme(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="BR-64"):
            ItemInformation(name="I", standard_identifier=Identifier(value="4000001000029"))

    def test_item_classification_needs_a_untdid_7143_scheme(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            ItemClassificationIdentifier(value="43211503")  # type: ignore[call-arg]  # missing scheme is the point
        with pytest.raises(pydantic.ValidationError, match="BR-CL-13"):
            ItemClassificationIdentifier(value="43211503", scheme_id="NOPE")
        assert ItemClassificationIdentifier(value="1", scheme_id=" STI ").scheme_id == "STI"


class TestBinaryObject:
    def test_round_trips_binary_content_through_json_as_base64(self) -> None:
        obj = BinaryObject(content=b"\x00\xff%PDF", mime_code="application/pdf", filename="a.pdf")
        text = obj.model_dump_json()
        assert '"AP8lUERG"' in text
        assert BinaryObject.model_validate_json(text) == obj

    def test_content_must_be_bytes(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            BinaryObject(content="text")  # type: ignore[arg-type]  # refusing str is the point

    def test_mime_code_is_compared_exactly(self) -> None:
        # BR-CL-24 compares @mimeCode without normalize-space.
        with pytest.raises(pydantic.ValidationError, match="BR-CL-24"):
            BinaryObject(content=b"x", mime_code=" application/pdf")
        with pytest.raises(pydantic.ValidationError, match="BR-CL-24"):
            BinaryObject(content=b"x", mime_code="application/zip")

    def test_mime_code_and_filename_are_optional(self) -> None:
        assert BinaryObject(content=b"x").mime_code is None


class TestPriceSigns:
    def test_net_price_must_not_be_negative(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="BR-27"):
            PriceDetails(item_net_price=Decimal("-0.01"))

    def test_gross_price_must_not_be_negative(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="BR-28"):
            PriceDetails(item_net_price=Decimal("1"), item_gross_price=Decimal("-1"))

    def test_zero_prices_and_any_discount_are_allowed(self) -> None:
        price = PriceDetails(
            item_net_price=Decimal("0"), item_gross_price=Decimal("0"), item_price_discount=Decimal("-1")
        )
        assert price.item_net_price == 0

    def test_unit_prices_keep_their_precision(self) -> None:
        assert str(PriceDetails(item_net_price=Decimal("0.00101")).item_net_price) == "0.00101"


_REASONS: list[tuple[type[t.Any], str, dict[str, t.Any]]] = [
    (DocumentLevelAllowance, "BR-33", {"amount": Decimal("1"), "vat_category_code": "S"}),
    (DocumentLevelCharge, "BR-38", {"amount": Decimal("1"), "vat_category_code": "S"}),
    (InvoiceLineAllowance, "BR-42", {"amount": Decimal("1")}),
    (InvoiceLineCharge, "BR-44", {"amount": Decimal("1")}),
]


class TestAllowanceReasons:
    @pytest.mark.parametrize(("model", "rule", "data"), _REASONS)
    def test_reason_or_reason_code_is_required(self, model: type[t.Any], rule: str, data: dict[str, t.Any]) -> None:
        with pytest.raises(pydantic.ValidationError, match=rule):
            model(**data)

    @pytest.mark.parametrize(("model", "rule", "data"), _REASONS)
    def test_either_one_is_enough(self, model: type[t.Any], rule: str, data: dict[str, t.Any]) -> None:
        assert model(**data, reason="Discount").reason == "Discount"
        code = "95" if "Allowance" in model.__name__ else "FC"
        assert model(**data, reason_code=code).reason_code == code

    def test_allowance_and_charge_reason_codes_use_their_own_lists(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="BR-CL-19"):
            InvoiceLineAllowance(amount=Decimal("1"), reason_code="FC")
        with pytest.raises(pydantic.ValidationError, match="BR-CL-20"):
            InvoiceLineCharge(amount=Decimal("1"), reason_code="95")
