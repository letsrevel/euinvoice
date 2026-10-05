"""UBL invoice lines (BG-25 and its groups) and the allowance/charge element shared with the document level.

Element order follows ``InvoiceLineType`` / ``CreditNoteLineType``, ``ItemType``, ``PriceType`` and
``AllowanceChargeType`` of the UBL 2.1 XSD. A credit note writes ``cac:CreditNoteLine`` with
``cbc:CreditedQuantity`` (``maindoc/UBL-CreditNote-2.1.xsd``); the CEN binding accepts both
(BR-16, BR-22, BR-23 in ``UBL/EN16931-UBL-model.sch``).
"""

import typing as t

from lxml import etree

from euinvoice.errors import ModelError
from euinvoice.model import (
    DocumentLevelAllowance,
    DocumentLevelCharge,
    InvoiceLine,
    InvoiceLineAllowance,
    InvoiceLineCharge,
    ItemInformation,
    PriceDetails,
)
from euinvoice.syntax.ubl._build import (
    Context,
    aggregate,
    amount,
    basic,
    date,
    identifier,
    number,
    quantity,
    tax_category,
)

__all__ = ["OBJECT_DOCUMENT_TYPE", "write_allowance_charge", "write_line"]

OBJECT_DOCUMENT_TYPE: t.Final = "130"
"""``cbc:DocumentTypeCode`` that marks a document reference as an invoiced object identifier (BT-18 at
document level, BT-128 on a line): CEN UBL-SR-43 (``UBL/EN16931-UBL-syntax.sch``) and bt-mapping.md."""

type AllowanceOrCharge = DocumentLevelAllowance | DocumentLevelCharge | InvoiceLineAllowance | InvoiceLineCharge


def write_allowance_charge(parent: etree._Element, entry: AllowanceOrCharge, currency: str) -> None:
    """Append one ``cac:AllowanceCharge`` (BG-20, BG-21, BG-27 or BG-28).

    ``cbc:ChargeIndicator`` is ``true`` for charges and ``false`` for allowances, which is how the CEN
    binding tells them apart (``Document_level_charges`` etc. in ``UBL/EN16931-UBL-model.sch``). Only
    document level entries carry a VAT category (BR-32, BR-37).

    Args:
        parent: The document root or a line element.
        entry: The allowance or charge.
        currency: The invoice currency code (BT-5).
    """
    element = aggregate(parent, "AllowanceCharge")
    is_charge = isinstance(entry, DocumentLevelCharge | InvoiceLineCharge)
    basic(element, "ChargeIndicator", "true" if is_charge else "false")
    basic(element, "AllowanceChargeReasonCode", entry.reason_code)
    basic(element, "AllowanceChargeReason", entry.reason)
    basic(element, "MultiplierFactorNumeric", number(entry.percentage))
    amount(element, "Amount", entry.amount, currency)
    amount(element, "BaseAmount", entry.base_amount, currency)
    if isinstance(entry, DocumentLevelAllowance | DocumentLevelCharge):
        tax_category(element, "TaxCategory", entry.vat_category_code, entry.vat_rate)


def write_line(root: etree._Element, line: InvoiceLine, context: Context) -> None:
    """Append one invoice line (BG-25) as ``cac:InvoiceLine`` or ``cac:CreditNoteLine``.

    Args:
        root: The ``Invoice`` or ``CreditNote`` element.
        line: The line.
        context: The document context (root kind, currency).

    Raises:
        ModelError: The line's price cannot be expressed in UBL (see :func:`_price`).
    """
    element = aggregate(root, "CreditNoteLine" if context.credit_note else "InvoiceLine")
    basic(element, "ID", line.identifier)
    basic(element, "Note", line.note)
    quantity_name = "CreditedQuantity" if context.credit_note else "InvoicedQuantity"
    quantity(element, quantity_name, line.invoiced_quantity, line.invoiced_quantity_unit_code)
    amount(element, "LineExtensionAmount", line.net_amount, context.currency)
    basic(element, "AccountingCost", line.buyer_accounting_reference)
    if line.period is not None:
        period = aggregate(element, "InvoicePeriod")
        basic(period, "StartDate", date(line.period.start_date))
        basic(period, "EndDate", date(line.period.end_date))
    if line.purchase_order_line_reference is not None:
        basic(aggregate(element, "OrderLineReference"), "LineID", line.purchase_order_line_reference)
    if line.object_identifier is not None:
        reference = aggregate(element, "DocumentReference")
        identifier(reference, "ID", line.object_identifier)
        basic(reference, "DocumentTypeCode", OBJECT_DOCUMENT_TYPE)
    entries: tuple[AllowanceOrCharge, ...] = (*line.allowances, *line.charges)
    for entry in entries:
        write_allowance_charge(element, entry, context.currency)
    _item(element, line)
    _price(element, line.price_details, context.currency)


