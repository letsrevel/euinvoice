"""The unmapped bookkeeping shared by the UBL and the CII reader (``euinvoice.syntax._marks``)."""

import copy
import typing as t

import pytest
from _cii_invoices import all_terms_invoice
from hypothesis import given
from hypothesis import strategies as st
from lxml import etree

from _invoices import minimal_invoice
from euinvoice import _xml
from euinvoice.model import ItemAttribute
from euinvoice.syntax import _read_errors as read_errors
from euinvoice.syntax import cii, ubl
from euinvoice.syntax._marks import Marks
from euinvoice.syntax.result import ParseResult
from euinvoice.syntax.ubl import _cursor as ubl_cursor

_XML_LANG: t.Final = "{http://www.w3.org/XML/1998/namespace}lang"

Writer = t.Callable[[], bytes]
Reader = t.Callable[[etree._Element], ParseResult]

READERS: t.Final[dict[str, tuple[Writer, Reader]]] = {
    "ubl": (lambda: ubl.write(minimal_invoice()), ubl.read),
    "cii": (lambda: cii.write(all_terms_invoice()), cii.read),
}
# The invoice line (BG-25) element of each syntax.
_LINES: t.Final = {
    "ubl": f"{{{_xml.UBL_CAC}}}InvoiceLine",
    "cii": f"{{{_xml.CII_RAM}}}IncludedSupplyChainTradeLineItem",
}


@pytest.mark.parametrize("syntax", list(READERS))
def test_xml_lang_is_reported_with_the_xml_prefix(syntax: str) -> None:
    write, read = READERS[syntax]
    root = _xml.parse(write())
    root.set(_XML_LANG, "en")
    result = read(_xml.parse(etree.tostring(root)))
    path = root.getroottree().getpath(root)
    assert result.unmapped == (f"{path}/@xml:lang",)


# XPaths without a getpath per element (#80). libxml2's xmlGetNodePath, behind lxml's getpath, scans every sibling
# at every level, so one call below the invoice root costs O(lines): a getpath per element made both readers
# quadratic in the number of lines.

_URI_A: t.Final = "urn:example:a"
_URI_B: t.Final = "urn:example:b"
# Default namespaces ("*" steps), prefixes, one prefix bound to two URIs, one URI under two prefixes, an undeclared
# URI (lxml invents a prefix) and no namespace at all.
_NSMAPS: t.Final[tuple[dict[str | None, str], ...]] = (
    {},
    {None: _URI_A},
    {None: _URI_B},
    {"a": _URI_A},
    {"a": _URI_B},
    {"b": _URI_A},
)
# The last name overflows libxml2's 100-byte step buffer once prefixed.
_LOCAL_NAMES: t.Final = ("x", "y", "z" * 120)

Spec = tuple[str | None, str, int, bool, list[t.Any]]


def _specs(children: st.SearchStrategy[list[Spec]]) -> st.SearchStrategy[Spec]:
    """An element: namespace, local name, ``nsmap`` index, comment before it, children."""
    return st.tuples(
        st.sampled_from((None, _URI_A, _URI_B)),
        st.sampled_from(_LOCAL_NAMES),
        st.integers(0, len(_NSMAPS) - 1),
        st.booleans(),
        children,
    )


_TREES: t.Final = st.recursive(_specs(st.just([])), lambda inner: _specs(st.lists(inner, max_size=5)), max_leaves=25)


def _build(spec: Spec, parent: etree._Element | None = None) -> etree._Element:
    """The element ``spec`` describes, with an attribute ``k`` (and a comment before it when flagged)."""
    namespace, local, nsmap, comment, children = spec
    tag = local if namespace is None else f"{{{namespace}}}{local}"
    if parent is None:
        element = etree.Element(tag, nsmap=_NSMAPS[nsmap])  # type: ignore[arg-type]  # lxml-stubs omit the None (default) prefix
    else:
        if comment:
            parent.append(etree.Comment("not an element"))
        element = etree.SubElement(parent, tag, nsmap=_NSMAPS[nsmap])  # type: ignore[arg-type]  # lxml-stubs omit the None (default) prefix
    element.set("k", "v")
    for child in children:
        _build(child, element)
    return element


def _getpath_unmapped(root: etree._Element, marked: set[etree._Element]) -> tuple[str, ...]:
    """The ``unmapped`` expected for ``marked``, every XPath from lxml's ``getpath`` (the oracle)."""
    tree = root.getroottree()
    found: list[str] = []

    def walk(element: etree._Element) -> None:
        found.append(f"{tree.getpath(element)}/@k")
        for child in element.iterchildren("*"):
            if child in marked:
                walk(child)
            else:
                found.append(tree.getpath(child))

    walk(root)
    return tuple(found)


@given(spec=_TREES)
def test_unmapped_xpaths_are_the_ones_getpath_writes(spec: Spec) -> None:
    root = _build(spec)
    marks = Marks(root)
    inner = {element for element in root.iter("*") if len(element)}  # leaves stay unmapped
    for element in inner:
        marks.mark(element)
    assert marks.unmapped() == _getpath_unmapped(root, inner | {root})


@pytest.mark.parametrize("syntax", list(READERS))
def test_reading_does_not_compute_an_xpath_per_element(syntax: str, monkeypatch: pytest.MonkeyPatch) -> None:
    write, read = READERS[syntax]
    root = _xml.parse(write())
    line = next(root.iter(_LINES[syntax]))
    etree.SubElement(line, f"{{{_URI_A}}}Unmapped", nsmap={"x": _URI_A})
    for _ in range(30):
        line.addnext(copy.deepcopy(line))
    root = _xml.parse(etree.tostring(root))
    calls: list[etree._Element] = []
    marks_path, cursor_path = Marks.path, ubl_cursor._path

    def count_marks(marks: Marks, element: etree._Element) -> str:
        calls.append(element)
        return marks_path(marks, element)

    def count_cursor(element: etree._Element) -> str:
        calls.append(element)
        return cursor_path(element)

    monkeypatch.setattr(Marks, "path", count_marks)
    monkeypatch.setattr(ubl_cursor, "_path", count_cursor)
    unmapped = read(root).unmapped
    assert len([path for path in unmapped if path.endswith("/x:Unmapped")]) == 31
    assert calls == [root]  # every other XPath is built from its parent's


def test_build_computes_the_error_location_only_on_failure() -> None:
    untouchable = t.cast(etree._Element, object())  # computing its XPath raises AttributeError
    built = read_errors.build(ItemAttribute, untouchable, {"name": "Colour", "value": "Blue"})
    assert built == ItemAttribute(name="Colour", value="Blue")
