"""The offline-decidable SdI checks of FatturaPA (IMPLEMENTATION_PLAN.md D8 as amended by ADR 0001, issue #121).

FatturaPA has no official Schematron and no public validator. Its oracle is the pinned XSD 1.2.3 plus the checks
the Sistema di Interscambio (SdI) runs, which Allegato A ("Specifiche tecniche", version 1.9.1, 31/03/2026),
Appendix 1 describes in prose. :func:`check` encodes the ones decidable from the document alone. Each failure is
a :class:`~euinvoice.report.Finding` whose ``rule_id`` is the SdI error code, whose message starts with that
code's Allegato A description (the "fatture ordinarie" wording, quoted in Italian) and whose ``source`` is
:data:`SOURCE`. These are our reading of official prose, not an official executable rule set.

Severity: every code of Appendix 1 makes SdI reject the file ("il documento viene rifiutato", ricevuta di scarto),
so each finding must be blocking: ``fatal`` or ``error``. Allegato A has no severity levels; we use ``error``.
In euinvoice reports ``fatal`` is the flag an official machine-readable artifact gives (the XSD step, a Schematron
``flag``) and, for the XSD, a failure that stops validation; SdI reports these checks together, so none stops the
others.

Precondition: the document has passed the FatturaPA 1.2.3 XSD (``validate()`` runs these checks only then, the
same short-circuit as for the Schematron steps). Allegato A, Appendix 1 applies to the "fattura ordinaria", which
FPA12 and FPR12 both are (00427 names both); the simplified invoice (FSM10) has another namespace and is not
detected as FatturaPA.

Implemented, each citing its code (the constant :data:`DESCRIPTIONS` holds the quoted text): 00313, 00400, 00401,
00409, 00411, 00413, 00414, 00415, 00417, 00418, 00419, 00420, 00421, 00422, 00423, 00424, 00425, 00427, 00428, 00429,
00430, 00437, 00438, 00443, 00444, 00445, 00471, 00472, 00473, 00474, 00475, 00476. Where Allegato A's prose
leaves part of a check open, the SdI "Elenco dei controlli" v2.0 (31/01/2025, 46 pp., sha256
a3ec6b4b5f74c43bca8c5849f49b33d2c9b0784c5d227f32a25a81b1d7caf9f2, fetch only, never committed) settles it with its
pseudo-code (decision 0, #130 / #154): 00409 (Elenco pp. 15-16), 00419 (p. 22), 00423 (pp. 26-30) and 00424
(p. 31). Where Allegato A is explicit it wins (D8): the 00423 tolerance (``> 0.01`` fails, 2.2.1.11), the
00418 scope (every document; the Elenco checks TD04 only), the 00471 scope (13 TipoDocumento; the Elenco 7) and the
00443/00444 wording (the Elenco prints 00443 for 00444 on p. 38). SdI may therefore accept a document for which we
report 00418 or 00471 (#130).

Not implemented, with the reason:

* tax register or SdI state (#115 decision 2): 00300-00306 and 00320-00327 (identifiers and VAT groups checked
  in the Anagrafe Tributaria); 00311, 00312 (``CodiceDestinatario`` existing / active in SdI); 00330 (a
  ``PECDestinatario`` that is one of SdI's own mailboxes: the set is SdI's data); 00398 and 00399 (IPA registry
  checks for public-administration recipients, from the SdI "Elenco dei controlli" v2.0, not in Allegato A: 00398
  the IPA office code, 00399 an FPR12 sent to a buyer registered in IPA); 00403 (the invoice date after
  the date SdI receives the file: the receipt date is SdI's); 00404 (duplicate of an invoice sent earlier);
  00477 (invalidated declaration of intent).
* the transmitted file, not the XML ``validate()`` receives: 00001, 00002 (file name; 00002 also needs SdI
  state), 00003 (file size, decided on #121: the limit applies to the transmitted file, which may be a signed
  ``.xml.p7m`` envelope, and Allegato A §1.3.1 gives it as "5MB" without saying whether that is 10^6 or 2^20
  bytes; the FatturaPA file helper of #119 owns it), 00106 (empty or unreadable compressed file).
* signature: 00100-00105, 00107. v1 is unsigned (#115 decision 1), and certificate checks need CA state.
* format: 00200 and 00201 are the XSD step, reported as ``XSD`` findings of the pinned schema (00201 is SdI's cap
  of 50 format errors per receipt, a receipt detail).
* simplified invoices only: 00460.
"""

