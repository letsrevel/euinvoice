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
the lines). A BG-23 with one block gives it its BT-117 (row 2.2.2.6); one split by Natura (rate 0 only) gives each
block ``AliquotaIVA * ImponibileImporto / 100`` rounded half up (Allegato A, DatiRiepilogo / Imposta), and their sum
must equal BT-117.
"""

import dataclasses
import typing as t
from decimal import Decimal

from lxml import etree

from euinvoice.model import Invoice, InvoiceLine, VatBreakdown
from euinvoice.model.amounts import quantize_amount
from euinvoice.model.codes import VatCategory
from euinvoice.model.it import EsigibilitaIVA, ItalianExtension, ItalianVatSummary, Natura, TipoCessionePrestazione
from euinvoice.syntax.fatturapa._write_codes import CHARGEABILITY_OF_VAT_POINT
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
from euinvoice.syntax.fatturapa._write_preflight import UNSUPPORTED_CATEGORIES

__all__ = ["write_goods"]

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


def _category(line: InvoiceLine, index: int) -> VatCategory:
    category = VatCategory(line.vat_information.category_code)
    if category in UNSUPPORTED_CATEGORIES:
        raise cannot_express(
            f"BT-151 (lines[{index}].vat_information.category_code)",
            f"VAT category {category} has no Natura in App. 5.1 of the Regole tecniche v2.6 (#133)",
        )
    return category


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
        _price_discount(
            element,
            price.item_price_discount,
            price.item_gross_price is not None,
            term("BT-147", "price_details.item_price_discount"),
        )
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


def _price_discount(element: etree._Element, discount: Decimal, gross: bool, term: str) -> None:
    """2.2.1.10 ScontoMaggiorazione from BT-147.

    Row 2.2.1.10.1: "Se BT-147 maggiore di zero è valorizzato con 'SC', se minore di zero con 'MG'"; row 2.2.1.10.3:
    the amount "a meno del segno".
    """
    if not gross:
        raise cannot_express(
            term,
            "2.2.1.9 PrezzoUnitario is the net price BT-146 without a gross price BT-148, so "
            "a discount on it would be applied twice",
        )
    if discount == 0:
        raise cannot_express(
            term, "row 2.2.1.10.1 maps a discount above zero to SC and below zero to MG; zero is neither"
        )
    adjustment = child(element, "ScontoMaggiorazione")
    child(adjustment, "Tipo", "SC" if discount > 0 else "MG")
    child(adjustment, "Importo", amount8(discount.copy_abs(), term, "2.2.1.10.3 Importo"))


@dataclasses.dataclass
class _Block:
    """One DatiRiepilogo being built."""

    rate: Decimal
    nature: Natura | None
    category: VatCategory
    taxable: Decimal = Decimal("0.00")
    accessory: Decimal | None = None
    tax: Decimal = Decimal("0.00")
    summary: ItalianVatSummary | None = None

    @property
    def split(self) -> bool:
        return self.category is VatCategory.SPLIT_PAYMENT


type _Key = tuple[Decimal, Natura | None, bool]


def _blocks(invoice: Invoice) -> dict[_Key, _Block]:
    blocks: dict[_Key, _Block] = {}
    for index, line in enumerate(invoice.lines):
        category = _category(line, index)
        nature = None if line.it is None else line.it.nature
        rate_ = t.cast(Decimal, line.vat_information.rate)
        block = blocks.setdefault(
            (rate_, nature, category is VatCategory.SPLIT_PAYMENT), _Block(rate_, nature, category)
        )
        block.taxable += line.net_amount
        if line.it is not None and line.it.supply_type is TipoCessionePrestazione.AC:
            # Row 2.2.2.3 SpeseAccessorie: the sum of BT-131 of the lines whose TipoCessionePrestazione is AC.
            block.accessory = (block.accessory or Decimal("0.00")) + line.net_amount
    return blocks


def _of_group(group: VatBreakdown, block: _Block) -> bool:
    return VatCategory(group.category_code) is block.category and group.rate == block.rate


def _amounts(invoice: Invoice, blocks: dict[_Key, _Block]) -> None:
    """Give each block its Imposta and check every BG-23 against its blocks (see the module docstring)."""
    claimed: set[_Key] = set()
    for index, group in enumerate(invoice.vat_breakdown):
        term = f"BG-23 (vat_breakdown[{index}])"
        if VatCategory(group.category_code) in UNSUPPORTED_CATEGORIES:
            raise cannot_express(
                term,
                f"VAT category {group.category_code} has no Natura in App. 5.1 of the Regole tecniche v2.6 (#133)",
            )
        mine = [key for key, block in blocks.items() if _of_group(group, block)]
        claimed.update(mine)
        taxable = sum((blocks[key].taxable for key in mine), Decimal("0.00"))
        if taxable != group.taxable_amount:
            raise cannot_express(
                term,
                f"BT-116 {group.taxable_amount} differs from the sum of its lines' BT-131, "
                f"{taxable}; DatiRiepilogo has no place for a document level allowance or charge "
                "(SdI 00422 compares ImponibileImporto with the lines)",
            )
        if len(mine) == 1:
            blocks[mine[0]].tax = group.tax_amount
            continue
        for key in mine:
            block = blocks[key]
            block.tax = quantize_amount(block.rate * block.taxable / _HUNDRED)
        tax = sum((blocks[key].tax for key in mine), Decimal("0.00"))
        if tax != group.tax_amount:
            raise cannot_express(
                term,
                f"BT-117 {group.tax_amount} differs from the Imposta of its {len(mine)} DatiRiepilogo by Natura, {tax}",
            )
    for key, block in blocks.items():
        if key not in claimed:
            raise cannot_express(
                "BG-23 (vat_breakdown)",
                f"no VAT BREAKDOWN of category {block.category} at rate "
                f"{format(block.rate, 'f')}, which lines carry (BR-CO-18)",
            )


def _match_summaries(it: ItalianExtension, blocks: dict[_Key, _Block]) -> None:
    """Attach each ``it.vat_summaries`` entry to the block of its key; an entry with no block is refused."""
    for index, summary in enumerate(it.vat_summaries):
        key = (summary.rate, summary.nature, summary.vat_chargeability is EsigibilitaIVA.S)
        if key not in blocks:
            mode = "split payment (EsigibilitaIVA S, VAT category B)" if key[2] else "ordinary payment"
            raise cannot_express(
                f"it.vat_summaries[{index}]",
                f"no line has rate {format(summary.rate, 'f')}, Natura {summary.nature} and {mode}, so this "
                "DatiRiepilogo data belongs to no summary",
            )
        blocks[key].summary = summary


def _chargeability(invoice: Invoice, block: _Block) -> EsigibilitaIVA | None:
    """EsigibilitaIVA (row 2.2.2.7): S for category B; else the summary's, or BT-8's (3, 35 → I, 432 → D)."""
    if block.split:
        return EsigibilitaIVA.S
    own = None if block.summary is None else block.summary.vat_chargeability
    code = invoice.vat_point_date_code
    derived = None if code is None else CHARGEABILITY_OF_VAT_POINT[code]
    if own is not None and derived is not None and own is not derived:
        raise cannot_express(
            "BT-8 (vat_point_date_code)",
            f"it gives EsigibilitaIVA {derived} (App. 4.1 row "
            f"2.2.2.7), but it.vat_summaries sets {own} for rate {format(block.rate, 'f')}",
        )
    return own or derived


def write_goods(body: etree._Element, invoice: Invoice, it: ItalianExtension) -> None:
    """2.2 DatiBeniServizi: the lines, then one DatiRiepilogo per (rate, Natura, split payment)."""
    blocks = _blocks(invoice)
    _amounts(invoice, blocks)
    _match_summaries(it, blocks)
    if invoice.vat_point_date_code is not None and all(block.split for block in blocks.values()):
        raise cannot_express(
            "BT-8 (vat_point_date_code)",
            "every DatiRiepilogo is split payment (EsigibilitaIVA S, App. 4.1 row 2.2.2.7), so none can carry it",
        )
    goods = child(body, "DatiBeniServizi")
    for index, line in enumerate(invoice.lines):
        _write_line(goods, index, line)
    for block in blocks.values():
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
        chargeability = _chargeability(invoice, block)
        if chargeability is not None:
            child(summary, "EsigibilitaIVA", chargeability)
        if block.summary is not None and block.summary.legal_reference is not None:
            child(summary, "RiferimentoNormativo", block.summary.legal_reference)
