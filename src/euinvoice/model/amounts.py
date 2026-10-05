"""Decimal types for the EN 16931 semantic data types Amount, Unit price amount, Quantity and Percentage.

All four accept ``Decimal``, ``int`` and ``xs:decimal`` strings, reject ``float``, ``bool``, ``NaN`` and
infinities (D3, see :func:`euinvoice.model._base.to_decimal`), and never round on their own.

Which business terms are limited to two decimals was read from the pinned CEN validation artifacts
``validation-1.3.16``:

* ``schematron/abstract/EN16931-model.sch`` (UBL and CII alike) limits these amounts to at most two
  fraction digits (all ``flag="fatal"``): BR-DEC-01/02 (BT-92/93), BR-DEC-05/06 (BT-99/100), BR-DEC-09..18
  (BT-106..115), BR-DEC-19/20 (BT-116/117), BR-DEC-23 (BT-131), BR-DEC-24/25 (BT-136/137) and
  BR-DEC-27/28 (BT-141/142). That is every business term of data type Amount.
* ``schematron/UBL/EN16931-UBL-syntax.sch`` rule UBL-DT-01 ("Amounts shall be decimal up to two fraction
  digits") applies to every UBL element named ``*Amount`` except ``*PriceAmount`` and the amounts inside
  ``cac:Price/cac:AllowanceCharge``. Those are exactly the unit price amounts BT-146, BT-147 and BT-148.
* No rule limits the decimals of unit price amounts, quantities (BT-129, BT-149) or percentages
  (BT-94, BT-96, BT-101, BT-103, BT-119, BT-138, BT-143, BT-152).

The rules test the lexical form, ``string-length(substring-after(., '.')) <= 2``, so ``1.230`` fails
although it equals ``1.23``. :data:`Amount` therefore trims surplus trailing zeros (lossless: the value
is unchanged) and rejects anything that would need rounding. Rounding is explicit: call
:func:`quantize_amount`.
"""

import typing as t
from decimal import MAX_PREC, ROUND_HALF_UP, Decimal, localcontext

import pydantic

from euinvoice.errors import ModelError
from euinvoice.model._base import to_decimal

__all__ = ["AMOUNT_DECIMALS", "Amount", "Percentage", "Quantity", "UnitPriceAmount", "quantize_amount"]

AMOUNT_DECIMALS: t.Final = 2
"""Maximum fraction digits of an Amount (BR-DEC-*, UBL-DT-01)."""

_CENT = Decimal(1).scaleb(-AMOUNT_DECIMALS)


def quantize_amount(value: Decimal) -> Decimal:
    """Round a monetary amount to two decimals, half up (ties away from zero), per D11.

    The result always has exactly two fraction digits (``7`` becomes ``7.00``). It does not depend on
    the active ``decimal`` context, so large values never raise or lose integer digits.

    Args:
        value: A finite ``Decimal``.

    Returns:
        ``value`` rounded with ``ROUND_HALF_UP`` to two decimals.

    Raises:
        ModelError: ``value`` is a float or not finite.
    """
    value = to_decimal(value)
    with localcontext(prec=MAX_PREC):
        return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _check_amount(value: Decimal) -> Decimal:
    """Enforce at most two fraction digits (BR-DEC-*, UBL-DT-01), trimming surplus trailing zeros.

    Args:
        value: A finite ``Decimal``.

    Returns:
        ``value`` unchanged, or with trailing zeros beyond the second decimal removed.

    Raises:
        ModelError: ``value`` has a non-zero digit after the second decimal.
    """
    sign, digits, exponent = value.as_tuple()
    surplus = -t.cast(int, exponent) - AMOUNT_DECIMALS
    if surplus <= 0:
        return value
    if any(digits[-surplus:]):
        raise ModelError(
            f"amount {format(value, 'f')} has more than {AMOUNT_DECIMALS} decimals, which EN 16931 forbids "
            "for amounts (BR-DEC-*, UBL-DT-01). Round it explicitly with "
            "euinvoice.model.amounts.quantize_amount()."
        )
    return Decimal((sign, digits[:-surplus] or (0,), -AMOUNT_DECIMALS))


_DECIMAL_ONLY = pydantic.BeforeValidator(to_decimal)

Amount = t.Annotated[Decimal, _DECIMAL_ONLY, pydantic.AfterValidator(_check_amount)]
"""EN 16931 data type Amount: at most two decimals (BR-DEC-*, UBL-DT-01), never rounded implicitly."""

UnitPriceAmount = t.Annotated[Decimal, _DECIMAL_ONLY]
"""EN 16931 data type Unit price amount (BT-146..148): precision is kept as given."""

Quantity = t.Annotated[Decimal, _DECIMAL_ONLY]
"""EN 16931 data type Quantity (BT-129, BT-149): precision is kept as given."""

Percentage = t.Annotated[Decimal, _DECIMAL_ONLY]
"""EN 16931 data type Percentage: precision is kept as given.

Rates are percentages, ``19`` rather than ``0.19``: BR-S-09 computes the VAT as ``Percent div 100``.
"""
