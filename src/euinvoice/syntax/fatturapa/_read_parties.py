"""FatturaPA header parties → SELLER (BG-4) and BUYER (BG-7), App. 4.1 of the Regole tecniche v2.6 in reverse.

Row ids are those of the Rappresentazione tabellare (``1.2.x`` CedentePrestatore, ``1.4.x`` CessionarioCommittente).
Elements App. 4.1 marks "Mappatura non considerabile" or EXT without a model home (Titolo, StabileOrganizzazione,
IscrizioneREA, the Albo data, Fax, the buyer's RappresentanteFiscale) stay unmarked, so they are reported.
"""

import pydantic
from lxml import etree

from euinvoice.errors import ParseError
from euinvoice.model import (
    Buyer,
    BuyerPostalAddress,
    Seller,
    SellerContact,
    SellerPostalAddress,
)
from euinvoice.model.it.extension import Latin60Text
from euinvoice.syntax._read_errors import build
from euinvoice.syntax.fatturapa._read_cursor import Cursor

__all__ = ["CODICE_FISCALE", "buyer", "person_names", "post_code", "seller"]

CODICE_FISCALE = "0210"
"""ISO 6523 ICD of the Italian codice fiscale: App. 4.1 rows 1.2.1.2 and 1.4.1.2 ("schemeIdentifier … 0210")."""


def seller(cursor: Cursor, header: etree._Element) -> Seller:
    """1.2 ``CedentePrestatore`` → BG-4 (App. 4.1)."""
    party = cursor.one(header, "CedentePrestatore")
    data = cursor.one(party, "DatiAnagrafici")
    contacts = cursor.one(party, "Contatti")
    contact = None
    if contacts is not None:
        phone, email = cursor.text(contacts, "Telefono"), cursor.text(contacts, "Email")  # 1.2.5.1 BT-42, 1.2.5.3 BT-43
        if phone is not None or email is not None:
            contact = build(SellerContact, contacts, {"telephone": phone, "email": email})
    values = {
        "name": _name(cursor, data),  # 1.2.1.3.1-3 → BT-27
        "identifiers": _eori(cursor, data),  # 1.2.1.3.5 → BT-29
        "legal_registration_identifier": _fiscal_code(cursor, data),  # 1.2.1.2 → BT-30
        "vat_identifier": _vat(cursor, data),  # 1.2.1.1 → BT-31
        "postal_address": _address(cursor, party, SellerPostalAddress),  # 1.2.2 → BG-5
        "contact": contact,
        # 1.2.6 RiferimentoAmministrazione → BT-19 is a document term; read in _read.py.
    }
    # A missing party leaves the model's required fields empty; build() then names them (BR-06 …) at the header.
    return build(Seller, header if party is None else party, values)


def buyer(cursor: Cursor, header: etree._Element) -> Buyer:
    """1.4 ``CessionarioCommittente`` → BG-7 (App. 4.1)."""
    party = cursor.one(header, "CessionarioCommittente")
    data = cursor.one(party, "DatiAnagrafici")
    eori = _eori(cursor, data)
    values = {
        "name": _name(cursor, data),  # 1.4.1.3.1-3 → BT-44
        "identifier": eori[0] if eori else None,  # 1.4.1.3.5 → BT-46
        "legal_registration_identifier": _fiscal_code(cursor, data),  # 1.4.1.2 → BT-47
        "vat_identifier": _vat(cursor, data),  # 1.4.1.1 → BT-48
        "postal_address": _address(cursor, party, BuyerPostalAddress),  # 1.4.2 → BG-8
    }
    return build(Buyer, header if party is None else party, values)


def _vat(cursor: Cursor, data: etree._Element | None) -> str | None:
    """``IdFiscaleIVA`` → ``IdPaese`` + ``IdCodice`` (App. 4.1: "In BT-31 [BT-48] vengono concatenati")."""
    vat = cursor.one(data, "IdFiscaleIVA")
    if vat is None:
        return None
    country, code = cursor.text(vat, "IdPaese"), cursor.text(vat, "IdCodice")
    return f"{country or ''}{code or ''}"


def _fiscal_code(cursor: Cursor, data: etree._Element | None) -> dict[str, str] | None:
    """``CodiceFiscale`` → BT-30 / BT-47 with scheme 0210 (App. 4.1 rows 1.2.1.2, 1.4.1.2)."""
    code = cursor.text(data, "CodiceFiscale")
    return None if code is None else {"value": code, "scheme_id": CODICE_FISCALE}


def _eori(cursor: Cursor, data: etree._Element | None) -> tuple[dict[str, str], ...]:
    """``Anagrafica/CodEORI`` → BT-29 / BT-46 as ``EORI:`` + the code (App. 4.1 rows 1.2.1.3.5, 1.4.1.3.5)."""
    code = cursor.text(cursor.one(data, "Anagrafica"), "CodEORI")
    return () if code is None else ({"value": f"EORI:{code}"},)


