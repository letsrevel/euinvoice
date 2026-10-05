"""EN 16931 parties: Seller BG-4, Buyer BG-7, Payee BG-10, Seller tax representative BG-11.

Each postal address (BG-5, BG-8, BG-12, BG-15) and contact (BG-6, BG-9) is its own class because
its business terms carry different BT ids; the classes share field names, so code that only reads
``city`` or ``country_code`` works with any of them.

Cardinalities are those of ``docs/reference/bt-mapping.md``: a term is required only where a
``fatal`` CEN rule (validation-1.3.16) demands it, and each such field cites its rule.
"""

import typing as t

from euinvoice.model._base import EuInvoiceModel, bt
from euinvoice.model.datatypes import (
    EAS_SCHEME,
    ICD_SCHEME,
    CountryCode,
    Identifier,
    NonBlankText,
    Text,
)

__all__ = [
    "Buyer",
    "BuyerContact",
    "BuyerPostalAddress",
    "Payee",
    "Seller",
    "SellerContact",
    "SellerPostalAddress",
    "SellerTaxRepresentative",
    "TaxRepresentativePostalAddress",
]


class SellerPostalAddress(EuInvoiceModel):
    """SELLER POSTAL ADDRESS (BG-5). Required in the Seller (BR-08)."""

    address_line_1: t.Annotated[Text | None, bt("BT-35")] = None
    """Seller address line 1."""
    address_line_2: t.Annotated[Text | None, bt("BT-36")] = None
    """Seller address line 2."""
    address_line_3: t.Annotated[Text | None, bt("BT-162")] = None
    """Seller address line 3."""
    city: t.Annotated[Text | None, bt("BT-37")] = None
    """Seller city."""
    post_code: t.Annotated[Text | None, bt("BT-38")] = None
    """Seller post code."""
    country_subdivision: t.Annotated[Text | None, bt("BT-39")] = None
    """Seller country subdivision."""
    country_code: t.Annotated[CountryCode, bt("BT-40")]
    """Seller country code (BR-09)."""


class SellerContact(EuInvoiceModel):
    """SELLER CONTACT (BG-6)."""

    contact_point: t.Annotated[Text | None, bt("BT-41")] = None
    """Seller contact point."""
    telephone: t.Annotated[Text | None, bt("BT-42")] = None
    """Seller contact telephone number."""
    email: t.Annotated[Text | None, bt("BT-43")] = None
    """Seller contact email address."""


class Seller(EuInvoiceModel):
    """SELLER (BG-4)."""

    name: t.Annotated[NonBlankText, bt("BT-27")]
    """Seller name (BR-06)."""
    trading_name: t.Annotated[Text | None, bt("BT-28")] = None
    """Seller trading name."""
    identifiers: t.Annotated[tuple[t.Annotated[Identifier, ICD_SCHEME], ...], bt("BT-29")] = ()
    """Seller identifiers (0..n), scheme from ISO 6523 ICD (BR-CL-10/11)."""
    legal_registration_identifier: t.Annotated[t.Annotated[Identifier, ICD_SCHEME] | None, bt("BT-30")] = None
    """Seller legal registration identifier, scheme from ISO 6523 ICD (BR-CL-11)."""
    vat_identifier: t.Annotated[Text | None, bt("BT-31")] = None
    """Seller VAT identifier."""
    tax_registration_identifier: t.Annotated[Text | None, bt("BT-32")] = None
    """Seller tax registration identifier."""
    additional_legal_information: t.Annotated[Text | None, bt("BT-33")] = None
    """Seller additional legal information."""
    electronic_address: t.Annotated[t.Annotated[Identifier, EAS_SCHEME] | None, bt("BT-34")] = None
    """Seller electronic address; its scheme is mandatory (BR-62) and a CEF EAS code (BR-CL-25)."""
    postal_address: t.Annotated[SellerPostalAddress, bt("BG-5")]
    """SELLER POSTAL ADDRESS (BR-08)."""
    contact: t.Annotated[SellerContact | None, bt("BG-6")] = None
    """SELLER CONTACT."""


