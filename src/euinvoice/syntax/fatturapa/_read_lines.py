"""FatturaPA ``DatiBeniServizi`` → BG-25, BG-23 and their ``.it`` data (#120).

App. 4.1 of the Regole tecniche v2.6 in reverse; row ids are those of the Rappresentazione tabellare. The VAT
summaries are read first: a line carries no ``EsigibilitaIVA``, so its category B (split payment) vs S comes from the
summary at its rate (App. 4.1 row 2.2.2.7, "Se BT-118 = B allora <EsigibilitaIVA> = S"). The BG-23 are built last,
from the summaries and the lines (:func:`breakdown`).
"""

import dataclasses
import typing as t
from decimal import Decimal

from lxml import etree

from euinvoice.errors import ParseError
from euinvoice.model import InvoiceLine, VatBreakdown
from euinvoice.model.amounts import quantize_amount
from euinvoice.model.codes._generated import UNECE_REC20_REC21_UNIT
from euinvoice.model.it import ItalianVatSummary, Natura
from euinvoice.syntax._marks import XML_SPACE
from euinvoice.syntax._read_errors import build
from euinvoice.syntax.fatturapa._exemption import exemption_reason
from euinvoice.syntax.fatturapa._read_adjust import Claimed, claim
from euinvoice.syntax.fatturapa._read_adjust import read as read_adjustments
from euinvoice.syntax.fatturapa._read_codes import NATURE_CATEGORY, POLICY_ISSUE
from euinvoice.syntax.fatturapa._read_cursor import Cursor

__all__ = [
    "Summaries",
    "Summary",
    "breakdown",
    "lines",
    "nature_category",
    "read_nature",
    "summaries",
    "vat_category",
    "vat_point_date_code",
]

_CENT: t.Final = Decimal("0.01")
_ZERO: t.Final = Decimal("0.00")
_TWO_DECIMALS: t.Final = Decimal("0.01")
_NO_EXEMPTION: t.Final = frozenset({"S", "B", "Z"})  # BR-S-10, BR-B-10, BR-Z-10: no BT-120 / BT-121
_ONE_UNIT: t.Final = "C62"  # UN/ECE Rec 20 "one": BT-130 when UnitaMisura is absent or not a code (#132 item 5)
_NO_PREFIX: t.Final = "Identificativo del prodotto"  # App. 4.1 row 2.2.1.3.1: CodiceTipo of a BT-155 without prefix
_REFERENCES: t.Final = ("RiferimentoTesto", "RiferimentoNumero", "RiferimentoData")  # 2.2.1.16.2-4


def _strip_trailing_zeros(value: Decimal) -> Decimal:
    """Strip trailing zeros from a Decimal, keeping at least 2 decimals.

    Used on computed BT-146 (item_net_price) and BT-147 (item_price_discount) after
    ScontoMaggiorazione cascading, to ensure the value (equality) is unchanged while
    the exponent strips unnecessary zeros. E.g., 420.92058750000000 becomes 420.9205875;
    480.00 stays 480.00. The result's exponent is always between -N and -2.
    """
    normalized = value.normalize()
    # normalize() can produce exponent notation for integers (e.g., 4.8E+2); ensure at least 2 decimals
    exponent = t.cast(int, normalized.as_tuple().exponent)
    if exponent > -2:
        return value.quantize(_TWO_DECIMALS)
    return normalized


@dataclasses.dataclass(frozen=True)
class Summary:
    """One 2.2.2 ``DatiRiepilogo`` as read, before the BG-23 of its category and rate is built."""

    element: etree._Element
    rate: Decimal
    nature: Natura | None
    chargeability: str | None
    legal: str | None
    taxable: Decimal
    tax: Decimal
    category: str
    reason_code: str | None


@dataclasses.dataclass(frozen=True)
class Summaries:
    """The 2.2.2 ``DatiRiepilogo`` of a body.

    Attributes:
        read: Each summary as read, in document order.
        extension: The ``Invoice.it.vat_summaries`` entries, one per rate, Natura and split payment.
        split: Per rate of the summaries without ``Natura``: whether it is split payment (``EsigibilitaIVA`` S).
        integration: The document is a TD16, which may carry a ``Natura`` with a rate (#132 item 21).
    """

    read: tuple[Summary, ...]
    extension: tuple[ItalianVatSummary, ...]
    split: t.Mapping[Decimal, bool]
    integration: bool = False


