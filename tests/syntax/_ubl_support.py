"""Builders for the UBL writer unit tests: a minimal synthetic invoice and its parts with keyword overrides.

Fake parties, example.com addresses and the test IBAN only (CLAUDE.md fixtures rule).
"""

import datetime
import typing as t
from decimal import Decimal

from lxml import etree

from euinvoice import _xml
from euinvoice.model import (
    Buyer,
    BuyerPostalAddress,
    DocumentTotals,
    Invoice,
    InvoiceLine,
    ItemInformation,
    LineVatInformation,
    PaymentInstructions,
    PriceDetails,
    ProcessControl,
    Seller,
    SellerPostalAddress,
    VatBreakdown,
)
from euinvoice.syntax import ubl

TEST_IBAN: t.Final = "DE02120300000000202051"


def seller(**changes: t.Any) -> Seller:
    data: dict[str, t.Any] = {
        "name": "Seller Example GmbH",
        "vat_identifier": "DE000000000",
        "postal_address": SellerPostalAddress(country_code="DE"),
    }
    return Seller(**(data | changes))


def buyer(**changes: t.Any) -> Buyer:
    data: dict[str, t.Any] = {"name": "Buyer Example AG", "postal_address": BuyerPostalAddress(country_code="DE")}
    return Buyer(**(data | changes))


def payment(**changes: t.Any) -> PaymentInstructions:
    return PaymentInstructions(**({"payment_means_type_code": "58"} | changes))


def price(**changes: t.Any) -> PriceDetails:
    return PriceDetails(**({"item_net_price": Decimal("50")} | changes))


def item(**changes: t.Any) -> ItemInformation:
    return ItemInformation(**({"name": "Widget"} | changes))


def line(**changes: t.Any) -> InvoiceLine:
    data: dict[str, t.Any] = {
        "identifier": "1",
        "invoiced_quantity": Decimal("2"),
        "invoiced_quantity_unit_code": "C62",
        "net_amount": Decimal("100.00"),
        "price_details": price(),
        "vat_information": LineVatInformation(category_code="S", rate=Decimal("19")),
        "item": item(),
    }
    return InvoiceLine(**(data | changes))


def totals(**changes: t.Any) -> DocumentTotals:
    data: dict[str, t.Any] = {
        "sum_of_line_net_amounts": Decimal("100.00"),
        "total_without_vat": Decimal("100.00"),
        "total_vat": Decimal("19.00"),
        "total_with_vat": Decimal("119.00"),
        "amount_due": Decimal("119.00"),
    }
    return DocumentTotals(**(data | changes))


def invoice(**changes: t.Any) -> Invoice:
    """A minimal invoice (only the CEN-mandatory terms plus BT-110, which UBL needs) with ``changes`` applied."""
    data: dict[str, t.Any] = {
        "number": "INV-1",
        "issue_date": datetime.date(2026, 1, 15),
        "type_code": "380",
        "currency_code": "EUR",
        "process_control": ProcessControl(specification_identifier="urn:cen.eu:en16931:2017"),
        "seller": seller(),
        "buyer": buyer(),
        "totals": totals(),
        "vat_breakdown": (
            VatBreakdown(
                taxable_amount=Decimal("100.00"), tax_amount=Decimal("19.00"), category_code="S", rate=Decimal("19")
            ),
        ),
        "lines": (line(),),
    }
    return Invoice(**(data | changes))


def written(document: Invoice) -> etree._Element:
    """Write ``document`` and parse the output back with the hardened parser."""
    return _xml.parse(ubl.write(document))


def xpath(root: etree._Element, path: str) -> t.Any:
    """Evaluate ``path`` with the ``cac`` / ``cbc`` prefixes."""
    return root.xpath(path, namespaces=_xml.UBL_NSMAP)
