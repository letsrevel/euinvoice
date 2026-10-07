"""FatturaPA ``DatiBeniServizi`` and ``DatiPagamento`` → BG-25, BG-23, BG-16 and their ``.it`` data (#120).

App. 4.1 of the Regole tecniche v2.6 in reverse; row ids are those of the Rappresentazione tabellare. The VAT
summaries are read first: a line carries no ``EsigibilitaIVA``, so its category B (split payment) vs S comes from the
summary at its rate (App. 4.1 row 2.2.2.7, "Se BT-118 = B allora <EsigibilitaIVA> = S").
"""

import dataclasses
import typing as t
from decimal import Decimal

from lxml import etree

from euinvoice.errors import ParseError
from euinvoice.model import InvoiceLine, VatBreakdown
from euinvoice.model.codes._generated import UNECE_REC20_REC21_UNIT
from euinvoice.model.it import ItalianPayment, ItalianVatSummary, Natura
from euinvoice.syntax._marks import XML_SPACE
from euinvoice.syntax.fatturapa._read_codes import NATURE_CATEGORY, PAYMENT_MEANS, POLICY_ISSUE
from euinvoice.syntax.fatturapa._read_cursor import Cursor

__all__ = ["Summaries", "lines", "payment", "summaries"]

_CENT: t.Final = Decimal("0.01")
_ONE_UNIT: t.Final = "C62"  # UN/ECE Rec 20 "one": BT-130 when UnitaMisura is absent or not a code (#132 item 5)
_NO_PREFIX: t.Final = "Identificativo del prodotto"  # App. 4.1 row 2.2.1.3.1: CodiceTipo of a BT-155 without prefix
_REFERENCES: t.Final = ("RiferimentoTesto", "RiferimentoNumero", "RiferimentoData")  # 2.2.1.16.2-4


@dataclasses.dataclass(frozen=True)
class Summaries:
    """The 2.2.2 ``DatiRiepilogo`` of a body.

    Attributes:
        breakdown: One BG-23 per ``DatiRiepilogo`` (App. 4.1 row 2.2.2).
        extension: The ``Invoice.it.vat_summaries`` entries, one per rate, Natura and split payment.
        split: Per rate of the summaries without ``Natura``: whether each is split payment (``EsigibilitaIVA`` S).
    """

    breakdown: tuple[VatBreakdown, ...]
    extension: tuple[ItalianVatSummary, ...]
    split: t.Mapping[Decimal, frozenset[bool]]


def summaries(cursor: Cursor, goods: etree._Element | None) -> Summaries:
    """2.2.2 ``DatiRiepilogo`` → BG-23 (rows 2.2.2.1, .5, .6 → BT-119, BT-116, BT-117) and ``.it.vat_summaries``.

    BT-118 and BT-121 come from ``Natura`` by App. 5.1, BT-120 is the ``Natura`` code (App. 5.1, column BT-120);
    without ``Natura`` the category is B for ``EsigibilitaIVA`` S, else S. ``Natura``, ``EsigibilitaIVA`` and
    ``RiferimentoNormativo`` go to the extension (rows 2.2.2.2, .7, .8). ``SpeseAccessorie`` (derived from the lines)
    and ``Arrotondamento`` ("Mappatura non considerabile") are reported. Two summaries with the same rate, Natura and
    split payment but different extension data (a D vs I split) both become BG-23; what the second says differently
    (``EsigibilitaIVA``, ``RiferimentoNormativo``) is reported, as the extension holds one entry per key (#132 item
    15).
    """
    breakdown: list[VatBreakdown] = []
    entries: dict[tuple[Decimal, Natura | None, bool], ItalianVatSummary] = {}
    split: dict[Decimal, set[bool]] = {}
    for element in [cursor.use(e) for e in cursor.children(goods, "DatiRiepilogo")]:
        rate = cursor.decimal(element, "AliquotaIVA", "2.2.2.1")
        nature = _nature(cursor, element, "2.2.2.2")
        chargeability = cursor.code(element, "EsigibilitaIVA")
        legal = cursor.text(element, "RiferimentoNormativo")
        if nature is None:
            category, reason = ("B" if chargeability == "S" else "S"), None
            if rate is not None:
                split.setdefault(rate, set()).add(chargeability == "S")
        else:
            category, reason = NATURE_CATEGORY[nature]
        breakdown.append(
            cursor.model(
                VatBreakdown,
                element,
                taxable_amount=cursor.decimal(element, "ImponibileImporto", "2.2.2.5"),
                tax_amount=cursor.decimal(element, "Imposta", "2.2.2.6"),
                category_code=category,
                rate=rate,
                exemption_reason=None if nature is None else nature.value,
                exemption_reason_code=reason,
            )
        )
        if nature is None and chargeability is None and legal is None:
            continue
        entry = cursor.model(
            ItalianVatSummary, element, rate=rate, nature=nature, vat_chargeability=chargeability, legal_reference=legal
        )
        key = (entry.rate, entry.nature, chargeability == "S")
        if key not in entries:
            entries[key] = entry
        else:  # the extension keeps the first entry of a key: report what this one says differently
            kept = entries[key]
            if chargeability is not None and kept.vat_chargeability != entry.vat_chargeability:
                cursor.discard(cursor.children(element, "EsigibilitaIVA")[0])
            if legal is not None and kept.legal_reference != entry.legal_reference:
                cursor.discard(cursor.children(element, "RiferimentoNormativo")[0])
    return Summaries(tuple(breakdown), tuple(entries.values()), {r: frozenset(s) for r, s in split.items()})


