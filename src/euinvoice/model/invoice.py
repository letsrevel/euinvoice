"""The EN 16931 invoice root (BG-0) with its header terms and the groups BG-1, BG-2 and BG-3.

One model serves invoices and credit notes alike (D4): the invoice type code BT-3 tells them apart.
EN 16931-1 gives the root no identifier (XRechnung 3.0.2 spec §11.1); ``BG-0`` is this library's
name for it.
"""

import typing as t

from euinvoice.model._base import EuInvoiceModel, bt
from euinvoice.model.allowances import DocumentLevelAllowance, DocumentLevelCharge
from euinvoice.model.datatypes import (
    OBJECT_SCHEME,
    CurrencyCode,
    Date,
    DocumentTypeCode,
    Identifier,
    NonBlankText,
    Text,
    TextSubjectCode,
    VatPointDateCode,
    at_least_one,
)
from euinvoice.model.delivery import DeliveryInformation
from euinvoice.model.documents import AdditionalSupportingDocument
from euinvoice.model.lines import InvoiceLine, LineDraft
from euinvoice.model.parties import Buyer, Payee, Seller, SellerTaxRepresentative
from euinvoice.model.payment import PaymentInstructions
from euinvoice.model.tax import VatBreakdown
from euinvoice.model.totals import DocumentTotals

__all__ = ["ROOT_ID", "Invoice", "InvoiceDraft", "InvoiceNote", "PrecedingInvoiceReference", "ProcessControl"]

ROOT_ID: t.Final = "BG-0"
"""The id this library gives the unnamed EN 16931 root, i.e. :class:`Invoice` itself."""


class InvoiceNote(EuInvoiceModel):
    """INVOICE NOTE (BG-1).

    The note text is optional here although the XRechnung and Peppol tables give it cardinality 1:
    no CEN rule requires it and the CII XSD allows a note with a subject code only (see "Open
    questions" in ``docs/reference/bt-mapping.md``).
    """

    subject_code: t.Annotated[TextSubjectCode | None, bt("BT-21")] = None
    """Invoice note subject code, UNTDID 4451 (BR-CL-08)."""
    note: t.Annotated[Text | None, bt("BT-22")] = None
    """Invoice note."""


class ProcessControl(EuInvoiceModel):
    """PROCESS CONTROL (BG-2). Always present because BT-24 is mandatory (BR-01)."""

    business_process_type: t.Annotated[Text | None, bt("BT-23")] = None
    """Business process type (Peppol and XRechnung require it; EN 16931 does not)."""
    specification_identifier: t.Annotated[NonBlankText, bt("BT-24")]
    """Specification identifier, e.g. ``urn:cen.eu:en16931:2017`` (BR-01)."""


class PrecedingInvoiceReference(EuInvoiceModel):
    """PRECEDING INVOICE REFERENCE (BG-3)."""

    reference: t.Annotated[Text, bt("BT-25")]
    """Preceding Invoice reference (BR-55)."""
    issue_date: t.Annotated[Date | None, bt("BT-26")] = None
    """Preceding Invoice issue date."""


