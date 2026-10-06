"""Read UBL invoice lines (BG-25 and its groups) and the allowance/charge element shared with the document level.

XPaths are those of ``docs/reference/bt-mapping.md``, mirrored from the writer (``_lines.py``). A
``CreditNote`` has ``cac:CreditNoteLine`` with ``cbc:CreditedQuantity`` (``maindoc/UBL-CreditNote-2.1.xsd``).
"""

import datetime
import typing as t

from lxml import etree

from euinvoice.model import (
    DocumentLevelAllowance,
    DocumentLevelCharge,
    Identifier,
    InvoiceLine,
    InvoiceLineAllowance,
    InvoiceLineCharge,
    InvoiceLinePeriod,
    ItemAttribute,
    ItemClassificationIdentifier,
    ItemInformation,
    LineVatInformation,
    PriceDetails,
)
from euinvoice.syntax.ubl._build import VAT_SCHEME
from euinvoice.syntax.ubl._cursor import CAC, CBC, Cursor, build, normalize_space
from euinvoice.syntax.ubl._lines import OBJECT_DOCUMENT_TYPE

__all__ = ["read_allowance_charge", "read_line", "read_object_identifier", "read_period", "take_vat_scheme"]

type _Entry = DocumentLevelAllowance | DocumentLevelCharge | InvoiceLineAllowance | InvoiceLineCharge

_DOCUMENT_LEVEL: t.Final[dict[bool, tuple[type[_Entry], str]]] = {
    False: (DocumentLevelAllowance, "BG-20"),
    True: (DocumentLevelCharge, "BG-21"),
}
_LINE_LEVEL: t.Final[dict[bool, tuple[type[_Entry], str]]] = {
    False: (InvoiceLineAllowance, "BG-27"),
    True: (InvoiceLineCharge, "BG-28"),
}


def read_allowance_charge(cursor: Cursor, element: etree._Element, currency: str, *, line: bool) -> _Entry | None:
    """Read one ``cac:AllowanceCharge`` as an allowance or a charge (``cbc:ChargeIndicator``).

    Only document level entries carry a VAT category (BR-32, BR-37); in a line, UBL-CR-558 forbids
    ``cac:TaxCategory``, which then stays unmapped. An entry without ``cbc:ChargeIndicator`` (mandatory in
    the UBL 2.1 XSD) cannot be classified and stays unmapped as a whole.

    Args:
        cursor: The document cursor.
        element: The ``cac:AllowanceCharge``.
        currency: The invoice currency code (BT-5).
        line: ``True`` for a line level entry.

    Returns:
        The allowance or charge, or ``None`` without a charge indicator.

    Raises:
        ParseError: The entry is not valid (e.g. BR-33: no reason and no reason code).
    """
    is_charge = cursor.boolean(element, CBC + "ChargeIndicator")
    if is_charge is None:
        return None
    fields: dict[str, t.Any] = {
        "reason_code": cursor.text(element, CBC + "AllowanceChargeReasonCode"),
        "reason": cursor.text(element, CBC + "AllowanceChargeReason"),
        "percentage": cursor.text(element, CBC + "MultiplierFactorNumeric"),
        "amount": cursor.amount(element, CBC + "Amount", currency),
        "base_amount": cursor.amount(element, CBC + "BaseAmount", currency),
    }
    model, group = (_LINE_LEVEL if line else _DOCUMENT_LEVEL)[is_charge]
    if not line:
        category = cursor.first(element, CAC + "TaxCategory")
        fields["vat_category_code"], fields["vat_rate"] = _category(cursor, category)
    return build(model, element, group, **fields)


def _category(cursor: Cursor, category: etree._Element | None) -> tuple[str | None, str | None]:
    """Read a VAT category's code and rate.

    Its ``cac:TaxScheme/cbc:ID`` is part of the binding only as ``VAT`` (the CEN rules select VAT categories with
    ``cac:TaxScheme/normalize-space(upper-case(cbc:ID))='VAT'``, e.g. BR-CO-04 in ``UBL/EN16931-UBL-model.sch``);
    another value stays unmapped.
    """
    take_vat_scheme(cursor, category)
    return cursor.text(category, CBC + "ID"), cursor.text(category, CBC + "Percent")