def summaries(cursor: Cursor, goods: etree._Element | None, *, integration: bool = False) -> Summaries:
    """Read 2.2.2 ``DatiRiepilogo`` (rows 2.2.2.1 to 2.2.2.8) and their ``.it.vat_summaries`` entries.

    The category is App. 5.1's for ``Natura``; without one it is B for ``EsigibilitaIVA`` S (row 2.2.2.7), else S.
    ``Natura``, ``EsigibilitaIVA`` and ``RiferimentoNormativo`` go to the extension, keyed by rate, Natura and split
    payment (#118). Two summaries of one key that differ (a D vs I split, two legal references) keep the first in
    the extension, and what the second says differently is reported (#132 item 15). ``SpeseAccessorie`` (derived
    from the lines) and ``Arrotondamento`` ("Mappatura non considerabile") are reported. Each rate has one payment
    mode (row 2.2.2.7), so split payment at one rate and ordinary VAT at another read as categories B and S, as
    declared, for validation to report BR-B-02 (#132 item 22); both at one rate are refused, as a line has no
    ``EsigibilitaIVA`` (#132 item 16). On a TD16 (``integration``), a ``Natura`` with a rate other than 0 reads as
    category S at that rate (#132 item 21, :func:`nature_category`).
    """
    read: list[Summary] = []
    entries: dict[tuple[Decimal, Natura | None, bool], ItalianVatSummary] = {}
    split: dict[Decimal, set[bool]] = {}
    for element in [cursor.use(e) for e in cursor.children(goods, "DatiRiepilogo")]:
        nature = read_nature(cursor, element, "2.2.2.2")
        chargeability = cursor.code(element, "EsigibilitaIVA")
        legal = cursor.text(element, "RiferimentoNormativo")
        values = {"nature": nature, "vat_chargeability": chargeability, "legal_reference": legal}
        entry = build(ItalianVatSummary, element, {"rate": cursor.decimal(element, "AliquotaIVA", "2.2.2.1"), **values})
        if nature is None:
            category, reason = ("B" if chargeability == "S" else "S"), None
            split.setdefault(entry.rate, set()).add(chargeability == "S")
        else:
            category, reason = nature_category(cursor, element, nature, entry.rate, integration=integration)
        taxable = _required(cursor, element, "ImponibileImporto", "2.2.2.5")
        tax = _required(cursor, element, "Imposta", "2.2.2.6")
        read.append(Summary(element, entry.rate, nature, chargeability, legal, taxable, tax, category, reason))
        if nature is None and chargeability is None and legal is None:
            continue
        key = (entry.rate, entry.nature, chargeability == "S")
        if key not in entries:
            entries[key] = entry
            continue
        kept = entries[key]  # the extension keeps the first entry of a key: report what this one says differently
        if chargeability is not None and kept.vat_chargeability != entry.vat_chargeability:
            cursor.discard(cursor.children(element, "EsigibilitaIVA")[0])
        if legal is not None and kept.legal_reference != entry.legal_reference:
            cursor.discard(cursor.children(element, "RiferimentoNormativo")[0])
    for rate, modes in split.items():
        if len(modes) > 1:
            raise ParseError(
                f"2.2.2.7: the rate {format(rate, 'f')} has both a split-payment (EsigibilitaIVA S) and an ordinary "
                "DatiRiepilogo, and a line has no EsigibilitaIVA (XSD 1.2.3), so its VAT category B or S is "
                f"undecidable ({POLICY_ISSUE})",
                location=cursor.path(goods if goods is not None else cursor.root),
            )
    return Summaries(
        tuple(read), tuple(entries.values()), {rate: True in modes for rate, modes in split.items()}, integration
    )


def _required(cursor: Cursor, element: etree._Element, name: str, ident: str) -> Decimal:
    value = cursor.decimal(element, name, ident)
    if value is None:
        raise ParseError(f"{ident} {name} is missing (required by XSD 1.2.3)", location=cursor.path(element))
    return value


