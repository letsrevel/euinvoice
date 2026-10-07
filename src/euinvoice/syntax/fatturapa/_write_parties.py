"""The FPR12 header parties: 1.2 ``<CedentePrestatore>`` (BG-4) and 1.4 ``<CessionarioCommittente>`` (BG-7).

Element order follows ``CedentePrestatoreType``, ``DatiAnagraficiCedenteType``, ``CessionarioCommittenteType``,
``DatiAnagraficiCessionarioType``, ``AnagraficaType``, ``IndirizzoType`` and ``ContattiType`` of the pinned XSD
1.2.3. Rows cited are App. 4.1 of the SdI "Regole tecniche fatture europee" v2.6.

For a TD17 the EN seller is the foreign supplier and the EN buyer the Italian party that issues the document; both
map as for any other document (App. 4.1 has no TD-specific rows), and 1.6 SoggettoEmittente says who issued it.
"""

import re
import typing as t

from lxml import etree

from euinvoice.model import Buyer, BuyerPostalAddress, Identifier, Invoice, Seller, SellerPostalAddress
from euinvoice.model.it import ItalianExtension
from euinvoice.syntax.fatturapa._write_format import BASIC, cannot_express, child, matching, text

__all__ = ["write_buyer", "write_seller"]

ITALY: t.Final = "IT"
CODICE_FISCALE_SCHEME: t.Final = "0210"
"""ICD scheme of the Italian codice fiscale (App. 4.1 rows 1.2.1.2 and 1.4.1.2: "schemeIdentifier ... 0210")."""
CODICE_FISCALE_PREFIX: t.Final = "CF:"
"""The prefix App. 4.1 rows 1.2.1.2 and 1.4.1.2 put before a codice fiscale in BT-30 / BT-47."""

_COUNTRY: t.Final = "[A-Z]{2}"  # NazioneType
_CODICE_FISCALE: t.Final = "[A-Z0-9]{11,16}"  # CodiceFiscaleType
_CAP: t.Final = "[0-9]{5}"  # CAPType
_PROVINCIA: t.Final = "[A-Z]{2}"  # ProvinciaType
_EMAIL: t.Final = re.compile(r"[^\n\r]+@[^\n\r]+[.]+[^\n\r]+")  # EmailContattiType .+@.+[.]+.+ (XSD '.': no CR/LF)


def _vat(parent: etree._Element, value: str, term: str) -> None:
    """IdFiscaleIVA (``IdFiscaleType``): App. 4.1 concatenates IdPaese and IdCodice into the VAT identifier."""
    country, code = value[:2], value[2:]
    vat = child(parent, "IdFiscaleIVA")
    child(vat, "IdPaese", matching(country, _COUNTRY, term, "IdPaese, the first two characters (NazioneType)"))
    if not 1 <= len(code) <= 28:
        raise cannot_express(
            term, f"IdCodice, the characters after the country code, takes 1 to 28 (CodiceType), got {len(code)}"
        )
    child(vat, "IdCodice", code)


def _codice_fiscale(parent: etree._Element, identifier: Identifier | None, term: str) -> None:
    """CodiceFiscale from a legal registration identifier with scheme 0210 or the ``CF:`` prefix.

    Rows 1.2.1.2 and 1.4.1.2; any other identifier has no FatturaPA element.
    """
    if identifier is None:
        return
    value = identifier.value
    if identifier.scheme_id is None and value.startswith(CODICE_FISCALE_PREFIX):
        value = value.removeprefix(CODICE_FISCALE_PREFIX)
    elif identifier.scheme_id != CODICE_FISCALE_SCHEME:
        raise cannot_express(
            term,
            f"only a codice fiscale is written (CodiceFiscale): scheme {CODICE_FISCALE_SCHEME} or the prefix "
            f"{CODICE_FISCALE_PREFIX!r}; got scheme {identifier.scheme_id!r}",
        )
    child(parent, "CodiceFiscale", matching(value, _CODICE_FISCALE, term, "CodiceFiscale (CodiceFiscaleType)"))


def _anagrafica(parent: etree._Element, name: str, term: str) -> None:
    # ponytail: always Denominazione. Allegato A asks for Nome and Cognome for natural persons, and App. 4.1 only
    # describes the reverse concatenation ("Nome&Cognome" or "Nome#Cognome"); how to split a name is a #115
    # decision 5 policy (#133). Upgrade path: a name split on Invoice.it.
    child(
        child(parent, "Anagrafica"), "Denominazione", text(name, term, "Denominazione (String80LatinType)", maximum=80)
    )


