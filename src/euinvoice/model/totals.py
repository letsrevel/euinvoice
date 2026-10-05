"""EN 16931 DOCUMENT TOTALS (BG-22).

BT-106, BT-109, BT-112 and BT-115 are mandatory (BR-12..BR-15). The arithmetic between the totals
(BR-CO-10..BR-CO-16) is checked and derived by ``calc``, not here.
"""

import typing as t

from euinvoice.model._base import EuInvoiceModel, bt
from euinvoice.model.amounts import Amount

__all__ = ["DocumentTotals"]


class DocumentTotals(EuInvoiceModel):
    """DOCUMENT TOTALS (BG-22). All amounts are in the invoice currency (BT-5) except BT-111."""

    sum_of_line_net_amounts: t.Annotated[Amount, bt("BT-106")]
    """Sum of Invoice line net amount (BR-12)."""
    sum_of_allowances: t.Annotated[Amount | None, bt("BT-107")] = None
    """Sum of allowances on document level."""
    sum_of_charges: t.Annotated[Amount | None, bt("BT-108")] = None
    """Sum of charges on document level."""
    total_without_vat: t.Annotated[Amount, bt("BT-109")]
    """Invoice total amount without VAT (BR-13)."""
    total_vat: t.Annotated[Amount | None, bt("BT-110")] = None
    """Invoice total VAT amount."""
    total_vat_in_accounting_currency: t.Annotated[Amount | None, bt("BT-111")] = None
    """Invoice total VAT amount in accounting currency (BT-6); required with BT-6 (BR-53, checked by
    ``calc.check``)."""
    total_with_vat: t.Annotated[Amount, bt("BT-112")]
    """Invoice total amount with VAT (BR-14)."""
    paid_amount: t.Annotated[Amount | None, bt("BT-113")] = None
    """Paid amount."""
    rounding_amount: t.Annotated[Amount | None, bt("BT-114")] = None
    """Rounding amount."""
    amount_due: t.Annotated[Amount, bt("BT-115")]
    """Amount due for payment (BR-15)."""
