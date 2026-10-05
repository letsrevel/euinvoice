"""EN 16931 PAYMENT INSTRUCTIONS (BG-16) with its groups BG-17, BG-18 and BG-19.

BG-16 occurs at most once and holds 0..n credit transfers, at most one card and at most one direct
debit (XRechnung 3.0.2 spec §11.6, §11.9, §11.23, §11.24). UBL repeats ``cac:PaymentMeans`` per
account, which is why its syntax rules demand one payment means code across them (UBL-SR-47), one
card (UBL-SR-54) and one mandate (UBL-SR-55).
"""

import typing as t

from euinvoice.model._base import EuInvoiceModel, bt
from euinvoice.model.datatypes import NonBlankText, PaymentMeansCode, Text

__all__ = ["CreditTransfer", "DirectDebit", "PaymentCardInformation", "PaymentInstructions"]


class CreditTransfer(EuInvoiceModel):
    """CREDIT TRANSFER (BG-17)."""

    payment_account_identifier: t.Annotated[NonBlankText, bt("BT-84")]
    """Payment account identifier, e.g. an IBAN (BR-50)."""
    payment_account_name: t.Annotated[Text | None, bt("BT-85")] = None
    """Payment account name."""
    payment_service_provider_identifier: t.Annotated[Text | None, bt("BT-86")] = None
    """Payment service provider identifier, e.g. a BIC."""


class PaymentCardInformation(EuInvoiceModel):
    """PAYMENT CARD INFORMATION (BG-18).

    The primary account number is optional here although the XRechnung and Peppol tables give it
    cardinality 1: no CEN rule requires it and the CII XSD makes it optional (see "Open questions" in
    ``docs/reference/bt-mapping.md``). BR-51 (at most the first 6 and last 4 digits) is a warning in UBL
    and is left to the Schematron.
    """

    primary_account_number: t.Annotated[Text | None, bt("BT-87")] = None
    """Payment card primary account number (masked, BR-51)."""
    holder_name: t.Annotated[Text | None, bt("BT-88")] = None
    """Payment card holder name."""


class DirectDebit(EuInvoiceModel):
    """DIRECT DEBIT (BG-19). Every term is optional in EN 16931 (XRechnung adds BR-DE-29/30/31)."""

    mandate_reference_identifier: t.Annotated[Text | None, bt("BT-89")] = None
    """Mandate reference identifier."""
    bank_assigned_creditor_identifier: t.Annotated[Text | None, bt("BT-90")] = None
    """Bank assigned creditor identifier."""
    debited_account_identifier: t.Annotated[Text | None, bt("BT-91")] = None
    """Debited account identifier."""


class PaymentInstructions(EuInvoiceModel):
    """PAYMENT INSTRUCTIONS (BG-16)."""

    payment_means_type_code: t.Annotated[PaymentMeansCode, bt("BT-81")]
    """Payment means type code, UNTDID 4461 (BR-49, BR-CL-16)."""
    payment_means_text: t.Annotated[Text | None, bt("BT-82")] = None
    """Payment means text."""
    remittance_information: t.Annotated[Text | None, bt("BT-83")] = None
    """Remittance information."""
    credit_transfers: t.Annotated[tuple[CreditTransfer, ...], bt("BG-17")] = ()
    """CREDIT TRANSFER (0..n)."""
    payment_card: t.Annotated[PaymentCardInformation | None, bt("BG-18")] = None
    """PAYMENT CARD INFORMATION."""
    direct_debit: t.Annotated[DirectDebit | None, bt("BG-19")] = None
    """DIRECT DEBIT."""