def _address(
    parent: etree._Element, address: SellerPostalAddress | BuyerPostalAddress, ids: tuple[str, ...], prefix: str
) -> None:
    """``IndirizzoType`` (rows 1.2.2.x / 1.4.2.x).

    ``ids`` are the BTs of line 1, line 2, city, post code, subdivision and country. Preflight reports the required
    ones that are missing.
    """
    line_1, line_2, city, post_code, subdivision, country = ids
    sede = child(parent, "Sede")
    child(
        sede,
        "Indirizzo",
        text(
            address.address_line_1 or "",
            f"{line_1} ({prefix}.address_line_1)",
            "Indirizzo (String60LatinType)",
            maximum=60,
        ),
    )
    if address.address_line_2 is not None:
        child(
            sede,
            "NumeroCivico",
            text(
                address.address_line_2,
                f"{line_2} ({prefix}.address_line_2)",
                "NumeroCivico (NumeroCivicoType)",
                maximum=8,
                charset=BASIC,
            ),
        )
    # ponytail: CAPType is five digits for every country; the sources give no convention for a foreign post code
    # (#133), so one that does not fit is refused.
    child(sede, "CAP", matching(address.post_code or "", _CAP, f"{post_code} ({prefix}.post_code)", "CAP (CAPType)"))
    child(sede, "Comune", text(address.city or "", f"{city} ({prefix}.city)", "Comune (String60LatinType)", maximum=60))
    if address.country_subdivision is not None:
        term = f"{subdivision} ({prefix}.country_subdivision)"
        # Allegato A 1.9.1, Sede/Provincia: "da valorizzare nei soli casi di sede in Italia".
        if address.country_code != ITALY:
            raise cannot_express(term, "Provincia is given only for an address in Italy (Allegato A 1.9.1)")
        child(sede, "Provincia", matching(address.country_subdivision, _PROVINCIA, term, "Provincia (ProvinciaType)"))
    child(
        sede,
        "Nazione",
        matching(address.country_code, _COUNTRY, f"{country} ({prefix}.country_code)", "Nazione (NazioneType)"),
    )


def write_seller(header: etree._Element, invoice: Invoice, it: ItalianExtension) -> None:
    """1.2 CedentePrestatore from the SELLER (BG-4) and ``it.tax_regime``."""
    seller: Seller = invoice.seller
    party = child(header, "CedentePrestatore")
    data = child(party, "DatiAnagrafici")
    _vat(data, seller.vat_identifier or "", "BT-31 (seller.vat_identifier)")
    _codice_fiscale(data, seller.legal_registration_identifier, "BT-30 (seller.legal_registration_identifier)")
    _anagrafica(data, seller.name, "BT-27 (seller.name)")
    child(data, "RegimeFiscale", it.tax_regime)
    _address(
        party, seller.postal_address, ("BT-35", "BT-36", "BT-37", "BT-38", "BT-39", "BT-40"), "seller.postal_address"
    )
    contact = seller.contact
    if contact is not None and (contact.telephone is not None or contact.email is not None):
        contatti = child(party, "Contatti")
        if contact.telephone is not None:
            child(
                contatti,
                "Telefono",
                text(
                    contact.telephone,
                    "BT-42 (seller.contact.telephone)",
                    "Telefono (TelFaxType)",
                    minimum=5,
                    maximum=12,
                    charset=BASIC,
                ),
            )
        if contact.email is not None:
            if not 7 <= len(contact.email) <= 256 or not _EMAIL.fullmatch(contact.email):
                raise cannot_express(
                    "BT-43 (seller.contact.email)",
                    "Email (EmailContattiType) takes 7 to 256 characters matching .+@.+[.]+.+",
                )
            child(contatti, "Email", contact.email)
    if invoice.buyer_accounting_reference is not None:
        child(
            party,
            "RiferimentoAmministrazione",
            text(
                invoice.buyer_accounting_reference,
                "BT-19 (buyer_accounting_reference)",
                "RiferimentoAmministrazione (String20Type)",
                maximum=20,
                charset=BASIC,
            ),
        )


def write_buyer(header: etree._Element, invoice: Invoice) -> None:
    """1.4 CessionarioCommittente from the BUYER (BG-7)."""
    buyer: Buyer = invoice.buyer
    party = child(header, "CessionarioCommittente")
    data = child(party, "DatiAnagrafici")
    if buyer.vat_identifier is not None:
        _vat(data, buyer.vat_identifier, "BT-48 (buyer.vat_identifier)")
    _codice_fiscale(data, buyer.legal_registration_identifier, "BT-47 (buyer.legal_registration_identifier)")
    _anagrafica(data, buyer.name, "BT-44 (buyer.name)")
    _address(
        party, buyer.postal_address, ("BT-50", "BT-51", "BT-52", "BT-53", "BT-54", "BT-55"), "buyer.postal_address"
    )