def take_vat_scheme(cursor: Cursor, category: etree._Element | None) -> None:
    """Take ``cac:TaxScheme/cbc:ID`` of a VAT category when it is ``VAT`` (see :func:`_category`).

    Args:
        cursor: The document cursor.
        category: The ``cac:TaxCategory`` or ``cac:ClassifiedTaxCategory``, or ``None``.
    """
    scheme = cursor.first(cursor.first(category, CAC + "TaxScheme"), CBC + "ID")
    if scheme is not None and normalize_space(scheme.text).upper() == VAT_SCHEME:
        cursor.take(scheme)


def read_object_identifier(cursor: Cursor, references: list[etree._Element]) -> Identifier | None:
    """Read the first document reference with ``cbc:DocumentTypeCode`` 130 (BT-18, BT-128; CEN UBL-SR-43).

    Args:
        cursor: The document cursor.
        references: The candidate ``cac:AdditionalDocumentReference`` or ``cac:DocumentReference`` elements.

    Returns:
        The identifier, or ``None``. Further references with code 130 stay unmapped.
    """
    for reference in references:
        if _type_code(reference) == OBJECT_DOCUMENT_TYPE:
            cursor.text(reference, CBC + "DocumentTypeCode")
            return cursor.identifier(reference, CBC + "ID")
    return None


def _type_code(reference: etree._Element) -> str | None:
    code = next(reference.iterchildren(CBC + "DocumentTypeCode"), None)
    return None if code is None else code.text or ""


def read_period(
    cursor: Cursor, element: etree._Element | None, terms: tuple[str, str]
) -> tuple[datetime.date | None, datetime.date | None]:
    """Read ``cbc:StartDate`` and ``cbc:EndDate`` of a ``cac:InvoicePeriod``.

    Args:
        cursor: The document cursor.
        element: The ``cac:InvoicePeriod``, or ``None``.
        terms: The BT ids of the start and end date, for errors.

    Returns:
        The start and end date (``None`` where missing).

    Raises:
        ParseError: A date is not ``YYYY-MM-DD``.
    """
    start, end = terms
    return cursor.date(element, CBC + "StartDate", start), cursor.date(element, CBC + "EndDate", end)


def read_line(cursor: Cursor, element: etree._Element, currency: str, *, credit_note: bool) -> InvoiceLine:
    """Read one ``cac:InvoiceLine`` or ``cac:CreditNoteLine`` (BG-25).

    Args:
        cursor: The document cursor.
        element: The line element.
        currency: The invoice currency code (BT-5).
        credit_note: ``True`` for a ``CreditNote`` (``cbc:CreditedQuantity``).

    Returns:
        The line.

    Raises:
        ParseError: The line or one of its groups is not valid.
    """
    quantity = cursor.first(element, CBC + ("CreditedQuantity" if credit_note else "InvoicedQuantity"))
    period = cursor.first(element, CAC + "InvoicePeriod")
    entries = [
        entry
        for allowance_charge in cursor.children(element, CAC + "AllowanceCharge")
        if (entry := read_allowance_charge(cursor, allowance_charge, currency, line=True)) is not None
    ]
    item = cursor.first(element, CAC + "Item")
    return build(
        InvoiceLine,
        element,
        "BG-25",
        identifier=cursor.text(element, CBC + "ID"),
        note=cursor.text(element, CBC + "Note"),
        object_identifier=read_object_identifier(cursor, cursor.children(element, CAC + "DocumentReference")),
        invoiced_quantity=cursor.value(quantity),
        invoiced_quantity_unit_code=cursor.attribute(quantity, "unitCode"),
        net_amount=cursor.amount(element, CBC + "LineExtensionAmount", currency),
        purchase_order_line_reference=cursor.text(cursor.first(element, CAC + "OrderLineReference"), CBC + "LineID"),
        buyer_accounting_reference=cursor.text(element, CBC + "AccountingCost"),
        period=_line_period(cursor, period),
        allowances=tuple(entry for entry in entries if isinstance(entry, InvoiceLineAllowance)),
        charges=tuple(entry for entry in entries if isinstance(entry, InvoiceLineCharge)),
        price_details=_price(cursor, cursor.first(element, CAC + "Price"), currency),
        vat_information=_vat_information(cursor, item),
        item=None if item is None else _item(cursor, item),
    )


