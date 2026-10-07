"""Shared base of every EN 16931 model: frozen config, BT/BG metadata and Decimal-only conversion.

Every model field carries its EN 16931 identifier in its metadata (IMPLEMENTATION_PLAN.md D3) via
:func:`bt`, used inside ``typing.Annotated`` so the pydantic mypy plugin still sees defaults::

    class Totals(EuInvoiceModel):
        tax_exclusive: t.Annotated[Amount, bt("BT-109")]
        prepaid: t.Annotated[Amount | None, bt("BT-113")] = None

The one exception is a per-country extension hook (D3 as amended by ADR 0001), e.g. ``Invoice.it``: it carries
:func:`extension` instead of a BT, the BT index skips it, and the fields inside cite their national element ids.
"""

import re
import typing as t
from decimal import Decimal

import pydantic
from pydantic.fields import FieldInfo

from euinvoice.errors import ModelError

__all__ = [
    "XSD_DECIMAL_PATTERN",
    "EuInvoiceModel",
    "bt",
    "bt_id",
    "extension",
    "extension_of",
    "set_extensions",
    "to_decimal",
    "without_extensions",
]

_BT_ID = re.compile(r"B[TG]-(?:0|[1-9][0-9]*)")
_COUNTRY = re.compile(r"[a-z]{2}")

XSD_DECIMAL_PATTERN: t.Final = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)"
"""Lexical space of xs:decimal (XML Schema 1.1 Part 2, §3.3.3): optional sign, ASCII digits (unlike
``\\d``) with an optional fraction, no exponent. Unanchored."""

_XSD_DECIMAL = re.compile(XSD_DECIMAL_PATTERN)
_XML_WHITESPACE = " \t\n\r"  # stripped first: xs:decimal has whiteSpace=collapse


class EuInvoiceModel(pydantic.BaseModel):
    """Base class of every euinvoice model.

    Instances are immutable (``frozen``), hashable and compared by value. Unknown fields are rejected
    (``extra="forbid"``) so typos never vanish silently. Validation uses pydantic's default (lax) mode,
    so Python and JSON input behave alike: a list fills a tuple field, a code value fills a ``StrEnum``
    field, an ISO string fills a date field. A field that must not coerce (e.g. ``"3"`` into ``3``)
    opts in with ``pydantic.StrictInt`` or ``pydantic.Strict()``. The numeric types are Decimal-only
    whatever the mode (see :func:`to_decimal`).
    """

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid", validate_default=True)


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


def extension(country: str) -> FieldInfo:
    """Return the metadata of a per-country extension hook such as ``Invoice.it`` (D3 as amended, ADR 0001).

    The hook has no EN 16931 id: :mod:`euinvoice.model.bt_index` skips it, and the fields of the extension cite
    their national element ids instead. Use it inside ``typing.Annotated``.

    Args:
        country: The lower-case ISO 3166-1 alpha-2 code the hook is named after, e.g. ``"it"``.

    Returns:
        The pydantic ``FieldInfo``, ``json_schema_extra={"extension": country}``.

    Raises:
        ValueError: ``country`` is not two lower-case letters.
    """
    if not _COUNTRY.fullmatch(country):
        raise ValueError(f"extension country must be two lower-case letters, got {country!r}")
    return t.cast(FieldInfo, pydantic.Field(json_schema_extra={"extension": country}))


def extension_of(model: type[pydantic.BaseModel], field: str) -> str | None:
    """Return the country of the extension hook ``model.field`` (see :func:`extension`), or ``None``.

    Args:
        model: The model class.
        field: The field name.

    Returns:
        E.g. ``"it"``, or ``None`` for a field that is not an extension hook.

    Raises:
        KeyError: ``model`` has no field called ``field``.
    """
    extra = model.model_fields[field].json_schema_extra
    country = extra.get("extension") if isinstance(extra, dict) else None
    return country if isinstance(country, str) else None


def set_extensions(model: pydantic.BaseModel, prefix: str = "") -> tuple[str, ...]:
    """Return the path of every extension hook that is set in ``model``, at any depth.

    Writers of a syntax with no place for an extension use it to refuse the invoice instead of dropping the
    extension silently (D3 as amended, plan §1).

    Args:
        model: An instance, e.g. an :class:`~euinvoice.model.Invoice`.
        prefix: Prepended to every path (used by the recursion).

    Returns:
        The paths in field order, with indexes for repeated groups, e.g. ``("it", "lines[1].it")``.
    """
    found: list[str] = []
    for name in type(model).model_fields:
        value = getattr(model, name)
        if extension_of(type(model), name) is not None:
            if value is not None:
                found.append(f"{prefix}{name}")
        elif isinstance(value, pydantic.BaseModel):
            found.extend(set_extensions(value, f"{prefix}{name}."))
        elif isinstance(value, tuple):
            for index, item in enumerate(value):
                if isinstance(item, pydantic.BaseModel):
                    found.extend(set_extensions(item, f"{prefix}{name}[{index}]."))
    return tuple(found)


def without_extensions[M: pydantic.BaseModel](model: M) -> tuple[M, tuple[str, ...]]:
    """Return ``model`` with every set extension hook cleared, and the paths of the hooks it cleared.

    A read FatturaPA invoice sets ``Invoice.it`` (and often ``InvoiceLine.it``), so the UBL and CII writers refuse it
    (D3 as amended: an extension is never dropped silently). This drops them on request and reports what it dropped,
    so the caller can decide, e.g. before ``to_xml``. The paths are those of :func:`set_extensions`.

    Args:
        model: An instance, e.g. an :class:`~euinvoice.model.Invoice`.

    Returns:
        The model without extensions (``model`` itself when none is set) and the cleared paths, e.g.
        ``("it", "lines[1].it")``.
    """
    dropped = set_extensions(model)
    return (model if not dropped else _strip(model)), dropped


def _strip[V](value: V) -> V:
    """``value`` with every extension hook below it set to ``None`` (models rebuilt only where something changed)."""
    if isinstance(value, tuple):
        return t.cast(V, tuple(_strip(item) for item in value))
    if not isinstance(value, pydantic.BaseModel):
        return value
    update: dict[str, object] = {}
    for name in type(value).model_fields:
        old = getattr(value, name)
        new = None if extension_of(type(value), name) is not None else _strip(old)
        if new != old:
            update[name] = new
    # model_copy skips validation, which is safe here: only optional hooks become None (their default).
    return t.cast(V, value.model_copy(update=update))


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
