"""Navigation, value conversion and bookkeeping shared by the CII reader modules.

:class:`Reader` walks an already parsed ``rsm:CrossIndustryInvoice`` (D10: the reader never parses). Every
element and attribute it maps is marked, so :meth:`Reader.unmapped` can list the rest (``ParseResult.unmapped``).
Model errors become :class:`~euinvoice.errors.ParseError` located at the element being read.
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
from euinvoice.syntax.cii._build import DATE_FORMAT

_XML_SPACE: t.Final = " \t\r\n"
_DATE_102: t.Final = re.compile(r"[0-9]{8}")
_TRUE: t.Final = frozenset({"true", "1"})
_FALSE: t.Final = frozenset({"false", "0"})
"""The ``xs:boolean`` lexical space (XML Schema Part 2 §3.2.2) of ``udt:Indicator``."""


class Reader:
    """Request-scoped state of one CII read: the tree and the nodes mapped so far."""

    def __init__(self, root: etree._Element) -> None:
        """Start reading at ``root``, which counts as mapped.

        Args:
            root: The ``rsm:CrossIndustryInvoice`` element.
        """
        self.root = root
        self._tree = root.getroottree()
        # lxml keeps one proxy per node while it is referenced, and the set holds the references.
        self._elements: set[etree._Element] = {root}
        self._attributes: set[tuple[etree._Element, str]] = set()

    def path(self, element: etree._Element) -> str:
        """The XPath of ``element`` (``ElementTree.getpath``)."""
        return self._tree.getpath(element)

    def use(self, element: etree._Element) -> etree._Element:
        """Mark ``element`` as mapped and return it."""
        self._elements.add(element)
        return element

    def discard(self, element: etree._Element) -> None:
        """Unmark ``element``: it was read, but its value is not the one the model kept."""
        self._elements.discard(element)

    def children(self, parent: etree._Element | None, name: str, namespace: str = _xml.CII_RAM) -> list[etree._Element]:
        """The child elements called ``name``, without marking them (``[]`` without a parent)."""
        return [] if parent is None else parent.findall(f"{{{namespace}}}{name}")

    def each(self, parent: etree._Element | None, name: str, namespace: str = _xml.CII_RAM) -> list[etree._Element]:
        """The child elements called ``name``, all marked."""
        return [self.use(child) for child in self.children(parent, name, namespace)]

    def one(self, parent: etree._Element | None, name: str, namespace: str = _xml.CII_RAM) -> etree._Element | None:
        """The first child element called ``name``, marked; later ones stay unmapped (the model has room for one)."""
        found = self.children(parent, name, namespace)
        return self.use(found[0]) if found else None

    def text(self, parent: etree._Element | None, name: str) -> str | None:
        """The text of the first ``ram:<name>`` child, ``None`` without one (an empty element reads as ``""``)."""
        element = self.one(parent, name)
        return None if element is None else content(element)

    def attribute(self, element: etree._Element, name: str) -> str | None:
        """The unqualified attribute ``name`` of ``element``, marked."""
        value = element.get(name)
        if value is not None:
            self._attributes.add((element, name))
        return value

    def identifier(self, element: etree._Element) -> Identifier:
        """An identifier with its ``@schemeID``; the scheme list is checked by the model field that receives it."""
        return Identifier(value=content(element), scheme_id=self.attribute(element, "schemeID"))

    def date(
        self,
        parent: etree._Element | None,
        name: str,
        term: str,
        *,
        string: str = "DateTimeString",
        namespace: str = _xml.CII_UDT,
    ) -> datetime.date | None:
        """Read ``ram:<name>/udt:<string>[@format='102']`` (the inverse of the writer's ``date_time`` / ``date``).

        Args:
            parent: The element holding ``ram:<name>``.
            name: The date element, e.g. ``IssueDateTime``.
            term: The business term id, for the error message.
            string: ``DateTimeString`` or ``DateString`` (BT-7).
            namespace: ``udt``, or ``qdt`` for BT-26 (``ram:FormattedIssueDateTime``).

        Returns:
            The date, or ``None`` without ``ram:<name>``.

        Raises:
            ParseError: The date has no string, a format other than ``102`` (CCYYMMDD) or no valid calendar
                date. Only format 102 is interpreted: CII-DT-097 checks dates only for ``@format='102'`` and
                the CEN rules (BR-03, BR-29, BR-30) select it (binding note on #13).
        """
        holder = self.one(parent, name)
        if holder is None:
            return None
        element = self.one(holder, string, namespace)
        if element is None:
            raise ParseError(f"{term}: ram:{name} has no {string}", location=self.path(holder))
        code = self.attribute(element, "format")
        text = content(element).strip(_XML_SPACE)
        if code == DATE_FORMAT and _DATE_102.fullmatch(text):
            try:
                return datetime.date(int(text[:4]), int(text[4:6]), int(text[6:]))
            except ValueError:
                pass
        raise ParseError(
            f"{term}: cannot interpret the date {text!r} with format {code!r}; EN 16931 CII dates are "
            "format 102, CCYYMMDD (CII-DT-097)",
            location=self.path(element),
        )

    def indicator(self, parent: etree._Element, name: str, term: str) -> bool:
        """Read ``ram:<name>/udt:Indicator`` (``xs:boolean``; CII-SR-183 forbids ``udt:IndicatorString``).

        Raises:
            ParseError: The indicator is missing or not an ``xs:boolean``.
        """
        element = self.one(self.one(parent, name), "Indicator", _xml.CII_UDT)
        text = None if element is None else content(element).strip(_XML_SPACE)
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ParseError(
            f"{term}: ram:{name}/udt:Indicator must be 'true' or 'false', got {text!r}",
            location=self.path(parent if element is None else element),
        )

    def model[M: EuInvoiceModel](
        self, cls: type[M], element: etree._Element, term: str | None = None, /, **values: object
    ) -> M:
        """Build ``cls`` from ``values``, turning model errors into a located :class:`ParseError`.

        Args:
            cls: The model class.
            element: The element the values were read from (the error location).
            term: The business term id of a class whose fields carry none (``ItemClassificationIdentifier``).
            **values: The field values.

        Returns:
            The validated model.

        Raises:
            ParseError: The values do not form a valid ``cls``; the message names each failing BT/BG id. A
                :class:`~euinvoice.errors.ModelError` raised by a model check arrives inside pydantic's
                ``ValidationError`` (it subclasses ``ValueError``), so it is covered too.
        """
        try:
            # None means "absent": a missing required term then reads as pydantic's "Field required".
            return cls(**{name: value for name, value in values.items() if value is not None})
        except pydantic.ValidationError as exc:
            problems = "; ".join(_problem(cls, error) for error in exc.errors())
            label = cls.__name__ if term is None else f"{term} {cls.__name__}"
            raise ParseError(f"cannot read {label}: {problems}", location=self.path(element)) from exc

    def unmapped(self) -> tuple[str, ...]:
        """The XPaths of the input no business term took (``ParseResult.unmapped``), in document order.

        Every element below a marked parent that is not marked itself is listed (its descendants are not listed
        separately), and so is every attribute of a marked element that is not marked (``.../@name``; a
        namespaced one as ``prefix:name``, e.g. ``@xsi:schemaLocation``). Comments and processing instructions
        carry no data and are skipped.
        """
        found: list[str] = []
        self._collect(self.root, found)
        return tuple(found)

    def _collect(self, element: etree._Element, found: list[str]) -> None:
        path = self.path(element)
        for key in element.attrib:
            name = key if isinstance(key, str) else key.decode()
            if (element, name) not in self._attributes:
                found.append(f"{path}/@{_attribute_name(element, name)}")
        for child in element:
            if isinstance(child, etree._Comment | etree._ProcessingInstruction):  # they carry no data
                continue
            if child in self._elements:
                self._collect(child, found)
            else:
                found.append(self.path(child))


def content(element: etree._Element) -> str:
    """The text of a leaf element (``""`` when empty)."""
    return element.text or ""


def _attribute_name(element: etree._Element, name: str) -> str:
    """``prefix:local`` for a namespaced attribute (Clark notation when the namespace has no prefix)."""
    qname = etree.QName(name)
    if not qname.namespace:
        return name
    prefixes = {uri: prefix for prefix, uri in element.nsmap.items() if prefix is not None}
    prefix = prefixes.get(qname.namespace)
    return name if prefix is None else f"{prefix}:{qname.localname}"


def _problem(cls: type[EuInvoiceModel], error: t.Any) -> str:
    """One pydantic error as ``BT-n (field): message``."""
    location = tuple(error["loc"])
    field = location[0] if location and isinstance(location[0], str) else None
    ident = bt_id(cls, field) if field is not None and field in cls.model_fields else None
    where = ".".join(str(part) for part in location)
    label = f"{ident} ({where})" if ident is not None else where or cls.__name__
    return f"{label}: {error['msg']}"
