"""FatturaPA 1.2.3 (Italy, SdI), plan M11: not an EN 16931 syntax; its non-EN data lives in ``Invoice.it`` (ADR 0001).

Writing (#119): :func:`write` turns an :class:`euinvoice.model.Invoice` into one FPR12 file with one body, unsigned,
with the transmission header from :class:`WriterOptions`; :func:`preflight` reports what the invoice lacks first.
:func:`file_name` and :func:`check_file` cover the SdI checks on the transmitted file (00001, 00003).
"""

from euinvoice.syntax.fatturapa._write import write
from euinvoice.syntax.fatturapa._write_preflight import preflight
from euinvoice.syntax.fatturapa.filename import MAX_FILE_SIZE, check_file, file_name
from euinvoice.syntax.fatturapa.options import RECIPIENT_FOREIGN, RECIPIENT_UNKNOWN, WriterOptions

__all__ = [
    "MAX_FILE_SIZE",
    "RECIPIENT_FOREIGN",
    "RECIPIENT_UNKNOWN",
    "WriterOptions",
    "check_file",
    "file_name",
    "preflight",
    "write",
]