def breakdown(
    vat: Summaries, at: etree._Element, extra: t.Iterable[tuple[str, Decimal]] = ()
) -> tuple[VatBreakdown, ...]:
    """BG-23: one per VAT category and rate, from the summaries of that category and rate.

    App. 4.1 row 2.2.2 maps ``DatiRiepilogo`` to BG-23, but FatturaPA keeps one summary per rate and Natura (and may
    split by EsigibilitaIVA), while EN 16931 has one BG-23 per category and rate (BR-S-08 and its siblings sum per
    category and rate): several summaries can make one BG-23 (e.g. N2.2 and N4, both E at 0 %, App. 5.1). Their
    Natura and RiferimentoNormativo stay in ``Invoice.it.vat_summaries``.

    * BT-116 / BT-117 are the sums of the summaries' ``ImponibileImporto`` / ``Imposta`` (rows 2.2.2.5-6), exactly
      as declared. A document whose summaries do not add up to its lines keeps them: the CEN rules (BR-S-08, …) judge
      it through ``validate()`` / ``calc.check`` (D8); the reader neither rounds nor rewrites them (#132 item 22).
    * BT-120 is ``Natura`` and ``RiferimentoNormativo`` joined by a space (rows 2.2.2.2, 2.2.2.8: "vengono
      concatenati"), the summaries of one BG-23 joined by ``"; "``: the separators are #132's, shared with the
      writer (:func:`~euinvoice.syntax.fatturapa._exemption.exemption_reason`). BT-121 is App. 5.1's code when they
      share it. Neither is set for S and B (BR-S-10, BR-B-10) nor for Z (App. 5.1 row N1 has no
      BT-120; BR-Z-10).
    * ``extra`` adds an empty BG-23 for a category and rate that only a document level charge or allowance the
      reader adds itself uses (the stamp duty's Z, BR-Z-01), unless the summaries already have one.
    """
    groups: dict[tuple[str, Decimal], list[Summary]] = {}
    for summary in vat.read:
        groups.setdefault((summary.category, summary.rate), []).append(summary)
    for key in extra:
        groups.setdefault(key, [])
    found: list[VatBreakdown] = []
    for (category, rate), members in groups.items():
        reason, code = _exemption(category, members)
        values = {
            "taxable_amount": sum((m.taxable for m in members), _ZERO),
            "tax_amount": sum((m.tax for m in members), _ZERO),
            "category_code": category,
            "rate": rate,
            "exemption_reason": reason,
            "exemption_reason_code": code,
        }
        found.append(build(VatBreakdown, members[0].element if members else at, values))
    return tuple(found)


def _exemption(category: str, members: list[Summary]) -> tuple[str | None, str | None]:
    """BT-120 and BT-121 of the BG-23 made of ``members`` (see :func:`breakdown`)."""
    if category in _NO_EXEMPTION or not members:
        return None, None
    # A member of a category outside _NO_EXEMPTION has a Natura: only App. 5.1's Natura rows give one (vat_category).
    natures: list[tuple[Natura, str | None]] = []
    for member in members:
        if member.nature is None:  # pragma: no cover - the invariant above: fail loudly if it ever breaks
            raise AssertionError(f"a category {category} VAT summary without Natura reached BT-120")
        natures.append((member.nature, member.legal))
    reason = exemption_reason(natures)
    codes = {member.reason_code for member in members}
    return reason, codes.pop() if len(codes) == 1 else None


def vat_point_date_code(vat: Summaries) -> str | None:
    """BT-8 ``432`` when every summary that is not split payment has ``EsigibilitaIVA`` D, else ``None``.

    Row 2.2.2.7: "Se BT-8 = 432 allora <EsigibilitaIVA> = D"; I comes from both 3 and 35 there, so it gives no BT-8.
    """
    modes = {summary.chargeability for summary in vat.read if summary.chargeability != "S"}
    return "432" if modes == {"D"} else None


def lines(cursor: Cursor, goods: etree._Element | None, vat: Summaries) -> tuple[InvoiceLine, ...]:
    """2.2.1 ``DettaglioLinee`` → BG-25, one line each (App. 4.1 row 2.2.1)."""
    return tuple(_line(cursor, cursor.use(element), vat) for element in cursor.children(goods, "DettaglioLinee"))


