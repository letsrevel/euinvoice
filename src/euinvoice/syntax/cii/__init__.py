"""UN/CEFACT Cross Industry Invoice D16B (CEN/TS 16931-3-3): ``rsm:CrossIndustryInvoice``.

:func:`write` serializes an :class:`~euinvoice.model.Invoice` (invoice or credit note alike, D4).
The XPath of each business term is listed in ``docs/reference/bt-mapping.md``.
"""

from euinvoice.syntax.cii._write import write

__all__ = ["write"]
