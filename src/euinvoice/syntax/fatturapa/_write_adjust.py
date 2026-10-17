"""Line allowances and charges (BG-27, BG-28) as 2.2.1.10 ScontoMaggiorazione and 2.2.1.16 AltriDatiGestionali (#151).

Decision of #133 item 12 (option c, 2026-10-17). App. 4.1 of the SdI "Regole tecniche fatture europee" v2.6 maps an
allowance to ``<ScontoMaggiorazione>`` ``Tipo`` SC and a charge to MG, with ``Importo`` the amount divided by the
invoiced quantity BT-129 (or a ``Percentuale``). ``ScontoMaggiorazione`` has no place for a reason, which EN 16931
requires (BR-42, BR-44), so each reason is carried in 2.2.1.16 ``AltriDatiGestionali``, written after
``RiferimentoAmministrazione`` (``DettaglioLineeType`` of XSD 1.2.3):

* ``TipoDato`` (``String10Type``): the business term id: ``BT-139`` (allowance reason), ``BT-140`` (allowance reason
  code), ``BT-144`` (charge reason), ``BT-145`` (charge reason code);
* ``RiferimentoTesto`` (``String60LatinType``): the reason or the code;
* ``RiferimentoNumero`` (``Amount8DecimalType``): the 1-based position, among the line's ``ScontoMaggiorazione``, of
  the one it explains. The reader (:mod:`._read_adjust`) maps the pair back, so FPR12 → model → FPR12 is lossless.

The entries of a line are, in this order: BT-147 (the item price discount, if not zero; it has no reason), the
allowances, the charges. SdI 00423 (Allegato A 1.9.1, 2.2.1.11) is ``PrezzoTotale = (PrezzoUnitario ±
ScontoMaggiorazione) * Quantita`` with a tolerance of 0.01; :func:`euinvoice.validation.sdi.check` applies the
entries in order to a running price (Elenco dei controlli v2.0, #162): ``Importo`` per unit or a cascading
``Percentuale``. Only ``Importo`` is written, so any number of allowances and charges can be; BT-137, BT-138,
BT-142 and BT-143 are refused by choice of #151, not because the checker cannot evaluate a percentage (follow-up).

An amount must survive the division: ``Importo`` is ``Amount8DecimalType`` (at most 8 decimals) and the reader
multiplies it by BT-129 again, so an amount whose quotient has no such exact value is refused, never rounded.
BT-131 is not an input of the mapping (it is ``PrezzoTotale``, written as is), but EN 16931 ties it to the entries:
BT-131 = BT-129 * BT-146 - sum(BT-136) + sum(BT-141). No CEN rule states that (BR-24 only requires BT-131,
BR-DEC-23 limits its decimals); it is Peppol BIS 3.0.21 PEPPOL-EN16931-R120 (slack 0.02), as
:func:`euinvoice.calc.line_net_amount` notes. :func:`check` reports a BT-131 that SdI 00423 would refuse.
"""

import dataclasses
import typing as t
from decimal import Decimal, localcontext

from lxml import etree

from euinvoice.model import InvoiceLine, InvoiceLineAllowance, InvoiceLineCharge
from euinvoice.model.amounts import quantize_amount
from euinvoice.report import Finding
from euinvoice.syntax.fatturapa._write_format import amount8, child, fits
from euinvoice.syntax.fatturapa._write_rules import LINE_TOTAL, UNWRITTEN, finding

__all__ = ["Entry", "check", "entries", "write_adjustments", "write_reasons"]

_UNIT_PLACES: t.Final = Decimal(1).scaleb(-8)  # Amount8DecimalType
_TOLERANCE: t.Final = Decimal("0.01")  # SdI 00423
_REASON_MAX: t.Final = 60  # String60LatinType


@dataclasses.dataclass(frozen=True)
class Entry:
    """One allowance or charge as ScontoMaggiorazione: ``Tipo``, per unit ``Importo`` and the ``TipoDato`` reasons."""

    tipo: t.Literal["SC", "MG"]
    importo: Decimal
    reasons: tuple[tuple[str, str], ...]


def unit_amount(amount: Decimal, quantity: Decimal) -> Decimal | None:
    """``Importo`` for ``amount`` over ``quantity``, or ``None`` when no ``Amount8DecimalType`` gives ``amount`` again.

    The quotient is exact or it is refused: the reader multiplies it by the quantity.
    """
    if quantity <= 0:
        return None
    with localcontext(prec=80):
        unit = (amount / quantity).quantize(_UNIT_PLACES)
        return unit.normalize() if unit * quantity == amount else None


def _importo(amount: Decimal, quantity: Decimal) -> Decimal:
    """:func:`unit_amount` of an amount :func:`check` accepted."""
    unit = unit_amount(amount, quantity)
    if unit is None:  # pragma: no cover - entries() runs only after check() found no error
        raise AssertionError(f"{amount} over {quantity} was not checked by check()")
    return unit


def entries(line: InvoiceLine) -> list[Entry]:
    """The ScontoMaggiorazione of BG-27 then BG-28 (after :func:`check`); BT-147 is written separately."""
    quantity = line.invoiced_quantity
    found = [
        Entry(
            "SC",
            _importo(a.amount, quantity),
            _reasons(("BT-139", a.reason), ("BT-140", a.reason_code)),
        )
        for a in line.allowances
    ]
    found += [
        Entry(
            "MG",
            _importo(c.amount, quantity),
            _reasons(("BT-144", c.reason), ("BT-145", c.reason_code)),
        )
        for c in line.charges
    ]
    return found


