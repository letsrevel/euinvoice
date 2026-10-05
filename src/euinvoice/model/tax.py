"""EN 16931 VAT BREAKDOWN (BG-23), including the VAT exemption reason (BT-120, BT-121).

BT-116, BT-117 and BT-118 are mandatory (BR-45..BR-47). The rate BT-119 is optional in the model:
BR-48 requires it except for category ``O`` (not subject to VAT), a cross-field rule that
``calc.check`` and the Schematron enforce together with the per-category rules (BR-S-*, BR-Z-*, …).
"""

import typing as t

from euinvoice.model._base import EuInvoiceModel, bt
from euinvoice.model.amounts import Amount, Percentage
from euinvoice.model.datatypes import Text, VatCategoryCode, VatExemptionReasonCode

__all__ = ["VatBreakdown"]


class VatBreakdown(EuInvoiceModel):
    """VAT BREAKDOWN (BG-23)."""

    taxable_amount: t.Annotated[Amount, bt("BT-116")]
    """VAT category taxable amount (BR-45)."""
    tax_amount: t.Annotated[Amount, bt("BT-117")]
    """VAT category tax amount (BR-46)."""
    category_code: t.Annotated[VatCategoryCode, bt("BT-118")]
    """VAT category code, UNTDID 5305 (BR-47, BR-CL-17)."""
    rate: t.Annotated[Percentage | None, bt("BT-119")] = None
    """VAT category rate as a percentage, ``19`` for 19 % (BR-48, BR-S-09)."""
    exemption_reason: t.Annotated[Text | None, bt("BT-120")] = None
    """VAT exemption reason text."""
    exemption_reason_code: t.Annotated[VatExemptionReasonCode | None, bt("BT-121")] = None
    """VAT exemption reason code, CEF VATEX (BR-CL-22), stored upper-cased."""
