"""UBL 2.1 syntax binding (CEN/TS 16931-3-2): ``Invoice`` and ``CreditNote`` documents.

:func:`write` serializes :class:`euinvoice.model.Invoice`. The XPath of every business term is listed in
``docs/reference/bt-mapping.md``; the writer modules cite the UBL 2.1 XSD types whose sequence they follow.
"""

from euinvoice.syntax.ubl._write import write

__all__ = ["write"]
