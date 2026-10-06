"""EN 16931 DELIVERY INFORMATION (BG-13) with INVOICING PERIOD (BG-14) and DELIVER TO ADDRESS (BG-15).

The model follows the semantic tree of EN 16931-1 as restated in the XRechnung 3.0.2 specification
(§11.7, §11.8, §11.18): BG-14 and BG-15 are direct parts of BG-13, so an invoicing period is set as
``Invoice(delivery=DeliveryInformation(invoicing_period=...))`` even though UBL writes it at document
level (``/Invoice/cac:InvoicePeriod``).
"""

import typing as t

from euinvoice.model._base import EuInvoiceModel, bt
from euinvoice.model.datatypes import ICD_SCHEME, CountryCode, Date, Identifier, Text

__all__ = ["DeliverToAddress", "DeliveryInformation", "InvoicingPeriod"]


class InvoicingPeriod(EuInvoiceModel):
    """INVOICING PERIOD (BG-14).

    BR-29 (end not before start) and BR-CO-19 (start or end present) are business rules, not checked
    by the model: :func:`euinvoice.calc.check` reports them, the official Schematron decides (D8).
    """

    start_date: t.Annotated[Date | None, bt("BT-73")] = None
    """Invoicing period start date."""
    end_date: t.Annotated[Date | None, bt("BT-74")] = None
    """Invoicing period end date."""


class DeliverToAddress(EuInvoiceModel):
    """DELIVER TO ADDRESS (BG-15)."""

    address_line_1: t.Annotated[Text | None, bt("BT-75")] = None
    """Deliver to address line 1."""
    address_line_2: t.Annotated[Text | None, bt("BT-76")] = None
    """Deliver to address line 2."""
    address_line_3: t.Annotated[Text | None, bt("BT-165")] = None
    """Deliver to address line 3."""
    city: t.Annotated[Text | None, bt("BT-77")] = None
    """Deliver to city."""
    post_code: t.Annotated[Text | None, bt("BT-78")] = None
    """Deliver to post code."""
    country_subdivision: t.Annotated[Text | None, bt("BT-79")] = None
    """Deliver to country subdivision."""
    country_code: t.Annotated[CountryCode, bt("BT-80")]
    """Deliver to country code (BR-57)."""


class DeliveryInformation(EuInvoiceModel):
    """DELIVERY INFORMATION (BG-13)."""

    deliver_to_party_name: t.Annotated[Text | None, bt("BT-70")] = None
    """Deliver to party name."""
    deliver_to_location_identifier: t.Annotated[t.Annotated[Identifier, ICD_SCHEME] | None, bt("BT-71")] = None
    """Deliver to location identifier, scheme from ISO 6523 ICD (BR-CL-26)."""
    actual_delivery_date: t.Annotated[Date | None, bt("BT-72")] = None
    """Actual delivery date."""
    invoicing_period: t.Annotated[InvoicingPeriod | None, bt("BG-14")] = None
    """INVOICING PERIOD."""
    deliver_to_address: t.Annotated[DeliverToAddress | None, bt("BG-15")] = None
    """DELIVER TO ADDRESS."""
