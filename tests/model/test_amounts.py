import typing as t
from decimal import MAX_PREC, ROUND_HALF_UP, Decimal, localcontext

import pydantic
import pytest
from hypothesis import given
from hypothesis import strategies as st

from euinvoice.errors import ModelError
from euinvoice.model._base import EuInvoiceModel
from euinvoice.model.amounts import Amount, Percentage, Quantity, UnitPriceAmount, quantize_amount


class _Holder(EuInvoiceModel):
    amount: Amount | None = None
    price: UnitPriceAmount | None = None
    quantity: Quantity | None = None
    rate: Percentage | None = None


_FIELDS = ("amount", "price", "quantity", "rate")

finite_decimals = st.decimals(allow_nan=False, allow_infinity=False)


def _build(field: str, value: object) -> Decimal:
    result = getattr(_Holder.model_validate({field: value}), field)
    assert isinstance(result, Decimal)
    return result


class TestAllTypes:
    @pytest.mark.parametrize("field", _FIELDS)
    @given(value=st.floats())
    def test_float_is_always_rejected(self, field: str, value: float) -> None:
        with pytest.raises(pydantic.ValidationError, match="float"):
            _Holder.model_validate({field: value})

    @pytest.mark.parametrize("field", _FIELDS)
    @pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), "NaN", "inf"])
    def test_non_finite_is_rejected(self, field: str, value: object) -> None:
        with pytest.raises(pydantic.ValidationError):
            _Holder.model_validate({field: value})

    @pytest.mark.parametrize("field", _FIELDS)
    def test_int_is_accepted_exactly(self, field: str) -> None:
        assert _build(field, 42) == Decimal(42)

    @pytest.mark.parametrize("field", _FIELDS)
    def test_xsd_decimal_string_is_accepted(self, field: str) -> None:
        assert _build(field, "12.5") == Decimal("12.5")

    @pytest.mark.parametrize("field", _FIELDS)
    def test_bool_is_rejected(self, field: str) -> None:
        with pytest.raises(pydantic.ValidationError, match="bool"):
            _Holder.model_validate({field: True})

    @pytest.mark.parametrize("field", _FIELDS)
    def test_json_number_with_fraction_is_rejected_as_float(self, field: str) -> None:
        with pytest.raises(pydantic.ValidationError, match="float"):
            _Holder.model_validate_json(f'{{"{field}": 1.5}}')

    @pytest.mark.parametrize("field", _FIELDS)
    def test_json_string_is_accepted(self, field: str) -> None:
        holder = _Holder.model_validate_json(f'{{"{field}": "1.5"}}')
        assert getattr(holder, field) == Decimal("1.5")

    @pytest.mark.parametrize("field", _FIELDS)
    def test_json_round_trip_is_exact(self, field: str) -> None:
        holder = _Holder.model_validate({field: Decimal("1.50")})
        again = _Holder.model_validate_json(holder.model_dump_json())
        assert getattr(again, field).as_tuple() == Decimal("1.50").as_tuple()


class TestUnrestrictedTypes:
    @pytest.mark.parametrize("field", ["price", "quantity", "rate"])
    def test_keeps_full_precision(self, field: str) -> None:
        result = _build(field, Decimal("0.123456789"))
        assert result.as_tuple() == Decimal("0.123456789").as_tuple()

    @pytest.mark.parametrize("field", ["price", "quantity", "rate"])
    @given(value=finite_decimals)
    def test_any_finite_decimal_is_kept_unchanged(self, field: str, value: Decimal) -> None:
        assert _build(field, value).as_tuple() == value.as_tuple()


