"""The FPR12 2.2 ``<DatiBeniServizi>``: 2.2.1 ``<DettaglioLinee>`` lines and 2.2.2 ``<DatiRiepilogo>`` summaries.

There is one DettaglioLinee per INVOICE LINE (BG-25).

Element order follows ``DettaglioLineeType``, ``ScontoMaggiorazioneType`` and ``DatiRiepilogoType`` of the pinned XSD
1.2.3; rows cited are App. 4.1 of the SdI "Regole tecniche fatture europee" v2.6.

Summaries. Allegato A 1.9.1 (DatiRiepilogo) asks for one block "per ogni aliquota IVA e modalità di versamento
dell'imposta ("scissione dei pagamenti" od ordinaria), e/o per ogni natura", so a block is keyed like
``ItalianVatSummary``: (rate, Natura, split payment), split payment being VAT category B (App. 4.1 row 2.2.2.7). Each
block lies inside one VAT BREAKDOWN (BG-23) of the same category and rate (App. 5.1 gives each Natura one category),
and its ``ImponibileImporto`` is the sum of its lines' BT-131. A BG-23 must equal the sum of its blocks: an amount the
lines do not carry (a document level allowance or charge) has no place in DatiRiepilogo (SdI 00422 compares it with
the lines), and a BG-23 without lines has no block at all (except the zero stamp duty's own). A BG-23 with one block
gives it its BT-117 (row 2.2.2.6); one split by Natura (rate 0 only) gives each block
``AliquotaIVA * ImponibileImporto / 100`` rounded half up (Allegato A, DatiRiepilogo / Imposta), and their sum must
equal BT-117. :func:`summarize` reports what keeps the blocks from being built as pre-flight findings.
"""

import dataclasses
import re
import typing as t
from decimal import Decimal

from lxml import etree

from euinvoice.model import Invoice, InvoiceLine, VatBreakdown
from euinvoice.model.amounts import quantize_amount
from euinvoice.model.codes import VatCategory
from euinvoice.model.it import EsigibilitaIVA, ItalianExtension, ItalianVatSummary, Natura, TipoCessionePrestazione
from euinvoice.report import Finding
from euinvoice.syntax.fatturapa._write_codes import CHARGEABILITY_OF_VAT_POINT, VATEX_OF_NATURA
from euinvoice.syntax.fatturapa._write_format import (
    BASIC,
    amount2,
    amount8,
    cannot_express,
    child,
    date,
    quantity,
    rate,
    text,
)
from euinvoice.syntax.fatturapa._write_refuse import is_stamp_duty_group
from euinvoice.syntax.fatturapa._write_rules import SUMMARY, UNSUPPORTED_CATEGORIES, finding

__all__ = ["Block", "summarize", "write_goods"]

_LINE_NUMBER_MAX: t.Final = 9999  # NumeroLineaType
_HUNDRED: t.Final = Decimal(100)


def _line_number(identifier: str, term: str) -> str:
    """NumeroLinea (row 2.2.1.1, ``NumeroLineaType`` 1..9999) from BT-126.

    BT-126 is text: only its canonical decimal form is accepted, so that it reads back unchanged.
    """
    canonical = identifier.isascii() and identifier.isdigit() and str(int(identifier)) == identifier
    if not canonical or not 1 <= int(identifier) <= _LINE_NUMBER_MAX:
        raise cannot_express(term, f"NumeroLinea (NumeroLineaType) is an integer from 1 to 9999, got {identifier!r}")
    return identifier


