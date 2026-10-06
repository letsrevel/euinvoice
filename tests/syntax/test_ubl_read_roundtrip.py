"""Property: the UBL reader gives back every invoice the UBL writer wrote (plan §7, ``read(write(inv)) == inv``)."""

from _ubl_strategies import ubl_invoices
from hypothesis import given

from _invoices import minimal_invoice, rebuild
from euinvoice import _xml
from euinvoice.model import BuyerContact, Invoice, SellerContact
from euinvoice.syntax import ubl


@given(ubl_invoices)
def test_read_inverts_write(invoice: Invoice) -> None:
    assert ubl.read(_xml.parse(ubl.write(invoice))) == ubl.ParseResult(invoice=invoice)


def test_empty_contacts_round_trip() -> None:
    # Issue #30: an empty BG-6 / BG-9 (the CII reader builds one from an empty ram:DefinedTradeContact, as in CEN
    # CII_business_example_02.xml) is written as an empty cac:Contact and read back as that group: the element is
    # mapped, so it is not listed in unmapped.
    invoice = minimal_invoice()
    invoice = rebuild(
        invoice,
        seller=invoice.seller.model_copy(update={"contact": SellerContact()}),
        buyer=invoice.buyer.model_copy(update={"contact": BuyerContact()}),
    )
    assert ubl.read(_xml.parse(ubl.write(invoice))) == ubl.ParseResult(invoice=invoice)
