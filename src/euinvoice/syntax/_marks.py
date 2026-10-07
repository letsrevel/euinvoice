"""The bookkeeping behind ``ParseResult.unmapped``, shared by the UBL and the CII reader.

A reader marks every element and attribute it maps to a business term; :meth:`Marks.unmapped` lists the rest, so
nothing in the input is dropped silently (IMPLEMENTATION_PLAN.md §4). Syntax-agnostic: how a reader navigates and
converts values stays in its own module.
"""

import re
import typing as t

from lxml import etree

from euinvoice import _xml
from euinvoice.model.datatypes import normalize_space

__all__ = ["XML_SPACE", "XSD_DATE", "XSD_DATE_TIME", "Marks", "attribute_name", "normalize_space"]

XML_SPACE: t.Final = " \t\r\n"
"""XML whitespace (#x20, #x9, #xD, #xA): what XPath ``normalize-space`` and ``whiteSpace=collapse`` strip."""

_ZONE: t.Final = r"(Z|[+-](?:(?:0[0-9]|1[0-3]):[0-5][0-9]|14:00))"

XSD_DATE: t.Final = re.compile(rf"([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}){_ZONE}?")
"""``xs:date`` (XML Schema 1.1 Part 2, §3.3.9) with a four-digit year: the date, then an optional time zone."""

XSD_DATE_TIME: t.Final = re.compile(
    rf"([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}(?:\.[0-9]+)?{_ZONE}?"
)
"""``xs:dateTime`` (XML Schema 1.1 Part 2, §3.3.7) with a four-digit year: the date, the time, an optional time zone."""

_XML_NAMESPACE: t.Final = "http://www.w3.org/XML/1998/namespace"


def attribute_name(element: etree._Element, name: str) -> str:
    """``prefix:local`` for a namespaced attribute (``xml:lang``, ``xsi:schemaLocation``); Clark notation otherwise.

    Args:
        element: The element carrying the attribute (its ``nsmap`` gives the prefix).
        name: The attribute name as lxml reports it (Clark notation when namespaced).

    Returns:
        The name to show in an ``unmapped`` XPath.
    """
    qname = etree.QName(name)
    if not qname.namespace:
        return name
    prefixes = {uri: prefix for prefix, uri in element.nsmap.items() if prefix is not None}
    prefixes[_XML_NAMESPACE] = "xml"  # bound by definition, never declared (Namespaces in XML 1.0, §3)
    prefix = prefixes.get(qname.namespace)
    return name if prefix is None else f"{prefix}:{qname.localname}"


class Marks:
    """The elements and attributes of one document that a reader mapped.

    ``unmapped()`` lists, in document order: every unmarked element below a marked parent (once, at the top of
    its subtree), every unmarked attribute of a marked element (``…/@prefix:name``), and ``…/text()`` for a
    marked element only part of whose text was mapped (see :meth:`mark_partial_text`). Comments and processing
    instructions carry no data and are skipped.
    """

    def __init__(self, root: etree._Element) -> None:
        """Start with only ``root`` marked.

        Args:
            root: The document's root element.
        """
        self.root = root
        # lxml keeps one proxy per node while it is referenced, and the set holds the references.
        self._elements: set[etree._Element] = {root}
        self._attributes: set[tuple[etree._Element, str]] = set()
        self._partial_text: set[etree._Element] = set()

    def path(self, element: etree._Element) -> str:
        """The XPath of ``element`` (:func:`euinvoice._xml.getpath`).

        It costs O(siblings at every ancestor level), so it must not be called once per element.
        """
        return _xml.getpath(element)

    def mark(self, element: etree._Element) -> etree._Element:
        """Mark ``element`` as mapped and return it."""
        self._elements.add(element)
        return element

    def is_marked(self, element: etree._Element) -> bool:
        """Whether ``element`` is marked."""
        return element in self._elements

    def unmark(self, element: etree._Element) -> None:
        """Unmark ``element``: it was read, but its value is not the one the model kept."""
        self._elements.discard(element)

    def mark_attribute(self, element: etree._Element, name: str) -> None:
        """Mark the attribute ``name`` of ``element`` as mapped."""
        self._attributes.add((element, name))

    def mark_partial_text(self, element: etree._Element) -> None:
        """Report ``element``'s text as only partly mapped (``…/text()`` in :meth:`unmapped`)."""
        self._partial_text.add(element)

    def unmapped(self) -> tuple[str, ...]:
        """The XPaths of the input no business term took (``ParseResult.unmapped``), in document order."""
        found: list[str] = []
        self._collect(self.root, _ancestor_steps(self.root), found)
        return tuple(found)

    def _collect(self, element: etree._Element, steps: list[bytes], found: list[str]) -> None:
        attributes = [key if isinstance(key, str) else key.decode() for key in element.attrib]
        unmapped = [name for name in attributes if (element, name) not in self._attributes]
        if unmapped or element in self._partial_text:
            path = _join(steps)
            found.extend(f"{path}/@{attribute_name(element, name)}" for name in unmapped)
            if element in self._partial_text:
                found.append(f"{path}/text()")
        for child, step in _steps(element):
            steps.append(step)
            if child in self._elements:
                self._collect(child, steps, found)
            else:
                found.append(_join(steps))
            steps.pop()