def _write_line(goods: etree._Element, index: int, line: InvoiceLine) -> None:
    """One DettaglioLinee (rows 2.2.1.1-2.2.1.15)."""

    def term(ident: str, path: str) -> str:
        return f"{ident} (lines[{index}].{path})"

    nature = None if line.it is None else line.it.nature
    supply = None if line.it is None else line.it.supply_type
    element = child(goods, "DettaglioLinee")
    child(element, "NumeroLinea", _line_number(line.identifier, term("BT-126", "identifier")))
    if supply is not None:
        child(element, "TipoCessionePrestazione", supply)
    child(
        element,
        "Descrizione",
        text(line.item.name, term("BT-153", "item.name"), "2.2.1.4 Descrizione (String1000LatinType)", maximum=1000),
    )
    child(
        element, "Quantita", quantity(line.invoiced_quantity, term("BT-129", "invoiced_quantity"), "2.2.1.5 Quantita")
    )
    child(
        element,
        "UnitaMisura",
        text(
            line.invoiced_quantity_unit_code,
            term("BT-130", "invoiced_quantity_unit_code"),
            "2.2.1.6 UnitaMisura (String10Type)",
            maximum=10,
            charset=BASIC,
        ),
    )
    if line.period is not None:
        if line.period.start_date is not None:
            child(
                element,
                "DataInizioPeriodo",
                date(line.period.start_date, term("BT-134", "period.start_date"), "2.2.1.7 DataInizioPeriodo"),
            )
        if line.period.end_date is not None:
            child(
                element,
                "DataFinePeriodo",
                date(line.period.end_date, term("BT-135", "period.end_date"), "2.2.1.8 DataFinePeriodo"),
            )
    price = line.price_details
    # Row 2.2.1.9: "Se presente BT-148, viene valorizzato con il suo importo, altrimenti ... BT-146".
    if price.item_gross_price is not None:
        child(
            element,
            "PrezzoUnitario",
            amount8(price.item_gross_price, term("BT-148", "price_details.item_gross_price"), "2.2.1.9 PrezzoUnitario"),
        )
    else:
        child(
            element,
            "PrezzoUnitario",
            amount8(price.item_net_price, term("BT-146", "price_details.item_net_price"), "2.2.1.9 PrezzoUnitario"),
        )
    if price.item_price_discount is not None:
        _price_discount(element, price.item_price_discount, term("BT-147", "price_details.item_price_discount"))
    child(element, "PrezzoTotale", amount8(line.net_amount, term("BT-131", "net_amount"), "2.2.1.11 PrezzoTotale"))
    child(
        element,
        "AliquotaIVA",
        rate(
            t.cast(Decimal, line.vat_information.rate), term("BT-152", "vat_information.rate"), "2.2.1.12 AliquotaIVA"
        ),
    )
    if nature is not None:
        child(element, "Natura", nature)
    if line.buyer_accounting_reference is not None:
        child(
            element,
            "RiferimentoAmministrazione",
            text(
                line.buyer_accounting_reference,
                term("BT-133", "buyer_accounting_reference"),
                "2.2.1.15 RiferimentoAmministrazione (String20Type)",
                maximum=20,
                charset=BASIC,
            ),
        )


def _price_discount(element: etree._Element, discount: Decimal, term: str) -> None:
    """2.2.1.10 ScontoMaggiorazione from BT-147, after the gross price BT-148 (preflight requires one).

    Row 2.2.1.10.1: "Se BT-147 maggiore di zero è valorizzato con 'SC', se minore di zero con 'MG'"; row 2.2.1.10.3:
    the amount "a meno del segno". A zero discount needs no element: PrezzoUnitario then equals BT-146.
    """
    if discount == 0:
        return
    adjustment = child(element, "ScontoMaggiorazione")
    child(adjustment, "Tipo", "SC" if discount > 0 else "MG")
    child(adjustment, "Importo", amount8(discount.copy_abs(), term, "2.2.1.10.3 Importo"))


@dataclasses.dataclass
class Block:
    """One DatiRiepilogo (2.2.2)."""

    rate: Decimal
    nature: Natura | None
    category: VatCategory
    taxable: Decimal = Decimal("0.00")
    accessory: Decimal | None = None
    tax: Decimal = Decimal("0.00")
    summary: ItalianVatSummary | None = None
    chargeability: EsigibilitaIVA | None = None
    legal_reference: str | None = None

    @property
    def split(self) -> bool:
        """Split payment: VAT category B (EsigibilitaIVA S, row 2.2.2.7)."""
        return self.category is VatCategory.SPLIT_PAYMENT


type _Key = tuple[Decimal, Natura | None, bool]


def _blocks(invoice: Invoice) -> dict[_Key, Block]:
    """The blocks of the lines; a line without a rate or of category O/L/M is left to its own finding."""
    blocks: dict[_Key, Block] = {}
    for line in invoice.lines:
        category = VatCategory(line.vat_information.category_code)
        line_rate = line.vat_information.rate
        if line_rate is None or category in UNSUPPORTED_CATEGORIES:
            continue
        nature = None if line.it is None else line.it.nature
        key = (line_rate, nature, category is VatCategory.SPLIT_PAYMENT)
        block = blocks.setdefault(key, Block(line_rate, nature, category))
        block.taxable += line.net_amount
        if line.it is not None and line.it.supply_type is TipoCessionePrestazione.AC:
            # Row 2.2.2.3 SpeseAccessorie: the sum of BT-131 of the lines whose TipoCessionePrestazione is AC.
            block.accessory = (block.accessory or Decimal("0.00")) + line.net_amount
    return blocks


def _of_group(group: VatBreakdown, block: Block) -> bool:
    return VatCategory(group.category_code) is block.category and group.rate == block.rate


