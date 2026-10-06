"""Model strings are restricted to the XML 1.0 ``Char`` production (issue #57).

Both UBL and CII instances are XML 1.0 documents, so a character outside ``Char`` (W3C XML 1.0 5th
ed. §2.2) can never be written in any syntax and is refused when the model is built.
"""

import re
import typing as t
from decimal import Decimal

import pydantic
import pytest
from hypothesis import given
from hypothesis import strategies as st
from lxml import etree

from euinvoice import _xml
from euinvoice.model import BinaryObject, Identifier, ItemClassificationIdentifier, VatBreakdown
from euinvoice.model.datatypes import NonBlankText, Text


class _Holder(pydantic.BaseModel):
    text: Text = ""
    non_blank: NonBlankText = "x"


def _is_xml_char(char: str) -> bool:
    """The XML 1.0 ``Char`` production, spelled out independently of the code under test."""
    code = ord(char)
    return code in (0x9, 0xA, 0xD) or 0x20 <= code <= 0xD7FF or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF


OFFENDERS: t.Final = [
    pytest.param("\x00", "U+0000", id="NUL"),
    pytest.param("\x01", "U+0001", id="C0"),
    pytest.param("\x0b", "U+000B", id="VT"),
    pytest.param("\x1f", "U+001F", id="US"),
    pytest.param("￾", "U+FFFE", id="FFFE"),
    pytest.param("￿", "U+FFFF", id="FFFF"),
    pytest.param("\ud800", "U+D800", id="lone-high-surrogate"),
    pytest.param("\udfff", "U+DFFF", id="lone-low-surrogate"),
]
ALLOWED_EDGES: t.Final = ["\t", "\n", "\r", " ", "퟿", "", "�", "\U00010000", "\U0010ffff"]


@pytest.mark.parametrize(("char", "code_point"), OFFENDERS)
def test_text_rejects_non_xml_char_naming_code_point_and_index(char: str, code_point: str) -> None:
    with pytest.raises(pydantic.ValidationError, match=rf"{re.escape(code_point)} at index 2 .*XML 1\.0"):
        _Holder(text="ab" + char + "c")


@pytest.mark.parametrize("char", ALLOWED_EDGES)
def test_text_accepts_xml_char_edges(char: str) -> None:
    assert _Holder(text="a" + char).text == "a" + char


def test_first_offender_is_reported() -> None:
    with pytest.raises(pydantic.ValidationError, match=r"U\+0001 at index 1"):
        _Holder(text="a\x01\x00")


@pytest.mark.parametrize(
    ("build", "where"),
    [
        pytest.param(lambda: _Holder(non_blank="x\x00"), "non_blank", id="NonBlankText"),
        pytest.param(
            lambda: VatBreakdown(taxable_amount=Decimal("1.00"), tax_amount=Decimal("0.00"), category_code="E\x00"),
            "category_code",
            id="code",
        ),
        pytest.param(lambda: Identifier(value="1\x00"), "value", id="Identifier.value"),
        pytest.param(lambda: Identifier(value="1", scheme_id="0088\x00"), "scheme_id", id="Identifier.scheme_id"),
        pytest.param(
            lambda: ItemClassificationIdentifier(value="1", scheme_id="STI", scheme_version_id="1\x00"),
            "scheme_version_id",
            id="ItemClassificationIdentifier.scheme_version_id",
        ),
        pytest.param(
            lambda: ItemClassificationIdentifier(value="1", scheme_id="STI\x00"),
            "scheme_id",
            id="ItemClassificationIdentifier.scheme_id",
        ),
        pytest.param(lambda: BinaryObject(content=b"", filename="a\x00.pdf"), "filename", id="BinaryObject.filename"),
        pytest.param(
            lambda: BinaryObject(content=b"", mime_code="application/pdf\x00"),
            "mime_code",
            id="BinaryObject.mime_code",
        ),
    ],
)
def test_every_string_type_rejects_non_xml_chars(build: t.Callable[[], object], where: str) -> None:
    with pytest.raises(pydantic.ValidationError, match=r"U\+0000 at index") as info:
        build()
    assert info.value.errors()[0]["loc"][0] == where


@given(st.text(st.characters(exclude_categories=())))  # the default strategy omits surrogates (Cs)
def test_accepted_iff_every_char_is_xml_1_0(text: str) -> None:
    valid = all(_is_xml_char(c) for c in text)
    try:
        _Holder(text=text)
    except pydantic.ValidationError:
        assert not valid
    else:
        assert valid


@given(st.text())
def test_accepted_text_survives_an_xml_round_trip(text: str) -> None:
    try:
        value = _Holder(text=text).text
    except pydantic.ValidationError:
        return
    element = etree.Element("x", a=value)
    element.text = value
    back = _xml.parse(etree.tostring(element, encoding="UTF-8"))
    assert (back.text or "") == value
    assert back.get("a") == value