import collections
import re
import typing as t
from decimal import ROUND_HALF_UP, Decimal

from lxml import etree

from euinvoice import _xml
from euinvoice.report import Finding, Severity

__all__ = ["DESCRIPTIONS", "SOURCE", "check"]

SOURCE: t.Final = "sdi"
"""The ``source`` of every SdI finding."""

# The "fatture ordinarie" description of each implemented code, quoted from Allegato A 1.9.1, Appendix 1.
DESCRIPTIONS: t.Final[t.Mapping[str, str]] = {
    "00313": 'l\'elemento 1.1.4 <CodiceDestinatario> può essere valorizzato con "XXXXXXX" per comunicare i dati di '
    "fatture emesse esclusivamente verso soggetti non residenti (1.4.1.1 <IdFiscaleIVA> deve essere valorizzato e "
    '1.4.1.1.1 <IdPaese> deve essere diverso da "IT")',
    "00400": "2.2.1.14 <Natura> non presente a fronte di 2.2.1.12 <AliquotaIVA> pari a zero",
    "00401": "2.2.1.14 <Natura> presente a fronte di 2.2.1.12 <AliquotaIVA> diversa da zero",
    "00409": "Fattura duplicata nel lotto",
    "00411": "2.1.1.5 <DatiRitenuta> non presente a fronte di almeno un blocco 2.2.1 <DettaglioLinee> con "
    "2.2.1.13 <Ritenuta> uguale a SI",
    "00413": "2.1.1.7.7 <Natura> non presente a fronte di 2.1.1.7.5 <AliquotaIVA> pari a zero",
    "00414": "2.1.1.7.7 <Natura> presente a fronte di 2.1.1.7.5 <AliquotaIVA> diversa da zero",
    "00415": "2.1.1.5 <DatiRitenuta> non presente a fronte di 2.1.1.7.6 <Ritenuta> uguale a SI",
    "00417": "1.4.1.1 <IdFiscaleIVA> e 1.4.1.2 <CodiceFiscale> non valorizzati",
    "00418": "2.1.1.3 <Data> antecedente a 2.1.6.3 <Data>",
    "00419": "2.2.2 <DatiRiepilogo> non presente in corrispondenza di almeno un valore di 2.1.1.7.5 <AliquotaIVA> "
    "o 2.2.1.12 <AliquotaIVA>",
    "00420": "2.2.2.2 <Natura> con valore di tipo N6 a fronte di 2.2.2.7 <EsigibilitaIVA> uguale a S "
    "(scissione pagamenti)",
    "00421": "2.2.2.6 <Imposta> non calcolato secondo le regole definite nelle specifiche tecniche",
    "00422": "2.2.2.5 <ImponibileImporto> non calcolato secondo le regole definite nelle specifiche tecniche",
    "00423": "2.2.1.11 <PrezzoTotale> non calcolato secondo le regole definite nelle specifiche tecniche",
    "00424": "2.2.1.12 <AliquotaIVA> o 2.2.2.1 <AliquotaIVA> o 2.1.1.7.5 <AliquotaIVA> non indicata in termini "
    "percentuali",
    "00425": "2.1.1.4 <Numero> non contenente caratteri numerici",
    "00427": "1.1.4 <CodiceDestinatario> di 7 caratteri a fronte di 1.1.3 <FormatoTrasmissione> con valore FPA12 "
    "o 1.1.4 <CodiceDestinatario> di 6 caratteri a fronte di 1.1.3 <FormatoTrasmissione> con valore FPR12",
    "00428": "1.1.3 <FormatoTrasmissione> non coerente con il valore dell'attributo VERSION",
    "00429": "2.2.2.2 <Natura> non presente a fronte di 2.2.2.1 <AliquotaIVA> pari a zero",
    "00430": "2.2.2.2 <Natura> presente a fronte di 2.2.2.1 <AliquotaIVA> diversa da zero",
    "00437": "2.1.1.8.2 <Percentuale> e 2.1.1.8.3 <Importo> non presenti a fronte di 2.1.1.8.1 <Tipo> valorizzato",
    "00438": "2.2.1.10.2 <Percentuale> e 2.2.1.10.3 <Importo> non presenti a fronte di 2.2.1.10.1 <Tipo> valorizzato",
    "00443": "non c'è corrispondenza tra i valori indicati nell'elemento 2.2.1.12 <AliquotaIVA> o 2.1.1.7.5 "
    "<AliquotaIVA> e quelli dell'elemento 2.2.2.1 <AliquotaIVA>",
    "00444": "non c'è corrispondenza tra i valori indicati nell'elemento 2.2.1.14 <Natura> o 2.1.1.7.7 <Natura> e "
    "quelli dell'elemento 2.2.2.2 <Natura>",
    "00445": "non è più ammesso il valore generico N2, N3 o N6 come codice natura dell'operazione",
    "00471": "per il valore indicato nell'elemento 2.1.1.1 <TipoDocumento> il cedente/prestatore non può essere "
    "uguale al cessionario/committente",
    "00472": "per il valore indicato nell'elemento 2.1.1.1 <TipoDocumento> il cedente/prestatore deve essere "
    "uguale al cessionario/committente",
    "00473": "per il valore indicato nell'elemento 2.1.1.1 <TipoDocumento> il valore presente nell'elemento "
    "1.2.1.1.1 <IdPaese> non è ammesso",
    "00474": "per il valore indicato nell'elemento 2.1.1.1 <TipoDocumento> non sono ammesse linee di dettaglio con "
    "l'elemento 2.2.1.12 <AliquotaIVA> contenente valore zero",
    "00475": "per il valore indicato nell'elemento 2.1.1.1 <TipoDocumento> deve essere presente l'elemento 1.4.1.1 "
    "<IdFiscaleIVA> del cessionario/committente",
    "00476": "gli elementi 1.2.1.1.1 <IdPaese> e 1.4.1.1.1 <IdPaese> non possono essere entrambi valorizzati con "
    "codice diverso da IT",
}

