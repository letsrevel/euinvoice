"""Read the UBL parties (BG-4, BG-7, BG-10, BG-11) and the delivery (BG-13, BG-15).

XPaths are those of ``docs/reference/bt-mapping.md``, mirrored from the writer (``_parties.py``).
"""

import typing as t

from lxml import etree

from euinvoice.model import (
    Buyer,
    BuyerContact,
    BuyerPostalAddress,
    DeliverToAddress,
    InvoicingPeriod,
    Payee,
    Seller,
    SellerContact,
    SellerPostalAddress,
    SellerTaxRepresentative,
    TaxRepresentativePostalAddress,
)
from euinvoice.model.delivery import DeliveryInformation
from euinvoice.syntax.ubl._build import VAT_SCHEME
from euinvoice.syntax.ubl._cursor import CAC, CBC, Cursor, build, normalize_space
from euinvoice.syntax.ubl._parties import SEPA_SCHEME, TAX_REGISTRATION_SCHEME

__all__ = ["Parties", "read_delivery", "read_parties", "take_creditor_id"]

type _Address = SellerPostalAddress | BuyerPostalAddress | TaxRepresentativePostalAddress | DeliverToAddress
type _Contact = SellerContact | BuyerContact


class Parties(t.NamedTuple):
    """The parties of one document, plus the bank assigned creditor identifier BT-90 found among them."""

    seller: Seller | None
    buyer: Buyer | None
    payee: Payee | None
    tax_representative: SellerTaxRepresentative | None
    creditor_ids: tuple[etree._Element, ...]
    """The ``cbc:ID[@schemeID='SEPA']`` elements (Payee's first), not yet taken: BT-90 is taken with
    :func:`take_creditor_id` only when PAYMENT INSTRUCTIONS (BG-16) exist to hold it."""


def read_parties(cursor: Cursor) -> Parties:
    """Read the Seller, Buyer, Payee and Seller tax representative.

    BT-90 (``cac:PartyIdentification/cbc:ID[@schemeID='SEPA']``, CEN BR-CO-26 / UBL-SR-29, issue #10) is
    read from the Payee or else the Seller. A Seller's SEPA id that differs from the Payee's has no place
    in the model and stays unmapped.

    Args:
        cursor: The document cursor.

    Returns:
        The parties; a missing mandatory party is ``None`` for the model to report.

    Raises:
        ParseError: A party is not valid.
    """
    root = cursor.root
    seller_party = cursor.first(cursor.first(root, CAC + "AccountingSupplierParty"), CAC + "Party")
    buyer_party = cursor.first(cursor.first(root, CAC + "AccountingCustomerParty"), CAC + "Party")
    payee_party = cursor.first(root, CAC + "PayeeParty")
    representative = cursor.first(root, CAC + "TaxRepresentativeParty")
    return Parties(
        seller=None if seller_party is None else _seller(cursor, seller_party),
        buyer=None if buyer_party is None else _buyer(cursor, buyer_party),
        payee=None if payee_party is None else _payee(cursor, payee_party),
        tax_representative=None if representative is None else _tax_representative(cursor, representative),
        creditor_ids=(*_sepa_ids(cursor, payee_party), *_sepa_ids(cursor, seller_party)),
    )


def take_creditor_id(cursor: Cursor, candidates: tuple[etree._Element, ...]) -> str:
    """Take BT-90 (the first candidate) and every other candidate with the same value.

    The writer puts BT-90 under one party only; a copy with the same value under the other party adds
    nothing, so it is taken too. A different value stays unmapped.

    Args:
        cursor: The document cursor.
        candidates: :attr:`Parties.creditor_ids`, not empty.

    Returns:
        BT-90.
    """
    value = candidates[0].text or ""
    for element in candidates:
        if (element.text or "") == value:
            cursor.take(element)
            cursor.attribute(element, "schemeID")
    return value


