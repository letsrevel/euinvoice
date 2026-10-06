"""Element access shared by the UBL reader modules, with the bookkeeping behind ``ParseResult.unmapped``.

Every element and attribute the reader maps to a business term is *taken* through :class:`Cursor`, which
records it in the shared :class:`~euinvoice.syntax._marks.Marks`; what was never taken is reported by
:meth:`Cursor.unmapped`, so nothing in the input is dropped silently (IMPLEMENTATION_PLAN.md §4). Values are
handed to the model as read: the model's types convert and check them (Decimal-only numbers, code lists), and
:func:`build` turns a model error into a :class:`~euinvoice.errors.ParseError` that names the business term and
the element (shared with the CII reader).
"""

import datetime
import re
import typing as t

from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ParseError
from euinvoice.model import Identifier
from euinvoice.model._base import EuInvoiceModel
from euinvoice.syntax import _read_errors as read_errors
from euinvoice.syntax._marks import XML_SPACE, Marks

__all__ = ["CAC", "CBC", "Cursor", "build", "type_code"]

CAC: t.Final = f"{{{_xml.UBL_CAC}}}"
"""Clark prefix of the UBL common aggregate components (``cac``)."""
CBC: t.Final = f"{{{_xml.UBL_CBC}}}"
"""Clark prefix of the UBL common basic components (``cbc``)."""

_DATE: t.Final = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})(Z|[+-](?:(?:0[0-9]|1[0-3]):[0-5][0-9]|14:00))?")
"""``xs:date`` (XML Schema 1.1 Part 2, §3.3.9) with a four-digit year: the date, then an optional time zone."""

_BOOLEANS: t.Final = {"true": True, "1": True, "false": False, "0": False}
"""The ``xs:boolean`` lexical space (XML Schema 1.1 Part 2, §3.3.2)."""


def type_code(reference: etree._Element) -> str | None:
    """The ``cbc:DocumentTypeCode`` text of a document reference without taking it (``None`` without one).

    Args:
        reference: A ``cac:AdditionalDocumentReference`` or ``cac:DocumentReference``.

    Returns:
        The code, or ``None``.
    """
    code = next(reference.iterchildren(CBC + "DocumentTypeCode"), None)
    return None if code is None else code.text or ""


def _path(element: etree._Element) -> str:
    return _xml.getpath(element)


def build[M: EuInvoiceModel](model: type[M], at: etree._Element, term: str, /, **values: object) -> M:
    """Build a model from values read at ``at`` with the shared :func:`euinvoice.syntax._read_errors.build`.

    Args:
        model: The model class.
        at: The element the values were read from; its XPath is the error location.
        term: The BT/BG id of the model, named in the error message (``cannot read <term> <Class>: …``).
        **values: The field values (``None`` means absent).

    Returns:
        The model.

    Raises:
        ParseError: The values do not form a valid model; the message names each failing BT/BG id.
    """
    return read_errors.build(model, at, values, term)