def _name(cursor: Cursor, data: etree._Element | None) -> str | None:
    """``Anagrafica`` → the party name: ``Denominazione``, else ``Nome Cognome``.

    App. 4.1 folds ``Nome`` and ``Cognome`` into one BT, so the name is ``Nome Cognome`` (policy item 2 of #132);
    :func:`person_names` keeps the split in ``Invoice.it`` (#150). App. 4.1 rows 1.2.1.3.1-3 / 1.4.1.3.1-3 also
    prefix the BT with ``Denominazione:`` or ``Nome#Cognome:``, the CIUS-IT marker of which form a name takes
    (BR-IT-091, BR-IT-171); the reader keeps the plain name, as its BT-24 claims no CIUS-IT (``_read``). ``EORI:``
    stays: it is part of the BT-29 / BT-46 identifier's value, which carries no scheme.
    """
    registry = cursor.one(data, "Anagrafica")
    name = cursor.text(registry, "Denominazione")
    if name is not None:
        return name
    parts = [part for part in (cursor.text(registry, "Nome"), cursor.text(registry, "Cognome")) if part is not None]
    return " ".join(parts) if parts else None


_LATIN_60: pydantic.TypeAdapter[str] = pydantic.TypeAdapter(Latin60Text)


def person_names(cursor: Cursor, header: etree._Element, party: str) -> dict[str, str | None]:
    """The ``Invoice.it`` name split of a natural person: ``Nome`` and ``Cognome`` of ``party`` (#150).

    Args:
        cursor: The reading cursor.
        header: The ``FatturaElettronicaHeader``.
        party: ``"CedentePrestatore"`` (1.2.1.3.2-3) or ``"CessionarioCommittente"`` (1.4.1.3.2-3).

    Returns:
        The ``it`` fields (``seller_*`` or ``buyer_*``): empty for a ``Denominazione`` (a "persona non fisica").

    Raises:
        ParseError: A part does not fit String60LatinType, or only one of the two is given.
    """
    registry = cursor.one(cursor.one(cursor.one(header, party), "DatiAnagrafici"), "Anagrafica")
    if cursor.children(registry, "Denominazione"):
        return {}
    prefix, ids = (
        ("seller", ("1.2.1.3.2", "1.2.1.3.3"))
        if party == "CedentePrestatore"
        else ("buyer", ("1.4.1.3.2", "1.4.1.3.3"))
    )
    found: dict[str, str | None] = {}
    for field, tag, ident in (("first_name", "Nome", ids[0]), ("last_name", "Cognome", ids[1])):
        element = cursor.one(registry, tag)
        if element is None:
            continue
        try:
            found[f"{prefix}_{field}"] = _LATIN_60.validate_python(element.text or "")
        except pydantic.ValidationError as exc:
            raise ParseError(f"{ident} {tag}: {exc.errors()[0]['msg']}", location=cursor.path(element)) from None
    if len(found) == 1 and registry is not None:
        missing, ident = ("Cognome", ids[1]) if f"{prefix}_first_name" in found else ("Nome", ids[0])
        raise ParseError(
            f"{ident} {missing}: missing; AnagraficaType takes Nome and Cognome together",
            location=cursor.path(registry),
        )
    return found


def post_code(cursor: Cursor, address: etree._Element, country: str | None) -> str | None:
    """``CAP`` → BT-38 / BT-53 / BT-78, except the generic ``00000`` of an address outside Italy, which is no post code.

    AdE FAQ n. 63 (pp. 27-28) and n. 74 (pp. 33-34) of the compendium of 22/12/2022 (sha256
    763eec56...1862): "il campo CAP andrà compilato con il valore generico 00000". The element is still consumed.
    """
    code = cursor.text(address, "CAP")
    return None if code == "00000" and country != "IT" else code


def _address[A: SellerPostalAddress | BuyerPostalAddress](
    cursor: Cursor, party: etree._Element | None, cls: type[A]
) -> A | None:
    """``Sede`` → BG-5 / BG-8 (App. 4.1 rows 1.2.2.x, 1.4.2.x)."""
    sede = cursor.one(party, "Sede")
    if sede is None:
        return None
    country = cursor.code(sede, "Nazione")
    values = {
        "address_line_1": cursor.text(sede, "Indirizzo"),  # BT-35 / BT-50
        "address_line_2": cursor.text(sede, "NumeroCivico"),  # BT-36 / BT-51
        "post_code": post_code(cursor, sede, country),  # BT-38 / BT-53
        "city": cursor.text(sede, "Comune"),  # BT-37 / BT-52
        "country_subdivision": cursor.text(sede, "Provincia"),  # BT-39 / BT-54
        "country_code": country,  # BT-40 / BT-55
    }
    return build(cls, sede, values)