class _InvoiceBody(EuInvoiceModel):
    """The fields the invoice shares with its draft: everything except BG-22, BG-23 and BG-25.

    Fields follow the order of EN 16931-1 as restated in the XRechnung 3.0.2 specification §11.1.
    """

    number: t.Annotated[NonBlankText, bt("BT-1")]
    """Invoice number (BR-02)."""
    issue_date: t.Annotated[Date, bt("BT-2")]
    """Invoice issue date (BR-03)."""
    type_code: t.Annotated[DocumentTypeCode, bt("BT-3")]
    """Invoice type code, UNTDID 1001 (BR-04, BR-CL-01), e.g. ``"380"`` or ``"381"``."""
    currency_code: t.Annotated[CurrencyCode, bt("BT-5")]
    """Invoice currency code, ISO 4217 (BR-05, BR-CL-04)."""
    vat_accounting_currency_code: t.Annotated[CurrencyCode | None, bt("BT-6")] = None
    """VAT accounting currency code, ISO 4217 (BR-CL-05)."""
    vat_point_date: t.Annotated[Date | None, bt("BT-7")] = None
    """Value added tax point date."""
    vat_point_date_code: t.Annotated[VatPointDateCode | None, bt("BT-8")] = None
    """Value added tax point date code, UNTDID 2005 (BR-CL-06)."""
    payment_due_date: t.Annotated[Date | None, bt("BT-9")] = None
    """Payment due date."""
    buyer_reference: t.Annotated[Text | None, bt("BT-10")] = None
    """Buyer reference (XRechnung requires it, BR-DE-15; EN 16931 does not)."""
    project_reference: t.Annotated[Text | None, bt("BT-11")] = None
    """Project reference."""
    contract_reference: t.Annotated[Text | None, bt("BT-12")] = None
    """Contract reference."""
    purchase_order_reference: t.Annotated[Text | None, bt("BT-13")] = None
    """Purchase order reference."""
    sales_order_reference: t.Annotated[Text | None, bt("BT-14")] = None
    """Sales order reference."""
    receiving_advice_reference: t.Annotated[Text | None, bt("BT-15")] = None
    """Receiving advice reference."""
    despatch_advice_reference: t.Annotated[Text | None, bt("BT-16")] = None
    """Despatch advice reference."""
    tender_or_lot_reference: t.Annotated[Text | None, bt("BT-17")] = None
    """Tender or lot reference."""
    invoiced_object_identifier: t.Annotated[t.Annotated[Identifier, OBJECT_SCHEME] | None, bt("BT-18")] = None
    """Invoiced object identifier, scheme from UNTDID 1153 (BR-CL-07)."""
    buyer_accounting_reference: t.Annotated[Text | None, bt("BT-19")] = None
    """Buyer accounting reference."""
    payment_terms: t.Annotated[Text | None, bt("BT-20")] = None
    """Payment terms."""
    notes: t.Annotated[tuple[InvoiceNote, ...], bt("BG-1")] = ()
    """INVOICE NOTE (0..n)."""
    process_control: t.Annotated[ProcessControl, bt("BG-2")]
    """PROCESS CONTROL."""
    preceding_invoice_references: t.Annotated[tuple[PrecedingInvoiceReference, ...], bt("BG-3")] = ()
    """PRECEDING INVOICE REFERENCE (0..n)."""
    seller: t.Annotated[Seller, bt("BG-4")]
    """SELLER (BR-06, BR-08)."""
    buyer: t.Annotated[Buyer, bt("BG-7")]
    """BUYER (BR-07, BR-10)."""
    payee: t.Annotated[Payee | None, bt("BG-10")] = None
    """PAYEE."""
    seller_tax_representative: t.Annotated[SellerTaxRepresentative | None, bt("BG-11")] = None
    """SELLER TAX REPRESENTATIVE PARTY."""
    delivery: t.Annotated[DeliveryInformation | None, bt("BG-13")] = None
    """DELIVERY INFORMATION, including the INVOICING PERIOD (BG-14)."""
    payment_instructions: t.Annotated[PaymentInstructions | None, bt("BG-16")] = None
    """PAYMENT INSTRUCTIONS (XRechnung requires it, BR-DE-1; EN 16931 does not)."""
    allowances: t.Annotated[tuple[DocumentLevelAllowance, ...], bt("BG-20")] = ()
    """DOCUMENT LEVEL ALLOWANCES (0..n)."""
    charges: t.Annotated[tuple[DocumentLevelCharge, ...], bt("BG-21")] = ()
    """DOCUMENT LEVEL CHARGES (0..n)."""
    additional_supporting_documents: t.Annotated[tuple[AdditionalSupportingDocument, ...], bt("BG-24")] = ()
    """ADDITIONAL SUPPORTING DOCUMENTS (0..n)."""


class Invoice(_InvoiceBody):
    """An EN 16931 invoice or credit note (the root, ``BG-0``).

    Every field carries its BT/BG id (see :mod:`euinvoice.model.bt_index`). Build an invoice with the
    constructor or ``model_validate``: pydantic's ``model_copy(update=...)`` does **not** validate the
    updated values.
    """

    totals: t.Annotated[DocumentTotals, bt("BG-22")]
    """DOCUMENT TOTALS. Required: the UBL 2.1 XSD has ``cac:LegalMonetaryTotal`` minOccurs=1
    (``UBL-Invoice-2.1.xsd``), and in CII the CEN rule BR-CO-15 (fatal, invoice context) fails without
    it."""
    vat_breakdown: t.Annotated[tuple[VatBreakdown, ...], at_least_one("BR-CO-18"), bt("BG-23")]
    """VAT BREAKDOWN (1..n, BR-CO-18)."""
    lines: t.Annotated[tuple[InvoiceLine, ...], at_least_one("BR-16"), bt("BG-25")]
    """INVOICE LINE (1..n, BR-16)."""


class InvoiceDraft(_InvoiceBody):
    """An invoice without its derived totals (BG-22) and VAT breakdown (BG-23), the input of ``calc``.

    It has every field of :class:`Invoice` except ``totals`` and ``vat_breakdown``, with the same types
    and checks; its lines are :class:`LineDraft` (no BT-131).
    """

    lines: t.Annotated[tuple[LineDraft, ...], at_least_one("BR-16"), bt("BG-25")]
    """INVOICE LINE drafts (1..n, BR-16)."""
