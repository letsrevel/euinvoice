"""The FatturaPA reader (#120): one :class:`~euinvoice.syntax.result.ParseResult` per ``FatturaElettronicaBody``.

It reads a parsed ``FatturaElettronica`` (FPR12 or FPA12, XSD 1.2.3).
The mapping is App. 4.1 of the SdI "Regole tecniche fatture europee" v2.6 ("FatturaPA e modello semantico") in
reverse, with the code tables of App. 5; each mapping cites its row (the ids of the Rappresentazione tabellare). Data
with no business term goes to ``Invoice.it`` / ``InvoiceLine.it`` (D3 as amended, ADR 0001). Everything else (the
transmission data of 1.1, which are writer options; the EXT rows outside the v1 extension, such as withholding,
social-security funds, stamp duty, Art73 or the intermediary; and every "Mappatura non considerabile" row) is left
unmarked, so it is listed in ``ParseResult.unmapped``: nothing is dropped silently. Where FatturaPA holds a value the
model cannot (more than two decimals in an amount, a generic Natura, several discounts on a line, …), the reader
refuses with :class:`~euinvoice.errors.ParseError` instead of rounding or guessing; the open policy questions are
listed in https://github.com/letsrevel/euinvoice/issues/132.

FatturaPA has no specification identifier, so BT-24 is the CIUS-IT one of Regole tecniche v2.6 §4.1.3.1, by the
seller's country (BT-40): ``…CIUS-IT:2.0.0#conformant#urn:fatturapa.gov.it:EXT-IT:1.0.0`` for an Italian seller,
``…CIUS-IT:2.0.0`` otherwise. BT-106, BT-109 and BT-110 have no FatturaPA element and are derived per BR-CO-10,
BR-CO-13 and BR-CO-14 (no document-level allowance or charge is mapped); BT-112 and BT-115 too when the document
does not carry ``ImportoTotaleDocumento`` (2.1.1.9) or a single ``ImportoPagamento`` (2.4.2.6).
"""

import typing as t
from decimal import Decimal

from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ParseError, UnsupportedDocumentError
from euinvoice.model import Invoice, InvoiceLine, VatBreakdown
from euinvoice.model.it import TipoDocumento
from euinvoice.syntax._marks import XML_SPACE
from euinvoice.syntax.fatturapa._read_codes import TYPE_CODE
from euinvoice.syntax.fatturapa._read_cursor import Cursor
from euinvoice.syntax.fatturapa._read_lines import lines, payment, summaries
from euinvoice.syntax.fatturapa._read_parties import buyer, seller
from euinvoice.syntax.result import ParseResult

__all__ = ["DOMESTIC_SPECIFICATION", "SPECIFICATION", "read", "read_all"]

_ROOT: t.Final = f"{{{_xml.FATTURAPA}}}FatturaElettronica"
_FORMAT: t.Final = "FPR12"  # the root's versione the v1 writer emits (#115 decision 1); FPA12 is reported
_CONVENTION: t.Final = "AVV"  # UNTDID 1153 scheme of BT-18 from DatiConvenzione (App. 4.1 row 2.1.4.2)

SPECIFICATION: t.Final = "urn:cen.eu:en16931:2017#compliant#urn:fatturapa.gov.it:CIUS-IT:2.0.0"
"""BT-24 of a read document whose seller is not Italian (Regole tecniche v2.6 §4.1.3.1, BT-40 not IT)."""
DOMESTIC_SPECIFICATION: t.Final = f"{SPECIFICATION}#conformant#urn:fatturapa.gov.it:EXT-IT:1.0.0"
"""BT-24 of a read document whose seller is Italian (Regole tecniche v2.6 §4.1.3.1, BT-40 = IT)."""


def read(root: etree._Element) -> ParseResult:
    """Read the one invoice of a FatturaPA document.

    Args:
        root: The ``FatturaElettronica`` element, from :func:`euinvoice._xml.parse` (D10).

    Returns:
        The invoice and the unmapped XPaths.

    Raises:
        UnsupportedDocumentError: The document is a lotto, with several ``FatturaElettronicaBody`` (read it with
            :func:`read_all`).
        ParseError: See :func:`read_all`.
    """
    bodies = _bodies(root)
    if len(bodies) > 1:
        raise UnsupportedDocumentError(
            f"the FatturaPA document is a lotto of {len(bodies)} invoices (one FatturaElettronicaBody each); read "
            "them with euinvoice.parse_all()"
        )
    return _read_body(root, bodies[0])