def _group(invoice: Invoice, it: ItalianExtension, index: int, blocks: dict[_Key, Block]) -> t.Iterator[Finding]:
    """Check one BG-23 against its blocks and give them their Imposta."""
    group = invoice.vat_breakdown[index]
    location = f"vat_breakdown[{index}]"
    mine = [block for block in blocks.values() if _of_group(group, block)]
    if not mine:
        own = group.taxable_amount == group.tax_amount == 0 and is_stamp_duty_group(
            invoice, it, group.category_code, group.rate
        )
        if not own:
            yield finding(
                SUMMARY,
                location,
                f"BG-23 of category {group.category_code} has no line, so no DatiRiepilogo can carry it (only the zero "
                "stamp duty's own breakdown, BR-IT-DC-480, is left to 2.1.1.6 DatiBollo)",
            )
        return
    taxable = sum((block.taxable for block in mine), Decimal("0.00"))
    if taxable != group.taxable_amount:
        yield finding(
            SUMMARY,
            f"{location}.taxable_amount",
            f"BT-116 {group.taxable_amount} differs from the sum of its lines' BT-131, {taxable}; DatiRiepilogo has no "
            "place for a document level allowance or charge (SdI 00422 compares ImponibileImporto with the lines)",
        )
    if len(mine) == 1:
        mine[0].tax = group.tax_amount
        return
    for block in mine:
        block.tax = quantize_amount(block.rate * block.taxable / _HUNDRED)
    tax = sum((block.tax for block in mine), Decimal("0.00"))
    if tax != group.tax_amount:
        yield finding(
            SUMMARY,
            f"{location}.tax_amount",
            f"BT-117 {group.tax_amount} differs from the Imposta of its {len(mine)} DatiRiepilogo by Natura, {tax}",
        )


def _amounts(invoice: Invoice, it: ItalianExtension, blocks: dict[_Key, Block]) -> t.Iterator[Finding]:
    """Check every BG-23 against its blocks (see the module docstring) and every block against a BG-23."""
    for index, group in enumerate(invoice.vat_breakdown):
        if VatCategory(group.category_code) not in UNSUPPORTED_CATEGORIES:  # else reported by structure()
            yield from _group(invoice, it, index, blocks)
    for block in blocks.values():
        if not any(_of_group(group, block) for group in invoice.vat_breakdown):
            yield finding(
                SUMMARY,
                "vat_breakdown",
                f"no VAT BREAKDOWN of category {block.category} at rate {format(block.rate, 'f')}, which lines carry "
                "(BR-CO-18)",
            )


def _match_summaries(it: ItalianExtension, blocks: dict[_Key, Block]) -> t.Iterator[Finding]:
    """Attach each ``it.vat_summaries`` entry to the block of its key; an entry with no block is reported."""
    for index, summary in enumerate(it.vat_summaries):
        key = (summary.rate, summary.nature, summary.vat_chargeability is EsigibilitaIVA.S)
        if key not in blocks:
            mode = "split payment (EsigibilitaIVA S, VAT category B)" if key[2] else "ordinary payment"
            yield finding(
                SUMMARY,
                f"it.vat_summaries[{index}]",
                f"it.vat_summaries[{index}] cannot be written in FatturaPA: no line has rate "
                f"{format(summary.rate, 'f')}, Natura {summary.nature} and {mode}, so this DatiRiepilogo data belongs "
                "to no summary",
            )
            continue
        blocks[key].summary = summary
        blocks[key].legal_reference = summary.legal_reference


def _chargeability(invoice: Invoice, blocks: dict[_Key, Block]) -> t.Iterator[Finding]:
    """EsigibilitaIVA (row 2.2.2.7): S for category B; else the summary's, or BT-8's (3, 35 → I, 432 → D)."""
    code = invoice.vat_point_date_code
    derived = None if code is None else CHARGEABILITY_OF_VAT_POINT[code]
    if derived is not None and blocks and all(block.split for block in blocks.values()):
        yield finding(
            SUMMARY,
            "vat_point_date_code",
            "BT-8: every DatiRiepilogo is split payment (EsigibilitaIVA S, App. 4.1 row 2.2.2.7), so none can carry it",
        )
    for block in blocks.values():
        if block.split:
            block.chargeability = EsigibilitaIVA.S
            continue
        own = None if block.summary is None else block.summary.vat_chargeability
        if own is not None and derived is not None and own is not derived:
            yield finding(
                SUMMARY,
                "vat_point_date_code",
                f"BT-8 gives EsigibilitaIVA {derived} (App. 4.1 row 2.2.2.7), but it.vat_summaries sets {own} for rate "
                f"{format(block.rate, 'f')}",
            )
        block.chargeability = own or derived


_REFERENCE: t.Final = re.compile(r"[\x00-\xff]{1,100}")  # String100LatinType (xs:normalizedString)


