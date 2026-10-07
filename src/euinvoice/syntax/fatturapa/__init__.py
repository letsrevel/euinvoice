"""FatturaPA 1.2.3 (Italy, SdI), plan M11: not an EN 16931 syntax; its non-EN data lives in ``Invoice.it`` (ADR 0001).

Reading (#120): :func:`read` maps a parsed document with one ``FatturaElettronicaBody`` (FPR12, and FPA12 as the
schema is shared) into an :class:`euinvoice.model.Invoice` with ``Invoice.it``, per App. 4.1 of the Regole tecniche
v2.6 in reverse, listing what it could not map in :attr:`ParseResult.unmapped`; :func:`read_all` reads every body of
a lotto, one result each.
"""

from euinvoice.syntax.fatturapa._read import read, read_all
from euinvoice.syntax.result import ParseResult

__all__ = [
    "ParseResult",
    "read",
    "read_all",
]