def _reasons(*pairs: tuple[str, str | None]) -> tuple[tuple[str, str], ...]:
    return tuple((term, value) for term, value in pairs if value is not None)


def _discount(line: InvoiceLine) -> Decimal:
    """BT-147, written as the first ScontoMaggiorazione unless zero."""
    return line.price_details.item_price_discount or Decimal(0)


def check(index: int, line: InvoiceLine) -> t.Iterator[Finding]:
    """Findings that keep the line's BG-27 / BG-28 from being written (see the module docstring)."""
    quantity = line.invoiced_quantity
    ok = True
    groups: tuple[tuple[str, tuple[InvoiceLineAllowance | InvoiceLineCharge, ...], tuple[str, str, str]], ...] = (
        ("allowances", line.allowances, ("BT-136", "BT-139", "BT-140")),
        ("charges", line.charges, ("BT-141", "BT-144", "BT-145")),
    )
    for group, items, (amount_term, reason_term, code_term) in groups:
        for i, item in enumerate(items):
            where = f"lines[{index}].{group}[{i}]"
            if unit_amount(item.amount, quantity) is None:
                ok = False
                why = (
                    "BT-129 is 0, so there is no unit amount"
                    if quantity == 0
                    else f"BT-129 is {quantity}, negative; QuantitaType is unsigned (a negative line is written with a "
                    "negative PrezzoUnitario and cannot carry an explained ScontoMaggiorazione, #151)"
                    if quantity < 0
                    else f"{item.amount} / BT-129 {quantity} has no Amount8DecimalType value that gives {item.amount} "
                    "again when multiplied by BT-129"
                )
                yield finding(
                    UNWRITTEN,
                    f"{where}.amount",
                    f"{amount_term} cannot be written in FatturaPA: 2.2.1.10.3 Importo is the amount per unit "
                    f"(App. 4.1), and {why}",
                )
            for field, term in (("reason", reason_term), ("reason_code", code_term)):
                value = getattr(item, field)
                if value is not None and not fits(value, maximum=_REASON_MAX):
                    yield finding(
                        UNWRITTEN,
                        f"{where}.{field}",
                        f"{term} cannot be written in FatturaPA: it goes to 2.2.1.16 AltriDatiGestionali "
                        "RiferimentoTesto (String60LatinType: 1 to 60 Latin-1 characters without tab or line break)",
                    )
    if ok and (line.allowances or line.charges):
        yield from _total(index, line)


def _total(index: int, line: InvoiceLine) -> t.Iterator[Finding]:
    """SdI 00423 on BT-131, as the checker computes it: (PrezzoUnitario ± Importo...) * Quantita, tolerance 0.01."""
    price = line.price_details
    unit = price.item_gross_price if price.item_gross_price is not None else price.item_net_price
    entry_sum = sum((-e.importo if e.tipo == "SC" else e.importo for e in entries(line)), Decimal(0))
    expected = (unit - _discount(line) + entry_sum) * line.invoiced_quantity
    exact = None if line.it is None else line.it.total_price
    # PrezzoTotale as written: the declared exact value when it rounds to BT-131 (a mismatch is TOTAL_PRICE's)
    written = exact if exact is not None and quantize_amount(exact) == line.net_amount else line.net_amount
    if abs(written - expected) > _TOLERANCE:
        if expected == quantize_amount(expected):
            expected = quantize_amount(expected)
        yield finding(
            LINE_TOTAL,
            f"lines[{index}].net_amount",
            f"PrezzoTotale {format(written, 'f')} (BT-131 {line.net_amount}) is not what SdI check 00423 "
            f"accepts: (PrezzoUnitario ± ScontoMaggiorazione) * Quantita = {format(expected, 'f')}, "
            "tolerance ±0.01; EN 16931 gives BT-131 = BT-129 x BT-146 - sum(BT-136) + sum(BT-141) "
            "(Peppol BIS PEPPOL-EN16931-R120)",
        )


def write_adjustments(element: etree._Element, line: InvoiceLine) -> None:
    """The ScontoMaggiorazione of BG-27 then BG-28, after BT-147's (rows 2.2.1.10.1 and 2.2.1.10.3)."""
    for entry in entries(line):
        adjustment = child(element, "ScontoMaggiorazione")
        child(adjustment, "Tipo", entry.tipo)
        child(adjustment, "Importo", amount8(entry.importo, "BT-136/BT-141", "2.2.1.10.3 Importo"))


def write_reasons(element: etree._Element, line: InvoiceLine) -> None:
    """The 2.2.1.16 AltriDatiGestionali carrying each reason, pointing at its ScontoMaggiorazione."""
    first = 2 if _discount(line) != 0 else 1
    for position, entry in enumerate(entries(line), first):
        for term, value in entry.reasons:
            other = child(element, "AltriDatiGestionali")
            child(other, "TipoDato", term)
            child(other, "RiferimentoTesto", value)
            child(other, "RiferimentoNumero", amount8(Decimal(position), term, "2.2.1.16.3 RiferimentoNumero"))