_CENT: t.Final = Decimal("0.01")
_EURO: t.Final = Decimal(1)
_HUNDRED: t.Final = Decimal(100)
# TipoDocumento sets, quoted from the code descriptions of Allegato A 1.9.1, Appendix 1.
_TD_NOT_SELF: t.Final = frozenset(
    {"TD01", "TD02", "TD03", "TD06", "TD16", "TD17", "TD18", "TD19", "TD20", "TD24", "TD25", "TD28", "TD29"}
)  # 00471
_TD_SELF: t.Final = frozenset({"TD21", "TD27"})  # 00472
_TD_FOREIGN_SELLER: t.Final = frozenset({"TD17", "TD18", "TD19", "TD28"})  # 00473, no Italian cedente
_TD_BUYER_VAT_ID: t.Final = frozenset({"TD16", "TD17", "TD18", "TD19", "TD20", "TD22", "TD23", "TD28", "TD29"})  # 00475
_TD_SPLAFONAMENTO: t.Final = "TD21"  # 00474 "autofattura per splafonamento" (TipoDocumentoType, XSD 1.2.3)
_TD_REVERSE_CHARGE_INTEGRATION: t.Final = "TD16"  # the exception of 00401 and 00430
_TD_CREDIT_NOTE: t.Final = "TD04"  # 00409 credit-note rule (00404 is out of scope)
_GENERIC_NATURA: t.Final = frozenset({"N2", "N3", "N6"})  # 00445, fatture ordinarie
_DIGIT: t.Final = re.compile(r"[0-9]")

_CEDENTE: t.Final = "FatturaElettronicaHeader/CedentePrestatore/DatiAnagrafici"
_CESSIONARIO: t.Final = "FatturaElettronicaHeader/CessionarioCommittente/DatiAnagrafici"
_DGD: t.Final = "DatiGenerali/DatiGeneraliDocumento"
_LINES: t.Final = "DatiBeniServizi/DettaglioLinee"
_SUMMARIES: t.Final = "DatiBeniServizi/DatiRiepilogo"
_CASSA: t.Final = f"{_DGD}/DatiCassaPrevidenziale"