def _line_period(cursor: Cursor, period: etree._Element | None) -> InvoiceLinePeriod | None:
    """BG-26, ``None`` without dates (an empty ``cac:InvoicePeriod`` stays unmapped)."""
    start, end = read_period(cursor, period, ("BT-134", "BT-135"))
    if period is None or (start is None and end is None):
        return None
    return build(InvoiceLinePeriod, period, "BG-26", start_date=start, end_date=end)


def _vat_information(cursor: Cursor, item: etree._Element | None) -> LineVatInformation | None:
    category = cursor.first(item, CAC + "ClassifiedTaxCategory")
    if category is None:
        return None
    code, rate = _category(cursor, category)
    return build(LineVatInformation, category, "BG-30", category_code=code, rate=rate)


def _price(cursor: Cursor, price: etree._Element | None, currency: str) -> PriceDetails | None:
    """Read PRICE DETAILS (BG-29); BT-147/BT-148 come from the price allowance (``ChargeIndicator`` false).

    A price-level charge (``ChargeIndicator`` true) is no business term (Peppol PEPPOL-EN16931-R044) and
    stays unmapped.
    """
    if price is None:
        return None
    base_quantity = cursor.first(price, CBC + "BaseQuantity")
    allowance = next(
        (
            element
            for element in cursor.children(price, CAC + "AllowanceCharge")
            if _indicator(element) in ("false", "0")
        ),
        None,
    )
    if allowance is not None:
        cursor.boolean(allowance, CBC + "ChargeIndicator")
    return build(
        PriceDetails,
        price,
        "BG-29",
        item_net_price=cursor.amount(price, CBC + "PriceAmount", currency),
        item_price_discount=cursor.amount(allowance, CBC + "Amount", currency),
        item_gross_price=cursor.amount(allowance, CBC + "BaseAmount", currency),
        base_quantity=cursor.value(base_quantity),
        base_quantity_unit_code=cursor.attribute(base_quantity, "unitCode"),
    )


def _indicator(allowance_charge: etree._Element) -> str | None:
    """The ``cbc:ChargeIndicator`` text without surrounding whitespace, or ``None``."""
    element = next(allowance_charge.iterchildren(CBC + "ChargeIndicator"), None)
    return None if element is None else (element.text or "").strip(" \t\r\n")


def _item(cursor: Cursor, item: etree._Element) -> ItemInformation:
    standard = cursor.first(item, CAC + "StandardItemIdentification")
    return build(
        ItemInformation,
        item,
        "BG-31",
        name=cursor.text(item, CBC + "Name"),
        description=cursor.text(item, CBC + "Description"),
        sellers_identifier=cursor.text(cursor.first(item, CAC + "SellersItemIdentification"), CBC + "ID"),
        buyers_identifier=cursor.text(cursor.first(item, CAC + "BuyersItemIdentification"), CBC + "ID"),
        standard_identifier=cursor.identifier(standard, CBC + "ID"),
        classification_identifiers=tuple(
            _classification(cursor, element, code)
            for element in cursor.children(item, CAC + "CommodityClassification")
            # cbc:ItemClassificationCode is optional in CommodityClassificationType (UBL 2.1 XSD): an entry
            # without it (e.g. only cbc:NatureCode) is no BT-158 and stays unmapped.
            if (code := cursor.first(element, CBC + "ItemClassificationCode")) is not None
        ),
        country_of_origin=cursor.text(cursor.first(item, CAC + "OriginCountry"), CBC + "IdentificationCode"),
        attributes=tuple(
            build(
                ItemAttribute,
                element,
                "BG-32",
                name=cursor.text(element, CBC + "Name"),
                value=cursor.text(element, CBC + "Value"),
            )
            for element in cursor.children(item, CAC + "AdditionalItemProperty")
        ),
    )


def _classification(cursor: Cursor, element: etree._Element, code: etree._Element) -> ItemClassificationIdentifier:
    return build(
        ItemClassificationIdentifier,
        element,
        "BT-158",
        value=cursor.value(code),
        scheme_id=cursor.attribute(code, "listID"),
        scheme_version_id=cursor.attribute(code, "listVersionID"),
    )
