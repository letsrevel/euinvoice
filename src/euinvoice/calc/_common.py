"""Rounding helpers (shared by :func:`complete` and :func:`check`) and the finding helpers of :func:`check`.

Sources: see :mod:`euinvoice.calc`.
"""

import math
import typing as t
from collections.abc import Iterable, Iterator
from decimal import MAX_PREC, ROUND_FLOOR, Context, Decimal
from fractions import Fraction

from euinvoice.model.bt_index import path_of
from euinvoice.report import Finding, Severity

ZERO: t.Final = Decimal("0.00")
_WIDE = Context(prec=MAX_PREC)  # rescaling must never round digits away

SOURCE: t.Final = "calc"
"""The ``source`` of every :class:`~euinvoice.report.Finding` that :func:`check` returns."""

PORTABILITY: t.Final = "EUINV-CALC-PORTABILITY"
"""Rule id of the warning :func:`check` reports when only one syntax binding rejects an official rule."""

_BINDING_FILES: t.Final = {
    "UBL": "schematron/UBL/EN16931-UBL-model.sch",
    "CII": "schematron/CII/EN16931-CII-model.sch",
}


def round_cents(value: Fraction) -> Decimal:
    """Round an exact rational to two decimals, half up (ties away from zero), per D11.

    Working on ``Fraction`` keeps quotients exact: rounding a quotient that ``decimal`` had already cut
    to its context precision could turn a value just below a tie into a tie.

    Args:
        value: The exact value.

    Returns:
        The value rounded to two decimals, with exactly two fraction digits.
    """
    cents = math.floor(abs(value) * 100 + Fraction(1, 2))
    return Decimal(cents if value >= 0 else -cents).scaleb(-2, _WIDE)


def xpath_round(value: Decimal) -> Decimal:
    """XPath ``fn:round``: to the nearest integer, ties towards positive infinity.

    Args:
        value: A finite decimal.

    Returns:
        The rounded integral value.
    """
    return (value + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR, context=_WIDE)


def total(amounts: Iterable[Decimal]) -> Decimal:
    """Sum two-decimal amounts.

    Args:
        amounts: The amounts.

    Returns:
        Their sum, ``0.00`` when there are none.
    """
    # ponytail: sums and differences of amounts use the default 28-digit decimal context, exact up to
    # 10**26 currency units. Upgrade path: run them under localcontext(_WIDE) if that ever matters.
    return sum(amounts, ZERO)


def at(ident: str, *indices: int) -> str:
    """The model path of a BT/BG id with concrete indices, e.g. ``vat_breakdown[1].tax_amount``.

    Args:
        ident: A BT/BG id of :data:`euinvoice.model.bt_index.BT_INDEX`.
        *indices: One index per repeated group on the path, outermost first.

    Returns:
        The path; ``[]`` left over where fewer indices were given (``vat_breakdown[]`` → ``vat_breakdown``).
    """
    path = path_of(ident)
    for index in indices:
        path = path.replace("[]", f"[{index}]", 1)
    return path.removesuffix("[]")


def fmt(value: Decimal | None) -> str:
    """A decimal for a message: fixed-point, or ``absent``."""
    return "absent" if value is None else format(value, "f")


def verdict(rule_id: str, location: str, message: str, *, ubl: bool, cii: bool) -> Iterator[Finding]:
    """Turn the outcome of one official rule in both syntax bindings into findings (D8).

    The rule is reported ``fatal`` under its own id only if its test fails in **both** bindings. If
    only one binding rejects it, the invoice is valid in one syntax and not the other: that is a
    ``warning`` with rule id :data:`PORTABILITY` naming the rule and the rejecting binding.

    Args:
        rule_id: The official rule id, e.g. ``BR-S-08``.
        location: The model path.
        message: What is wrong, with the values.
        ubl: Whether the test of ``schematron/UBL/EN16931-UBL-model.sch`` passes.
        cii: Whether the test of ``schematron/CII/EN16931-CII-model.sch`` passes.

    Yields:
        Nothing, one fatal finding, or one portability warning.
    """
    if ubl and cii:
        return
    if not ubl and not cii:
        yield Finding(rule_id=rule_id, severity=Severity.FATAL, location=location, message=message, source=SOURCE)
        return
    rejecting, accepting = ("UBL", "CII") if not ubl else ("CII", "UBL")
    yield Finding(
        rule_id=PORTABILITY,
        severity=Severity.WARNING,
        location=location,
        message=f"{rule_id} fails in the {rejecting} binding only ({_BINDING_FILES[rejecting]}); the "
        f"{accepting} binding accepts it, so the invoice is valid in {accepting} but not in {rejecting}. "
        f"{message}",
        source=SOURCE,
    )


def fatal(rule_id: str, location: str, message: str) -> Iterator[Finding]:
    """A rule whose test is the same in both bindings and fails: one fatal finding.

    Args:
        rule_id: The official rule id.
        location: The model path.
        message: What is wrong, with the values.

    Yields:
        The fatal finding.
    """
    yield from verdict(rule_id, location, message, ubl=False, cii=False)
