"""Navigation, value conversion and bookkeeping of the FatturaPA reader (#120).

:class:`Cursor` walks an already parsed ``FatturaElettronica`` (D10: the reader never parses). Below the root, every
FatturaPA element is unqualified (XSD 1.2.3, ``elementFormDefault="unqualified"``), so children are found by their
local name alone. Every element and attribute the reader maps is marked, so :meth:`Cursor.unmapped` can list the rest
(``ParseResult.unmapped``); model errors become :class:`~euinvoice.errors.ParseError` located at the element read.
"""

import datetime
import re
from decimal import Decimal

from lxml import etree

from euinvoice.errors import ModelError, ParseError
from euinvoice.model._base import to_decimal
from euinvoice.syntax._marks import XML_SPACE, XSD_DATE, XSD_DATE_TIME, Marks


class Cursor:
    """Request-scoped state of reading one ``FatturaElettronicaBody`` with the shared header.

    Attributes:
        root: The ``FatturaElettronica`` element.
    """

    def __init__(self, root: etree._Element, body: etree._Element) -> None:
        """Start reading ``body`` of ``root``; the root and the body count as mapped.

        Args:
            root: The ``FatturaElettronica`` element.
            body: The ``FatturaElettronicaBody`` this read maps; its sibling bodies belong to other invoices.
        """
        self.root = root
        self._marks = Marks(root)
        self._marks.mark(body)
        self._others = [other for other in root.findall("FatturaElettronicaBody") if other != body]

    def use(self, element: etree._Element) -> etree._Element:
        """Mark ``element`` as mapped and return it."""
        return self._marks.mark(element)

    def discard(self, element: etree._Element | None) -> None:
        """Unmark ``element``: it was read, but the model does not keep its value as such (it is reported)."""
        if element is not None:
            self._marks.unmark(element)

    def partial(self, element: etree._Element) -> None:
        """Report ``element``'s text as only partly mapped (``…/text()`` in ``unmapped``)."""
        self._marks.mark_partial_text(element)

    def attribute(self, element: etree._Element, name: str) -> None:
        """Mark the unqualified attribute ``name`` of ``element`` as mapped."""
        self._marks.mark_attribute(element, name)

    @staticmethod
    def children(parent: etree._Element | None, name: str) -> list[etree._Element]:
        """The child elements called ``name``, without marking them (``[]`` without a parent)."""
        return [] if parent is None else parent.findall(name)

    def one(self, parent: etree._Element | None, name: str) -> etree._Element | None:
        """The first child called ``name``, marked (the XSD allows at most one wherever this is used)."""
        found = self.children(parent, name)
        return self.use(found[0]) if found else None

    def text(self, parent: etree._Element | None, name: str) -> str | None:
        """The text of the child ``name``, marked; ``None`` without one (an empty element reads as ``""``)."""
        element = self.one(parent, name)
        return None if element is None else (element.text or "")

    def code(self, parent: etree._Element | None, name: str) -> str | None:
        """The text of the child ``name`` stripped of XML whitespace, marked.

        The XSD codes are ``xs:string`` enumerations and patterns; the model checks the value.
        """
        value = self.text(parent, name)
        return None if value is None else value.strip(XML_SPACE)

    def decimal(self, parent: etree._Element | None, name: str, ident: str) -> Decimal | None:
        """The ``xs:decimal`` child ``name`` as an exact ``Decimal`` (D3), marked.

        Args:
            parent: The parent element, or ``None``.
            name: The child's local name.
            ident: Its FatturaPA element id, e.g. ``"2.2.1.9"``, for the error message.

        Raises:
            ParseError: The text is not an ``xs:decimal`` literal.
        """
        element = self.one(parent, name)
        if element is None:
            return None
        try:
            return to_decimal(element.text or "")
        except ModelError as exc:
            raise ParseError(f"{ident} {name}: {exc}", location=self.path(element)) from None

    def date(self, parent: etree._Element | None, name: str, ident: str) -> datetime.date | None:
        """The ``xs:date`` child ``name`` (``whiteSpace=collapse``), marked.

        ``xs:date`` may carry a time zone, which the model's calendar date cannot hold: it is reported as
        ``<element path>/text()`` in ``unmapped``, as the UBL reader does.

        Raises:
            ParseError: The text is not a calendar date ``YYYY-MM-DD``, with an optional time zone.
        """
        element = self.one(parent, name)
        return None if element is None else self._date(element, ident, XSD_DATE, zone_only=True)

    def date_of_time(self, parent: etree._Element | None, name: str, ident: str) -> datetime.date | None:
        """The calendar date of the ``xs:dateTime`` child ``name``, marked; the time is reported as ``…/text()``.

        Raises:
            ParseError: The text is not an ``xs:dateTime``.
        """
        element = self.one(parent, name)
        return None if element is None else self._date(element, ident, XSD_DATE_TIME, zone_only=False)

    def _date(self, element: etree._Element, ident: str, pattern: re.Pattern[str], *, zone_only: bool) -> datetime.date:
        text = (element.text or "").strip(XML_SPACE)
        match = pattern.fullmatch(text)
        if match is not None:
            try:
                value = datetime.date.fromisoformat(match.group(1))
            except ValueError:
                pass
            else:
                if not zone_only or match.group(2) is not None:
                    self.partial(element)
                return value
        kind = "xs:date" if zone_only else "xs:dateTime"
        raise ParseError(f"{ident} {element.tag}: {text!r} is not an {kind}", location=self.path(element))

    def path(self, element: etree._Element) -> str:
        """The XPath of ``element``."""
        return self._marks.path(element)

    def unmapped(self) -> tuple[str, ...]:
        """The XPaths of the header and of this body that no model field took, in document order.

        The other bodies of a lotto are other invoices (their own :class:`~euinvoice.syntax.result.ParseResult`),
        so they are not listed here.
        """
        others = {self.path(other) for other in self._others}  # unmarked, so each is listed once, as a whole
        return tuple(path for path in self._marks.unmapped() if path not in others)
