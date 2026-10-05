"""CII trade parties: Seller BG-4, Buyer BG-7, Seller tax representative BG-11, Payee BG-10, ship-to BG-13.

Children of ``ram:TradePartyType`` follow its D16B XSD sequence: ``ID``, ``GlobalID``, ``Name``,
``Description``, ``SpecifiedLegalOrganization``, ``DefinedTradeContact``, ``PostalTradeAddress``,
``URIUniversalCommunication``, ``SpecifiedTaxRegistration``. XPaths per business term are those of
``docs/reference/bt-mapping.md`` (KoSIT XRechnung visualization ``cii-xr.xsl``).
"""

from lxml import etree

from euinvoice.model import (
    Buyer,
    BuyerContact,
    BuyerPostalAddress,
    DeliverToAddress,
    DeliveryInformation,
    Identifier,
    Payee,
    Seller,
    SellerContact,
    SellerPostalAddress,
    SellerTaxRepresentative,
    TaxRepresentativePostalAddress,
)
from euinvoice.syntax.cii._build import identifier, opt, party_id, sub

_Address = SellerPostalAddress | BuyerPostalAddress | TaxRepresentativePostalAddress | DeliverToAddress

VAT_SCHEME: str = "VA"
"""``@schemeID`` of a VAT identifier (BT-31, BT-48, BT-63): BR-56 and BR-AF-02 select ``ram:ID[@schemeID='VA']``."""
FISCAL_SCHEME: str = "FC"
"""``@schemeID`` of the Seller tax registration identifier (BT-32), selected as ``'FC'`` by BR-AF-02 etc."""


def address(parent: etree._Element, value: _Address) -> None:
    """Append ``ram:PostalTradeAddress`` (BG-5, BG-8, BG-12, BG-15) in ``ram:TradeAddressType`` order.

    ``LineOne``/``LineTwo``/``LineThree`` carry address lines 1-3: CII-DT-088 and CII-DT-096 forbid
    ``StreetName`` and ``AdditionalStreetName``.
    """
    element = sub(parent, "PostalTradeAddress")
    opt(element, "PostcodeCode", value.post_code)
    opt(element, "LineOne", value.address_line_1)
    opt(element, "LineTwo", value.address_line_2)
    opt(element, "LineThree", value.address_line_3)
    opt(element, "CityName", value.city)
    sub(element, "CountryID", value.country_code)
    opt(element, "CountrySubDivisionName", value.country_subdivision)


def _legal_organization(parent: etree._Element, legal_id: Identifier | None, trading_name: str | None) -> None:
    """``ram:SpecifiedLegalOrganization``: ``ram:ID`` (BT-30/47/61) then ``TradingBusinessName`` (BT-28/45)."""
    if legal_id is None and trading_name is None:
        return
    element = sub(parent, "SpecifiedLegalOrganization")
    if legal_id is not None:
        identifier(element, "ID", legal_id)
    opt(element, "TradingBusinessName", trading_name)


def _contact(parent: etree._Element, value: SellerContact | BuyerContact | None) -> None:
    """``ram:DefinedTradeContact`` (BG-6, BG-9).

    The contact point (BT-41, BT-56) is bound to ``ram:PersonName`` or ``ram:DepartmentName``; it is
    written as ``ram:PersonName``, as in the KoSIT testsuite (``01.02_comprehensive_test_uncefact.xml``).
    """
    if value is None:
        return
    element = sub(parent, "DefinedTradeContact")
    opt(element, "PersonName", value.contact_point)
    if value.telephone is not None:
        sub(sub(element, "TelephoneUniversalCommunication"), "CompleteNumber", value.telephone)
    if value.email is not None:
        sub(sub(element, "EmailURIUniversalCommunication"), "URIID", value.email)


def _electronic_address(parent: etree._Element, value: Identifier | None) -> None:
    """``ram:URIUniversalCommunication/ram:URIID[@schemeID]`` (BT-34, BT-49; BR-62, BR-63, BR-CL-25)."""
    if value is not None:
        identifier(sub(parent, "URIUniversalCommunication"), "URIID", value)


def _tax_registration(parent: etree._Element, value: str | None, scheme: str) -> None:
    if value is not None:
        sub(sub(parent, "SpecifiedTaxRegistration"), "ID", value, schemeID=scheme)


def seller(parent: etree._Element, value: Seller) -> None:
    """Append ``ram:SellerTradeParty`` (BG-4).

    BT-29 repeats (``ram:ID`` and ``ram:GlobalID`` are both 0..n); identifiers without a scheme come first
    because the XSD sequence puts ``ram:ID`` before ``ram:GlobalID``.
    """
    element = sub(parent, "SellerTradeParty")
    for item in sorted(value.identifiers, key=lambda i: i.scheme_id is not None):
        party_id(element, item)
    sub(element, "Name", value.name)
    opt(element, "Description", value.additional_legal_information)
    _legal_organization(element, value.legal_registration_identifier, value.trading_name)
    _contact(element, value.contact)
    address(element, value.postal_address)
    _electronic_address(element, value.electronic_address)
    _tax_registration(element, value.vat_identifier, VAT_SCHEME)
    _tax_registration(element, value.tax_registration_identifier, FISCAL_SCHEME)


def buyer(parent: etree._Element, value: Buyer) -> None:
    """Append ``ram:BuyerTradeParty`` (BG-7)."""
    element = sub(parent, "BuyerTradeParty")
    if value.identifier is not None:
        party_id(element, value.identifier)
    sub(element, "Name", value.name)
    _legal_organization(element, value.legal_registration_identifier, value.trading_name)
    _contact(element, value.contact)
    address(element, value.postal_address)
    _electronic_address(element, value.electronic_address)
    _tax_registration(element, value.vat_identifier, VAT_SCHEME)


def tax_representative(parent: etree._Element, value: SellerTaxRepresentative) -> None:
    """Append ``ram:SellerTaxRepresentativeTradeParty`` (BG-11)."""
    element = sub(parent, "SellerTaxRepresentativeTradeParty")
    sub(element, "Name", value.name)
    address(element, value.postal_address)
    _tax_registration(element, value.vat_identifier, VAT_SCHEME)


def payee(parent: etree._Element, value: Payee) -> None:
    """Append ``ram:PayeeTradeParty`` (BG-10)."""
    element = sub(parent, "PayeeTradeParty")
    if value.identifier is not None:
        party_id(element, value.identifier)
    sub(element, "Name", value.name)
    _legal_organization(element, value.legal_registration_identifier, None)


def ship_to(parent: etree._Element, value: DeliveryInformation) -> None:
    """Append ``ram:ShipToTradeParty`` (BT-70, BT-71, BG-15) when any of them is set."""
    parts = (value.deliver_to_party_name, value.deliver_to_location_identifier, value.deliver_to_address)
    if all(part is None for part in parts):
        return
    element = sub(parent, "ShipToTradeParty")
    if value.deliver_to_location_identifier is not None:
        party_id(element, value.deliver_to_location_identifier)
    opt(element, "Name", value.deliver_to_party_name)
    if value.deliver_to_address is not None:
        address(element, value.deliver_to_address)
