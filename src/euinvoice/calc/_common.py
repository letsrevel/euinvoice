"""Rounding helpers and the per-VAT-category rule table shared by :func:`complete` and :func:`check`.

Sources: CEN validation artifacts ``validation-1.3.16``, ``schematron/abstract/EN16931-model.sch``
(rule ids and texts) with ``schematron/UBL/EN16931-UBL-model.sch`` and
``schematron/CII/EN16931-CII-model.sch`` (the tests).
"""

import dataclasses
import enum
import math
import typing as t
from collections.abc import Iterable
from decimal import MAX_PREC, ROUND_FLOOR, Context, Decimal
from fractions import Fraction

from euinvoice.model.codes import VatCategory

ZERO: t.Final = Decimal("0.00")
_WIDE = Context(prec=MAX_PREC)  # rescaling must never round digits away


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


class RateRule(enum.Enum):
    """What the ``-05``/``-06``/``-07`` rules of a VAT category require of BT-152, BT-96 and BT-103."""

    POSITIVE = "greater than zero"
    NOT_NEGATIVE = "zero or greater than zero"
    ZERO = "0 (zero)"
    ABSENT = "absent"

    def accepts(self, rate: Decimal | None) -> bool:
        """Whether ``rate`` satisfies the rule (a missing rate fails every rule but ``ABSENT``).

        Args:
            rate: The VAT rate, or ``None``.

        Returns:
            ``True`` if the rule holds.
        """
        if self is RateRule.ABSENT:
            return rate is None
        if rate is None:  # XPath: a comparison with an empty sequence is false
            return False
        if self is RateRule.POSITIVE:
            return rate > 0
        if self is RateRule.NOT_NEGATIVE:
            return rate >= 0
        return rate == 0


@dataclasses.dataclass(frozen=True, slots=True)
class CategoryRules:
    """The CEN rules of one VAT category code (``BR-<prefix>-01`` … ``-10``).

    Attributes:
        prefix: The rule id prefix, e.g. ``BR-S`` for ``S`` or ``BR-IC`` for ``K``.
        name: The category name the rule texts use.
        rate: What ``-05``/``-06``/``-07`` require of the line, allowance and charge VAT rates.
        per_rate: ``-01`` asks for "at least one" breakdown and ``-08`` sums per rate (S, L, M);
            otherwise ``-01`` asks for "exactly one" breakdown and ``-08`` sums the whole category.
        zero_tax: ``-09`` requires BT-117 = 0; otherwise ``-09`` repeats BR-CO-17.
        needs_reason: ``-10`` requires BT-120 or BT-121; otherwise ``-10`` forbids both.
    """

    prefix: str
    name: str
    rate: RateRule
    per_rate: bool
    zero_tax: bool
    needs_reason: bool


# BR-AF-05/06/07: UBL tests ">= 0", CII "> 0"; the stricter CII test is applied (see the package doc).
CATEGORY_RULES: t.Final[dict[str, CategoryRules]] = {
    VatCategory.STANDARD_RATED: CategoryRules("BR-S", "Standard rated", RateRule.POSITIVE, True, False, False),
    VatCategory.ZERO_RATED: CategoryRules("BR-Z", "Zero rated", RateRule.ZERO, False, True, False),
    VatCategory.EXEMPT: CategoryRules("BR-E", "Exempt from VAT", RateRule.ZERO, False, True, True),
    VatCategory.REVERSE_CHARGE: CategoryRules("BR-AE", "Reverse charge", RateRule.ZERO, False, True, True),
    VatCategory.INTRA_COMMUNITY_SUPPLY: CategoryRules(
        "BR-IC", "Intra-community supply", RateRule.ZERO, False, True, True
    ),
    VatCategory.EXPORT_OUTSIDE_EU: CategoryRules("BR-G", "Export outside the EU", RateRule.ZERO, False, True, True),
    VatCategory.NOT_SUBJECT_TO_VAT: CategoryRules("BR-O", "Not subject to VAT", RateRule.ABSENT, False, True, True),
    VatCategory.IGIC: CategoryRules("BR-AF", "IGIC", RateRule.POSITIVE, True, False, False),
    VatCategory.IPSI: CategoryRules("BR-AG", "IPSI", RateRule.NOT_NEGATIVE, True, False, False),
}
"""The rules of each VAT category code. ``B`` (split payment) has none of these: its only CEN rules,
BR-B-01 and BR-B-02, are about the seller's country and mixing with ``S``, not about amounts."""
