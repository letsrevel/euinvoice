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
        """The XPath of ``element`` (``ElementTree.getpath``).

        It costs O(siblings at every ancestor level), so it must not be called once per element.
        """
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
        self._collect(self.root, self.path(self.root), found)
        return tuple(found)

    def _collect(self, element: etree._Element, path: str, found: list[str]) -> None:
        for key in element.attrib:
            name = key if isinstance(key, str) else key.decode()
            if (element, name) not in self._attributes:
                found.append(f"{path}/@{attribute_name(element, name)}")
        if element in self._partial_text:
            found.append(f"{path}/text()")
        for child, step in self._steps(element):
            child_path = f"{path}/{step}"
            if child in self._elements:
                self._collect(child, child_path, found)
            else:
                found.append(child_path)

    def _steps(self, parent: etree._Element) -> list[tuple[etree._Element, str]]:
        """Each child element of ``parent`` with the last step of its ``getpath`` XPath, in one pass (#80).

        ``getpath`` is libxml2's ``xmlGetNodePath``, which counts the siblings at every level of every call, so
        one call per element was quadratic in the number of invoice lines. This writes the same steps for every
        element a reader can list (libxml2 2.14.6 ``tree.c``, ``xmlGetNodePath``, ``XML_ELEMENT_NODE`` branch;
        libxml2 also truncates the tail of very long no-namespace ancestor paths, which readers never list):
        ``prefix:name``, ``name`` without a namespace, or ``*`` in a default namespace; then ``[n]``, the
        1-based position among the siblings it counts, unless it is the only one. A ``*`` step counts every
        sibling element; any other counts those with the same local name and either no namespace or the same
        prefix (not the same URI). Comments and PIs carry no data and are neither listed nor counted.
        """
        children = list(parent.iterchildren("*"))
        names: list[str | None] = []
        for child in children:
            qname = etree.QName(child)
            if not qname.namespace:
                names.append(qname.localname)
            else:
                prefix = t.cast(str | None, child.prefix)  # lxml-stubs say str; None in a default namespace
                names.append(None if prefix is None else f"{prefix}:{qname.localname}")
        totals: dict[str | None, int] = {}
        for name in names:
            totals[name] = totals.get(name, 0) + 1
        seen: dict[str | None, int] = {}
        steps: list[tuple[etree._Element, str]] = []
        for position, (child, name) in enumerate(zip(children, names, strict=True), start=1):
            seen[name] = seen.get(name, 0) + 1
            index, count = (position, len(children)) if name is None else (seen[name], totals[name])
            # libxml2 writes ``prefix:name`` into a 100-byte buffer with snprintf size 99, keeping 98 bytes.
            # ponytail: such a name falls back to getpath, O(siblings) each, so a crafted invoice with many
            # long-prefixed siblings is quadratic again. Upgrade path: replicate the byte truncation (cut the
            # UTF-8 at 98 bytes as libxml2 does, then decode the way lxml decodes the result) and drop the fallback.
            if name is not None and len(name.encode()) > 98:
                steps.append((child, self.path(child).rpartition("/")[2]))
            else:
                step = "*" if name is None else name
                steps.append((child, step if count == 1 else f"{step}[{index}]"))
        return steps
