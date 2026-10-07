r"""Lexical forms of the FatturaPA 1.2.3 simple types the writer fills, and the refusal error.

Every type is read from the pinned XSD (``Schema_VFPR12_v1.2.3.xsd``). The writer never rounds, truncates or
transliterates: a value that does not fit is refused with :class:`~euinvoice.errors.ModelError`, whose message
starts with the business term (plan §1, "never silently dropped").

* Text: the ``String<n>Type`` family is ``xs:normalizedString`` restricted to ``\p{IsBasicLatin}`` (U+0000..U+007F,
  e.g. ``String20Type``) or to ``[\p{IsBasicLatin}\p{IsLatin-1Supplement}]`` (U+0000..U+00FF, the ``*LatinType``
  ones), with a length range. ``xs:normalizedString`` replaces tab, line feed and carriage return by spaces before
  validation, so text holding one would not be read back as written; it is refused.
* Decimals: ``Amount2DecimalType`` ``[\-]?[0-9]{1,11}\.[0-9]{2}``, ``Amount8DecimalType``
  ``[\-]?[0-9]{1,11}\.[0-9]{2,8}``, ``QuantitaType`` ``[0-9]{1,12}\.[0-9]{2,8}`` and ``RateType``
  ``[0-9]{1,3}\.[0-9]{2}`` (max 100.00). Missing decimals are padded and surplus trailing zeros trimmed, both
  without changing the value; anything that would need rounding is refused. A zero is written unsigned.
"""

import datetime
import re
import typing as t
from decimal import MAX_PREC, Decimal, localcontext

from lxml import etree

from euinvoice.errors import ModelError

__all__ = [
    "BASIC",
    "LATIN",
    "amount2",
    "amount8",
    "cannot_express",
    "child",
    "date",
    "matching",
    "quantity",
    "rate",
    "text",
]

BASIC: t.Final = r"\x00-\x7f"
r"""``\p{IsBasicLatin}`` as a regular expression character class body."""
LATIN: t.Final = r"\x00-\xff"
r"""``[\p{IsBasicLatin}\p{IsLatin-1Supplement}]`` as a character class body."""

_NORMALIZED: t.Final = r"\t\n\r"
_RATE_MAX: t.Final = Decimal(100)
_EPOCH: t.Final = datetime.date(1970, 1, 1)  # DataFatturaType minInclusive


def cannot_express(term: str, reason: str) -> ModelError:
    """Build the error for a model value FatturaPA has no place for.

    Args:
        term: The business term id(s) or extension path, first in the message (e.g. ``"BT-127"``).
        reason: Why FatturaPA cannot carry it, citing the XSD type or the source row.

    Returns:
        The error to raise.
    """
    return ModelError(f"{term} cannot be written in FatturaPA: {reason}")


def child(parent: etree._Element, tag: str, value: str | None = None) -> etree._Element:
    """Append the unqualified child ``tag`` (the FatturaPA XSD sets no ``elementFormDefault``) with text ``value``.

    Args:
        parent: The parent element.
        tag: The local name.
        value: The text, already in its lexical form, or ``None`` for an element with children.

    Returns:
        The new element.
    """
    new = etree.SubElement(parent, tag)
    new.text = value
    return new


def matching(value: str, pattern: str, term: str, element: str) -> str:
    """Return ``value`` if it matches the XSD ``pattern`` (a Python regular expression with the same meaning).

    Raises:
        ModelError: It does not match.
    """
    if not re.fullmatch(pattern, value):
        raise cannot_express(term, f"{element} must match {pattern}, got {value!r}")
    return value


def text(value: str, term: str, element: str, *, maximum: int, charset: str = LATIN, minimum: int = 1) -> str:
    """Return ``value`` if it fits a FatturaPA string type.

    Args:
        value: The text.
        term: The business term (and model path) it comes from, for the message.
        element: The FatturaPA element and XSD type, for the message (e.g. ``"2.1.1.4 Numero (String20Type)"``).
        maximum: The maximum length in characters.
        charset: :data:`BASIC` or :data:`LATIN`.
        minimum: The minimum length.

    Returns:
        ``value`` unchanged.

    Raises:
        ModelError: ``value`` is too short or too long, or holds a character outside ``charset`` or a tab or line
            break.
    """
    name = "Basic Latin (U+0000..U+007F)" if charset == BASIC else "Basic Latin and Latin-1 (U+0000..U+00FF)"
    if not minimum <= len(value) <= maximum:
        raise cannot_express(term, f"{element} takes {minimum} to {maximum} characters, got {len(value)}")
    if bad := re.search(f"[^{charset}]|[{_NORMALIZED}]", value):
        raise cannot_express(
            term,
            f"{element} takes only {name} characters without tab or line break (xs:normalizedString would "
            f"replace them), got {bad.group()!r} at position {bad.start()}",
        )
    return value


def _fixed(value: Decimal, term: str, element: str, *, decimals: tuple[int, int], digits: int, signed: bool) -> str:
    """Format ``value`` with ``decimals`` (min, max) fraction digits and at most ``digits`` integer digits."""
    low, high = decimals
    if value == 0:
        value = value.copy_abs()
    if value.is_signed() and not signed:
        raise cannot_express(term, f"{element} is unsigned, got {format(value, 'f')}")
    with localcontext(prec=MAX_PREC):
        places = -t.cast(int, value.as_tuple().exponent)
        if places > high:
            trimmed = value.quantize(Decimal(1).scaleb(-high))
            if trimmed != value:
                raise cannot_express(
                    term, f"{element} takes at most {high} decimals, got {format(value, 'f')} (round it first)"
                )
            value = trimmed
        elif places < low:
            value = value.quantize(Decimal(1).scaleb(-low))
    formatted = format(value, "f")
    if len(formatted.lstrip("-").split(".")[0]) > digits:
        raise cannot_express(term, f"{element} takes at most {digits} integer digits, got {formatted}")
    return formatted


def amount2(value: Decimal, term: str, element: str) -> str:
    """``Amount2DecimalType``: exactly two decimals, signed, at most 11 integer digits."""
    return _fixed(value, term, f"{element} (Amount2DecimalType)", decimals=(2, 2), digits=11, signed=True)


def amount8(value: Decimal, term: str, element: str) -> str:
    """``Amount8DecimalType``: two to eight decimals, signed, at most 11 integer digits."""
    return _fixed(value, term, f"{element} (Amount8DecimalType)", decimals=(2, 8), digits=11, signed=True)


def quantity(value: Decimal, term: str, element: str) -> str:
    """``QuantitaType``: two to eight decimals, unsigned, at most 12 integer digits."""
    return _fixed(value, term, f"{element} (QuantitaType)", decimals=(2, 8), digits=12, signed=False)


def rate(value: Decimal, term: str, element: str) -> str:
    """``RateType``: a percentage from 0.00 to 100.00 with exactly two decimals."""
    formatted = _fixed(value, term, f"{element} (RateType)", decimals=(2, 2), digits=3, signed=False)
    if value > _RATE_MAX:
        raise cannot_express(term, f"{element} (RateType) is at most 100.00, got {formatted}")
    return formatted


def date(value: datetime.date, term: str, element: str, *, invoice_date: bool = False) -> str:
    """``xs:date`` (``DataFatturaType`` from 1970-01-01 when ``invoice_date``)."""
    if invoice_date and value < _EPOCH:
        raise cannot_express(term, f"{element} (DataFatturaType) starts at 1970-01-01, got {value.isoformat()}")
    return value.isoformat()
