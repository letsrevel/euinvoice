"""Registry of every EN 16931 business term and group id and where it lives in :class:`Invoice`.

It is derived by walking the model's field metadata (:func:`euinvoice.model._base.bt`), never kept by
hand, so it cannot drift from the model. Paths are dotted field names from the root; ``[]`` marks a
repeated field (a tuple), e.g. ``lines[].item.name`` for BT-153. The root itself is ``BG-0`` with the
empty path.

Per-country extension hooks such as ``Invoice.it`` (marked with :func:`euinvoice.model._base.extension`) are
skipped explicitly: they hold no EN 16931 business term (D3 as amended, ADR 0001).

The completeness of the index against the official id list is a test
(``tests/model/test_bt_index.py``).
"""

import types
import typing as t
from collections.abc import Mapping

import pydantic

from euinvoice.model._base import EuInvoiceModel, bt_id, extension_of
from euinvoice.model.invoice import ROOT_ID, Invoice

__all__ = ["BT_INDEX", "PATH_INDEX", "build_index", "id_of", "path_of"]


def _unwrap(annotation: t.Any) -> tuple[t.Any, bool]:
    """Strip ``Optional`` and ``tuple[X, ...]`` from a field annotation.

    Args:
        annotation: A pydantic field annotation (``Annotated`` already removed by pydantic).

    Returns:
        The inner type and whether the field repeats.
    """
    repeated = False
    while True:
        origin = t.get_origin(annotation)
        if origin is t.Annotated:
            annotation = t.get_args(annotation)[0]
        elif origin in (t.Union, types.UnionType):
            (annotation,) = (arg for arg in t.get_args(annotation) if arg is not type(None))
        elif origin is tuple:
            annotation, repeated = t.get_args(annotation)[0], True
        else:
            return annotation, repeated


def _walk(model: type[pydantic.BaseModel], prefix: str, index: dict[str, str]) -> None:
    for name, field in model.model_fields.items():
        if extension_of(model, name) is not None:
            continue  # national data, no BT (D3 as amended)
        inner, repeated = _unwrap(field.annotation)
        path = f"{prefix}{name}{'[]' if repeated else ''}"
        ident = bt_id(model, name)
        if ident is not None:
            if ident in index:
                raise ValueError(f"{ident} is declared twice: {index[ident]!r} and {path!r}")
            index[ident] = path
        if isinstance(inner, type) and issubclass(inner, EuInvoiceModel):
            _walk(inner, f"{path}.", index)


def build_index(root: type[pydantic.BaseModel] = Invoice) -> dict[str, str]:
    """Walk a model and map every BT/BG id it declares to its path.

    Args:
        root: The root model, :class:`Invoice` by default (whose own id is ``BG-0``).

    Returns:
        ``{id: path}`` in declaration order.

    Raises:
        ValueError: An id is declared on two fields.
    """
    index = {ROOT_ID: ""}
    _walk(root, "", index)
    return index


BT_INDEX: t.Final[Mapping[str, str]] = types.MappingProxyType(build_index())
"""Every BT/BG id → its path in :class:`Invoice`, e.g. ``"BT-40"`` → ``"seller.postal_address.country_code"``."""

PATH_INDEX: t.Final[Mapping[str, str]] = types.MappingProxyType({path: ident for ident, path in BT_INDEX.items()})
"""The reverse of :data:`BT_INDEX`: path → id."""


def path_of(ident: str) -> str:
    """Return the model path of a BT/BG id.

    Args:
        ident: E.g. ``"BT-153"``.

    Returns:
        E.g. ``"lines[].item.name"`` (``""`` for ``BG-0``).

    Raises:
        KeyError: ``ident`` is not an EN 16931 id of the model.
    """
    return BT_INDEX[ident]


def id_of(path: str) -> str:
    """Return the BT/BG id of a model path.

    Args:
        path: A path as in :data:`BT_INDEX`, e.g. ``"seller.name"``.

    Returns:
        E.g. ``"BT-27"``.

    Raises:
        KeyError: No business term or group lives at ``path``.
    """
    return PATH_INDEX[path]
