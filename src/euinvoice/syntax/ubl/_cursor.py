"""Element access shared by the UBL reader modules, with the bookkeeping behind ``ParseResult.unmapped``.

Every element and attribute the reader maps to a business term is *taken* through :class:`Cursor`. What
was never taken is reported by :meth:`Cursor.unmapped`, so nothing in the input is dropped silently
(IMPLEMENTATION_PLAN.md §4). Values are handed to the model as read: the model's types convert and check
them (Decimal-only numbers, code lists), and :func:`build` turns a model error into a
:class:`~euinvoice.errors.ParseError` that names the business term and the element.
"""

import datetime
import re
import typing as t

import pydantic
from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ParseError
from euinvoice.model import Identifier
from euinvoice.model._base import EuInvoiceModel, bt_id

__all__ = ["CAC", "CBC", "Cursor", "build", "normalize_space"]

CAC: t.Final = f"{{{_xml.UBL_CAC}}}"
"""Clark prefix of the UBL common aggregate components (``cac``)."""
CBC: t.Final = f"{{{_xml.UBL_CBC}}}"
"""Clark prefix of the UBL common basic components (``cbc``)."""

_XML_SPACE: t.Final = " \t\r\n"
"""XML whitespace, stripped from ``xs:date`` and ``xs:boolean`` values (both have ``whiteSpace=collapse``)."""

_XML_NAMESPACE: t.Final = "http://www.w3.org/XML/1998/namespace"
_XML_SPACE_RUN: t.Final = re.compile(r"[ \t\r\n]+")
_DATE: t.Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

_BOOLEANS: t.Final = {"true": True, "1": True, "false": False, "0": False}
"""The ``xs:boolean`` lexical space (XML Schema 1.1 Part 2, §3.3.2)."""


def normalize_space(text: str | None) -> str:
    """XPath ``normalize-space``: XML whitespace runs collapsed to one space and stripped (``None`` is ``""``).

    Args:
        text: The text.

    Returns:
        The normalized text.
    """
    return " ".join(part for part in _XML_SPACE_RUN.split(text or "") if part)


def _path(element: etree._Element) -> str:
    return element.getroottree().getpath(element)


def build[M: EuInvoiceModel](model: type[M], at: etree._Element, term: str, /, **values: object) -> M:
    """Build a model from values read at ``at``, turning a validation error into :class:`ParseError`.

    ``None`` means "absent": a missing mandatory term then reads as pydantic's "Field required". The message
    has the form ``cannot read <term> <Class>: <BT-n> (<field>): <reason>; …``, the same as the CII reader's.

    Args:
        model: The model class.
        at: The element the values were read from; its XPath is the error location.
        term: The BT/BG id of the model (named for errors that concern no single field, e.g. BR-33).
        **values: The field values.

    Returns:
        The model.

    Raises:
        ParseError: The values do not form a valid model. A :class:`~euinvoice.errors.ModelError` raised by a
            model check arrives inside pydantic's ``ValidationError`` and keeps its CEN rule id.
    """
    try:
        return model(**{name: value for name, value in values.items() if value is not None})
    except pydantic.ValidationError as exc:
        problems = "; ".join(_problem(model, error) for error in exc.errors())
        raise ParseError(f"cannot read {term} {model.__name__}: {problems}", location=_path(at)) from exc


def _problem(model: type[EuInvoiceModel], error: t.Any) -> str:
    """One pydantic error as ``BT-n (field): message``."""
    location = tuple(error["loc"])
    field = location[0] if location and isinstance(location[0], str) else None
    ident = bt_id(model, field) if field is not None and field in model.model_fields else None
    where = ".".join(str(part) for part in location)
    label = f"{ident} ({where})" if ident is not None else where or model.__name__
    return f"{label}: {error['msg']}"


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
        self._taken: set[etree._Element] = {root}
        self._taken_attributes: set[tuple[etree._Element, str]] = set()

    def take(self, element: etree._Element) -> etree._Element:
        """Mark ``element`` and its ancestors as mapped.

        Args:
            element: The element.

        Returns:
            ``element``.
        """
        node: etree._Element | None = element
        while node is not None and node not in self._taken:
            self._taken.add(node)
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

        ``xs:date`` may carry a time zone (``2026-01-15Z``); the model keeps a calendar date only, so such a
        value is refused instead of losing the zone silently.

        Args:
            element: The date element.
            term: The business term id, for the error message.

        Returns:
            The date.

        Raises:
            ParseError: The text is not a calendar date ``YYYY-MM-DD``.
        """
        text = (self.value(element) or "").strip(_XML_SPACE)
        if _DATE.fullmatch(text):
            try:
                return datetime.date.fromisoformat(text)
            except ValueError:
                pass
        raise ParseError(
            f"{term}: cannot interpret the date {text!r}; EN 16931 UBL dates are xs:date YYYY-MM-DD without a "
            "time zone (the model keeps a calendar date)",
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
        self._taken_attributes.add((element, name))
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

    def boolean(self, parent: etree._Element | None, tag: str) -> bool | None:
        """Read an ``xs:boolean`` (``true``, ``false``, ``1``, ``0``, surrounding whitespace allowed).

        Args:
            parent: The parent element, or ``None``.
            tag: The Clark name.

        Returns:
            The value, or ``None`` if the element is missing.

        Raises:
            ParseError: The text is not an ``xs:boolean``.
        """
        element = self.first(parent, tag)
        if element is None:
            return None
        value = _BOOLEANS.get((self.value(element) or "").strip(_XML_SPACE))
        if value is None:
            raise ParseError(
                f"expected an xs:boolean (true, false, 1, 0), got {element.text!r}", location=_path(element)
            )
        return value

    def unmapped(self) -> tuple[str, ...]:
        """List what the reader did not map, in document order.

        Returns:
            The XPath (lxml ``getpath``) of each element that was not taken under a taken parent, and
            ``<element path>/@<name>`` of each attribute that was not taken on a taken element. Comments
            and processing instructions carry no data and are not listed.
        """
        found: list[str] = []
        self._collect(self.root, found)
        return tuple(found)

    def _collect(self, element: etree._Element, found: list[str]) -> None:
        for name in t.cast(list[str], element.keys()):  # str for parsed documents; the stubs also allow bytes
            if (element, name) not in self._taken_attributes:
                found.append(f"{_path(element)}/@{_attribute_name(element, name)}")
        for child in element.iterchildren("*"):
            if child in self._taken:
                self._collect(child, found)
            else:
                found.append(_path(child))


def _attribute_name(element: etree._Element, name: str) -> str:
    """``prefix:local`` for a namespaced attribute (``xml:lang``, ``xsi:schemaLocation``); Clark notation otherwise."""
    qname = etree.QName(name)
    if not qname.namespace:
        return name
    prefixes = {uri: prefix for prefix, uri in element.nsmap.items() if prefix is not None}
    prefixes[_XML_NAMESPACE] = "xml"  # bound by definition, never declared (Namespaces in XML 1.0, §3)
    prefix = prefixes.get(qname.namespace)
    return name if prefix is None else f"{prefix}:{qname.localname}"