def _line(cursor: Cursor, element: etree._Element, vat: Summaries) -> InvoiceLine:
    supply = cursor.code(element, "TipoCessionePrestazione")  # 2.2.1.2 → .it.supply_type
    nature = read_nature(cursor, element, "2.2.1.14")  # → .it.nature and BT-151 (App. 5.1)
    rate = cursor.decimal(element, "AliquotaIVA", "2.2.1.12")  # → BT-152
    start = cursor.date(element, "DataInizioPeriodo", "2.2.1.7")  # → BT-134
    end = cursor.date(element, "DataFinePeriodo", "2.2.1.8")  # → BT-135
    claimed = claim(cursor, element)  # the AltriDatiGestionali that explain a ScontoMaggiorazione → BG-27 / BG-28
    attributes = [
        _attribute(cursor, adg) for adg in cursor.children(element, "AltriDatiGestionali") if adg not in claimed.entries
    ]  # → BG-32
    # 2.2.1.5 Quantita → BT-129. Absent, it is 1: Allegato A 1.9.1 says Quantita "può non essere valorizzato nei casi
    # in cui la prestazione non sia quantificabile", 00423 checks PrezzoTotale as (PrezzoUnitario ±
    # ScontoMaggiorazione) * Quantita, and the official FPR03 body 2 has PrezzoUnitario = PrezzoTotale.
    quantity = cursor.decimal(element, "Quantita", "2.2.1.5")
    price, negative = _price(cursor, element, claimed)
    net_amount, exact = _net_amount(cursor, element)  # 2.2.1.11 → BT-131, .it.total_price beyond two decimals
    count = Decimal(1) if quantity is None else quantity
    allowances, charges = read_adjustments(cursor, element, claimed, count, negative=negative)
    values = {
        "identifier": cursor.code(element, "NumeroLinea"),  # 2.2.1.1 → BT-126
        "invoiced_quantity": -count if negative else count,
        "invoiced_quantity_unit_code": _unit(cursor, element),  # 2.2.1.6 → BT-130
        "buyer_accounting_reference": cursor.text(element, "RiferimentoAmministrazione"),  # 2.2.1.15 → BT-133
        "period": None if start is None and end is None else {"start_date": start, "end_date": end},
        "price_details": price,
        "allowances": allowances,  # 2.2.1.10 SC + 2.2.1.16 → BG-27
        "charges": charges,  # 2.2.1.10 MG + 2.2.1.16 → BG-28
        "vat_information": {"category_code": vat_category(cursor, element, nature, rate, vat), "rate": rate},
        "item": {
            "name": cursor.text(element, "Descrizione"),  # 2.2.1.4 → BT-153
            "sellers_identifier": _article(cursor, element),  # 2.2.1.3 → BT-155
            "attributes": tuple(a for a in attributes if a is not None),
        },
        "net_amount": net_amount,
        "it": None
        if supply is None and nature is None and exact is None
        else {"supply_type": supply, "nature": nature, "total_price": exact},
    }
    return build(InvoiceLine, element, values)


def read_nature(cursor: Cursor, parent: etree._Element, ident: str) -> Natura | None:
    """``Natura``, refusing a code App. 5.1 gives no VAT category (#132 item 6)."""
    element = cursor.one(parent, "Natura")
    if element is None:
        return None
    text = (element.text or "").strip(XML_SPACE)
    try:
        nature = Natura(text)
    except ValueError:
        raise ParseError(
            f"{ident} Natura: {text!r} is not a NaturaType code (XSD 1.2.3)", location=cursor.path(element)
        ) from None
    if nature not in NATURE_CATEGORY:
        raise ParseError(
            f"{ident} Natura: the generic code {nature} has no VAT category in App. 5.1 of the Regole tecniche v2.6 "
            f"(the SdI refuses it since 2021, check 00445); the reader does not guess one ({POLICY_ISSUE})",
            location=cursor.path(element),
        )
    return nature