def check(root: etree._Element) -> tuple[Finding, ...]:
    """Run the offline SdI checks of Allegato A 1.9.1, Appendix 1 on a FatturaPA document.

    Args:
        root: The ``FatturaElettronica`` root element of a document that passed the FatturaPA 1.2.3 XSD.

    Returns:
        One ``error`` finding per failed check, located at the offending element (an XPath), in the order: header
        checks, then each body's checks, then the batch (lotto) check 00409. Empty when every check passes.
    """
    findings = list(_header(root))
    bodies = root.findall("FatturaElettronicaBody")
    for body in bodies:
        findings += _parties(root, body)
        findings += _lines(body)
        findings += _cassa(body)
        findings += _summaries(body)
        findings += _document(body)
    findings += _duplicates(bodies)
    return tuple(findings)


def _finding(code: str, element: etree._Element, detail: str) -> Finding:
    """An ``error`` finding for SdI ``code`` at ``element``: the Allegato A text, then what was found."""
    message = f"SdI {code} (Allegato A 1.9.1, Appendix 1): {DESCRIPTIONS[code]}. {detail}"
    return Finding(
        rule_id=code, severity=Severity.ERROR, location=_xml.getpath(element), message=message, source=SOURCE
    )


def _child(element: etree._Element, path: str) -> etree._Element:
    """The ``path`` under ``element`` that the FatturaPA XSD requires.

    Raises:
        ValueError: It is missing: the document did not pass the XSD, which :func:`check` requires.
    """
    found = element.find(path)
    if found is None:
        raise ValueError(f"{_xml.getpath(element)} has no {path}; sdi.check needs a document valid against the XSD")
    return found


def _text(element: etree._Element, path: str) -> str | None:
    """The text of the first ``path`` under ``element`` with XSD whitespace collapsed, or ``None`` if absent."""
    found = element.find(path)
    return None if found is None else " ".join((found.text or "").split())


def _decimal(element: etree._Element, path: str) -> Decimal | None:
    """An optional ``xs:decimal`` child (``Amount*Type``, ``RateType``, ``QuantitaType``), ``None`` if absent."""
    text = _text(element, path)
    return None if text is None else Decimal(text)


def _amount(element: etree._Element, path: str) -> Decimal:
    """A required ``xs:decimal`` child."""
    return Decimal(" ".join((_child(element, path).text or "").split()))


_DATE: t.Final = re.compile(r"(-?[0-9]{4,})-([0-9]{2})-([0-9]{2})")


def _date(text: str) -> tuple[int, int, int]:
    """An ``xs:date`` as ``(year, month, day)``, which orders like the date for any XSD year.

    ponytail: an xs:date timezone (e.g. 2026-01-01+01:00) is ignored, so dates compare as written. Allegato A does not
    say how SdI compares dates with timezones; FatturaPA dates are written without one in practice.
    """
    match = t.cast(re.Match[str], _DATE.match(text))  # the XSD types every date as xs:date
    year, month, day = match.groups()
    return int(year), int(month), int(day)


def _vat_id(party: etree._Element | None) -> tuple[str, str] | None:
    """A party's ``IdFiscaleIVA`` as ``(IdPaese, IdCodice)``, or ``None`` if it has none."""
    found = None if party is None else party.find("IdFiscaleIVA")
    if found is None:
        return None
    return (_text(found, "IdPaese") or "", _text(found, "IdCodice") or "")


def _header(root: etree._Element) -> t.Iterator[Finding]:
    """00428, 00427, 00313, 00417, 00476: transmission data and the parties' identifiers."""
    transmission = _child(root, "FatturaElettronicaHeader/DatiTrasmissione")
    formato = _text(transmission, "FormatoTrasmissione")
    versione = root.get("versione")
    if formato != versione:
        yield _finding(
            "00428", transmission, f"FormatoTrasmissione is {formato!r}, the versione attribute {versione!r}."
        )
    destinatario = _text(transmission, "CodiceDestinatario") or ""
    if (formato, len(destinatario)) in {("FPA12", 7), ("FPR12", 6)}:
        yield _finding(
            "00427", transmission, f"CodiceDestinatario {destinatario!r} with FormatoTrasmissione {formato}."
        )
    cessionario = root.find(_CESSIONARIO)
    buyer = _vat_id(cessionario)
    if destinatario == "XXXXXXX" and (buyer is None or buyer[0] == "IT"):
        found = "no IdFiscaleIVA" if buyer is None else "IdPaese IT"
        yield _finding("00313", transmission, f"CodiceDestinatario XXXXXXX, but the cessionario has {found}.")
    if cessionario is not None and buyer is None and cessionario.find("CodiceFiscale") is None:
        yield _finding("00417", cessionario, "The cessionario/committente has neither.")
    seller = _vat_id(root.find(_CEDENTE))
    if seller is not None and buyer is not None and seller[0] != "IT" and buyer[0] != "IT":
        header = _child(root, "FatturaElettronicaHeader")
        yield _finding("00476", header, f"IdPaese {seller[0]} and {buyer[0]}.")