def read_all(root: etree._Element) -> tuple[ParseResult, ...]:
    """Read every invoice of a FatturaPA document, one per ``FatturaElettronicaBody`` (2, cardinality 1..n).

    The bodies of a lotto share the header (seller, buyer, transmission data), so each result maps the header again;
    its ``unmapped`` lists the unmapped header content and that of its own body, never the other bodies.

    Args:
        root: The ``FatturaElettronica`` element, from :func:`euinvoice._xml.parse` (D10).

    Returns:
        One result per body, in document order.

    Raises:
        ParseError: ``root`` is not a FatturaPA 1.2 ``FatturaElettronica`` or has no body; or a body holds what the
            model cannot represent without rounding or guessing (the message names the FatturaPA element id and
            the BT); or its content does not form a valid model (the message names the BT/BG id).
    """
    return tuple(_read_body(root, body) for body in _bodies(root))


def _bodies(root: etree._Element) -> list[etree._Element]:
    if root.tag != _ROOT:
        raise ParseError(f"expected the FatturaPA root {_ROOT}, got {root.tag}", location=_xml.getpath(root))
    bodies = root.findall("FatturaElettronicaBody")
    if not bodies:
        raise ParseError("2 FatturaElettronicaBody: a FatturaPA document has at least one", location=_xml.getpath(root))
    return bodies


def _read_body(root: etree._Element, body: etree._Element) -> ParseResult:
    cursor = Cursor(root, body)
    if root.get("versione") == _FORMAT:
        cursor.attribute(root, "versione")
    header = cursor.one(root, "FatturaElettronicaHeader")
    if header is None:
        raise ParseError("1 FatturaElettronicaHeader: a FatturaPA document has one", location=_xml.getpath(root))
    the_seller, the_buyer = seller(cursor, header), buyer(cursor, header)
    seller_party = cursor.one(header, "CedentePrestatore")
    general = cursor.one(body, "DatiGenerali")
    document = cursor.one(general, "DatiGeneraliDocumento")
    kind = _document_type(cursor, document)
    goods = cursor.one(body, "DatiBeniServizi")
    vat = summaries(cursor, goods)
    invoice_lines = lines(cursor, goods, vat)
    paid = payment(cursor, body)
    domestic = the_seller.postal_address.country_code == "IT"
    extension = {
        "tax_regime": cursor.code(cursor.one(seller_party, "DatiAnagrafici"), "RegimeFiscale"),  # 1.2.1.8
        "issuer": cursor.code(header, "SoggettoEmittente"),  # 1.6
        "document_type": kind,  # 2.1.1.1
        "vat_summaries": vat.extension,  # 2.2.2
        "payment": paid.pop("it_payment", None),  # 2.4
    }
    invoice = cursor.model(
        Invoice,
        body,
        number=cursor.text(document, "Numero"),  # 2.1.1.4 → BT-1
        issue_date=cursor.date(document, "Data", "2.1.1.3"),  # → BT-2
        type_code=None if kind is None else TYPE_CODE[kind],  # 2.1.1.1 → BT-3 (App. 5.4)
        currency_code=cursor.code(document, "Divisa"),  # 2.1.1.2 → BT-5
        buyer_accounting_reference=cursor.text(seller_party, "RiferimentoAmministrazione"),  # 1.2.6 → BT-19
        notes=tuple({"note": cursor.use(c).text or ""} for c in cursor.children(document, "Causale")),  # 2.1.1.11
        process_control={"specification_identifier": DOMESTIC_SPECIFICATION if domestic else SPECIFICATION},
        preceding_invoice_references=_preceding(cursor, general),  # 2.1.6 → BG-3
        seller=the_seller,
        buyer=the_buyer,
        delivery=_delivery(cursor, general),  # 2.1.9 → BG-13
        lines=invoice_lines,
        vat_breakdown=vat.breakdown,
        totals=_totals(
            cursor, document, invoice_lines, vat.breakdown, t.cast(Decimal | None, paid.pop("amount_due", None))
        ),
        it=extension,
        **_references(cursor, general),
        **paid,
    )
    return ParseResult(invoice=invoice, unmapped=cursor.unmapped())


def _document_type(cursor: Cursor, document: etree._Element | None) -> TipoDocumento | None:
    element = cursor.one(document, "TipoDocumento")
    if element is None:
        return None  # build() names the missing BT-3 and 2.1.1.1
    text = (element.text or "").strip(XML_SPACE)
    try:
        return TipoDocumento(text)
    except ValueError:
        raise ParseError(
            f"2.1.1.1 TipoDocumento: {text!r} is not a TipoDocumentoType code (XSD 1.2.3)",
            location=cursor.path(element),
        ) from None


def _single(cursor: Cursor, general: etree._Element | None, name: str) -> etree._Element | None:
    """The block ``name`` if it is the only one and refers to no line, else ``None`` (all reported, #132 item 14).

    App. 4.1 rows 2.1.2 to 2.1.8: "Se unico a livello di documento".
    """
    blocks = cursor.children(general, name)
    if len(blocks) != 1 or cursor.children(blocks[0], "RiferimentoNumeroLinea"):
        return None
    return cursor.use(blocks[0])


