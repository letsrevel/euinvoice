"""Shared base of every EN 16931 model: frozen config, BT/BG metadata and Decimal-only conversion.

Every model field carries its EN 16931 identifier in its metadata (IMPLEMENTATION_PLAN.md D3) via
:func:`bt`, used inside ``typing.Annotated`` so the pydantic mypy plugin still sees defaults::

    class Totals(EuInvoiceModel):
        tax_exclusive: t.Annotated[Amount, bt("BT-109")]
        prepaid: t.Annotated[Amount | None, bt("BT-113")] = None
"""

import re
import typing as t
from decimal import Decimal

import pydantic
from pydantic.fields import FieldInfo

from euinvoice.errors import ModelError

__all__ = ["EuInvoiceModel", "bt", "bt_id", "to_decimal"]

_BT_ID = re.compile(r"B[TG]-(?:0|[1-9][0-9]*)")

# Lexical space of xs:decimal (XML Schema 1.1 Part 2, §3.3.3): optional sign, digits with an optional
# fraction, no exponent. Surrounding XML whitespace is collapsed first (whiteSpace=collapse).
_XSD_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")  # ASCII digits only, unlike \d
_XML_WHITESPACE = " \t\n\r"


class EuInvoiceModel(pydantic.BaseModel):
    """Base class of every euinvoice model.

    Instances are immutable (``frozen``), hashable and compared by value. Unknown fields are rejected
    (``extra="forbid"``) so typos never vanish silently, and validation is ``strict`` so pydantic never
    coerces between types behind the caller's back (e.g. ``"3"`` into ``3``). Numeric types do their own,
    documented conversion (see :func:`to_decimal`).
    """

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid", strict=True, validate_default=True)


def bt(ident: str) -> FieldInfo:
    """Return field metadata carrying an EN 16931 business term or group id (D3).

    Use it inside ``typing.Annotated``: ``t.Annotated[Amount, bt("BT-109")]``. The id is stored as
    ``json_schema_extra={"bt": ident}`` and shows up in the JSON schema.

    Args:
        ident: A business term (``BT-<n>``) or business group (``BG-<n>``) id.

    Returns:
        The pydantic ``FieldInfo`` to put in the ``Annotated`` metadata.

    Raises:
        ValueError: ``ident`` is not of the form ``BT-<n>`` or ``BG-<n>``.
    """
    if not _BT_ID.fullmatch(ident):
        raise ValueError(f"EN 16931 id must look like BT-<n> or BG-<n>, got {ident!r}")
    return t.cast(FieldInfo, pydantic.Field(json_schema_extra={"bt": ident}))


def bt_id(model: type[pydantic.BaseModel], field: str) -> str | None:
    """Return the BT/BG id declared with :func:`bt` on ``model.field``, or ``None`` if it has none.

    Args:
        model: The model class.
        field: The field name.

    Returns:
        The id, e.g. ``"BT-109"``, or ``None``.

    Raises:
        KeyError: ``model`` has no field called ``field``.
    """
    extra = model.model_fields[field].json_schema_extra
    ident = extra.get("bt") if isinstance(extra, dict) else None
    return ident if isinstance(ident, str) else None


def to_decimal(value: object) -> Decimal:
    """Convert ``value`` to a finite ``Decimal`` without ever going through binary floating point (D3).

    Accepted inputs, all converted exactly:

    * ``Decimal`` (returned unchanged);
    * ``int`` (exact by construction);
    * ``str`` in the ``xs:decimal`` lexical space (sign, digits, optional fraction, surrounding XML
      whitespace allowed). This is how amounts appear in UBL and CII, so text read from XML converts
      directly. Exponents, underscores, ``NaN`` and ``Infinity`` are not ``xs:decimal`` and are refused.

    Rejected: ``float`` (its binary value is not the decimal the caller wrote, e.g. ``1.1`` is
    ``1.100000000000000088817841970012523…``), ``bool``, non-finite decimals and every other type.

    Args:
        value: The raw input.

    Returns:
        The finite ``Decimal``.

    Raises:
        ModelError: ``value`` is not one of the accepted inputs.
    """
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, bool):  # before int: bool is an int subclass
        raise ModelError(f"bool is not a number here, got {value!r}")
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        raise ModelError(
            f"float is not accepted for amounts, quantities, prices or rates (got {value!r}): binary floats "
            "cannot represent most decimal values exactly. Pass a Decimal or a str, e.g. Decimal('1.10')."
        )
    elif isinstance(value, str):
        text = value.strip(_XML_WHITESPACE)
        if not _XSD_DECIMAL.fullmatch(text):
            raise ModelError(f"expected an xs:decimal literal such as '1.10' (no exponent), got {value!r}")
        result = Decimal(text)
    else:
        raise ModelError(f"expected a Decimal, int or xs:decimal str, got {type(value).__name__}")
    if not result.is_finite():
        raise ModelError(f"number must be finite, got {result!r}")
    return result
