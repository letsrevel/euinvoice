"""Byte-mutation strategies for the hostile-input properties of the Factur-X tests (``tests/facturx/*_hostile.py``)."""

import typing as t

from hypothesis import strategies as st

type Edit = tuple[t.Literal["overwrite", "insert", "delete"], int, bytes]

EDITS: t.Final = st.lists(
    st.tuples(
        st.sampled_from(["overwrite", "insert", "delete"]),
        st.integers(min_value=0),
        st.binary(min_size=1, max_size=16),
    ),
    max_size=8,
)
"""Up to 8 byte-run edits: overwrite or insert the run at a position, or delete as many bytes as it is long."""
CUTS: t.Final = st.one_of(st.none(), st.integers(min_value=0))
"""Where to truncate the result, if at all."""


def mutate(source: bytes, edits: list[Edit], cut: int | None) -> bytes:
    """Apply ``edits`` (positions wrap around the current length), then truncate at ``cut``."""
    data = bytearray(source)
    for kind, position, run in edits:
        at = position % (len(data) + 1)
        if kind == "overwrite":
            data[at : at + len(run)] = run
        elif kind == "insert":
            data[at:at] = run
        else:
            del data[at : at + len(run)]
    if cut is not None:
        del data[cut % (len(data) + 1) :]
    return bytes(data)