def lines(cursor: Cursor, goods: etree._Element | None, vat: Summaries) -> tuple[InvoiceLine, ...]:
    """2.2.1 ``DettaglioLinee`` → BG-25, one line each (App. 4.1 row 2.2.1)."""
    return tuple(_line(cursor, cursor.use(element), vat) for element in cursor.children(goods, "DettaglioLinee"))


def _line(cursor: Cursor, element: etree._Element, vat: Summaries) -> InvoiceLine:
    supply = cursor.code(element, "TipoCessionePrestazione")  # 2.2.1.2 → .it.supply_type
    nature = _nature(cursor, element, "2.2.1.14")  # → .it.nature and BT-151 (App. 5.1)
    rate = cursor.decimal(element, "AliquotaIVA", "2.2.1.12")  # → BT-152
    start = cursor.date(element, "DataInizioPeriodo", "2.2.1.7")  # → BT-134
    end = cursor.date(element, "DataFinePeriodo", "2.2.1.8")  # → BT-135
    attributes = [_attribute(cursor, adg) for adg in cursor.children(element, "AltriDatiGestionali")]  # → BG-32
    quantity = cursor.decimal(element, "Quantita", "2.2.1.5")  # → BT-129; absent: 1 (#132 item 4)
    return cursor.model(
        InvoiceLine,
        element,
        identifier=cursor.code(element, "NumeroLinea"),  # 2.2.1.1 → BT-126
        invoiced_quantity=Decimal(1) if quantity is None else quantity,
        invoiced_quantity_unit_code=_unit(cursor, element),  # 2.2.1.6 → BT-130
        buyer_accounting_reference=cursor.text(element, "RiferimentoAmministrazione"),  # 2.2.1.15 → BT-133
        period=None if start is None and end is None else {"start_date": start, "end_date": end},
        price_details=_price(cursor, element),
        vat_information={"category_code": _category(cursor, element, nature, rate, vat), "rate": rate},
        item={
            "name": cursor.text(element, "Descrizione"),  # 2.2.1.4 → BT-153
            "sellers_identifier": _article(cursor, element),  # 2.2.1.3 → BT-155
            "attributes": tuple(a for a in attributes if a is not None),
        },
        net_amount=_net_amount(cursor, element),
        it=None if supply is None and nature is None else {"supply_type": supply, "nature": nature},
    )


def _nature(cursor: Cursor, parent: etree._Element, ident: str) -> Natura | None:
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


def _category(
    cursor: Cursor, element: etree._Element, nature: Natura | None, rate: Decimal | None, vat: Summaries
) -> str | None:
    """BT-151: by ``Natura`` (App. 5.1), else S, or B when the summary at the line's rate is split payment."""
    if nature is not None:
        return NATURE_CATEGORY[nature][0]
    if rate is None:
        return None  # build() names the missing BT-152 / BT-151
    if rate == 0:
        raise ParseError(
            "2.2.1.14 Natura is required for a line with AliquotaIVA 0 (SdI check 00400); without it App. 5.1 gives "
            "the line no VAT category (BT-151)",
            location=cursor.path(element),
        )
    modes = vat.split.get(rate, frozenset({False}))
    if len(modes) > 1:
        raise ParseError(
            f"2.2.2.7: the rate {format(rate, 'f')} has both a split-payment (EsigibilitaIVA S) and an ordinary "
            f"DatiRiepilogo, and a line has no EsigibilitaIVA, so its VAT category B or S is undecidable "
            f"({POLICY_ISSUE})",
            location=cursor.path(element),
        )
    return "B" if True in modes else "S"


def _unit(cursor: Cursor, element: etree._Element) -> str:
    """2.2.1.6 ``UnitaMisura`` → BT-130 if it is a UN/ECE Rec 20/21 code; else ``C62``, the text reported."""
    unit = cursor.one(element, "UnitaMisura")
    if unit is not None and (unit.text or "") in UNECE_REC20_REC21_UNIT:
        return unit.text or ""
    cursor.discard(unit)
    return _ONE_UNIT