def _item(line_element: etree._Element, line: InvoiceLine) -> None:
    item: ItemInformation = line.item
    element = aggregate(line_element, "Item")
    basic(element, "Description", item.description)
    basic(element, "Name", item.name)
    if item.buyers_identifier is not None:
        basic(aggregate(element, "BuyersItemIdentification"), "ID", item.buyers_identifier)
    if item.sellers_identifier is not None:
        basic(aggregate(element, "SellersItemIdentification"), "ID", item.sellers_identifier)
    if item.standard_identifier is not None:
        identifier(aggregate(element, "StandardItemIdentification"), "ID", item.standard_identifier)
    if item.country_of_origin is not None:
        basic(aggregate(element, "OriginCountry"), "IdentificationCode", item.country_of_origin)
    for classification in item.classification_identifiers:
        basic(
            aggregate(element, "CommodityClassification"),
            "ItemClassificationCode",
            classification.value,
            listID=classification.scheme_id,  # BR-65: exists(@listID)
            listVersionID=classification.scheme_version_id,
        )
    vat = line.vat_information
    tax_category(element, "ClassifiedTaxCategory", vat.category_code, vat.rate)
    for attribute in item.attributes:
        property_element = aggregate(element, "AdditionalItemProperty")
        basic(property_element, "Name", attribute.name)
        basic(property_element, "Value", attribute.value)


def _price(line_element: etree._Element, price: PriceDetails, currency: str) -> None:
    """Append ``cac:Price`` (BG-29).

    The item price discount BT-147 and gross price BT-148 share one ``cac:AllowanceCharge`` with
    ``cbc:ChargeIndicator`` ``false`` (bt-mapping.md; Peppol ``part/price.xml`` fixes the indicator).

    Raises:
        ModelError: BT-150 without BT-149 (``cbc:BaseQuantity`` needs a value to carry ``unitCode``), or
            BT-148 without BT-147 (``cbc:Amount`` is mandatory in ``AllowanceChargeType``, UBL 2.1 XSD).
    """
    if price.base_quantity_unit_code is not None and price.base_quantity is None:
        raise ModelError(
            "UBL cannot carry the item price base quantity unit of measure code (BT-150) without the item "
            "price base quantity (BT-149): it is the unitCode attribute of cac:Price/cbc:BaseQuantity"
        )
    if price.item_gross_price is not None and price.item_price_discount is None:
        raise ModelError(
            "UBL cannot carry the item gross price (BT-148) without the item price discount (BT-147): "
            "cac:Price/cac:AllowanceCharge requires cbc:Amount (UBL 2.1 XSD AllowanceChargeType). "
            "Set BT-147, e.g. to BT-148 minus BT-146"
        )
    element = aggregate(line_element, "Price")
    amount(element, "PriceAmount", price.item_net_price, currency)
    quantity(element, "BaseQuantity", price.base_quantity, price.base_quantity_unit_code)
    if price.item_price_discount is not None:
        discount = aggregate(element, "AllowanceCharge")
        basic(discount, "ChargeIndicator", "false")
        amount(discount, "Amount", price.item_price_discount, currency)
        amount(discount, "BaseAmount", price.item_gross_price, currency)
