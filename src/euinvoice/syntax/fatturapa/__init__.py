"""FatturaPA 1.2 (Italy, SdI; XSD 1.2.3): ``FatturaElettronica``, FPR12 (and FPA12 on read).

:func:`read` maps a parsed document with one ``FatturaElettronicaBody`` into an :class:`~euinvoice.model.Invoice`
with its ``Invoice.it`` extension, listing what it could not map in :attr:`ParseResult.unmapped`; :func:`read_all`
reads every body of a lotto. The mapping follows App. 4.1 of the SdI "Regole tecniche fatture europee" v2.6.
"""

from euinvoice.syntax.fatturapa._read import read, read_all
from euinvoice.syntax.result import ParseResult

__all__ = ["ParseResult", "read", "read_all"]
