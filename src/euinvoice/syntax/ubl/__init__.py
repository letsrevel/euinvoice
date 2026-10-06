"""UBL 2.1 syntax binding (CEN/TS 16931-3-2): ``Invoice`` and ``CreditNote`` documents.

:func:`write` serializes :class:`euinvoice.model.Invoice`; :func:`read` maps a parsed document back to it and
lists what carries no business term in :attr:`ParseResult.unmapped`. The XPath of every business term is
listed in ``docs/reference/bt-mapping.md``; the writer modules cite the UBL 2.1 XSD types whose sequence
they follow.
"""

from euinvoice.syntax.result import ParseResult
from euinvoice.syntax.ubl._read import read
from euinvoice.syntax.ubl._write import write

__all__ = ["ParseResult", "read", "write"]
