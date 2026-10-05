"""EN 16931 INVOICE LINE (BG-25) and its groups BG-26, BG-29..BG-32.

The line allowances and charges (BG-27, BG-28) live in :mod:`euinvoice.model.allowances`.

Mandatory per line: BT-126 (BR-21), BT-129 (BR-22), BT-130 (BR-23), BT-131 (BR-24), the item name
BT-153 (BR-25), the item net price BT-146 (BR-26) and the item VAT category BT-151 (BR-CO-04), so
PRICE DETAILS (BG-29), LINE VAT INFORMATION (BG-30) and ITEM INFORMATION (BG-31) are always present.
"""

import typing as t

from euinvoice.model._base import EuInvoiceModel, bt
from euinvoice.model.allowances import InvoiceLineAllowance, InvoiceLineCharge
from euinvoice.model.amounts import Amount, Percentage, Quantity, UnitPriceAmount
from euinvoice.model.datatypes import (
    OBJECT_SCHEME,
    STANDARD_ITEM_SCHEME,
    CountryCode,
    Date,
    Identifier,
    ItemClassificationIdentifier,
    NonBlankText,
    Text,
    UnitCode,
    VatCategoryCode,
    not_negative,
)

__all__ = [
    "InvoiceLine",
    "InvoiceLinePeriod",
    "ItemAttribute",
    "ItemInformation",
    "LineDraft",
    "LineVatInformation",
    "PriceDetails",
]


class InvoiceLinePeriod(EuInvoiceModel):
    """INVOICE LINE PERIOD (BG-26). BR-30 (end not before start) and BR-CO-20 are left to ``calc.check``."""

    start_date: t.Annotated[Date | None, bt("BT-134")] = None
    """Invoice line period start date."""
    end_date: t.Annotated[Date | None, bt("BT-135")] = None
    """Invoice line period end date."""


class PriceDetails(EuInvoiceModel):
    """PRICE DETAILS (BG-29). Unit prices keep their precision (no BR-DEC limit, UBL-DT-01 exempts them)."""

    item_net_price: t.Annotated[UnitPriceAmount, not_negative("BR-27"), bt("BT-146")]
    """Item net price (BR-26), not negative (BR-27)."""
    item_price_discount: t.Annotated[UnitPriceAmount | None, bt("BT-147")] = None
    """Item price discount."""
    item_gross_price: t.Annotated[t.Annotated[UnitPriceAmount, not_negative("BR-28")] | None, bt("BT-148")] = None
    """Item gross price, not negative (BR-28)."""
    base_quantity: t.Annotated[Quantity | None, bt("BT-149")] = None
    """Item price base quantity."""
    base_quantity_unit_code: t.Annotated[UnitCode | None, bt("BT-150")] = None
    """Item price base quantity unit of measure code, UN/ECE Rec 20/21 (BR-CL-23)."""


class LineVatInformation(EuInvoiceModel):
    """LINE VAT INFORMATION (BG-30)."""

    category_code: t.Annotated[VatCategoryCode, bt("BT-151")]
    """Invoiced item VAT category code, UNTDID 5305 (BR-CO-04, BR-CL-18)."""
    rate: t.Annotated[Percentage | None, bt("BT-152")] = None
    """Invoiced item VAT rate as a percentage."""


class ItemAttribute(EuInvoiceModel):
    """ITEM ATTRIBUTES (BG-32)."""

    name: t.Annotated[Text, bt("BT-160")]
    """Item attribute name (BR-54)."""
    value: t.Annotated[Text, bt("BT-161")]
    """Item attribute value (BR-54)."""


class ItemInformation(EuInvoiceModel):
    """ITEM INFORMATION (BG-31)."""

    name: t.Annotated[NonBlankText, bt("BT-153")]
    """Item name (BR-25)."""
    description: t.Annotated[Text | None, bt("BT-154")] = None
    """Item description."""
    sellers_identifier: t.Annotated[Text | None, bt("BT-155")] = None
    """Item Seller's identifier."""
    buyers_identifier: t.Annotated[Text | None, bt("BT-156")] = None
    """Item Buyer's identifier."""
    standard_identifier: t.Annotated[t.Annotated[Identifier, STANDARD_ITEM_SCHEME] | None, bt("BT-157")] = None
    """Item standard identifier; its scheme is mandatory (BR-64) and an ISO 6523 ICD code (BR-CL-21)."""
    classification_identifiers: t.Annotated[tuple[ItemClassificationIdentifier, ...], bt("BT-158")] = ()
    """Item classification identifiers (0..n), each with a UNTDID 7143 scheme (BR-65, BR-CL-13)."""
    country_of_origin: t.Annotated[CountryCode | None, bt("BT-159")] = None
    """Item country of origin (BR-CL-15)."""
    attributes: t.Annotated[tuple[ItemAttribute, ...], bt("BG-32")] = ()
    """ITEM ATTRIBUTES (0..n)."""


class _LineBody(EuInvoiceModel):
    """The fields INVOICE LINE (BG-25) shares with its draft: everything except BT-131."""

    identifier: t.Annotated[NonBlankText, bt("BT-126")]
    """Invoice line identifier (BR-21)."""
    note: t.Annotated[Text | None, bt("BT-127")] = None
    """Invoice line note."""
    object_identifier: t.Annotated[t.Annotated[Identifier, OBJECT_SCHEME] | None, bt("BT-128")] = None
    """Invoice line object identifier, scheme from UNTDID 1153 (BR-CL-07)."""
    invoiced_quantity: t.Annotated[Quantity, bt("BT-129")]
    """Invoiced quantity (BR-22)."""
    invoiced_quantity_unit_code: t.Annotated[UnitCode, bt("BT-130")]
    """Invoiced quantity unit of measure code, UN/ECE Rec 20/21 (BR-23, BR-CL-23)."""
    purchase_order_line_reference: t.Annotated[Text | None, bt("BT-132")] = None
    """Referenced purchase order line reference."""
    buyer_accounting_reference: t.Annotated[Text | None, bt("BT-133")] = None
    """Invoice line Buyer accounting reference."""
    period: t.Annotated[InvoiceLinePeriod | None, bt("BG-26")] = None
    """INVOICE LINE PERIOD."""
    allowances: t.Annotated[tuple[InvoiceLineAllowance, ...], bt("BG-27")] = ()
    """INVOICE LINE ALLOWANCES (0..n)."""
    charges: t.Annotated[tuple[InvoiceLineCharge, ...], bt("BG-28")] = ()
    """INVOICE LINE CHARGES (0..n)."""
    price_details: t.Annotated[PriceDetails, bt("BG-29")]
    """PRICE DETAILS."""
    vat_information: t.Annotated[LineVatInformation, bt("BG-30")]
    """LINE VAT INFORMATION."""
    item: t.Annotated[ItemInformation, bt("BG-31")]
    """ITEM INFORMATION."""


class InvoiceLine(_LineBody):
    """INVOICE LINE (BG-25)."""

    net_amount: t.Annotated[Amount, bt("BT-131")]
    """Invoice line net amount (BR-24)."""


class LineDraft(_LineBody):
    """An invoice line without its derived net amount (BT-131), the input of ``calc`` (#9).

    It has every field of :class:`InvoiceLine` except ``net_amount``, with the same types and checks.
    """
