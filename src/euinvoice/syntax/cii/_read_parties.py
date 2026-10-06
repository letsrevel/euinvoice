"""Reading CII trade parties: Seller BG-4, Buyer BG-7, Seller tax representative BG-11, Payee BG-10, ship-to.

The inverse of ``_parties.py``; XPaths per business term are those of ``docs/reference/bt-mapping.md`` (KoSIT
XRechnung visualization ``cii-xr.xsl``).
"""

from lxml import etree

from euinvoice.model import (
    Buyer,
    BuyerContact,
    BuyerPostalAddress,
    DeliverToAddress,
    Identifier,
    Payee,
    Seller,
    SellerContact,
    SellerPostalAddress,
    SellerTaxRepresentative,
    TaxRepresentativePostalAddress,
)
from euinvoice.syntax.cii._build import FISCAL_SCHEME, VAT_SCHEME
from euinvoice.syntax.cii._reader import Reader, content

type _Address = SellerPostalAddress | BuyerPostalAddress | TaxRepresentativePostalAddress | DeliverToAddress


def address[A: _Address](reader: Reader, party: etree._Element, cls: type[A]) -> A | None:
    """``ram:PostalTradeAddress`` (BG-5, BG-8, BG-12, BG-15): ``LineOne``..``LineThree`` are address lines 1-3."""
    element = reader.one(party, "PostalTradeAddress")
    if element is None:
        return None
    return reader.model(
        cls,
        element,
        post_code=reader.text(element, "PostcodeCode"),
        address_line_1=reader.text(element, "LineOne"),
        address_line_2=reader.text(element, "LineTwo"),
        address_line_3=reader.text(element, "LineThree"),
        city=reader.text(element, "CityName"),
        country_code=reader.text(element, "CountryID"),
        country_subdivision=reader.text(element, "CountrySubDivisionName"),
    )


def party_ids(reader: Reader, party: etree._Element) -> list[Identifier]:
    """Every ``ram:ID`` then every ``ram:GlobalID`` of a party (BT-29, BT-46, BT-60, BT-71), with ``@schemeID``.

    The KoSIT binding of these terms is ``ram:ID`` or ``ram:GlobalID[exists(@schemeID)]``.
    """
    return [reader.identifier(e) for name in ("ID", "GlobalID") for e in reader.each(party, name)]


def single_id(reader: Reader, party: etree._Element) -> Identifier | None:
    """The first party identifier (BT-46, BT-60, BT-71 occur once); further ones stay unmapped."""
    for name in ("ID", "GlobalID"):
        element = reader.one(party, name)
        if element is not None:
            return reader.identifier(element)
    return None


def _legal(reader: Reader, party: etree._Element, *, trading: bool) -> tuple[Identifier | None, str | None]:
    """``ram:SpecifiedLegalOrganization``: ``ram:ID`` (BT-30/47/61) and ``TradingBusinessName`` (BT-28/45).

    The Payee has no trading name (``trading`` false), so there ``TradingBusinessName`` stays unmapped.
    """
    element = reader.one(party, "SpecifiedLegalOrganization")
    legal_id = reader.one(element, "ID")
    return (
        None if legal_id is None else reader.identifier(legal_id),
        reader.text(element, "TradingBusinessName") if trading else None,
    )


def _contact[C: (SellerContact, BuyerContact)](reader: Reader, party: etree._Element, cls: type[C]) -> C | None:
    """``ram:DefinedTradeContact`` (BG-6, BG-9); the contact point is ``ram:PersonName`` or ``ram:DepartmentName``.

    When both are present, ``ram:PersonName`` is taken (as the writer writes it) and ``ram:DepartmentName`` is
    left unmapped.
    """
    element = reader.one(party, "DefinedTradeContact")
    if element is None:
        return None
    point = reader.text(element, "PersonName")
    if point is None:
        point = reader.text(element, "DepartmentName")
    return reader.model(
        cls,
        element,
        contact_point=point,
        telephone=reader.text(reader.one(element, "TelephoneUniversalCommunication"), "CompleteNumber"),
        email=reader.text(reader.one(element, "EmailURIUniversalCommunication"), "URIID"),
    )