def _sepa_ids(cursor: Cursor, party: etree._Element | None) -> list[etree._Element]:
    return [
        element
        for identification in cursor.children(party, CAC + "PartyIdentification")
        for element in cursor.children(identification, CBC + "ID")
        if element.get("schemeID") == SEPA_SCHEME
    ]


def _identifications(cursor: Cursor, party: etree._Element) -> list[etree._Element]:
    """The ``cac:PartyIdentification`` elements that are not BT-90."""
    return [
        identification
        for identification in cursor.children(party, CAC + "PartyIdentification")
        if not _sepa_ids_in(identification)
    ]


def _sepa_ids_in(identification: etree._Element) -> bool:
    return any(element.get("schemeID") == SEPA_SCHEME for element in identification.iterchildren(CBC + "ID"))


def _tax_schemes(cursor: Cursor, party: etree._Element, *, other: bool = False) -> tuple[str | None, str | None]:
    """Return the VAT identifier and, if ``other``, the first other tax registration identifier of a party.

    ``cac:TaxScheme/cbc:ID`` tells them apart as the CEN binding does
    (``cac:TaxScheme/normalize-space(upper-case(cbc:ID))='VAT'``, BR-CO-09, UBL-SR-12 and UBL-SR-13 in
    ``UBL/EN16931-UBL-{model,syntax}.sch``). Only the Seller has a non-VAT term (BT-32); any further
    ``cac:PartyTaxScheme`` stays unmapped.
    """
    found: dict[bool, str] = {}
    for tax_scheme in cursor.children(party, CAC + "PartyTaxScheme"):
        company = next(tax_scheme.iterchildren(CBC + "CompanyID"), None)
        scheme = next(tax_scheme.iterchildren(CAC + "TaxScheme"), None)
        scheme_id = None if scheme is None else next(scheme.iterchildren(CBC + "ID"), None)
        if company is None or scheme_id is None:
            continue
        scheme_text = normalize_space(scheme_id.text)
        is_vat = scheme_text.upper() == VAT_SCHEME
        if is_vat in found or not (is_vat or other):
            continue
        if is_vat or scheme_text == TAX_REGISTRATION_SCHEME:  # another non-VAT scheme id is kept as unmapped
            cursor.take(scheme_id)
        found[is_vat] = cursor.text(tax_scheme, CBC + "CompanyID") or ""
    return found.get(True), found.get(False)


def _seller(cursor: Cursor, party: etree._Element) -> Seller:
    legal = cursor.first(party, CAC + "PartyLegalEntity")
    vat, tax_registration = _tax_schemes(cursor, party, other=True)
    return build(
        Seller,
        party,
        "BG-4",
        name=cursor.text(legal, CBC + "RegistrationName"),
        trading_name=cursor.text(cursor.first(party, CAC + "PartyName"), CBC + "Name"),
        identifiers=tuple(
            identifier
            for element in _identifications(cursor, party)
            if (identifier := cursor.identifier(element, CBC + "ID")) is not None
        ),
        legal_registration_identifier=cursor.identifier(legal, CBC + "CompanyID"),
        vat_identifier=vat,
        tax_registration_identifier=tax_registration,
        additional_legal_information=cursor.text(legal, CBC + "CompanyLegalForm"),
        electronic_address=cursor.identifier(party, CBC + "EndpointID"),
        postal_address=_address(cursor, party, CAC + "PostalAddress", SellerPostalAddress, "BG-5"),
        contact=_contact(cursor, party, SellerContact, "BG-6"),
    )


def _buyer(cursor: Cursor, party: etree._Element) -> Buyer:
    legal = cursor.first(party, CAC + "PartyLegalEntity")
    identifications = _identifications(cursor, party)
    return build(
        Buyer,
        party,
        "BG-7",
        name=cursor.text(legal, CBC + "RegistrationName"),
        trading_name=cursor.text(cursor.first(party, CAC + "PartyName"), CBC + "Name"),
        identifier=cursor.identifier(identifications[0], CBC + "ID") if identifications else None,
        legal_registration_identifier=cursor.identifier(legal, CBC + "CompanyID"),
        vat_identifier=_tax_schemes(cursor, party)[0],
        electronic_address=cursor.identifier(party, CBC + "EndpointID"),
        postal_address=_address(cursor, party, CAC + "PostalAddress", BuyerPostalAddress, "BG-8"),
        contact=_contact(cursor, party, BuyerContact, "BG-9"),
    )