class TestAmount:
    @pytest.mark.parametrize("raw", ["0", "1", "1.5", "-1.50", "1000000.99", "1E+3"])
    def test_keeps_values_with_at_most_two_decimals_unchanged(self, raw: str) -> None:
        value = Decimal(raw)
        assert _build("amount", value).as_tuple() == value.as_tuple()

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("1.230", "1.23"), ("1.5000", "1.50"), ("0.000", "0.00"), ("-2.100", "-2.10"), ("0E-7", "0.00")],
    )
    def test_trims_surplus_trailing_zeros_losslessly(self, raw: str, expected: str) -> None:
        result = _build("amount", Decimal(raw))
        assert result.as_tuple() == Decimal(expected).as_tuple()
        assert format(result, "f") == expected

    @pytest.mark.parametrize("raw", ["1.234", "0.001", "-0.005", "1E-5"])
    def test_rejects_more_than_two_decimals_instead_of_rounding(self, raw: str) -> None:
        with pytest.raises(pydantic.ValidationError, match=r"BR-DEC.*quantize_amount"):
            _Holder.model_validate({"amount": Decimal(raw)})

    @given(value=finite_decimals)
    def test_accepted_amounts_never_exceed_two_decimals(self, value: Decimal) -> None:
        try:
            result = _build("amount", value)
        except pydantic.ValidationError:
            assert value != quantize_amount(value)
        else:
            assert result == value
            assert len(format(result, "f").partition(".")[2]) <= 2


class TestQuantizeAmount:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1.005", "1.01"),
            ("1.004", "1.00"),
            ("2.675", "2.68"),
            ("-1.005", "-1.01"),
            ("-1.004", "-1.00"),
            ("0.125", "0.13"),
            ("7", "7.00"),
            ("1E+3", "1000.00"),
            ("12345678901234567890123456789.995", "12345678901234567890123456790.00"),
        ],
    )
    def test_rounds_half_up_to_two_decimals(self, raw: str, expected: str) -> None:
        result = quantize_amount(Decimal(raw))
        assert format(result, "f") == expected

    @given(value=finite_decimals)
    def test_has_exactly_two_decimals(self, value: Decimal) -> None:
        assert quantize_amount(value).as_tuple().exponent == -2

    @given(value=finite_decimals)
    def test_is_idempotent(self, value: Decimal) -> None:
        once = quantize_amount(value)
        assert quantize_amount(once) == once
        assert quantize_amount(once).as_tuple() == once.as_tuple()

    @given(value=finite_decimals)
    def test_matches_round_half_up(self, value: Decimal) -> None:
        result = quantize_amount(value)
        with localcontext(prec=MAX_PREC):  # exact arithmetic, whatever the magnitude
            error = abs(result - value)
        assert error <= Decimal("0.005")
        if error == Decimal("0.005"):
            assert abs(result) > abs(value)  # ties go away from zero (ROUND_HALF_UP)

    @given(cents=st.integers(min_value=-(10**12), max_value=10**12))
    def test_ties_round_away_from_zero(self, cents: int) -> None:
        tie = Decimal(cents).scaleb(-2) + Decimal("0.005").copy_sign(Decimal(cents) if cents else Decimal(1))
        expected = tie.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert quantize_amount(tie) == expected
        assert abs(quantize_amount(tie)) > abs(tie)

    @given(value=finite_decimals)
    def test_result_is_a_valid_amount(self, value: Decimal) -> None:
        assert _build("amount", quantize_amount(value)) == quantize_amount(value)

    @pytest.mark.parametrize("raw", [Decimal("NaN"), Decimal("-Infinity")])
    def test_rejects_non_finite(self, raw: Decimal) -> None:
        with pytest.raises(ModelError, match="finite"):
            quantize_amount(raw)

    def test_rejects_float(self) -> None:
        with pytest.raises(ModelError, match="float"):
            quantize_amount(t.cast(Decimal, 1.005))


class TestFixedPointFormatting:
    @pytest.mark.parametrize("field", _FIELDS)
    @given(value=finite_decimals)
    def test_format_f_never_yields_exponent_notation(self, field: str, value: Decimal) -> None:
        try:
            result = _build(field, value)
        except pydantic.ValidationError:
            return
        text = format(result, "f")
        assert "e" not in text.lower()
        assert Decimal(text) == result

    @given(value=finite_decimals)
    def test_quantized_amount_round_trips_through_format_f(self, value: Decimal) -> None:
        amount = quantize_amount(value)
        text = format(amount, "f")
        assert "e" not in text.lower()
        assert _build("amount", text).as_tuple() == amount.as_tuple()