def _electronic_address(reader: Reader, party: etree._Element) -> Identifier | None:
    """``ram:URIUniversalCommunication/ram:URIID[@schemeID]`` (BT-34, BT-49)."""
    element = reader.one(reader.one(party, "URIUniversalCommunication"), "URIID")
    return None if element is None else reader.identifier(element)


def _tax_registrations(reader: Reader, party: etree._Element, schemes: tuple[str, ...]) -> dict[str, str]:
    """``ram:SpecifiedTaxRegistration/ram:ID`` by ``@schemeID``: ``VA`` (BT-31, BT-48, BT-63), ``FC`` (BT-32).

    The first registration of each of ``schemes`` is mapped; any other stays unmapped (BR-56 and BR-AF-02 select
    ``ram:ID[@schemeID='VA']`` and ``'FC'``).
    """
    found: dict[str, str] = {}
    for registration in reader.children(party, "SpecifiedTaxRegistration"):
        ids = reader.children(registration, "ID")
        element = ids[0] if ids else None
        scheme = None if element is None else element.get("schemeID")
        if element is None or scheme is None or scheme not in schemes or scheme in found:
            continue
        reader.use(registration)
        reader.use(element)
        reader.attribute(element, "schemeID")
        found[scheme] = content(element)
    return found


def seller(reader: Reader, agreement: etree._Element | None) -> Seller | None:
    """``ram:SellerTradeParty`` (BG-4)."""
    element = reader.one(agreement, "SellerTradeParty")
    if element is None:
        return None
    legal_id, trading_name = _legal(reader, element, trading=True)
    taxes = _tax_registrations(reader, element, (VAT_SCHEME, FISCAL_SCHEME))
    return reader.model(
        Seller,
        element,
        identifiers=tuple(party_ids(reader, element)),
        name=reader.text(element, "Name"),
        additional_legal_information=reader.text(element, "Description"),
        legal_registration_identifier=legal_id,
        trading_name=trading_name,
        contact=_contact(reader, element, SellerContact),
        postal_address=address(reader, element, SellerPostalAddress),
        electronic_address=_electronic_address(reader, element),
        vat_identifier=taxes.get(VAT_SCHEME),
        tax_registration_identifier=taxes.get(FISCAL_SCHEME),
    )


def buyer(reader: Reader, agreement: etree._Element | None) -> Buyer | None:
    """``ram:BuyerTradeParty`` (BG-7); a ``FC`` tax registration has no business term here and stays unmapped."""
    element = reader.one(agreement, "BuyerTradeParty")
    if element is None:
        return None
    legal_id, trading_name = _legal(reader, element, trading=True)
    taxes = _tax_registrations(reader, element, (VAT_SCHEME,))
    return reader.model(
        Buyer,
        element,
        identifier=single_id(reader, element),
        name=reader.text(element, "Name"),
        legal_registration_identifier=legal_id,
        trading_name=trading_name,
        contact=_contact(reader, element, BuyerContact),
        postal_address=address(reader, element, BuyerPostalAddress),
        electronic_address=_electronic_address(reader, element),
        vat_identifier=taxes.get(VAT_SCHEME),
    )


def tax_representative(reader: Reader, agreement: etree._Element | None) -> SellerTaxRepresentative | None:
    """``ram:SellerTaxRepresentativeTradeParty`` (BG-11)."""
    element = reader.one(agreement, "SellerTaxRepresentativeTradeParty")
    if element is None:
        return None
    return reader.model(
        SellerTaxRepresentative,
        element,
        name=reader.text(element, "Name"),
        postal_address=address(reader, element, TaxRepresentativePostalAddress),
        vat_identifier=_tax_registrations(reader, element, (VAT_SCHEME,)).get(VAT_SCHEME),
    )


def payee(reader: Reader, settlement: etree._Element | None) -> Payee | None:
    """``ram:PayeeTradeParty`` (BG-10)."""
    element = reader.one(settlement, "PayeeTradeParty")
    if element is None:
        return None
    legal_id, _ = _legal(reader, element, trading=False)
    return reader.model(
        Payee,
        element,
        identifier=single_id(reader, element),
        name=reader.text(element, "Name"),
        legal_registration_identifier=legal_id,
    )
