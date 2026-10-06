"""The result of reading an XML invoice into the semantic model.

Readers never drop input silently (IMPLEMENTATION_PLAN.md §1, §4): every element or attribute present in
the input that has no business term in the model is listed in :attr:`ParseResult.unmapped`.
"""

import dataclasses

from euinvoice.model import Invoice


@dataclasses.dataclass(frozen=True, slots=True)
class ParseResult:
    """An invoice read from XML, plus the input it could not map.

    Attributes:
        invoice: The invoice built from the mapped business terms.
        unmapped: The location (an XPath as produced by ``lxml``'s ``getpath``) of each element or attribute
            in the input that the reader did not map to a business term, in document order. An attribute is
            ``<element path>/@prefix:name``; ``<element path>/text()`` means that only part of the element's text
            was mapped (e.g. the time zone of a UBL ``xs:date``, which the model's calendar date cannot hold).
    """

    invoice: Invoice
    unmapped: tuple[str, ...] = ()
