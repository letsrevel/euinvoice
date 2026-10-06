"""Per-term read tests of the UBL reader: one row per EN 16931 business term and group (several for some).

Each row is ``(id, changes, expected)``. ``changes`` are the model overrides of the matching row of the writer's
``BT_ROWS`` (``test_ubl_write_bts.py``, which pins the XPath each term is written to and read from), applied to the
minimal invoice; the invoice is written with the UBL writer and read back. ``expected`` is the tuple of values at
the term's model path (``BT_INDEX``) in the read invoice, or, for a group, the number of its instances; it is what
the row put in. The BT id comes first so the BT coverage gate (#32) can read the table.
"""

import typing as t

import pytest
from test_ubl_write_bts import BT_ROWS

from _invoices import minimal_invoice
from euinvoice import _xml
from euinvoice.model import path_of
from euinvoice.syntax import ubl

Expected = tuple[t.Any, ...] | int
Row = tuple[str, dict[str, t.Any], Expected]
"""``(BT/BG id, model overrides of the minimal invoice, expected)``; ``row[0]`` is the id (#32)."""


def values_at(model: t.Any, path: str) -> tuple[t.Any, ...]:
    """The values at a ``BT_INDEX`` path (``[]`` flattens a repeated field, ``None`` is skipped)."""
    items = [model]
    for part in filter(None, path.split(".")):
        name = part.removesuffix("[]")
        found: list[t.Any] = []
        for item in items:
            value = getattr(item, name)
            if part.endswith("[]"):
                found.extend(value)
            elif value is not None:
                found.append(value)
        items = found
    return tuple(items)


def _expected(term: str, changes: dict[str, t.Any]) -> Expected:
    values = values_at(minimal_invoice(**changes), path_of(term))
    return len(values) if term.startswith("BG-") else values


READ_ROWS: t.Final[tuple[Row, ...]] = tuple((row[0], row[1], _expected(row[0], row[1])) for row in BT_ROWS)
"""Every business term and group of the model, with the value(s) the reader must return for it."""


@pytest.mark.parametrize(
    ("term", "changes", "expected"), READ_ROWS, ids=[f"{r[0]}-{i}" for i, r in enumerate(READ_ROWS)]
)
def test_term_is_read(term: str, changes: dict[str, t.Any], expected: Expected) -> None:
    invoice = minimal_invoice(**changes)
    result = ubl.read(_xml.parse(ubl.write(invoice)))
    found = values_at(result.invoice, path_of(term))
    assert found, f"{term} was not read"
    assert (len(found) if isinstance(expected, int) else found) == expected, term
    assert result.invoice == invoice, term
    assert result.unmapped == (), term