def _same_party(root: etree._Element) -> bool | None:
    """Whether the cedente and the cessionario are the same subject (00471, 00472), or ``None`` if undecided.

    Same: equal ``IdFiscaleIVA`` (IdPaese and IdCodice). Undecided: the cessionario has no ``IdFiscaleIVA``, or the
    two share one but carry different ``CodiceFiscale`` values, as members of one VAT group do (Allegato A 00322 /
    00326: a group ``IdFiscaleIVA`` comes with the member's ``CodiceFiscale``). Allegato A says "stesso soggetto"
    without naming the identifier it compares (#130).
    """
    seller_party, buyer_party = _child(root, _CEDENTE), _child(root, _CESSIONARIO)
    seller, buyer = _vat_id(seller_party), _vat_id(buyer_party)
    if seller is None or buyer is None:
        return None
    if seller != buyer:
        return False
    seller_code, buyer_code = _text(seller_party, "CodiceFiscale"), _text(buyer_party, "CodiceFiscale")
    if seller_code is not None and buyer_code is not None and seller_code != buyer_code:
        return None  # one VAT group, two members
    return True


def _parties(root: etree._Element, body: etree._Element) -> t.Iterator[Finding]:
    """00471, 00472, 00473, 00475: what the body's TipoDocumento requires of the header's parties."""
    general = _child(body, _DGD)
    tipo = _text(general, "TipoDocumento") or ""
    same = _same_party(root)
    if tipo in _TD_NOT_SELF and same is True:
        yield _finding("00471", general, f"TipoDocumento {tipo}, and both parties have the same IdFiscaleIVA.")
    if tipo in _TD_SELF and same is False:
        yield _finding("00472", general, f"TipoDocumento {tipo}, and the parties have different IdFiscaleIVA.")
    seller = _vat_id(root.find(_CEDENTE))
    country = None if seller is None else seller[0]
    # ponytail: 00473 also says "Nei casi di TD17 e TD19 è ammessa l'indicazione del valore 'OO'"; whether that
    # forbids OO for TD18 and TD28 is not stated, so only IT (TD17/18/19/28) and non-IT (TD29) are checked (#130).
    if (tipo in _TD_FOREIGN_SELLER and country == "IT") or (tipo == "TD29" and country not in {None, "IT"}):
        yield _finding("00473", general, f"TipoDocumento {tipo} with cedente IdPaese {country}.")
    if tipo in _TD_BUYER_VAT_ID and _vat_id(root.find(_CESSIONARIO)) is None:
        yield _finding("00475", general, f"TipoDocumento {tipo} without the cessionario's IdFiscaleIVA.")


def _withholding(body: etree._Element) -> bool:
    return body.find(f"{_DGD}/DatiRitenuta") is not None


def _tipo(body: etree._Element) -> str:
    return _text(body, f"{_DGD}/TipoDocumento") or ""


