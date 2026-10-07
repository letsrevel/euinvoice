"""FatturaPA 1.2.3 (Italy, SdI), plan M11: not an EN 16931 syntax; its non-EN data lives in ``Invoice.it`` (ADR 0001).

Writing (#119): :func:`write` turns an :class:`euinvoice.model.Invoice` into one FPR12 file with one body, unsigned,
with the transmission header from :class:`Transmission`; :func:`preflight` reports first what keeps it from being
written.
:func:`file_name` and :func:`check_file` cover the SdI checks on the transmitted file (00001, 00003).
"""

from euinvoice.syntax.fatturapa._write import write
from euinvoice.syntax.fatturapa._write_preflight import preflight
from euinvoice.syntax.fatturapa.filename import EXTENSIONS, MAX_FILE_SIZE, check_file, file_name
from euinvoice.syntax.fatturapa.transmission import RECIPIENT_FOREIGN, RECIPIENT_UNKNOWN, Transmission

__all__ = [
    "EXTENSIONS",
    "MAX_FILE_SIZE",
    "RECIPIENT_FOREIGN",
    "RECIPIENT_UNKNOWN",
    "Transmission",
    "check_file",
    "file_name",
    "preflight",
    "write",
]
