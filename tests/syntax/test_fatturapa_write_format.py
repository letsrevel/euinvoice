"""Lexical forms of the FatturaPA 1.2.3 simple types (XSD patterns), never rounding (#119, D11)."""

import datetime
import re
import typing as t
from collections.abc import Callable
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from euinvoice.errors import ModelError
from euinvoice.syntax.fatturapa._write_format import BASIC, LATIN, amount2, amount8, date, quantity, rate, text

# The XSD 1.2.3 patterns, verbatim.
PATTERNS: t.Final[dict[str, str]] = {
    "amount2": r"[\-]?[0-9]{1,11}\.[0-9]{2}",
    "amount8": r"[\-]?[0-9]{1,11}\.[0-9]{2,8}",
    "quantity": r"[0-9]{1,12}\.[0-9]{2,8}",
    "rate": r"[0-9]{1,3}\.[0-9]{2}",
}
FORMATS: t.Final[dict[str, Callable[[Decimal, str, str], str]]] = {
    "amount2": amount2,
    "amount8": amount8,
    "quantity": quantity,
    "rate": rate,
}


@pytest.mark.parametrize(
    ("kind", "value", "expected"),
    [
        ("amount2", "5", "5.00"),
        ("amount2", "-0", "0.00"),
        ("amount2", "-1.5", "-1.50"),
        ("amount2", "1.500", "1.50"),
        ("amount8", "1E+2", "100.00"),
        ("amount8", "0.12345678", "0.12345678"),
        ("amount8", "0.1234567800", "0.12345678"),
        ("quantity", "3", "3.00"),
        ("quantity", "-0.00", "0.00"),
        ("rate", "22", "22.00"),
        ("rate", "1E+2", "100.00"),
        ("rate", "4.0", "4.00"),
    ],
)
def test_lexical_form(kind: str, value: str, expected: str) -> None:
    assert FORMATS[kind](Decimal(value), "BT-0", "E") == expected


@pytest.mark.parametrize(
    ("kind", "value", "match"),
    [
        ("amount2", "1.005", "at most 2 decimals"),
        ("amount2", "100000000000", "at most 11 integer digits"),
        ("amount8", "0.000000001", "at most 8 decimals"),
        ("quantity", "-1", "unsigned"),
        ("quantity", "1000000000000", "at most 12 integer digits"),
        ("rate", "100.01", "at most 100.00"),
        ("rate", "7.125", "at most 2 decimals"),
        ("rate", "-1", "unsigned"),
    ],
)
def test_values_that_would_need_rounding_or_do_not_fit(kind: str, value: str, match: str) -> None:
    with pytest.raises(ModelError, match=rf"^BT-0 cannot be written in FatturaPA: E .*{match}"):
        FORMATS[kind](Decimal(value), "BT-0", "E")


@given(st.decimals(allow_nan=False, allow_infinity=False, places=8, min_value=-(10**11) + 1, max_value=10**11 - 1))
def test_amount8_is_the_value_in_the_pattern(value: Decimal) -> None:
    formatted = amount8(value, "BT-0", "E")

    assert re.fullmatch(PATTERNS["amount8"], formatted)
    assert Decimal(formatted) == value


@given(st.decimals(allow_nan=False, allow_infinity=False, places=2, min_value=-(10**11) + 1, max_value=10**11 - 1))
def test_amount2_is_the_value_in_the_pattern(value: Decimal) -> None:
    formatted = amount2(value, "BT-0", "E")

    assert re.fullmatch(PATTERNS["amount2"], formatted)
    assert Decimal(formatted) == value


@given(st.decimals(allow_nan=False, allow_infinity=False, places=2, min_value=0, max_value=100))
def test_rate_is_the_value_in_the_pattern(value: Decimal) -> None:
    formatted = rate(value, "BT-0", "E")

    assert re.fullmatch(PATTERNS["rate"], formatted)
    assert Decimal(formatted) == value


@given(st.decimals(allow_nan=False, allow_infinity=False, places=8, min_value=0, max_value=10**12 - 1))
def test_quantity_is_the_value_in_the_pattern(value: Decimal) -> None:
    formatted = quantity(value, "BT-0", "E")

    assert re.fullmatch(PATTERNS["quantity"], formatted)
    assert Decimal(formatted) == value


def test_text_limits() -> None:
    assert text("Caffè", "BT-0", "E", maximum=5) == "Caffè"
    assert text("abc", "BT-0", "E", maximum=3, charset=BASIC) == "abc"
    with pytest.raises(ModelError, match=r"Basic Latin \(U\+0000..U\+007F\) characters"):
        text("è", "BT-0", "E", maximum=3, charset=BASIC)
    with pytest.raises(ModelError, match="Latin-1"):
        text("Ā", "BT-0", "E", maximum=3, charset=LATIN)
    with pytest.raises(ModelError, match="takes 5 to 12 characters, got 4"):
        text("1234", "BT-0", "E", minimum=5, maximum=12)
    with pytest.raises(ModelError, match="tab or line break"):
        text("a\rb", "BT-0", "E", maximum=10)


def test_invoice_date_from_1970() -> None:
    assert date(datetime.date(1970, 1, 1), "BT-2", "Data", invoice_date=True) == "1970-01-01"
    assert date(datetime.date(1969, 12, 31), "BT-26", "Data") == "1969-12-31"
    with pytest.raises(ModelError, match="DataFatturaType"):
        date(datetime.date(1969, 12, 31), "BT-2", "Data", invoice_date=True)