def _lines(body: etree._Element) -> t.Iterator[Finding]:
    """00400, 00401, 00411, 00423, 00424, 00438, 00474 on each DettaglioLinee (2.2.1)."""
    tipo = _tipo(body)
    withheld = False
    for line in body.iterfind(_LINES):
        rate, natura = _amount(line, "AliquotaIVA"), _text(line, "Natura")
        if rate == 0 and natura is None:
            yield _finding("00400", line, "AliquotaIVA 0 without Natura.")
        if rate != 0 and natura is not None and tipo != _TD_REVERSE_CHARGE_INTEGRATION:
            yield _finding("00401", line, f"AliquotaIVA {rate:f} with Natura {natura} (TipoDocumento {tipo}).")
        if rate == 0 and tipo == _TD_SPLAFONAMENTO:
            yield _finding("00474", line, f"TipoDocumento {tipo} with AliquotaIVA 0.")
        if _text(line, "Ritenuta") == "SI" and not withheld and not _withholding(body):
            withheld = True  # one finding per body: the missing block is the body's
            yield _finding("00411", line, "Ritenuta SI, and the body has no DatiRitenuta.")
        yield from _adjustments(line, "00438")
        yield from _line_total(line)
        yield from _percentage(line)


def _adjustments(parent: etree._Element, code: str) -> t.Iterator[Finding]:
    """00437 (document) / 00438 (line): a ScontoMaggiorazione with Tipo but neither Percentuale nor Importo."""
    for adjustment in parent.iterfind("ScontoMaggiorazione"):
        if adjustment.find("Percentuale") is None and adjustment.find("Importo") is None:
            yield _finding(code, adjustment, f"Tipo {_text(adjustment, 'Tipo')} without Percentuale or Importo.")


def _line_total(line: etree._Element) -> t.Iterator[Finding]:
    """00423: PrezzoTotale = (PrezzoUnitario ± ScontoMaggiorazione) * Quantita, tolerance ±0.01.

    The algorithm is the Elenco dei controlli v2.0, pp. 26-30 (worked examples Caso 1-3): Quantita absent counts as
    1; a running price starts at PrezzoUnitario and each ScontoMaggiorazione, in document order, changes it by
    ``sign * Importo`` (per unit) or, without Importo, by ``sign * price * Percentuale / 100`` (cascade); an entry
    with both uses Importo; SC is -1, MG +1. The result is compared exactly (no rounding) and fails when the
    difference exceeds 0.01: Allegato A 2.2.1.11 says "superiore a ±1 centesimo" where the Elenco passes only below
    0.01, and Allegato A is explicit (D8). An entry with neither is 00438 and leaves the price unchanged.
    """
    quantity = _decimal(line, "Quantita")
    price, total = _amount(line, "PrezzoUnitario"), _amount(line, "PrezzoTotale")
    for adjustment in line.iterfind("ScontoMaggiorazione"):
        sign = Decimal(-1) if _text(adjustment, "Tipo") == "SC" else Decimal(1)
        amount, percent = _decimal(adjustment, "Importo"), _decimal(adjustment, "Percentuale")
        if amount is not None:
            price += sign * amount
        elif percent is not None:
            price += sign * price * percent / _HUNDRED
    expected = price * (Decimal(1) if quantity is None else quantity)
    if abs(total - expected) > _CENT:
        yield _finding("00423", line, f"PrezzoTotale {total:f}, computed {expected:f} (tolerance ±0.01).")


def _percentage(element: etree._Element) -> t.Iterator[Finding]:
    """00424 (Elenco p. 31): an AliquotaIVA other than 0.00 that is below 1.00 (0.10 written for 10 %)."""
    rate = _amount(element, "AliquotaIVA")
    if rate != 0 and rate < 1:
        yield _finding("00424", element, f"AliquotaIVA {rate:f} is below 1.00; 10 % is written 10.00, not 0.10.")


def _cassa(body: etree._Element) -> t.Iterator[Finding]:
    """00413, 00414, 00415, 00424 on each DatiCassaPrevidenziale (2.1.1.7)."""
    withheld = False
    for cassa in body.iterfind(_CASSA):
        rate, natura = _amount(cassa, "AliquotaIVA"), _text(cassa, "Natura")
        if rate == 0 and natura is None:
            yield _finding("00413", cassa, "AliquotaIVA 0 without Natura.")
        if rate != 0 and natura is not None:
            yield _finding("00414", cassa, f"AliquotaIVA {rate:f} with Natura {natura}.")
        if _text(cassa, "Ritenuta") == "SI" and not withheld and not _withholding(body):
            withheld = True
            yield _finding("00415", cassa, "Ritenuta SI, and the body has no DatiRitenuta.")
        yield from _percentage(cassa)