# libxml2 2.14.6 tree.c, xmlGetNodePath, the bytes behind lxml's getpath (#80, #90):
#     char nametemp[100];
#     snprintf(nametemp, sizeof(nametemp) - 1, "%s:%s", (char *)cur->ns->prefix, (char *)cur->name);
# keeps 98 bytes of a prefixed name, and per step, leaf first:
#     buf_len = 500;
#     if (buf_len - len < sizeof(nametemp) + 20) { ... newSize = 2 * buf_len + len + sizeof(nametemp) + 20; ...}
#     snprintf((char *) buf, buf_len, "%s%s[%d]%s", sep, name, occur, (char *) buffer);
# so a path longer than its buffer loses its tail.
_NAME_BYTES: t.Final = 98
_PATH_BYTES: t.Final = 500
_ROOM: t.Final = 120


def _ancestor_steps(element: etree._Element) -> list[bytes]:
    """The steps of ``element``'s path, from the document element down (a reader may get an enveloped invoice)."""
    steps: list[bytes] = []
    node: etree._Element | None = element
    while node is not None:
        parent = node.getparent()
        if parent is None:
            steps.append(_step(_name(node), 1, 1))
        else:
            steps.append(next(step for child, step in _steps(parent) if child == node))
        node = parent
    return steps[::-1]


def _name(element: etree._Element) -> bytes | None:
    """The name in ``element``'s step: ``prefix:name`` cut to 98 bytes, ``name``, or ``None`` for a ``*`` step."""
    qname = etree.QName(element)
    if not qname.namespace:
        return qname.localname.encode()
    prefix = t.cast(str | None, element.prefix)  # lxml-stubs say str; None in a default namespace
    return None if prefix is None else f"{prefix}:{qname.localname}".encode()[:_NAME_BYTES]


def _step(name: bytes | None, index: int, count: int) -> bytes:
    """``/name``, ``/*`` for ``None``, then ``[index]`` unless it is the only one counted."""
    step = b"/" + (b"*" if name is None else name)
    return step if count == 1 else b"%s[%d]" % (step, index)


def _join(steps: list[bytes]) -> str:
    """The path of the steps, root first, as libxml2 assembles it (see above), decoded as :func:`_xml.getpath`."""
    path = b""
    size = _PATH_BYTES
    for step in reversed(steps):
        if size - len(path) < _ROOM:
            size = 2 * size + len(path) + _ROOM
        path = (step + path)[: size - 1]
    return _xml.path_text(path)


def _steps(parent: etree._Element) -> list[tuple[etree._Element, bytes]]:
    """Each child element of ``parent`` with its step of the ``getpath`` XPath, in one pass (#80).

    ``getpath`` is libxml2's ``xmlGetNodePath``, which counts the siblings at every level of every call, so one
    call per element was quadratic in the number of invoice lines. Its ``XML_ELEMENT_NODE`` branch writes
    ``prefix:name`` (cut to 98 bytes), ``name`` without a namespace, or ``*`` in a default namespace; then
    ``[n]``, the 1-based position among the siblings it counts, unless it is the only one. A ``*`` step counts
    every sibling element; any other counts those with the same full local name and either no namespace or the
    same prefix (not the same URI). Comments and PIs carry no data and are neither listed nor counted.
    """
    children = list(parent.iterchildren("*"))
    keys: list[tuple[str | None, str] | None] = []
    for child in children:
        qname = etree.QName(child)
        prefix = t.cast(str | None, child.prefix)  # lxml-stubs say str; None in a default namespace or none
        keys.append((prefix, qname.localname) if not qname.namespace or prefix is not None else None)
    totals: dict[tuple[str | None, str] | None, int] = {}
    for key in keys:
        totals[key] = totals.get(key, 0) + 1
    seen: dict[tuple[str | None, str] | None, int] = {}
    steps: list[tuple[etree._Element, bytes]] = []
    for position, (child, key) in enumerate(zip(children, keys, strict=True), start=1):
        seen[key] = seen.get(key, 0) + 1
        index, count = (position, len(children)) if key is None else (seen[key], totals[key])
        steps.append((child, _step(_name(child), index, count)))
    return steps
