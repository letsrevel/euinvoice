"""What :mod:`~euinvoice.facturx._embed` and :mod:`~euinvoice.facturx._extract` share about reading a PDF with pypdf.

Both run pypdf on untrusted input inside narrow boundaries that turn :data:`PYPDF_FAILURES` into ``PdfError`` with
their own message, and both read the catalog's XMP packet with :func:`metadata_bytes`.
"""

import typing as t

import pypdf
from pypdf.errors import PyPdfError

from euinvoice.errors import PdfError

__all__ = ["PYPDF_FAILURES", "metadata_bytes"]

PYPDF_FAILURES: t.Final = (PyPdfError, ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError)
"""What pypdf raises on malformed input besides its own ``PyPdfError`` hierarchy (found by byte-mutation fuzzing)."""


def metadata_bytes(reader: pypdf.PdfReader, *, missing: str) -> bytes:
    """Return the decoded XMP packet of the catalog's ``/Metadata`` stream.

    Args:
        reader: The open PDF.
        missing: The ``PdfError`` message when the catalog has no ``/Metadata``.

    Returns:
        The raw packet bytes (not parsed).

    Raises:
        PdfError: There is no ``/Metadata``, or it is not a stream.
    """
    metadata = reader.root_object.get("/Metadata")
    if metadata is None:
        raise PdfError(missing)
    stream = metadata.get_object()
    if not isinstance(stream, pypdf.generic.StreamObject):
        raise PdfError("the catalog /Metadata is not a stream")
    return stream.get_data()