def _summaries(body: etree._Element) -> t.Iterator[Finding]:
    """00429, 00430, 00420, 00421 per DatiRiepilogo; 00419, 00443, 00444, 00422 across the body."""
    tipo = _tipo(body)
    summaries = body.findall(_SUMMARIES)
    for summary in summaries:
        rate, natura = _amount(summary, "AliquotaIVA"), _text(summary, "Natura")
        if rate == 0 and natura is None:
            yield _finding("00429", summary, "AliquotaIVA 0 without Natura.")
        if rate != 0 and natura is not None and tipo != _TD_REVERSE_CHARGE_INTEGRATION:
            yield _finding("00430", summary, f"AliquotaIVA {rate:f} with Natura {natura} (TipoDocumento {tipo}).")
        if natura is not None and natura.startswith("N6") and _text(summary, "EsigibilitaIVA") == "S":
            yield _finding("00420", summary, f"Natura {natura} with EsigibilitaIVA S.")
        yield from _percentage(summary)
        yield from _tax(summary, rate)
    sources = [*body.iterfind(_LINES), *body.iterfind(_CASSA)]
    yield from _coverage(body, summaries, sources)
    yield from _taxable(summaries, sources)


def _tax(summary: etree._Element, rate: Decimal) -> t.Iterator[Finding]:
    """00421: Imposta = AliquotaIVA * ImponibileImporto / 100, rounded half up to 2 decimals, tolerance ±0.01."""
    taxable, tax = _amount(summary, "ImponibileImporto"), _amount(summary, "Imposta")
    # "arrotondato alla seconda cifra decimale (per difetto se la terza cifra decimale è inferiore a 5, per eccesso
    # se ... uguale o maggiore di 5)" (Allegato A, DatiRiepilogo / Imposta): ROUND_HALF_UP; the tolerance is ±1 cent,
    # applied to the amounts as written (in the document's Divisa).
    expected = (rate * taxable / _HUNDRED).quantize(_CENT, rounding=ROUND_HALF_UP)
    if abs(tax - expected) > _CENT:
        yield _finding("00421", summary, f"Imposta {tax:f}, computed {expected:f} (tolerance ±0.01).")


def _coverage(
    body: etree._Element, summaries: list[etree._Element], sources: list[etree._Element]
) -> t.Iterator[Finding]:
    """00419 (a count), 00443 (rates) and 00444 (Natura) of the lines and cassa blocks against the DatiRiepilogo.

    00419 follows the Elenco p. 22: one finding at the body's DatiBeniServizi when the number of DatiRiepilogo is
    less than the number of distinct rates over the lines and cassa blocks. So 00419 is a subset of the situations
    00443 reports (a missing rate beside a surplus block of another rate gives 00443 only, as SdI does).
    00443 is reported once per line or cassa block whose rate has no DatiRiepilogo, 00444 per Natura (Allegato A).
    """
    rates = {_amount(s, "AliquotaIVA") for s in summaries}
    naturas = {_text(s, "Natura") for s in summaries}
    distinct: set[Decimal] = set()
    for source in sources:
        rate, natura = _amount(source, "AliquotaIVA"), _text(source, "Natura")
        distinct.add(rate)
        if rate not in rates:
            yield _finding("00443", source, f"AliquotaIVA {rate:f} has no DatiRiepilogo.")
        if natura is not None and natura not in naturas:
            yield _finding("00444", source, f"Natura {natura} has no DatiRiepilogo.")
    if len(summaries) < len(distinct):
        detail = f"{len(summaries)} DatiRiepilogo for {len(distinct)} distinct AliquotaIVA."
        yield _finding("00419", _child(body, "DatiBeniServizi"), detail)