def nature_category(
    cursor: Cursor, element: etree._Element, nature: Natura, rate: Decimal | None, *, integration: bool
) -> tuple[str, str | None]:
    """The VAT category and BT-121 of a ``Natura`` (App. 5.1), or category S for a TD16 ``Natura`` with a rate.

    Every App. 5.1 category of a ``Natura`` (Z, E, G, K, AE) has rate 0 in EN 16931 (BR-Z-05, BR-E-05, BR-G-05,
    BR-IC-05, BR-AE-05 and their -06/-07/-09 siblings). The SdI accepts a ``Natura`` with a rate other than 0 only on
    TD16 (Allegato A 1.9.1, checks 00401 and 00430: "ad eccezione del caso in cui l'elemento TipoDocumento assume
    valore TD16"), where "è possibile indicare sia la natura … sia un valore diverso da zero". The maintainer's
    decision (#132 item 21): that is VAT charged at the rate, so category S (BR-S-05: rate above 0; no BT-120 or
    BT-121, BR-S-10) with the ``Natura`` kept in ``.it``. Any other document type is refused.

    Raises:
        ParseError: ``rate`` is not 0 and the document is not a TD16.
    """
    category, code = NATURE_CATEGORY[nature]
    if rate is None or rate == 0:
        return category, code
    if integration:
        return "S", None
    raise ParseError(
        f"Natura {nature} (VAT category {category}, App. 5.1) with AliquotaIVA {format(rate, 'f')}: EN 16931 "
        f"requires rate 0 for category {category} (BR-{'IC' if category == 'K' else category}-05), so the reader "
        "does not map it; only a TD16 may carry a Natura with a rate (Allegato A 1.9.1, 00401 and 00430), and it "
        f"reads as category S at that rate ({POLICY_ISSUE})",
        location=cursor.path(element),
    )


def vat_category(
    cursor: Cursor,
    element: etree._Element,
    nature: Natura | None,
    rate: Decimal | None,
    vat: Summaries,
    ident: str = "2.2.1.14",
) -> str | None:
    """BT-151 / BT-102: by ``Natura`` (App. 5.1), else S, or B when the summary at the rate is split payment."""
    if nature is not None:
        return nature_category(cursor, element, nature, rate, integration=vat.integration)[0]
    if rate is None:
        return None  # build() names the missing BT-152 / BT-151
    if rate == 0:
        raise ParseError(
            f"{ident} Natura is required with AliquotaIVA 0 (SdI checks 00400, 00413); without it App. 5.1 gives no "
            "VAT category (BT-151, BT-102)",
            location=cursor.path(element),
        )
    return "B" if vat.split.get(rate, False) else "S"


def _unit(cursor: Cursor, element: etree._Element) -> str:
    """2.2.1.6 ``UnitaMisura`` → BT-130 if it is a UN/ECE Rec 20/21 code; else ``C62``, the text reported."""
    unit = cursor.one(element, "UnitaMisura")
    code = "" if unit is None else (unit.text or "").strip(XML_SPACE)
    if code in UNECE_REC20_REC21_UNIT:
        return code
    cursor.discard(unit)
    return _ONE_UNIT


def _price(cursor: Cursor, element: etree._Element, claimed: Claimed) -> tuple[dict[str, object], bool]:
    """2.2.1.9 ``PrezzoUnitario`` and 2.2.1.10 ``ScontoMaggiorazione`` → BG-29, and whether the line is negative.

    App. 4.1 row 2.2.1.9 writes BT-148 when present, else BT-146; row 2.2.1.10 writes BT-147 as the ``Importo``, SC
    when positive, MG when negative. Several ``ScontoMaggiorazione`` fold into one BT-147 by the SdI's own algorithm,
    Elenco dei controlli v2.0 check 00423 (pp. 26-30, Casi 1-3), the one :func:`euinvoice.validation.sdi.check` runs
    on the XML (the reader may not import the validation layer, so the few lines are repeated). They are walked in
    document order with a running price that starts at ``PrezzoUnitario``; each changes it by ``sign * Importo``
    (SC -1, MG +1) or, without ``Importo``, by ``sign * price * Percentuale / 100``, exactly, so a percentage applies
    to the price the entries before it left (a percentage next to an ``Importo`` is reported). An entry with neither
    is reported (SdI check 00438) and changes nothing. BT-148 = ``PrezzoUnitario``, BT-147 = the sum of the
    discounts (the changes, negated) and BT-146 = BT-148 - BT-147. Without one,
    BT-146 = ``PrezzoUnitario``. Computed BT-146 and BT-147 have trailing zeros stripped, keeping at least 2 decimals.

    A negative ``PrezzoUnitario`` (``Amount8DecimalType`` is signed, ``QuantitaType`` is not, XSD 1.2.3) is how
    FatturaPA writes a discount or rebate line. BR-27 forbids a negative BT-146, but no CEN rule restricts the sign of
    BT-129, so the prices are negated and the caller negates BT-129: the line net amount is unchanged, and a writer
    can turn it back, as FatturaPA quantities are never negative.

    The ``ScontoMaggiorazione`` that ``AltriDatiGestionali`` explain are BG-27 / BG-28 (:mod:`._read_adjust`), not
    BT-147: they move the running price, as the SdI's cascade includes them, but are left out of BT-147, and
    BT-146 = BT-148 - BT-147 still holds.
    """
    unit_price = cursor.decimal(element, "PrezzoUnitario", "2.2.1.9")
    if unit_price is None:
        return {"item_net_price": None}, False
    sign = Decimal(-1) if unit_price < 0 else Decimal(1)
    price = unit_price  # the running price of 00423's cascade (signed, as the SdI computes it)
    discount = Decimal(0)  # BT-147: the entries nothing claims
    applied = False
    for position, found in enumerate(cursor.children(element, "ScontoMaggiorazione"), 1):
        adjustment = cursor.use(found)
        kind = cursor.code(adjustment, "Tipo")
        percent = cursor.decimal(adjustment, "Percentuale", "2.2.1.10.2")
        amount = cursor.decimal(adjustment, "Importo", "2.2.1.10.3")
        if kind not in ("SC", "MG"):
            raise ParseError(f"2.2.1.10.1 Tipo: {kind!r} is not SC or MG (XSD 1.2.3)", location=cursor.path(adjustment))
        if amount is None and percent is None:
            cursor.discard(adjustment)  # nothing to apply (SdI check 00438); reported
            continue
        unclaimed = position not in claimed.reasons
        if amount is not None and percent is not None and unclaimed:
            cursor.discard(cursor.children(adjustment, "Percentuale")[0])
        change = amount if amount is not None else (price * t.cast(Decimal, percent)).scaleb(-2)
        price += change if kind == "MG" else -change
        if unclaimed:
            discount += -change if kind == "MG" else change
            applied = True
    if not applied:
        return {"item_net_price": sign * unit_price}, sign < 0
    return {
        "item_net_price": _strip_trailing_zeros(sign * (unit_price - discount)),
        "item_price_discount": _strip_trailing_zeros(sign * discount),
        "item_gross_price": sign * unit_price,
    }, sign < 0


