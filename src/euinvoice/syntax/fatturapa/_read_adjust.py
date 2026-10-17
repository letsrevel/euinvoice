"""2.2.1.10 ``ScontoMaggiorazione`` + 2.2.1.16 ``AltriDatiGestionali`` → BG-27 and BG-28 (#151).

The reverse of :mod:`._write_adjust`: an ``AltriDatiGestionali`` whose ``TipoDato`` is ``BT-139`` or ``BT-140`` (an
allowance reason or reason code) or ``BT-144`` or ``BT-145`` (a charge's), with a ``RiferimentoTesto`` and a
``RiferimentoNumero`` that is the 1-based position of one of the line's ``ScontoMaggiorazione``, explains that
``ScontoMaggiorazione``. It is then a BG-27 (``Tipo`` SC) or BG-28 (MG), its amount is ``Importo`` * ``Quantita``
(BT-136 / BT-141: ``Importo`` is per unit, App. 4.1 row 2.2.1.10.3) and the reasons are BT-139 / BT-140 or BT-144 /
BT-145. The ``ScontoMaggiorazione`` that no entry explains is BT-147, as before (:func:`._read_lines._price`). Any
other ``AltriDatiGestionali`` stays a BG-32 item attribute, so a document that merely uses these ``TipoDato`` without
the pointer is read as before.
"""

import dataclasses
from decimal import Decimal

from lxml import etree

from euinvoice.errors import ParseError
from euinvoice.model.amounts import quantize_amount
from euinvoice.syntax._marks import XML_SPACE
from euinvoice.syntax.fatturapa._read_codes import POLICY_ISSUE
from euinvoice.syntax.fatturapa._read_cursor import Cursor

__all__ = ["Claimed", "claim", "read"]

_TERMS: dict[str, tuple[bool, str]] = {
    # TipoDato → (is a charge, model field of BG-27 / BG-28)
    "BT-139": (False, "reason"),
    "BT-140": (False, "reason_code"),
    "BT-144": (True, "reason"),
    "BT-145": (True, "reason_code"),
}


@dataclasses.dataclass
class Claimed:
    """What the ``AltriDatiGestionali`` of a line say about its ``ScontoMaggiorazione``.

    Attributes:
        entries: The ``AltriDatiGestionali`` that were taken (not BG-32 attributes).
        reasons: Per 1-based ``ScontoMaggiorazione`` position: whether it is a charge, and its reason fields.
    """

    entries: set[etree._Element] = dataclasses.field(default_factory=set)
    reasons: dict[int, tuple[bool, dict[str, str]]] = dataclasses.field(default_factory=dict)


def _position(adg: etree._Element, count: int) -> int | None:
    """``RiferimentoNumero`` as a position from 1 to ``count``, or ``None`` if it is not one."""
    text = (adg.findtext("RiferimentoNumero") or "").strip(XML_SPACE)
    try:
        number = Decimal(text)
    except ArithmeticError:
        return None
    if not number.is_finite():  # NaN, sNaN, Infinity
        return None
    return int(number) if number == number.to_integral_value() and 1 <= number <= count else None


def claim(cursor: Cursor, element: etree._Element) -> Claimed:
    """Take the ``AltriDatiGestionali`` of ``element`` that explain one of its ``ScontoMaggiorazione``.

    Raises:
        ParseError: Such an entry points at a ``ScontoMaggiorazione`` that cannot be the allowance or charge it says
            (no ``Importo``, a ``Percentuale``, or ``Tipo`` not SC / MG respectively), or an allowance and a charge
            reason point at the same one.
    """
    claimed = Claimed()
    sconti = cursor.children(element, "ScontoMaggiorazione")
    for adg in cursor.children(element, "AltriDatiGestionali"):
        term = (adg.findtext("TipoDato") or "").strip(XML_SPACE)
        position = _position(adg, len(sconti))
        if term not in _TERMS or position is None or adg.find("RiferimentoTesto") is None:
            continue
        charge, field = _TERMS[term]
        fields = claimed.reasons.setdefault(position, (charge, {}))[1]
        if claimed.reasons[position][0] is not charge:
            raise ParseError(
                f"2.2.1.16 {term}: ScontoMaggiorazione {position} is explained as an allowance and as a charge",
                location=cursor.path(adg),
            )
        if field in fields:
            continue  # a second reason of the same kind stays an attribute
        sconto = sconti[position - 1]
        if (
            sconto.find("Importo") is None
            or sconto.find("Percentuale") is not None
            or sconto.findtext("Tipo") != ("MG" if charge else "SC")
        ):
            raise ParseError(
                f"2.2.1.16 {term} explains ScontoMaggiorazione {position}, which is not {'MG' if charge else 'SC'} "
                f"with an Importo and no Percentuale, so it is not a line {'charge' if charge else 'allowance'} "
                f"({POLICY_ISSUE})",
                location=cursor.path(adg),
            )
        fields[field] = cursor.text(adg, "RiferimentoTesto") or ""
        cursor.one(adg, "TipoDato")
        cursor.one(adg, "RiferimentoNumero")
        claimed.entries.add(cursor.use(adg))
    return claimed


def read(
    cursor: Cursor, element: etree._Element, claimed: Claimed, quantity: Decimal, *, negative: bool
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    """The claimed ``ScontoMaggiorazione`` as BG-27 and BG-28 field dictionaries, in document order.

    Args:
        cursor: The cursor.
        element: The ``DettaglioLinee``.
        claimed: The result of :func:`claim`.
        quantity: BT-129 as the file gives it (``Quantita``, or 1 without one), positive.
        negative: Whether the line has a negative ``PrezzoUnitario`` (it reads as BT-129 < 0).

    Raises:
        ParseError: The line is negative and has explained sconti, or an amount has more than two decimals
            (BR-DEC-24, BR-DEC-27: the reader does not round, #132).
    """
    if negative and claimed.reasons:
        raise ParseError(
            "2.2.1.9 PrezzoUnitario is negative and 2.2.1.16 explains a ScontoMaggiorazione: the reader negates BT-129 "
            "for a negative price, and no source says how an allowance or charge amount follows that sign, so it does "
            f"not map them ({POLICY_ISSUE})",
            location=cursor.path(element),
        )
    allowances: list[dict[str, object]] = []
    charges: list[dict[str, object]] = []
    sconti = cursor.children(element, "ScontoMaggiorazione")
    for position in sorted(claimed.reasons):
        charge, fields = claimed.reasons[position]
        sconto = cursor.use(sconti[position - 1])
        cursor.one(sconto, "Tipo")
        importo = cursor.decimal(sconto, "Importo", "2.2.1.10.3")
        amount = (importo if importo is not None else Decimal(0)) * quantity
        if amount != quantize_amount(amount):
            raise ParseError(
                f"2.2.1.10.3 Importo {importo} times Quantita {quantity} is {format(amount, 'f')}, more than two "
                f"decimals; a line {'charge' if charge else 'allowance'} amount is an EN 16931 amount and the reader "
                f"does not round it ({POLICY_ISSUE})",
                location=cursor.path(sconto),
            )
        (charges if charge else allowances).append({"amount": quantize_amount(amount), **fields})
    return tuple(allowances), tuple(charges)