class BuyerPostalAddress(EuInvoiceModel):
    """BUYER POSTAL ADDRESS (BG-8). Required in the Buyer (BR-10)."""

    address_line_1: t.Annotated[Text | None, bt("BT-50")] = None
    """Buyer address line 1."""
    address_line_2: t.Annotated[Text | None, bt("BT-51")] = None
    """Buyer address line 2."""
    address_line_3: t.Annotated[Text | None, bt("BT-163")] = None
    """Buyer address line 3."""
    city: t.Annotated[Text | None, bt("BT-52")] = None
    """Buyer city."""
    post_code: t.Annotated[Text | None, bt("BT-53")] = None
    """Buyer post code."""
    country_subdivision: t.Annotated[Text | None, bt("BT-54")] = None
    """Buyer country subdivision."""
    country_code: t.Annotated[CountryCode, bt("BT-55")]
    """Buyer country code (BR-11)."""


class BuyerContact(EuInvoiceModel):
    """BUYER CONTACT (BG-9)."""

    contact_point: t.Annotated[Text | None, bt("BT-56")] = None
    """Buyer contact point."""
    telephone: t.Annotated[Text | None, bt("BT-57")] = None
    """Buyer contact telephone number."""
    email: t.Annotated[Text | None, bt("BT-58")] = None
    """Buyer contact email address."""


class Buyer(EuInvoiceModel):
    """BUYER (BG-7)."""

    name: t.Annotated[NonBlankText, bt("BT-44")]
    """Buyer name (BR-07)."""
    trading_name: t.Annotated[Text | None, bt("BT-45")] = None
    """Buyer trading name."""
    identifier: t.Annotated[t.Annotated[Identifier, ICD_SCHEME] | None, bt("BT-46")] = None
    """Buyer identifier, scheme from ISO 6523 ICD (BR-CL-10/11)."""
    legal_registration_identifier: t.Annotated[t.Annotated[Identifier, ICD_SCHEME] | None, bt("BT-47")] = None
    """Buyer legal registration identifier, scheme from ISO 6523 ICD (BR-CL-11)."""
    vat_identifier: t.Annotated[Text | None, bt("BT-48")] = None
    """Buyer VAT identifier."""
    electronic_address: t.Annotated[t.Annotated[Identifier, EAS_SCHEME] | None, bt("BT-49")] = None
    """Buyer electronic address; its scheme is mandatory (BR-63) and a CEF EAS code (BR-CL-25)."""
    postal_address: t.Annotated[BuyerPostalAddress, bt("BG-8")]
    """BUYER POSTAL ADDRESS (BR-10)."""
    contact: t.Annotated[BuyerContact | None, bt("BG-9")] = None
    """BUYER CONTACT."""


class Payee(EuInvoiceModel):
    """PAYEE (BG-10), used when the payee is not the Seller."""

    name: t.Annotated[Text, bt("BT-59")]
    """Payee name (BR-17: the CEN rule tests that it exists)."""
    identifier: t.Annotated[t.Annotated[Identifier, ICD_SCHEME] | None, bt("BT-60")] = None
    """Payee identifier, scheme from ISO 6523 ICD (BR-CL-10/11)."""
    legal_registration_identifier: t.Annotated[t.Annotated[Identifier, ICD_SCHEME] | None, bt("BT-61")] = None
    """Payee legal registration identifier, scheme from ISO 6523 ICD (BR-CL-11)."""


class TaxRepresentativePostalAddress(EuInvoiceModel):
    """SELLER TAX REPRESENTATIVE POSTAL ADDRESS (BG-12). Required in BG-11 (BR-19)."""

    address_line_1: t.Annotated[Text | None, bt("BT-64")] = None
    """Tax representative address line 1."""
    address_line_2: t.Annotated[Text | None, bt("BT-65")] = None
    """Tax representative address line 2."""
    address_line_3: t.Annotated[Text | None, bt("BT-164")] = None
    """Tax representative address line 3."""
    city: t.Annotated[Text | None, bt("BT-66")] = None
    """Tax representative city."""
    post_code: t.Annotated[Text | None, bt("BT-67")] = None
    """Tax representative post code."""
    country_subdivision: t.Annotated[Text | None, bt("BT-68")] = None
    """Tax representative country subdivision."""
    country_code: t.Annotated[CountryCode, bt("BT-69")]
    """Tax representative country code (BR-20)."""


class SellerTaxRepresentative(EuInvoiceModel):
    """SELLER TAX REPRESENTATIVE PARTY (BG-11)."""

    name: t.Annotated[NonBlankText, bt("BT-62")]
    """Seller tax representative name (BR-18)."""
    vat_identifier: t.Annotated[Text, bt("BT-63")]
    """Seller tax representative VAT identifier (BR-56)."""
    postal_address: t.Annotated[TaxRepresentativePostalAddress, bt("BG-12")]
    """SELLER TAX REPRESENTATIVE POSTAL ADDRESS (BR-19)."""