def _net_amount(cursor: Cursor, element: etree._Element) -> tuple[Decimal | None, Decimal | None]:
    """2.2.1.11 ``PrezzoTotale`` → BT-131, and the exact declared value when BT-131 had to round it (#132 item 1).

    ``Amount8DecimalType`` has 2 to 8 decimals, while BT-131 is an EN amount of at most two (BR-DEC-23). A value
    beyond two decimals gives BT-131 rounded half up (D11, :func:`~euinvoice.model.amounts.quantize_amount`); the
    exact value goes to ``.it.total_price`` (2.2.1.11) and the element's text is reported as only partly mapped
    (``…/PrezzoTotale/text()`` in ``unmapped``). A value with only trailing zeros loses nothing and is not reported.
    No other declared amount changes (item 22).
    """
    total = cursor.decimal(element, "PrezzoTotale", "2.2.1.11")
    if total is None or total == total.quantize(_CENT):
        return total, None
    cursor.partial(cursor.children(element, "PrezzoTotale")[0])
    return quantize_amount(total), total


def _article(cursor: Cursor, element: etree._Element) -> str | None:
    """The first 2.2.1.3 ``CodiceArticolo`` → BT-155 ``CodiceTipo:CodiceValore``; further ones are reported.

    App. 4.1 row 2.2.1.3.1: no prefix when ``CodiceTipo`` is "Identificativo del prodotto".
    """
    article = cursor.one(element, "CodiceArticolo")
    if article is None:
        return None
    kind, value = cursor.text(article, "CodiceTipo"), cursor.text(article, "CodiceValore")
    return value if kind == _NO_PREFIX else f"{kind}:{value}"


def _attribute(cursor: Cursor, element: etree._Element) -> dict[str, str] | None:
    """2.2.1.16 ``AltriDatiGestionali`` → BG-32: ``TipoDato`` → BT-160, the first ``Riferimento*`` → BT-161.

    Without any ``Riferimento*`` there is no BT-161 (BR-54), so the block is reported whole; further ones are
    reported.
    """
    references = [found for name in _REFERENCES for found in cursor.children(element, name)]
    if not references:
        return None
    cursor.use(element)
    value = cursor.use(references[0]).text or ""
    return {
        "name": cursor.text(element, "TipoDato") or "",
        "value": value if references[0].tag == "RiferimentoTesto" else value.strip(XML_SPACE),
    }
