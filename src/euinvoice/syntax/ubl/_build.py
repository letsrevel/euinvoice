"""Element builders shared by the UBL writer modules.

Elements are created with lxml's element API in the UBL namespaces of :mod:`euinvoice._xml`; nothing is
parsed here. Each helper writes nothing when its value is ``None``, so callers follow the XSD sequence
and pass optional business terms straight through.
"""

import datetime
import typing as t
from decimal import Decimal

from lxml import etree

from euinvoice import _xml
from euinvoice.model import Identifier

__all__ = [
    "VAT_SCHEME",
    "Context",
    "aggregate",
    "amount",
    "basic",
    "date",
    "identifier",
    "number",
    "quantity",
    "tax_category",
]

_CAC: t.Final = f"{{{_xml.UBL_CAC}}}"
_CBC: t.Final = f"{{{_xml.UBL_CBC}}}"

VAT_SCHEME: t.Final = "VAT"
"""``cac:TaxScheme/cbc:ID`` of every VAT category and VAT identifier: the CEN UBL binding selects VAT
terms with ``cac:TaxScheme/normalize-space(upper-case(cbc:ID))='VAT'`` (BR-32, BR-47, BR-CO-04, BR-56,
``UBL/EN16931-UBL-model.sch``)."""


class Context(t.NamedTuple):
    """What every part of one document needs to know about its root."""

    credit_note: bool
    """``True`` when the root is ``CreditNote`` (lines are ``cac:CreditNoteLine``)."""
    currency: str
    """The invoice currency code (BT-5), the ``currencyID`` of every amount except BT-111."""


def aggregate(parent: etree._Element, name: str) -> etree._Element:
    """Append an empty ``cac:<name>`` element.

    Args:
        parent: The parent element.
        name: The local name.

    Returns:
        The new element.
    """
    return etree.SubElement(parent, _CAC + name)


def basic(parent: etree._Element, tag: str, text: str | None, **attributes: str | None) -> etree._Element | None:
    """Append ``cbc:<tag>`` with ``text`` and the attributes that are not ``None``.

    Args:
        parent: The parent element.
        tag: The local name.
        text: The element's text; ``None`` writes nothing.
        **attributes: Attribute values; ``None`` values are left out.

    Returns:
        The new element, or ``None`` when ``text`` is ``None``.
    """
    if text is None:
        return None
    element = etree.SubElement(parent, _CBC + tag)
    element.text = text
    for key, value in attributes.items():
        if value is not None:
            element.set(key, value)
    return element


def number(value: Decimal | None) -> str | None:
    """Return ``value`` as fixed-point text (never exponent notation), or ``None``.

    Args:
        value: The number.

    Returns:
        ``format(value, "f")`` or ``None``.
    """
    return None if value is None else format(value, "f")


def date(value: datetime.date | None) -> str | None:
    """Return ``value`` as ``xs:date`` text (``YYYY-MM-DD``), or ``None``.

    Args:
        value: The date.

    Returns:
        The ISO 8601 calendar date or ``None``.
    """
    return None if value is None else value.isoformat()


def amount(parent: etree._Element, name: str, value: Decimal | None, currency: str) -> None:
    """Append an amount with its mandatory ``currencyID`` (UBL 2.1 ``AmountType``).

    Args:
        parent: The parent element.
        name: The local name, e.g. ``"TaxAmount"``.
        value: The amount; ``None`` writes nothing.
        currency: The ISO 4217 code for ``currencyID``.
    """
    basic(parent, name, number(value), currencyID=currency)


def quantity(parent: etree._Element, name: str, value: Decimal | None, unit: str | None) -> None:
    """Append a quantity with its optional ``unitCode``.

    Args:
        parent: The parent element.
        name: The local name, e.g. ``"InvoicedQuantity"``.
        value: The quantity; ``None`` writes nothing.
        unit: The UN/ECE Rec 20/21 unit code, or ``None``.
    """
    basic(parent, name, number(value), unitCode=unit)


def identifier(parent: etree._Element, name: str, value: Identifier | None) -> None:
    """Append ``cbc:<name>`` with an identifier and, if set, its ``schemeID``.

    Args:
        parent: The parent element.
        name: The local name, e.g. ``"EndpointID"``.
        value: The identifier; ``None`` writes nothing.
    """
    if value is not None:
        basic(parent, name, value.value, schemeID=value.scheme_id)


def tax_category(
    parent: etree._Element,
    name: str,
    code: str,
    rate: Decimal | None,
    *,
    exemption_code: str | None = None,
    exemption_reason: str | None = None,
) -> None:
    """Append a VAT category (UBL 2.1 ``TaxCategoryType`` sequence).

    Args:
        parent: The parent element.
        name: ``"TaxCategory"`` or ``"ClassifiedTaxCategory"``.
        code: The VAT category code (UNTDID 5305).
        rate: The VAT rate, or ``None``.
        exemption_code: The VAT exemption reason code (BT-121), or ``None``.
        exemption_reason: The VAT exemption reason text (BT-120), or ``None``.
    """
    category = aggregate(parent, name)
    basic(category, "ID", code)
    basic(category, "Percent", number(rate))
    basic(category, "TaxExemptionReasonCode", exemption_code)
    basic(category, "TaxExemptionReason", exemption_reason)
    basic(aggregate(category, "TaxScheme"), "ID", VAT_SCHEME)