def _references(cursor: Cursor, general: etree._Element | None) -> dict[str, object]:
    """The document references of 2.1.2 to 2.1.8 (App. 4.1); ``DatiSAL`` (2.1.7, BT-18 scheme AOR) is reported."""
    order = _single(cursor, general, "DatiOrdineAcquisto")
    contract = _single(cursor, general, "DatiContratto")
    convention = _single(cursor, general, "DatiConvenzione")
    convention_id = cursor.text(convention, "IdDocumento")
    return {
        "purchase_order_reference": cursor.text(order, "IdDocumento"),  # 2.1.2.2 → BT-13
        "contract_reference": cursor.text(contract, "IdDocumento"),  # 2.1.3.2 → BT-12
        "project_reference": cursor.text(contract, "CodiceCUP"),  # 2.1.3.6 → BT-11
        "tender_or_lot_reference": cursor.text(contract, "CodiceCIG"),  # 2.1.3.7 → BT-17
        "invoiced_object_identifier": None  # 2.1.4.2 → BT-18 scheme AVV
        if convention_id is None
        else {"value": convention_id, "scheme_id": _CONVENTION},
        "receiving_advice_reference": cursor.text(_single(cursor, general, "DatiRicezione"), "IdDocumento"),  # BT-15
        "despatch_advice_reference": cursor.text(_single(cursor, general, "DatiDDT"), "NumeroDDT"),  # 2.1.8.1 BT-16
    }


def _preceding(cursor: Cursor, general: etree._Element | None) -> tuple[dict[str, object], ...]:
    """2.1.6 ``DatiFattureCollegate`` → BG-3: ``IdDocumento`` → BT-25, ``Data`` → BT-26."""
    return tuple(
        {"reference": cursor.text(block, "IdDocumento"), "issue_date": cursor.date(block, "Data", "2.1.6.3")}
        for block in [cursor.use(b) for b in cursor.children(general, "DatiFattureCollegate")]
    )


def _delivery(cursor: Cursor, general: etree._Element | None) -> dict[str, object] | None:
    """2.1.9 ``DatiTrasporto`` → BG-13: ``DataOraConsegna`` → BT-72 (its time reported), ``IndirizzoResa`` → BG-15."""
    transport = cursor.one(general, "DatiTrasporto")
    if transport is None:
        return None
    date = cursor.date_of_time(transport, "DataOraConsegna", "2.1.9.13")
    place = cursor.one(transport, "IndirizzoResa")
    if date is None and place is None:
        cursor.discard(transport)  # nothing in it has a business term: reported whole
        return None
    address = None
    if place is not None:
        address = {
            "address_line_1": cursor.text(place, "Indirizzo"),  # 2.1.9.12.1 → BT-75
            "address_line_2": cursor.text(place, "NumeroCivico"),  # → BT-76
            "post_code": cursor.text(place, "CAP"),  # → BT-78
            "city": cursor.text(place, "Comune"),  # → BT-77
            "country_subdivision": cursor.text(place, "Provincia"),  # → BT-79
            "country_code": cursor.code(place, "Nazione"),  # → BT-80
        }
    return {"actual_delivery_date": date, "deliver_to_address": address}


def _totals(
    cursor: Cursor,
    document: etree._Element | None,
    invoice_lines: tuple[InvoiceLine, ...],
    breakdown: tuple[VatBreakdown, ...],
    amount_due: Decimal | None,
) -> dict[str, object]:
    """BG-22: BT-106/109/110 derived (BR-CO-10/13/14), BT-112, BT-114 and BT-115 read.

    BT-112 comes from 2.1.1.9, BT-114 from 2.1.1.10 and BT-115 from 2.4.2.6; without those, BT-112 follows BR-CO-15
    and BT-115 BR-CO-16 (with no paid amount).
    """
    line_total = sum((line.net_amount for line in invoice_lines), Decimal("0.00"))
    vat_total = sum((group.tax_amount for group in breakdown), Decimal("0.00"))
    with_vat = cursor.decimal(document, "ImportoTotaleDocumento", "2.1.1.9")
    rounding = cursor.decimal(document, "Arrotondamento", "2.1.1.10")
    if with_vat is None:
        with_vat = line_total + vat_total
    return {
        "sum_of_line_net_amounts": line_total,
        "total_without_vat": line_total,
        "total_vat": vat_total,
        "total_with_vat": with_vat,
        "rounding_amount": rounding,
        "amount_due": with_vat + (rounding or 0) if amount_due is None else amount_due,
    }