def _taxable(summaries: list[etree._Element], sources: list[etree._Element]) -> t.Iterator[Finding]:
    """00422: per distinct rate, ΣImponibileImporto = ΣPrezzoTotale + ΣImportoContributoCassa + ΣArrotondamento ±1.

    Allegato A sums Arrotondamento over the t DatiRiepilogo of one rate, so ImponibileImporto is summed over the
    same blocks (several DatiRiepilogo share a rate when their Natura or EsigibilitaIVA differ). Reported at the
    first DatiRiepilogo of the rate.
    """
    expected: collections.defaultdict[Decimal, Decimal] = collections.defaultdict(Decimal)
    for source in sources:
        amount = "PrezzoTotale" if source.tag == "DettaglioLinee" else "ImportoContributoCassa"
        expected[_amount(source, "AliquotaIVA")] += _amount(source, amount)
    declared: dict[Decimal, Decimal] = {}
    first: dict[Decimal, etree._Element] = {}
    for summary in summaries:
        rate = _amount(summary, "AliquotaIVA")
        first.setdefault(rate, summary)
        declared[rate] = declared.get(rate, Decimal(0)) + _amount(summary, "ImponibileImporto")
        expected[rate] += _decimal(summary, "Arrotondamento") or 0
    for rate, total in declared.items():
        if abs(total - expected[rate]) > _EURO:
            detail = f"AliquotaIVA {rate:f}: ImponibileImporto {total:f}, computed {expected[rate]:f} (tolerance ±1)."
            yield _finding("00422", first[rate], detail)


def _document(body: etree._Element) -> t.Iterator[Finding]:
    """00425, 00437, 00418, 00445 on the body's DatiGeneraliDocumento and Natura codes."""
    general = _child(body, _DGD)
    number = _text(general, "Numero") or ""
    if not _DIGIT.search(number):
        yield _finding("00425", general, f"Numero {number!r}.")
    yield from _adjustments(general, "00437")
    issued = _text(general, "Data") or ""
    for linked in body.iterfind("DatiGenerali/DatiFattureCollegate"):
        date = _text(linked, "Data")
        if date is not None and _date(issued) < _date(date):
            yield _finding("00418", linked, f"Data {issued} is before the linked invoice's {date}.")
    for path in (f"{_LINES}/Natura", f"{_CASSA}/Natura", f"{_SUMMARIES}/Natura"):
        for natura in body.iterfind(path):
            if (natura.text or "").strip() in _GENERIC_NATURA:
                yield _finding("00445", natura, f"Natura {natura.text}.")


class _Key(t.NamedTuple):
    """What 00409 compares of one body."""

    body: etree._Element
    number: str
    date: tuple[int, int, int]
    art73: bool
    tipo: str


def _same_document(a: _Key, b: _Key) -> bool:
    """Elenco pp. 15-16: ``a`` (the F of the pseudo-code) and ``b`` (an Fn) are duplicates.

    The period is the year of Data when F's Art73 is not SI, the full Data otherwise. Neither TD04: equal Numero and
    period. Either TD04: also the same TipoDocumento (so two TD04 are duplicates, a TD04 and another type never).
    """
    period = slice(None) if a.art73 else slice(0, 1)
    if a.number != b.number or a.date[period] != b.date[period]:
        return False
    return a.tipo == b.tipo or _TD_CREDIT_NOTE not in {a.tipo, b.tipo}


def _duplicates(bodies: list[etree._Element]) -> t.Iterator[Finding]:
    """00409: two bodies of one file (lotto) that the Elenco dei controlli v2.0, pp. 15-16, calls duplicates.

    The pseudo-code runs over every ordered pair (F, Fn) and reads Art73 on F only, so a pair is compared on the
    full Data only when both bodies carry Art73 SI; if either does not, the year decides (the iteration with the
    non-SI body as F). Allegato A (p. 122) is silent on both points and on two TD04 (#130, decision 0).

    All bodies share the header, so the cedente (and, for TD16-TD20, TD22, TD23, TD28, TD29, the cessionario whose
    numbering Allegato A says counts instead) is the same for every pair. A lotto mixing, say, a TD01 with a TD16
    body compares documents whose uniqueness keys belong to different parties; such a pair is still reported, as the
    Elenco pseudo-code does.
    """
    seen: list[_Key] = []
    for body in bodies:
        general = _child(body, _DGD)
        key = _Key(
            body=body,
            number=_text(general, "Numero") or "",
            date=_date(_text(general, "Data") or ""),
            art73=_text(general, "Art73") == "SI",
            tipo=_text(general, "TipoDocumento") or "",
        )
        for other in seen:
            if _same_document(key, other) or _same_document(other, key):
                where = _xml.getpath(other.body)
                yield _finding("00409", general, f"Numero {key.number!r} of {_text(general, 'Data')} repeats {where}.")
                break
        seen.append(key)
