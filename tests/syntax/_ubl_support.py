"""UBL-only helpers for the UBL writer tests; the invoices come from the syntax-neutral ``tests/_invoices.py``."""

import typing as t

from lxml import etree

from euinvoice import _xml
from euinvoice.model import Invoice
from euinvoice.syntax import ubl


def written(document: Invoice) -> etree._Element:
    """Write ``document`` and parse the output back with the hardened parser."""
    return _xml.parse(ubl.write(document))


def xpath(root: etree._Element, path: str) -> t.Any:
    """Evaluate ``path`` with the ``cac`` / ``cbc`` prefixes."""
    return root.xpath(path, namespaces=_xml.UBL_NSMAP)
