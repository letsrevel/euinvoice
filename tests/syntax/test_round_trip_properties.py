"""Property: invoices built through ``calc.complete`` pass ``calc.check`` and round-trip exactly (issue #31).

The invoices come from :func:`_property_drafts.invoices`, which avoids every writer normalization listed in
``docs/reference/bt-mapping.md``, so ``read(write(x))`` must return ``x`` itself with nothing unmapped. The
official-rule half of the property (XSD and Schematron) is ``tests/conformance/test_property_conformance.py``.
"""

import typing as t
from collections.abc import Callable

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from lxml import etree

from _property_drafts import TARGETS, Target, invoices
from euinvoice import _xml, calc
from euinvoice.model import Invoice
from euinvoice.syntax import Syntax, cii, ubl
from euinvoice.syntax.result import ParseResult

EACH_TARGET = pytest.mark.parametrize("target", TARGETS, ids=lambda target: target.profile.id)
CODECS: t.Final[dict[Syntax, tuple[Callable[[Invoice], bytes], Callable[[etree._Element], ParseResult]]]] = {
    Syntax.UBL: (ubl.write, ubl.read),
    Syntax.CII: (cii.write, cii.read),
}
_SETTINGS = settings(max_examples=50)  # deadline and health checks: the profiles in tests/conftest.py


@EACH_TARGET
@_SETTINGS
@given(data=st.data())
def test_completed_invoices_pass_check_in_both_syntaxes(target: Target, data: st.DataObject) -> None:
    invoice = data.draw(invoices(target))
    assert calc.check(invoice, syntax=Syntax.UBL) == ()
    assert calc.check(invoice, syntax=Syntax.CII) == ()
    ubl.write(invoice)  # raises ModelError for what UBL cannot express


@pytest.mark.parametrize("syntax", list(CODECS))
@EACH_TARGET
@_SETTINGS
@given(data=st.data())
def test_round_trip_is_exact(syntax: Syntax, target: Target, data: st.DataObject) -> None:
    invoice: Invoice = data.draw(invoices(target))
    write, read = CODECS[syntax]
    result = read(_xml.parse(write(invoice)))
    assert result.unmapped == ()
    assert result.invoice == invoice