def _price(cursor: Cursor, element: etree._Element) -> dict[str, object]:
    """2.2.1.9 ``PrezzoUnitario`` and 2.2.1.10 ``ScontoMaggiorazione`` → BG-29.

    App. 4.1 row 2.2.1.9 writes BT-148 when present, else BT-146; row 2.2.1.10 writes BT-147 as the ``Importo``, SC
    when positive, MG when negative. So one ``ScontoMaggiorazione`` reads as BT-148 = ``PrezzoUnitario``, BT-147 =
    ``Importo`` (or ``PrezzoUnitario * Percentuale / 100``, exact; a percentage next to an ``Importo`` is reported),
    negated for MG, and BT-146 = BT-148 - BT-147. Several are refused: cascade or sum is not settled (#130, #132 item
    12). Without one, BT-146 = ``PrezzoUnitario``.
    """
    unit_price = cursor.decimal(element, "PrezzoUnitario", "2.2.1.9")
    adjustments = cursor.children(element, "ScontoMaggiorazione")
    if len(adjustments) > 1:
        raise ParseError(
            f"2.2.1.10: {len(adjustments)} ScontoMaggiorazione on one line; whether they apply in cascade or add up "
            f"is not settled by the sources, so the reader does not apply them ({POLICY_ISSUE})",
            location=cursor.path(element),
        )
    if not adjustments or unit_price is None:
        return {"item_net_price": unit_price}
    adjustment = cursor.use(adjustments[0])
    kind = cursor.code(adjustment, "Tipo")
    percent = cursor.decimal(adjustment, "Percentuale", "2.2.1.10.2")
    amount = cursor.decimal(adjustment, "Importo", "2.2.1.10.3")
    if kind not in ("SC", "MG"):
        raise ParseError(f"2.2.1.10.1 Tipo: {kind!r} is not SC or MG (XSD 1.2.3)", location=cursor.path(adjustment))
    if amount is None and percent is None:
        cursor.discard(adjustment)  # nothing to apply (SdI check 00438); reported
        return {"item_net_price": unit_price}
    if amount is not None:
        cursor.discard(cursor.children(adjustment, "Percentuale")[0] if percent is not None else None)
    discount = amount if amount is not None else (unit_price * t.cast(Decimal, percent)).scaleb(-2)
    if kind == "MG":
        discount = -discount
    return {"item_net_price": unit_price - discount, "item_price_discount": discount, "item_gross_price": unit_price}


def _net_amount(cursor: Cursor, element: etree._Element) -> Decimal | None:
    """2.2.1.11 ``PrezzoTotale`` → BT-131, refused with more than two decimals (#132 item 1)."""
    total = cursor.decimal(element, "PrezzoTotale", "2.2.1.11")
    if total is not None and total != total.quantize(_CENT):
        raise ParseError(
            f"2.2.1.11 PrezzoTotale {format(total, 'f')} has more than two decimals; BT-131 is an EN 16931 amount "
            f"(BR-DEC-23) and the reader does not round it ({POLICY_ISSUE})",
            location=cursor.path(cursor.children(element, "PrezzoTotale")[0]),
        )
    return total


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


def payment(cursor: Cursor, body: etree._Element) -> dict[str, object]:
    """2.4 ``DatiPagamento`` → BG-16, BG-10, BT-9, BT-115 and ``.it.payment`` (App. 4.1 rows 2.4.x).

    The model holds one ``DatiPagamento`` with one ``DettaglioPagamento`` (``ItalianPayment``); further ones are
    reported, and then ``ImportoPagamento`` (an instalment, not the amount due) is reported too.
    """
    blocks = cursor.children(body, "DatiPagamento")
    if not blocks:
        return {}
    block = cursor.use(blocks[0])
    details = cursor.children(block, "DettaglioPagamento")
    detail = cursor.use(details[0]) if details else None
    conditions = cursor.code(block, "CondizioniPagamento")  # 2.4.1 → .it.payment.conditions
    method = cursor.code(detail, "ModalitaPagamento")  # 2.4.2.2 → .it.payment.method, BT-81 (App. 5.6)
    extension = cursor.model(ItalianPayment, block, conditions=conditions, method=method)
    iban = cursor.text(detail, "IBAN")  # 2.4.2.13 → BT-84
    bic = cursor.text(detail, "BIC") if iban is not None else None  # 2.4.2.16 → BT-86
    payee = cursor.text(detail, "Beneficiario")  # 2.4.2.1 → BT-59
    single = len(blocks) == 1 and len(details) == 1
    fields: dict[str, object] = {
        "it_payment": extension,
        "payment_due_date": cursor.date(detail, "DataScadenzaPagamento", "2.4.2.5"),  # → BT-9
        "amount_due": cursor.decimal(detail, "ImportoPagamento", "2.4.2.6") if single else None,  # → BT-115
        "payee": None if payee is None else {"name": payee},
    }
    if extension.method is not None:
        fields["payment_instructions"] = {
            "payment_means_type_code": PAYMENT_MEANS.get(extension.method, "1"),
            "remittance_information": cursor.text(detail, "CodicePagamento"),  # 2.4.2.21 → BT-83
            "credit_transfers": ()
            if iban is None
            else ({"payment_account_identifier": iban, "payment_service_provider_identifier": bic},),
        }
    return fields
