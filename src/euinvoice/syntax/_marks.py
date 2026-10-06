"""The bookkeeping behind ``ParseResult.unmapped``, shared by the UBL and the CII reader.

A reader marks every element and attribute it maps to a business term; :meth:`Marks.unmapped` lists the rest, so
nothing in the input is dropped silently (IMPLEMENTATION_PLAN.md §4). Syntax-agnostic: how a reader navigates and
converts values stays in its own module.
"""

import typing as t

from lxml import etree

from euinvoice.model.datatypes import normalize_space

__all__ = ["XML_SPACE", "Marks", "attribute_name", "normalize_space"]

XML_SPACE: t.Final = " \t\r\n"
"""XML whitespace (#x20, #x9, #xD, #xA): what XPath ``normalize-space`` and ``whiteSpace=collapse`` strip."""

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
        self._tree = root.getroottree()
        # lxml keeps one proxy per node while it is referenced, and the set holds the references.
        self._elements: set[etree._Element] = {root}
        self._attributes: set[tuple[etree._Element, str]] = set()
        self._partial_text: set[etree._Element] = set()

    def path(self, element: etree._Element) -> str:
        """The XPath of ``element`` (``ElementTree.getpath``)."""
        return self._tree.getpath(element)

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
        self._collect(self.root, found)
        return tuple(found)

    def _collect(self, element: etree._Element, found: list[str]) -> None:
        path = self.path(element)
        for key in element.attrib:
            name = key if isinstance(key, str) else key.decode()
            if (element, name) not in self._attributes:
                found.append(f"{path}/@{attribute_name(element, name)}")
        if element in self._partial_text:
            found.append(f"{path}/text()")
        for child in element.iterchildren("*"):  # elements only: comments and PIs carry no data
            if child in self._elements:
                self._collect(child, found)
            else:
                found.append(self.path(child))
