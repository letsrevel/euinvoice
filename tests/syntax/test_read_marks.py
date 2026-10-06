"""The unmapped bookkeeping shared by the UBL and the CII reader (``euinvoice.syntax._marks``)."""

import typing as t

import pytest
from _cii_invoices import all_terms_invoice
from lxml import etree

from _invoices import minimal_invoice
from euinvoice import _xml
from euinvoice.syntax import cii, ubl
from euinvoice.syntax.result import ParseResult

_XML_LANG: t.Final = "{http://www.w3.org/XML/1998/namespace}lang"

Writer = t.Callable[[], bytes]
Reader = t.Callable[[etree._Element], ParseResult]

READERS: t.Final[dict[str, tuple[Writer, Reader]]] = {
    "ubl": (lambda: ubl.write(minimal_invoice()), ubl.read),
    "cii": (lambda: cii.write(all_terms_invoice()), cii.read),
}


@pytest.mark.parametrize("syntax", list(READERS))
def test_xml_lang_is_reported_with_the_xml_prefix(syntax: str) -> None:
    write, read = READERS[syntax]
    root = _xml.parse(write())
    root.set(_XML_LANG, "en")
    result = read(_xml.parse(etree.tostring(root)))
    path = root.getroottree().getpath(root)
    assert result.unmapped == (f"{path}/@xml:lang",)
