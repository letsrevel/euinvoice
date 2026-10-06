"""Property: the UBL reader gives back every invoice the UBL writer wrote (plan §7, ``read(write(inv)) == inv``)."""

from _ubl_strategies import ubl_invoices
from hypothesis import given

from euinvoice import _xml
from euinvoice.model import Invoice
from euinvoice.syntax import ubl


@given(ubl_invoices)
def test_read_inverts_write(invoice: Invoice) -> None:
    assert ubl.read(_xml.parse(ubl.write(invoice))) == ubl.ParseResult(invoice=invoice)
