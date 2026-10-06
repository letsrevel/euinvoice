"""CII-specific test invoices, built on the syntax-neutral ``tests/_invoices.py``."""

import datetime

from _invoices import full_invoice
from euinvoice.model import Invoice


def all_terms_invoice() -> Invoice:
    """The coverage base of the per-term table: :func:`_invoices.full_invoice` plus BT-7.

    BT-7 and BT-8 are mutually exclusive (BR-CO-03), so this invoice is not CEN-valid; it exists so that every
    business term CII can carry is written at least once.
    """
    return full_invoice(vat_point_date=datetime.date(2026, 1, 10))
