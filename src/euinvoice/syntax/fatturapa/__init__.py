"""FatturaPA 1.2.3 (Italy, SdI), plan M11: not an EN 16931 syntax; its non-EN data lives in ``Invoice.it`` (ADR 0001).

Writing (#119): :func:`write` turns an :class:`euinvoice.model.Invoice` into one FPR12 file with one body, unsigned,
with the transmission header from :class:`Transmission`; :func:`preflight` reports first what keeps it from being
written. :func:`file_name` and :func:`check_file` cover the SdI checks on the transmitted file (00001, 00003).

Reading (#120): :func:`read` maps a parsed document with one ``FatturaElettronicaBody`` (FPR12, and FPA12 as the
schema is shared) into an :class:`euinvoice.model.Invoice` with ``Invoice.it``, per App. 4.1 of the Regole tecniche
v2.6 in reverse, listing what it could not map in :attr:`ParseResult.unmapped`; :func:`read_all` reads every body of
a lotto, one result each.
"""

from euinvoice.syntax.fatturapa._read import read, read_all
from euinvoice.syntax.fatturapa._write import write
from euinvoice.syntax.fatturapa._write_preflight import preflight
from euinvoice.syntax.fatturapa.filename import EXTENSIONS, MAX_FILE_SIZE, check_file, file_name
from euinvoice.syntax.fatturapa.transmission import RECIPIENT_FOREIGN, RECIPIENT_UNKNOWN, Transmission
from euinvoice.syntax.result import ParseResult

__all__ = [
    "EXTENSIONS",
    "MAX_FILE_SIZE",
    "RECIPIENT_FOREIGN",
    "RECIPIENT_UNKNOWN",
    "ParseResult",
    "Transmission",
    "check_file",
    "file_name",
    "preflight",
    "read",
    "read_all",
    "write",
]
