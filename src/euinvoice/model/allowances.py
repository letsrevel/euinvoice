"""EN 16931 allowances and charges: document level BG-20 / BG-21, invoice line level BG-27 / BG-28.

Each needs an amount (BR-31, BR-36, BR-41, BR-43) and a reason or a reason code or both (BR-33,
BR-38, BR-42, BR-44, all ``fatal`` in UBL and CII). Document level ones also need a VAT category
(BR-32, BR-37). That BT-97/BT-98 (and the other reason pairs) "indicate the same type" (BR-CO-05..08)
is a business rule left to the official Schematron (D8).
"""

import typing as t

import pydantic

from euinvoice.errors import ModelError
from euinvoice.model._base import EuInvoiceModel, bt
from euinvoice.model.amounts import Amount, Percentage
from euinvoice.model.datatypes import AllowanceReasonCode, ChargeReasonCode, Text, VatCategoryCode

__all__ = ["DocumentLevelAllowance", "DocumentLevelCharge", "InvoiceLineAllowance", "InvoiceLineCharge"]


class _NeedsReason(EuInvoiceModel):
    """Shared check of the subclasses' ``reason`` / ``reason_code`` fields: one must be present."""

    _reason_rule: t.ClassVar[str]

    @pydantic.model_validator(mode="after")
    def _check_reason(self) -> t.Self:
        if getattr(self, "reason") is None and getattr(self, "reason_code") is None:  # ruff: ignore[get-attr-with-constant]
            raise ModelError(f"a reason or a reason code is required ({self._reason_rule})")
        return self


class DocumentLevelAllowance(_NeedsReason):
    """DOCUMENT LEVEL ALLOWANCES (BG-20)."""

    _reason_rule = "BR-33"

    amount: t.Annotated[Amount, bt("BT-92")]
    """Document level allowance amount (BR-31)."""
    base_amount: t.Annotated[Amount | None, bt("BT-93")] = None
    """Document level allowance base amount."""
    percentage: t.Annotated[Percentage | None, bt("BT-94")] = None
    """Document level allowance percentage."""
    vat_category_code: t.Annotated[VatCategoryCode, bt("BT-95")]
    """Document level allowance VAT category code (BR-32)."""
    vat_rate: t.Annotated[Percentage | None, bt("BT-96")] = None
    """Document level allowance VAT rate."""
    reason: t.Annotated[Text | None, bt("BT-97")] = None
    """Document level allowance reason."""
    reason_code: t.Annotated[AllowanceReasonCode | None, bt("BT-98")] = None
    """Document level allowance reason code, UNTDID 5189 (BR-CL-19)."""


class DocumentLevelCharge(_NeedsReason):
    """DOCUMENT LEVEL CHARGES (BG-21)."""

    _reason_rule = "BR-38"

    amount: t.Annotated[Amount, bt("BT-99")]
    """Document level charge amount (BR-36)."""
    base_amount: t.Annotated[Amount | None, bt("BT-100")] = None
    """Document level charge base amount."""
    percentage: t.Annotated[Percentage | None, bt("BT-101")] = None
    """Document level charge percentage."""
    vat_category_code: t.Annotated[VatCategoryCode, bt("BT-102")]
    """Document level charge VAT category code (BR-37)."""
    vat_rate: t.Annotated[Percentage | None, bt("BT-103")] = None
    """Document level charge VAT rate."""
    reason: t.Annotated[Text | None, bt("BT-104")] = None
    """Document level charge reason."""
    reason_code: t.Annotated[ChargeReasonCode | None, bt("BT-105")] = None
    """Document level charge reason code, UNTDID 7161 (BR-CL-20)."""


class InvoiceLineAllowance(_NeedsReason):
    """INVOICE LINE ALLOWANCES (BG-27)."""

    _reason_rule = "BR-42"

    amount: t.Annotated[Amount, bt("BT-136")]
    """Invoice line allowance amount (BR-41)."""
    base_amount: t.Annotated[Amount | None, bt("BT-137")] = None
    """Invoice line allowance base amount."""
    percentage: t.Annotated[Percentage | None, bt("BT-138")] = None
    """Invoice line allowance percentage."""
    reason: t.Annotated[Text | None, bt("BT-139")] = None
    """Invoice line allowance reason."""
    reason_code: t.Annotated[AllowanceReasonCode | None, bt("BT-140")] = None
    """Invoice line allowance reason code, UNTDID 5189 (BR-CL-19)."""


class InvoiceLineCharge(_NeedsReason):
    """INVOICE LINE CHARGES (BG-28)."""

    _reason_rule = "BR-44"

    amount: t.Annotated[Amount, bt("BT-141")]
    """Invoice line charge amount (BR-43)."""
    base_amount: t.Annotated[Amount | None, bt("BT-142")] = None
    """Invoice line charge base amount."""
    percentage: t.Annotated[Percentage | None, bt("BT-143")] = None
    """Invoice line charge percentage."""
    reason: t.Annotated[Text | None, bt("BT-144")] = None
    """Invoice line charge reason."""
    reason_code: t.Annotated[ChargeReasonCode | None, bt("BT-145")] = None
    """Invoice line charge reason code, UNTDID 7161 (BR-CL-20)."""
