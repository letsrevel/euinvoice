"""Building model objects in a syntax reader, with model errors turned into located :class:`ParseError` s.

Syntax-agnostic: the CII reader and the UBL reader (#11) both use :func:`build`.
"""

from collections.abc import Mapping

import pydantic
import pydantic_core

from euinvoice.errors import ParseError
from euinvoice.model import bt_id


def build[M: pydantic.BaseModel](
    cls: type[M], location: str, values: Mapping[str, object], term: str | None = None
) -> M:
    """Build ``cls`` from ``values`` read from the input.

    ``None`` means "absent", so a missing required term reads as pydantic's "Field required" for its BT/BG id.

    Args:
        cls: The model class.
        location: The XPath of the element the values were read from (the error location).
        values: The field values.
        term: The business term id of a class whose fields carry none (e.g. ``ItemClassificationIdentifier``).

    Returns:
        The validated model.

    Raises:
        ParseError: The values do not form a valid ``cls``; the message names each failing BT/BG id. A
            :class:`~euinvoice.errors.ModelError` raised by a model check arrives inside pydantic's
            ``ValidationError`` (it subclasses ``ValueError``), so it is covered too.
    """
    try:
        return cls(**{name: value for name, value in values.items() if value is not None})
    except pydantic.ValidationError as exc:
        problems = "; ".join(_problem(cls, error) for error in exc.errors())
        label = cls.__name__ if term is None else f"{term} {cls.__name__}"
        raise ParseError(f"cannot read {label}: {problems}", location=location) from exc


def _problem(cls: type[pydantic.BaseModel], error: pydantic_core.ErrorDetails) -> str:
    """One pydantic error as ``BT-n (field): message``."""
    location = tuple(error["loc"])
    field = location[0] if location and isinstance(location[0], str) else None
    ident = bt_id(cls, field) if field is not None and field in cls.model_fields else None
    where = ".".join(str(part) for part in location)
    label = f"{ident} ({where})" if ident is not None else where or cls.__name__
    return f"{label}: {error['msg']}"
