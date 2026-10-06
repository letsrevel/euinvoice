"""Readers of the CII structures that occur both at document and at line level."""

import datetime

from lxml import etree

from euinvoice.model import Identifier
from euinvoice.syntax.cii._build import OBJECT_TYPE_CODE, VAT
from euinvoice.syntax.cii._reader import Reader, content

_XML_SPACE = " \t\r\n"


def code_of(reader: Reader, element: etree._Element) -> str | None:
    """The ``ram:TypeCode`` of ``element`` stripped of XML whitespace, without marking it."""
    found = reader.children(element, "TypeCode")
    return content(found[0]).strip(_XML_SPACE) if found else None


def vat_category(
    reader: Reader, parent: etree._Element | None, name: str
) -> tuple[etree._Element, str | None, str | None] | None:
    """The first ``ram:<name>`` with ``ram:TypeCode`` ``VAT``: the element, its category code and its rate.

    Only VAT is an EN 16931 trade tax (CII-DT-037; BR-32, BR-37, BR-47 select ``ram:TypeCode = 'VAT'``), so any
    other tax stays unmapped.
    """
    for element in reader.children(parent, name):
        if code_of(reader, element) == VAT:
            reader.use(element)
            reader.one(element, "TypeCode")
            return element, reader.text(element, "CategoryCode"), reader.text(element, "RateApplicablePercent")
    return None


def allowance_charge_values(reader: Reader, element: etree._Element, term: str) -> tuple[bool, dict[str, str | None]]:
    """A ``ram:SpecifiedTradeAllowanceCharge``: its ``ChargeIndicator`` and the fields shared by BG-20/21/27/28.

    Args:
        reader: The reader.
        element: The allowance or charge.
        term: The group ids, for an error message.

    Returns:
        ``True`` for a charge, and the ``amount``, ``base_amount``, ``percentage``, ``reason_code`` and ``reason``
        model fields.
    """
    charge = reader.indicator(element, "ChargeIndicator", term)
    return charge, {
        "percentage": reader.text(element, "CalculationPercent"),
        "base_amount": reader.text(element, "BasisAmount"),
        "amount": reader.text(element, "ActualAmount"),
        "reason_code": reader.text(element, "ReasonCode"),
        "reason": reader.text(element, "Reason"),
    }


def period_dates(reader: Reader, period: etree._Element, terms: tuple[str, str]) -> dict[str, datetime.date | None]:
    """``ram:StartDateTime`` and ``ram:EndDateTime`` of a ``ram:BillingSpecifiedPeriod`` (BG-14, BG-26)."""
    return {
        "start_date": reader.date(period, "StartDateTime", terms[0]),
        "end_date": reader.date(period, "EndDateTime", terms[1]),
    }


def object_identifier(reader: Reader, parent: etree._Element | None) -> Identifier | None:
    """An invoiced object identifier (BT-18, BT-128): ``ram:AdditionalReferencedDocument`` with ``TypeCode`` 130.

    ``ram:IssuerAssignedID`` is the value and ``ram:ReferenceTypeCode`` the scheme (BR-CL-07; CII-DT-024 allows it
    only with type code 130). The first such document with an ``ram:IssuerAssignedID`` is mapped.
    """
    for element in reader.children(parent, "AdditionalReferencedDocument"):
        value = reader.children(element, "IssuerAssignedID")
        if code_of(reader, element) == OBJECT_TYPE_CODE and value:
            reader.use(element)
            reader.one(element, "TypeCode")
            return Identifier(value=content(reader.use(value[0])), scheme_id=reader.text(element, "ReferenceTypeCode"))
    return None
