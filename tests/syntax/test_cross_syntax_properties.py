"""Property: the terms :data:`_strategies.invoices` generates survive UBL → model → CII → model → UBL → model (#30).

The invoices are the shared random :data:`_strategies.invoices`, mapped onto what both writers accept and give back
unchanged: :func:`_strategies.cii_expressible`, :func:`_strategies.cii_normalized` and
:func:`_ubl_strategies.ubl_expressible` take out exactly the refusals and normalizations that
``docs/reference/bt-mapping.md`` documents for each syntax. Every leg of the cross-syntax round trip must then be
exact, with nothing unmapped. The strategy draws every model field (``tests/test_strategies.py``, #89), so a mapper
that drops a term fails here. The corpus half, which reaches the term combinations the upstream samples carry, is
``tests/conformance/test_cross_syntax.py``.
"""

from _ubl_strategies import ubl_expressible
from hypothesis import assume, given, settings

from _strategies import cii_expressible, cii_normalized, invoices
from euinvoice import _xml
from euinvoice.model import Invoice
from euinvoice.syntax import cii, ubl
from euinvoice.syntax.result import ParseResult


def _both_expressible(invoice: Invoice) -> Invoice:
    return ubl_expressible(cii_normalized(cii_expressible(invoice)))


@settings(max_examples=60)
@given(invoices.map(_both_expressible))
def test_ubl_cii_ubl_round_trip_is_exact(invoice: Invoice) -> None:
    # A fixed point of both mappings; the composition reaches one for nearly every draw.
    assume(cii_normalized(invoice) == invoice and ubl_expressible(invoice) == invoice)
    from_ubl = ubl.read(_xml.parse(ubl.write(invoice)))
    assert from_ubl == ParseResult(invoice=invoice)
    from_cii = cii.read(_xml.parse(cii.write(from_ubl.invoice)))
    assert from_cii == ParseResult(invoice=invoice)
    assert ubl.read(_xml.parse(ubl.write(from_cii.invoice))) == ParseResult(invoice=invoice)