def _payee(cursor: Cursor, party: etree._Element) -> Payee:
    identifications = _identifications(cursor, party)
    return build(
        Payee,
        party,
        "BG-10",
        name=cursor.text(cursor.first(party, CAC + "PartyName"), CBC + "Name"),
        identifier=cursor.identifier(identifications[0], CBC + "ID") if identifications else None,
        legal_registration_identifier=cursor.identifier(
            cursor.first(party, CAC + "PartyLegalEntity"), CBC + "CompanyID"
        ),
    )


def _tax_representative(cursor: Cursor, party: etree._Element) -> SellerTaxRepresentative:
    return build(
        SellerTaxRepresentative,
        party,
        "BG-11",
        name=cursor.text(cursor.first(party, CAC + "PartyName"), CBC + "Name"),
        vat_identifier=_tax_schemes(cursor, party)[0],
        postal_address=_address(cursor, party, CAC + "PostalAddress", TaxRepresentativePostalAddress, "BG-12"),
    )


def _address[A: _Address](
    cursor: Cursor, parent: etree._Element | None, tag: str, model: type[A], group: str
) -> A | None:
    element = cursor.first(parent, tag)
    if element is None:
        return None
    return build(
        model,
        element,
        group,
        address_line_1=cursor.text(element, CBC + "StreetName"),
        address_line_2=cursor.text(element, CBC + "AdditionalStreetName"),
        address_line_3=cursor.text(cursor.first(element, CAC + "AddressLine"), CBC + "Line"),
        city=cursor.text(element, CBC + "CityName"),
        post_code=cursor.text(element, CBC + "PostalZone"),
        country_subdivision=cursor.text(element, CBC + "CountrySubentity"),
        country_code=cursor.text(cursor.first(element, CAC + "Country"), CBC + "IdentificationCode"),
    )


def _contact[C: _Contact](cursor: Cursor, party: etree._Element, model: type[C], group: str) -> C | None:
    element = cursor.first(party, CAC + "Contact")
    if element is None:
        return None
    return build(
        model,
        element,
        group,
        contact_point=cursor.text(element, CBC + "Name"),
        telephone=cursor.text(element, CBC + "Telephone"),
        email=cursor.text(element, CBC + "ElectronicMail"),
    )


def read_delivery(cursor: Cursor, period: InvoicingPeriod | None) -> DeliveryInformation | None:
    """Read DELIVERY INFORMATION (BG-13) from ``cac:Delivery`` plus the document-level invoicing period.

    Args:
        cursor: The document cursor.
        period: BG-14, read from ``/*/cac:InvoicePeriod`` (the model keeps it under BG-13).

    Returns:
        BG-13, or ``None`` when neither ``cac:Delivery`` nor BG-14 carries a business term.

    Raises:
        ParseError: The delivery is not valid.
    """
    element = cursor.first(cursor.root, CAC + "Delivery")
    if element is None and period is None:
        return None
    location = cursor.first(element, CAC + "DeliveryLocation")
    delivery = build(
        DeliveryInformation,
        element if element is not None else cursor.root,
        "BG-13",
        deliver_to_party_name=cursor.text(
            cursor.first(cursor.first(element, CAC + "DeliveryParty"), CAC + "PartyName"), CBC + "Name"
        ),
        deliver_to_location_identifier=cursor.identifier(location, CBC + "ID"),
        actual_delivery_date=cursor.date(element, CBC + "ActualDeliveryDate", "BT-72"),
        invoicing_period=period,
        deliver_to_address=_address(cursor, location, CAC + "Address", DeliverToAddress, "BG-15"),
    )
    return None if delivery == DeliveryInformation() else delivery  # an empty cac:Delivery stays unmapped
