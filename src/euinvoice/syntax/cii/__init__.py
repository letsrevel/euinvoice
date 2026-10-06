"""UN/CEFACT Cross Industry Invoice D16B (CEN/TS 16931-3-3): ``rsm:CrossIndustryInvoice``.

:func:`write` serializes an :class:`~euinvoice.model.Invoice` (invoice or credit note alike, D4); :func:`read` maps
a parsed instance back into one, listing what it could not map in :attr:`ParseResult.unmapped`.
The XPath of each business term is listed in ``docs/reference/bt-mapping.md``.
"""

from euinvoice.syntax.cii._read import read
from euinvoice.syntax.cii._write import write
from euinvoice.syntax.result import ParseResult

__all__ = ["ParseResult", "read", "write"]