def _reference(reason: str, mine: list[Block]) -> str | None:
    """Put BT-120 into the group's one block as RiferimentoNormativo; why it cannot be, or ``None``."""
    if len(mine) != 1:
        return f"its VAT BREAKDOWN has {len(mine)} DatiRiepilogo, not one"
    given = mine[0].legal_reference
    if given is not None:
        return None if given == reason else f"it.vat_summaries sets RiferimentoNormativo {given!r} for that summary"
    if not _REFERENCE.fullmatch(reason) or any(c in reason for c in "\t\n\r"):
        return "String100LatinType takes 1 to 100 Latin-1 characters without tab or line break"
    mine[0].legal_reference = reason
    return None


def _exemption_reasons(invoice: Invoice, blocks: dict[_Key, Block]) -> t.Iterator[Finding]:
    """BT-120 and BT-121 of each VAT BREAKDOWN: written, carried by Natura, or reported (never dropped).

    * BT-120 is 2.2.2.8 RiferimentoNormativo (App. 4.1 rows 2.2.2.2 and 2.2.2.8: "In BT-120 vengono concatenati
      2.2.2.2 <Natura> e 2.2.2.8 <RiferimentoNormativo>"). It is written into the group's DatiRiepilogo when the group
      has exactly one and ``it.vat_summaries`` gives it no ``legal_reference``; equal to that ``legal_reference`` it
      is already written. Otherwise it would be lost: an ``error``.
    * BT-121 is carried by Natura when it is the code App. 5.1 gives every Natura of the group (``VATEX-EU-132`` for
      N2.x, N4, N5; ``-G`` for N3.1, N3.3-N3.5; ``-IC`` for N3.2, N3.6; ``-AE`` for N6.x; ``-151`` for N7).
      Otherwise: an ``error``.
    """
    for index, group in enumerate(invoice.vat_breakdown):
        mine = [block for block in blocks.values() if _of_group(group, block)]
        reason, code = group.exemption_reason, group.exemption_reason_code
        if reason is not None and (why := _reference(reason, mine)) is not None:
            yield finding(
                SUMMARY,
                f"vat_breakdown[{index}].exemption_reason",
                f"BT-120 cannot be written in FatturaPA: it goes to 2.2.2.8 RiferimentoNormativo (App. 4.1 rows "
                f"2.2.2.2, 2.2.2.8), but {why}",
            )
        if code is not None:
            carried = {VATEX_OF_NATURA.get(block.nature) for block in mine if block.nature} or {None}
            if carried != {code.upper()}:
                yield finding(
                    SUMMARY,
                    f"vat_breakdown[{index}].exemption_reason_code",
                    f"BT-121 {code} cannot be written in FatturaPA: only Natura carries it, and App. 5.1 gives the "
                    f"group's Natura {sorted(str(b.nature) for b in mine)} the codes {sorted(map(str, carried))}",
                )


def summarize(invoice: Invoice, it: ItalianExtension) -> tuple[list[Block], list[Finding]]:
    """The DatiRiepilogo blocks of an invoice and the pre-flight findings that keep them from being written.

    Args:
        invoice: The invoice.
        it: Its ``Invoice.it``.

    Returns:
        The blocks in the order their first line appears, and ``SUMMARY`` findings located by model path.
    """
    blocks = _blocks(invoice)
    findings = [
        *_amounts(invoice, it, blocks),
        *_match_summaries(it, blocks),
        *_chargeability(invoice, blocks),
        *_exemption_reasons(invoice, blocks),
    ]
    return list(blocks.values()), findings


def write_goods(body: etree._Element, invoice: Invoice, blocks: list[Block]) -> None:
    """2.2 DatiBeniServizi: the lines, then one DatiRiepilogo per block (from :func:`summarize`)."""
    goods = child(body, "DatiBeniServizi")
    for index, line in enumerate(invoice.lines):
        _write_line(goods, index, line)
    for block in blocks:
        where = f"DatiRiepilogo at rate {format(block.rate, 'f')}"
        summary = child(goods, "DatiRiepilogo")
        child(summary, "AliquotaIVA", rate(block.rate, "BT-119", f"2.2.2.1 AliquotaIVA of the {where}"))
        if block.nature is not None:
            child(summary, "Natura", block.nature)
        if block.accessory is not None:
            child(
                summary,
                "SpeseAccessorie",
                amount2(block.accessory, "BT-131", f"2.2.2.3 SpeseAccessorie of the {where}"),
            )
        child(
            summary, "ImponibileImporto", amount2(block.taxable, "BT-116", f"2.2.2.5 ImponibileImporto of the {where}")
        )
        child(summary, "Imposta", amount2(block.tax, "BT-117", f"2.2.2.6 Imposta of the {where}"))
        if block.chargeability is not None:
            child(summary, "EsigibilitaIVA", block.chargeability)
        if block.legal_reference is not None:
            child(summary, "RiferimentoNormativo", block.legal_reference)
