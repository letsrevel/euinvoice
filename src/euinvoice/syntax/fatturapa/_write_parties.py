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
from euinvoice.syntax.fatturapa._write_refuse import codice_fiscale

__all__ = ["write_buyer", "write_seller"]

ITALY: t.Final = "IT"

_COUNTRY: t.Final = "[A-Z]{2}"  # NazioneType
_CODICE_FISCALE: t.Final = "[A-Z0-9]{11,16}"  # CodiceFiscaleType
_CAP: t.Final = "[0-9]{5}"  # CAPType
FOREIGN_CAP: t.Final = "00000"
"""The generic CAP for an address outside Italy whose post code is not five digits.

CAPType is ``[0-9]{5}`` and the technical rules have no foreign-address rule; Agenzia delle Entrate states the
convention in its FAQ compendium "Risposte alle domande più frequenti sulla fatturazione elettronica, aggiornato al
22 dicembre 2022" (sha256 763eec5617275d45b64fe35c6f99f8434649df5645abc0e38b63cc2d6b6a1862): FAQ n. 63 (pp. 27-28)
"il campo CAP andrà compilato con il valore generico 00000. Si potrà utilizzare l'indirizzo per indicare il CAP
straniero", and FAQ n. 74 (pp. 33-34) "si consiglia di utilizzare il codice convenzionale". A five-digit foreign code
is kept (the FAQ does not forbid it). The reader maps ``00000`` outside Italy back to no post code.
"""
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

    Rows 1.2.1.2 and 1.4.1.2; the pre-flight refuses any other identifier.
    """
    if identifier is None:
        return
    value = codice_fiscale(identifier)
    child(parent, "CodiceFiscale", matching(value, _CODICE_FISCALE, term, "CodiceFiscale (CodiceFiscaleType)"))


def _anagrafica(parent: etree._Element, it: ItalianExtension, *, party: str, name: str, term: str) -> None:
    """``AnagraficaType`` choice: ``Nome`` + ``Cognome`` of a natural person, else ``Denominazione`` = BT-27 / BT-44.

    Allegato A 1.9.1 (pp. 33 and 38) reserves ``Denominazione`` for a "persona non fisica".
    ``party`` (``seller`` or ``buyer``)
    names the pair in ``Invoice.it``; the pre-flight checks that the BT is ``Nome Cognome``.
    """
    anagrafica = child(parent, "Anagrafica")
    first, last = getattr(it, f"{party}_first_name"), getattr(it, f"{party}_last_name")
    if first is None or last is None:  # the extension sets both or neither
        child(anagrafica, "Denominazione", text(name, term, "Denominazione (String80LatinType)", maximum=80))
        return
    child(anagrafica, "Nome", text(first, f"it.{party}_first_name", "Nome (String60LatinType)", maximum=60))
    child(anagrafica, "Cognome", text(last, f"it.{party}_last_name", "Cognome (String60LatinType)", maximum=60))


def post_code_replaced(address: SellerPostalAddress | BuyerPostalAddress) -> bool:
    """Whether the writer replaces a post code of the address with :data:`FOREIGN_CAP` and so drops its value."""
    code = address.post_code
    # a genuine foreign 00000 reads back as no post code, so it counts as replaced too
    return (
        address.country_code != ITALY and code is not None and (code == FOREIGN_CAP or re.fullmatch(_CAP, code) is None)
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
    # Outside Italy a post code that is not five digits (or is absent) becomes 00000 (FAQ n. 63 / n. 74, see
    # FOREIGN_CAP). ponytail: the real code is not carried in Indirizzo (the FAQ says "si potrà", and a suffix in a
    # 60-character free-text line cannot be told from the street on the way back); the pre-flight warns instead.
    # Upgrade path: a post-code field on Invoice.it.
    if address.country_code != ITALY and (address.post_code is None or post_code_replaced(address)):
        cap = FOREIGN_CAP
    else:
        cap = matching(address.post_code or "", _CAP, f"{post_code} ({prefix}.post_code)", "CAP (CAPType)")
    child(sede, "CAP", cap)
    child(sede, "Comune", text(address.city or "", f"{city} ({prefix}.city)", "Comune (String60LatinType)", maximum=60))
    if address.country_subdivision is not None:
        term = f"{subdivision} ({prefix}.country_subdivision)"
        # Provincia is an Italian province code: for the cedente Allegato A 1.9.1 (Sede/Provincia: "da valorizzare nei
        # soli casi di sede in Italia") and CIUS-IT BR-IT-DC-150 (BT-39); for the cessionario BR-IT-220 (BT-54: "deve
        # essere utilizzato uno dei valori della lista delle province italiane"), App. 2 of the Regole tecniche v2.6.
        if address.country_code != ITALY:
            source = "Allegato A 1.9.1, BR-IT-DC-150" if subdivision == "BT-39" else "BR-IT-220"
            raise cannot_express(
                term, f"Provincia is an Italian province, given only for an address in Italy ({source})"
            )
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
    _anagrafica(data, it, party="seller", name=seller.name, term="BT-27 (seller.name)")
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


def write_buyer(header: etree._Element, invoice: Invoice, it: ItalianExtension) -> None:
    """1.4 CessionarioCommittente from the BUYER (BG-7)."""
    buyer: Buyer = invoice.buyer
    party = child(header, "CessionarioCommittente")
    data = child(party, "DatiAnagrafici")
    if buyer.vat_identifier is not None:
        _vat(data, buyer.vat_identifier, "BT-48 (buyer.vat_identifier)")
    _codice_fiscale(data, buyer.legal_registration_identifier, "BT-47 (buyer.legal_registration_identifier)")
    _anagrafica(data, it, party="buyer", name=buyer.name, term="BT-44 (buyer.name)")
    _address(
        party, buyer.postal_address, ("BT-50", "BT-51", "BT-52", "BT-53", "BT-54", "BT-55"), "buyer.postal_address"
    )
