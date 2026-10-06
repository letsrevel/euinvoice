"""Rounding helpers (shared by :func:`complete` and :func:`check`) and the finding helpers of :func:`check`.

Sources: see :mod:`euinvoice.calc`.
"""

import dataclasses
import math
import typing as t
from collections.abc import Iterable, Iterator
from decimal import MAX_PREC, ROUND_FLOOR, Context, Decimal
from fractions import Fraction

from euinvoice.model.bt_index import path_of
from euinvoice.report import Finding, Severity
from euinvoice.syntax import Syntax

ZERO: t.Final = Decimal("0.00")
_WIDE = Context(prec=MAX_PREC)  # rescaling must never round digits away

SOURCE: t.Final = "calc"
"""The ``source`` of every :class:`~euinvoice.report.Finding` that :func:`check` returns."""

PORTABILITY: t.Final = "EUINV-CALC-PORTABILITY"
"""Rule id of the warning :func:`check` reports when only one syntax binding rejects an official rule."""

_BINDING_FILES: t.Final = {
    Syntax.UBL: "schematron/UBL/EN16931-UBL-model.sch",
    Syntax.CII: "schematron/CII/EN16931-CII-model.sch",
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


@dataclasses.dataclass(frozen=True, slots=True)
class Verdict:
    """One official rule that fails in at least one syntax binding.

    Attributes:
        rule_id: The official rule id, e.g. ``BR-S-08``.
        location: The model path.
        message: What is wrong, with the values.
        ubl: Whether the test of ``schematron/UBL/EN16931-UBL-model.sch`` passes.
        cii: Whether the test of ``schematron/CII/EN16931-CII-model.sch`` passes.
    """

    rule_id: str
    location: str
    message: str
    ubl: bool
    cii: bool

    def passes(self, syntax: Syntax) -> bool:
        """Whether the rule's test in ``syntax`` passes.

        Args:
            syntax: The binding.

        Returns:
            The outcome of that binding's test.
        """
        return self.ubl if syntax is Syntax.UBL else self.cii

    def finding(self, syntax: Syntax | None) -> Finding | None:
        """The finding for a target syntax, or for both syntaxes (D8 policy, see :mod:`euinvoice.calc`).

        Args:
            syntax: The target syntax, or ``None`` for both.

        Returns:
            With a syntax: a fatal finding under :attr:`rule_id` if that binding rejects the rule, else
            ``None``. Without: fatal if both reject it, a :data:`PORTABILITY` warning if only one does.
        """
        if syntax is not None:
            return None if self.passes(syntax) else self._fatal()
        if not self.ubl and not self.cii:
            return self._fatal()
        rejecting, accepting = (Syntax.UBL, Syntax.CII) if not self.ubl else (Syntax.CII, Syntax.UBL)
        return Finding(
            rule_id=PORTABILITY,
            severity=Severity.WARNING,
            location=self.location,
            message=f"{self.rule_id} fails in the {rejecting.name} binding only ({_BINDING_FILES[rejecting]}); "
            f"the {accepting.name} binding's test accepts it. {self.message}",
            source=SOURCE,
        )

    def _fatal(self) -> Finding:
        return Finding(
            rule_id=self.rule_id, severity=Severity.FATAL, location=self.location, message=self.message, source=SOURCE
        )


def verdict(rule_id: str, location: str, message: str, *, ubl: bool, cii: bool) -> Iterator[Verdict]:
    """The verdict of one official rule in both bindings; nothing if both tests pass.

    Args:
        rule_id: The official rule id.
        location: The model path.
        message: What is wrong, with the values.
        ubl: Whether the UBL binding's test passes.
        cii: Whether the CII binding's test passes.

    Yields:
        Nothing, or one :class:`Verdict`.
    """
    if not (ubl and cii):
        yield Verdict(rule_id, location, message, ubl, cii)


def fatal(rule_id: str, location: str, message: str) -> Iterator[Verdict]:
    """A rule whose test is the same in both bindings and fails.

    Args:
        rule_id: The official rule id.
        location: The model path.
        message: What is wrong, with the values.

    Yields:
        The verdict, failing in both bindings.
    """
    yield from verdict(rule_id, location, message, ubl=False, cii=False)
