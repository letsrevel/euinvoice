"""The shared Hypothesis invoices (``tests/_strategies.py``) made expressible in UBL, for the reader's round trip.

:func:`ubl_expressible` changes only what the UBL writer refuses or normalizes by design, each documented in
``docs/reference/bt-mapping.md`` and covered by its own example test in ``test_ubl_read.py``:

* refused (``ModelError``): BT-110 missing, BT-87 missing, a credit note's BT-9 without BG-16, BT-148 below BT-146,
  BT-111 without BT-6, BT-111 with BT-6 equal to BT-5 (two ``cac:TaxTotal`` in one currency, BR-CO-15);
* normalized ("Normalizations", "The UBL reader"): BT-148 without BT-147 (BT-147 derived), groups with no term set
  (BG-1, BG-13, BG-14, BG-19, BG-26 read back as absent), a BT-22 without BT-21 that starts like a ``#CODE#``
  pair, and a BT-13 "NA" next to a BT-14 (read back as the writer's placeholder, i.e. no BT-13).
"""

import re
import typing as t

from _strategies import invoices
from euinvoice.model import (
    DeliveryInformation,
    DirectDebit,
    Invoice,
    InvoiceLine,
    InvoiceLinePeriod,
    InvoicingPeriod,
    PriceDetails,
)
from euinvoice.syntax.ubl._write import is_credit_note

_LEADING_CODE: t.Final = re.compile(r"#...#", re.S)


def _price(price: PriceDetails) -> PriceDetails:
    gross = price.item_gross_price
    if gross is not None and gross < price.item_net_price:
        gross = None  # a negative BT-147 is a price charge, refused (PEPPOL-EN16931-R044)
    discount = price.item_price_discount
    if gross is not None:
        discount = gross - price.item_net_price  # the writer's BT-147 (PEPPOL-EN16931-R046)
    return PriceDetails.model_validate({**dict(price), "item_gross_price": gross, "item_price_discount": discount})


def _line(line: InvoiceLine) -> InvoiceLine:
    period = None if line.period == InvoiceLinePeriod() else line.period
    return InvoiceLine.model_validate({**dict(line), "period": period, "price_details": _price(line.price_details)})


def _delivery(delivery: DeliveryInformation | None) -> DeliveryInformation | None:
    if delivery is None:
        return None
    period = None if delivery.invoicing_period == InvoicingPeriod() else delivery.invoicing_period
    delivery = DeliveryInformation.model_validate({**dict(delivery), "invoicing_period": period})
    return None if delivery == DeliveryInformation() else delivery


def ubl_expressible(invoice: Invoice) -> Invoice:
    """``invoice`` with the UBL writer's refusals and normalizations (module docstring) taken out."""
    instructions = invoice.payment_instructions
    if instructions is not None:
        card = instructions.payment_card
        if card is not None and card.primary_account_number is None:
            card = None
        debit = None if instructions.direct_debit == DirectDebit() else instructions.direct_debit
        instructions = instructions.model_validate({**dict(instructions), "payment_card": card, "direct_debit": debit})
    due_date = invoice.payment_due_date
    if is_credit_note(invoice.type_code) and instructions is None:
        due_date = None
    totals = invoice.totals
    if totals.total_vat is None:
        totals = totals.model_validate({**dict(totals), "total_vat": totals.total_without_vat})
    accounting = invoice.vat_accounting_currency_code
    if accounting is None or accounting == invoice.currency_code:
        totals = totals.model_validate({**dict(totals), "total_vat_in_accounting_currency": None})
    purchase_order = invoice.purchase_order_reference
    if purchase_order == "NA" and invoice.sales_order_reference is not None:
        purchase_order = None
    notes = tuple(
        note
        for note in invoice.notes
        if (note.note or note.subject_code) and not (note.subject_code is None and _LEADING_CODE.match(note.note or ""))
    )
    return Invoice.model_validate(
        {
            **dict(invoice),
            "payment_instructions": instructions,
            "payment_due_date": due_date,
            "totals": totals,
            "notes": notes,
            "purchase_order_reference": purchase_order,
            "delivery": _delivery(invoice.delivery),
            "lines": tuple(_line(line) for line in invoice.lines),
        }
    )


ubl_invoices: t.Final = invoices.map(ubl_expressible)
"""Random invoices and credit notes the UBL writer accepts and the reader must give back unchanged."""
