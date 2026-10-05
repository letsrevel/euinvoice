import enum
import typing as t
from decimal import Decimal

import pydantic
import pytest

from euinvoice.errors import ModelError
from euinvoice.model._base import EuInvoiceModel, bt, bt_id, to_decimal


class _Sample(EuInvoiceModel):
    number: t.Annotated[str, bt("BT-1")]
    seller_name: t.Annotated[str | None, bt("BT-27")] = None
    untagged: int = 0


class _Kind(enum.StrEnum):
    INVOICE = "380"


class _Lax(EuInvoiceModel):
    codes: tuple[str, ...] = ()
    kind: _Kind | None = None
    count: pydantic.StrictInt = 0


class TestEuInvoiceModel:
    def test_is_frozen(self) -> None:
        sample = _Sample(number="INV-1")
        with pytest.raises(pydantic.ValidationError, match="frozen"):
            sample.number = "INV-2"  # type: ignore[misc]  # assigning to a frozen field is the point

    def test_forbids_unknown_fields(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="extra"):
            _Sample.model_validate({"number": "INV-1", "nope": 1})

    def test_is_hashable_and_comparable(self) -> None:
        assert _Sample(number="INV-1") == _Sample(number="INV-1")
        assert hash(_Sample(number="INV-1")) == hash(_Sample(number="INV-1"))
        assert _Sample(number="INV-1") != _Sample(number="INV-2")

    def test_python_input_fills_tuple_and_str_enum_fields_like_json(self) -> None:
        python = _Lax.model_validate({"codes": ["a", "b"], "kind": "380"})
        json = _Lax.model_validate_json('{"codes": ["a", "b"], "kind": "380"}')
        assert python == json
        assert python.codes == ("a", "b")
        assert python.kind is _Kind.INVOICE

    def test_strict_opt_in_per_field(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            _Lax.model_validate({"count": "3"})


class TestBtMetadata:
    def test_field_carries_its_id_in_json_schema_extra(self) -> None:
        assert _Sample.model_fields["number"].json_schema_extra == {"bt": "BT-1"}

    def test_id_appears_in_the_json_schema(self) -> None:
        props = _Sample.model_json_schema()["properties"]
        assert props["number"]["bt"] == "BT-1"
        assert props["seller_name"]["bt"] == "BT-27"

    def test_bt_id_reads_the_id_back(self) -> None:
        assert bt_id(_Sample, "number") == "BT-1"
        assert bt_id(_Sample, "seller_name") == "BT-27"

    def test_bt_id_is_none_for_untagged_fields(self) -> None:
        assert bt_id(_Sample, "untagged") is None

    def test_bt_id_raises_for_unknown_fields(self) -> None:
        with pytest.raises(KeyError):
            bt_id(_Sample, "missing")

    @pytest.mark.parametrize("ident", ["BT-1", "BT-165", "BG-0", "BG-32"])
    def test_accepts_bt_and_bg_ids(self, ident: str) -> None:
        assert bt(ident).json_schema_extra == {"bt": ident}

    @pytest.mark.parametrize("ident", ["", "BT31", "bt-31", "BT-", "BX-1", "BT-31 ", "BT-01"])
    def test_rejects_malformed_ids(self, ident: str) -> None:
        with pytest.raises(ValueError, match="BT-<n> or BG-<n>"):
            bt(ident)


class TestToDecimal:
    def test_passes_decimals_through(self) -> None:
        value = Decimal("1.230")
        assert to_decimal(value) is value

    def test_converts_int_exactly(self) -> None:
        assert to_decimal(10**30) == Decimal("1000000000000000000000000000000")

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("19.99", Decimal("19.99")),
            ("-0.5", Decimal("-0.5")),
            ("+7", Decimal("7")),
            (".5", Decimal("0.5")),
            ("5.", Decimal("5")),
            (" 1.50\n", Decimal("1.50")),
        ],
    )
    def test_converts_xsd_decimal_strings(self, raw: str, expected: Decimal) -> None:
        result = to_decimal(raw)
        assert result == expected
        assert result.as_tuple() == expected.as_tuple()

    @pytest.mark.parametrize(
        "raw", ["1e3", "1E-2", "NaN", "Infinity", "-inf", "1_000", "\u0661", "1,5", "", "abc", "0x10"]
    )
    def test_rejects_strings_outside_the_xsd_decimal_lexical_space(self, raw: str) -> None:
        with pytest.raises(ModelError, match="xs:decimal"):
            to_decimal(raw)

    @pytest.mark.parametrize("raw", [1.5, 0.0, float("nan"), float("inf")])
    def test_rejects_float_with_a_clear_message(self, raw: float) -> None:
        with pytest.raises(ModelError, match=r"float.*Decimal\('1\.10'\)"):
            to_decimal(raw)

    @pytest.mark.parametrize("raw", [True, False])
    def test_rejects_bool(self, raw: bool) -> None:
        with pytest.raises(ModelError, match="bool"):
            to_decimal(raw)

    @pytest.mark.parametrize("raw", [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")])
    def test_rejects_non_finite_decimals(self, raw: Decimal) -> None:
        with pytest.raises(ModelError, match="finite"):
            to_decimal(raw)

    @pytest.mark.parametrize("raw", [None, b"1", [1], object()])
    def test_rejects_other_types(self, raw: object) -> None:
        with pytest.raises(ModelError, match="Decimal"):
            to_decimal(raw)