class Cursor:
    """Reads one UBL document and remembers which elements and attributes were mapped.

    An element counts as taken when it, or anything below it, was mapped; :meth:`unmapped` then lists
    every element that was not taken under a taken parent, and every attribute that was not taken on a
    taken element.
    """

    def __init__(self, root: etree._Element) -> None:
        """Start reading at the document root.

        Args:
            root: The ``Invoice`` or ``CreditNote`` element.
        """
        self.root = root
        self._marks = Marks(root)

    def take(self, element: etree._Element) -> etree._Element:
        """Mark ``element`` and its ancestors as mapped.

        Args:
            element: The element.

        Returns:
            ``element``.
        """
        node: etree._Element | None = element
        while node is not None and not self._marks.is_marked(node):
            self._marks.mark(node)
            node = node.getparent()
        return element

    def children(self, parent: etree._Element | None, tag: str) -> list[etree._Element]:
        """Return the children of ``parent`` called ``tag`` without taking them.

        Args:
            parent: The parent element, or ``None`` (no children).
            tag: The Clark name, e.g. ``CBC + "ID"``.

        Returns:
            The children in document order.
        """
        return [] if parent is None else list(parent.iterchildren(tag))

    def first(self, parent: etree._Element | None, tag: str) -> etree._Element | None:
        """Return the first child called ``tag`` without taking it; later ones stay unmapped.

        Containers are taken only through what is read inside them, so an empty one stays unmapped.

        Args:
            parent: The parent element, or ``None``.
            tag: The Clark name.

        Returns:
            The child, or ``None`` if there is none.
        """
        return next(iter(self.children(parent, tag)), None)

    def value(self, element: etree._Element | None) -> str | None:
        """Take ``element`` and return its text verbatim (``""`` when empty).

        Args:
            element: The element, or ``None``.

        Returns:
            The text, or ``None`` when ``element`` is ``None``.
        """
        return None if element is None else self.take(element).text or ""

    def text(self, parent: etree._Element | None, tag: str) -> str | None:
        """Take the first child called ``tag`` and return its text verbatim (``""`` when empty).

        Args:
            parent: The parent element, or ``None``.
            tag: The Clark name.

        Returns:
            The text, or ``None`` if there is no such child.
        """
        return self.value(self.first(parent, tag))

    def date(self, parent: etree._Element | None, tag: str, term: str) -> datetime.date | None:
        """Take the first child called ``tag`` and read it as a date (see :meth:`parse_date`).

        Args:
            parent: The parent element, or ``None``.
            tag: The Clark name.
            term: The business term id, for the error message.

        Returns:
            The date, or ``None`` if there is no such child.

        Raises:
            ParseError: The text is not a calendar date ``YYYY-MM-DD``.
        """
        element = self.first(parent, tag)
        return None if element is None else self.parse_date(element, term)

    def parse_date(self, element: etree._Element, term: str) -> datetime.date:
        """Take ``element`` and read its ``xs:date`` (``whiteSpace=collapse``, so surrounding whitespace is fine).

        ``xs:date`` may carry a time zone (``2026-01-15Z``, ``2026-01-15+01:00``); no CEN rule restricts it. The
        model keeps the calendar date only, so the date is read and the time zone, which has no business term,
        is reported as ``<element path>/text()`` in ``unmapped`` (part of the element's text was not mapped).

        Args:
            element: The date element.
            term: The business term id, for the error message.

        Returns:
            The date.

        Raises:
            ParseError: The text is not an ``xs:date`` with a four-digit year, or not a calendar date.
        """
        text = (self.value(element) or "").strip(XML_SPACE)
        match = _DATE.fullmatch(text)
        if match:
            try:
                value = datetime.date.fromisoformat(match.group(1))
            except ValueError:
                pass
            else:
                if match.group(2) is not None:
                    self._marks.mark_partial_text(element)
                return value
        raise ParseError(
            f"{term}: cannot interpret the date {text!r}; expected an xs:date YYYY-MM-DD, optionally with a time zone",
            location=_path(element),
        )

    def attribute(self, element: etree._Element | None, name: str) -> str | None:
        """Take and return an attribute of ``element``.

        Args:
            element: The element, or ``None``.
            name: The attribute name.

        Returns:
            The value, or ``None`` if the element or the attribute is missing.
        """
        value = None if element is None else element.get(name)
        if element is None or value is None:
            return None
        self._marks.mark_attribute(element, name)
        return value

    def identifier(self, parent: etree._Element | None, tag: str) -> Identifier | None:
        """Read an identifier with its optional ``schemeID``.

        Args:
            parent: The parent element, or ``None``.
            tag: The Clark name of the identifier element.

        Returns:
            The identifier, or ``None`` if the element is missing. Its scheme is checked by the field it
            is put in.
        """
        element = self.first(parent, tag)
        if element is None:
            return None
        return Identifier(value=self.value(element) or "", scheme_id=self.attribute(element, "schemeID"))

    def amount(self, parent: etree._Element | None, tag: str, currency: str | None) -> str | None:
        """Read an amount; its ``currencyID`` is taken only when it is ``currency``.

        A ``currencyID`` other than the expected one carries information the model has no place for
        (every amount but BT-111 is in BT-5), so it is left to :meth:`unmapped` instead of being dropped.

        Args:
            parent: The parent element, or ``None``.
            tag: The Clark name.
            currency: The expected ``currencyID``.

        Returns:
            The amount text for the model to convert, or ``None``.
        """
        element = self.first(parent, tag)
        if element is None:
            return None
        if element.get("currencyID") == currency:
            self.attribute(element, "currencyID")
        return self.value(element)

    def boolean(self, parent: etree._Element | None, tag: str, term: str) -> bool | None:
        """Read an ``xs:boolean`` (``true``, ``false``, ``1``, ``0``, surrounding whitespace allowed).

        Unlike the CII reader, which leaves a bad ``udt:Indicator`` unmapped, this raises: UBL's
        ``cbc:ChargeIndicator`` is typed ``xs:boolean`` (``IndicatorType``, UBL 2.1 XSD), so a document carrying
        anything else is not valid UBL and the XSD rejects it anyway.

        Args:
            parent: The parent element, or ``None``.
            tag: The Clark name.
            term: The BT/BG id(s) the value decides between, for the error message (e.g. ``"BG-20/BG-21"``).

        Returns:
            The value, or ``None`` if the element is missing.

        Raises:
            ParseError: The text is not an ``xs:boolean``.
        """
        element = self.first(parent, tag)
        if element is None:
            return None
        value = _BOOLEANS.get((self.value(element) or "").strip(XML_SPACE))
        if value is None:
            raise ParseError(
                f"{term}: expected an xs:boolean (true, false, 1, 0), got {element.text!r}", location=_path(element)
            )
        return value

    def unmapped(self) -> tuple[str, ...]:
        """List what the reader did not map, in document order (see :class:`~euinvoice.syntax._marks.Marks`).

        Returns:
            The XPath of each element not taken under a taken parent, ``…/@name`` of each attribute not taken on a
            taken element, and ``…/text()`` of each element whose text was only partly mapped.
        """
        return self._marks.unmapped()
