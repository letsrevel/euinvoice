"""The UBL 2.1 writer: :class:`euinvoice.model.Invoice` to ``Invoice`` or ``CreditNote`` bytes.

Document-level element order follows ``InvoiceType`` (``maindoc/UBL-Invoice-2.1.xsd``) or
``CreditNoteType`` (``maindoc/UBL-CreditNote-2.1.xsd``). The two differ where this writer cares:

* ``CreditNote`` has no ``cbc:DueDate``: BT-9 is ``cac:PaymentMeans/cbc:PaymentDueDate`` (Peppol upstream
  structure docs, peppol-bis-invoice-3 commit 806866b, not a pinned artifact:
  ``structure/syntax/ubl-creditnote.xml``; KoSIT xrechnung-visualization ``ubl-creditnote-xr.xsl``);
* ``CreditNote`` writes ``cbc:TaxPointDate`` before ``cbc:CreditNoteTypeCode``, ``Invoice`` after the notes;
* ``CreditNote`` has no ``cac:ProjectReference``: BT-11 is ``cac:AdditionalDocumentReference`` with
  ``cbc:DocumentTypeCode`` 50 (same two sources; CEN UBL-SR-43 allows 50 only in a ``CreditNote``);
* ``cac:OriginatorDocumentReference`` (BT-17) comes before the contract reference in ``Invoice`` and after
  the additional document references in ``CreditNote``.
"""

import base64
import typing as t
from decimal import Decimal

from lxml import etree

from euinvoice import _xml
from euinvoice.model import AdditionalSupportingDocument, Invoice, InvoiceNote, PaymentInstructions
from euinvoice.model._base import extension_paths
from euinvoice.model.codes import UNTDID_1001_CREDIT_NOTE_TYPE_UBL
from euinvoice.syntax.ubl._build import (
    Context,
    aggregate,
    amount,
    basic,
    cannot_express,
    date,
    identifier,
    tax_category,
)
from euinvoice.syntax.ubl._lines import OBJECT_DOCUMENT_TYPE, AllowanceOrCharge, write_allowance_charge, write_line
from euinvoice.syntax.ubl._parties import write_delivery, write_parties

__all__ = ["CARD_NETWORK_ID", "MISSING_ORDER_REFERENCE", "PROJECT_DOCUMENT_TYPE", "is_credit_note", "write"]

PROJECT_DOCUMENT_TYPE: t.Final = "50"
"""``cbc:DocumentTypeCode`` of the project reference BT-11 in a credit note (see the module docstring)."""

MISSING_ORDER_REFERENCE: t.Final = "NA"
"""``cac:OrderReference/cbc:ID`` written when only the sales order reference BT-14 is known.

``cbc:ID`` is mandatory in ``OrderReferenceType`` (UBL 2.1 XSD). Peppol upstream structure docs
(peppol-bis-invoice-3 commit 806866b, not a pinned artifact), ``structure/syntax/ubl-invoice.xml``
(BT-13): "In cases where sales order reference is provided, but there's no purchase order reference,
then use value 'NA' as this element is mandatory in UBL"."""

CARD_NETWORK_ID: t.Final = "NA"
"""``cac:CardAccount/cbc:NetworkID``, bound to no business term (bt-mapping.md note N2).

Pinned evidence: ``CardAccountType`` has ``cbc:NetworkID`` minOccurs=1 maxOccurs=1
(``common/UBL-CommonAggregateComponents-2.1.xsd``), and the CEN rules only restrict it by UBL-CR-675
(``UBL/EN16931-UBL-syntax.sch``: no ``@schemeID``, which is not written). The value comes from the
Peppol upstream structure docs (peppol-bis-invoice-3 commit 806866b, not a pinned artifact),
``structure/syntax/part/card-payment.xml``: "Syntax required element not related to a business term",
example value ``NA``."""


def is_credit_note(type_code: str) -> bool:
    """Tell whether an invoice type code (BT-3) is written with the ``CreditNote`` root (D4).

    CEN BR-CL-01 splits UNTDID 1001 into the ``cbc:InvoiceTypeCode`` and ``cbc:CreditNoteTypeCode`` lists
    (generated as ``UNTDID_1001_*_UBL``). They overlap only on 81, which goes to ``CreditNote`` because
    Peppol accepts it only there (P0101 lists 81, P0100 does not; issue #10). A UBL ``Invoice`` with code
    81 therefore reads back and is written again as a ``CreditNote``.

    Args:
        type_code: The invoice type code.

    Returns:
        ``True`` for the credit note list, ``False`` otherwise.
    """
    return type_code in UNTDID_1001_CREDIT_NOTE_TYPE_UBL


def write(invoice: Invoice) -> bytes:
    """Serialize an invoice as a UBL 2.1 ``Invoice`` or ``CreditNote`` (chosen by BT-3, see :func:`is_credit_note`).

    Every business term of the model is written where the CEN UBL binding expects it
    (``docs/reference/bt-mapping.md``), in UBL 2.1 XSD order, with ``currencyID`` = BT-5 on every amount
    except BT-111 (BT-6). The specification identifier BT-24 and business process BT-23 are written
    exactly as they are in the model. Business rules are not checked here: validate the output.

    Args:
        invoice: The invoice.

    Returns:
        The UTF-8 encoded document with an XML declaration.

    Raises:
        ModelError: The invoice holds something UBL cannot express: BT-87 or the BT-125 mime code or
            filename missing (decisions M2, M3 in bt-mapping.md), BT-110 missing with VAT, BT-111 without BT-6,
            BT-6 equal to BT-5, BT-9 in a credit note without PAYMENT INSTRUCTIONS (BG-16), BT-148 below
            BT-146, or BT-150 without BT-149. The message starts with the BT id. Also a set national extension
            (``it``, ``lines[i].it``), which only its national syntax carries (D3 as amended); the message starts
            with its path.
    """
    _refuse_extensions(invoice)
    credit_note = is_credit_note(invoice.type_code)
    namespace = _xml.UBL_CREDIT_NOTE if credit_note else _xml.UBL_INVOICE
    nsmap = {None: namespace, "cac": _xml.UBL_CAC, "cbc": _xml.UBL_CBC}
    tag = f"{{{namespace}}}{'CreditNote' if credit_note else 'Invoice'}"
    root = etree.Element(tag, nsmap=nsmap)  # type: ignore[arg-type]  # lxml-stubs omit the None (default) prefix
    context = Context(credit_note=credit_note, currency=invoice.currency_code)
    _header(root, invoice, credit_note)
    _references(root, invoice, credit_note)
    write_parties(root, invoice)
    write_delivery(root, invoice)
    _payment_means(root, invoice, credit_note)
    if invoice.payment_terms is not None:
        basic(aggregate(root, "PaymentTerms"), "Note", invoice.payment_terms)
    entries: tuple[AllowanceOrCharge, ...] = (*invoice.allowances, *invoice.charges)
    for entry in entries:
        write_allowance_charge(root, entry, invoice.currency_code)
    _tax_totals(root, invoice)
    _monetary_total(root, invoice)
    for line in invoice.lines:
        write_line(root, line, context)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _refuse_extensions(invoice: Invoice) -> None:
    """Refuse national extension data instead of dropping it silently (D3 as amended, plan §1)."""
    if extensions := extension_paths(invoice):
        raise cannot_express(
            ", ".join(extensions),
            "national extension data (e.g. FatturaPA data in Invoice.it, D3) has no place in UBL 2.1; it is written "
            "only in its national syntax. To write the EN 16931 content alone, pass the invoice through "
            "euinvoice.model.without_extensions() first",
        )


def _note_text(note: InvoiceNote) -> str | None:
    """BT-21 is the text between a leading ``#…#`` of ``cbc:Note`` (CEN UBL BR-CL-08, issue #10).

    A note with neither BT-21 nor BT-22 text writes nothing: an empty ``cbc:Note`` carries no business
    term and Peppol PEPPOL-EN16931-R008 forbids empty elements.
    """
    text = note.note or ""
    if note.subject_code is None:
        return text or None
    return f"#{note.subject_code}#{text}"


def _header(root: etree._Element, invoice: Invoice, credit_note: bool) -> None:
    process = invoice.process_control
    basic(root, "CustomizationID", process.specification_identifier)
    basic(root, "ProfileID", process.business_process_type)
    basic(root, "ID", invoice.number)
    basic(root, "IssueDate", date(invoice.issue_date))
    if credit_note:
        basic(root, "TaxPointDate", date(invoice.vat_point_date))
        basic(root, "CreditNoteTypeCode", invoice.type_code)
    else:
        basic(root, "DueDate", date(invoice.payment_due_date))
        basic(root, "InvoiceTypeCode", invoice.type_code)
    for note in invoice.notes:
        basic(root, "Note", _note_text(note))
    if not credit_note:
        basic(root, "TaxPointDate", date(invoice.vat_point_date))
    basic(root, "DocumentCurrencyCode", invoice.currency_code)
    basic(root, "TaxCurrencyCode", invoice.vat_accounting_currency_code)
    basic(root, "AccountingCost", invoice.buyer_accounting_reference)
    basic(root, "BuyerReference", invoice.buyer_reference)
    period = invoice.delivery.invoicing_period if invoice.delivery else None
    if period is not None or invoice.vat_point_date_code is not None:
        element = aggregate(root, "InvoicePeriod")  # BG-14 and BT-8 (UBL-SR-08: at most one)
        basic(element, "StartDate", date(period.start_date if period else None))
        basic(element, "EndDate", date(period.end_date if period else None))
        basic(element, "DescriptionCode", invoice.vat_point_date_code)


def _document_reference(root: etree._Element, name: str, reference: str | None) -> None:
    if reference is not None:
        basic(aggregate(root, name), "ID", reference)


def _references(root: etree._Element, invoice: Invoice, credit_note: bool) -> None:
    if invoice.purchase_order_reference is not None or invoice.sales_order_reference is not None:
        order = aggregate(root, "OrderReference")
        # The placeholder stands in for a missing BT-13 only: an empty BT-13 is written empty (issue #79).
        purchase_order = invoice.purchase_order_reference
        basic(order, "ID", MISSING_ORDER_REFERENCE if purchase_order is None else purchase_order)
        basic(order, "SalesOrderID", invoice.sales_order_reference)
    for preceding in invoice.preceding_invoice_references:
        reference = aggregate(aggregate(root, "BillingReference"), "InvoiceDocumentReference")
        basic(reference, "ID", preceding.reference)
        basic(reference, "IssueDate", date(preceding.issue_date))
    _document_reference(root, "DespatchDocumentReference", invoice.despatch_advice_reference)
    _document_reference(root, "ReceiptDocumentReference", invoice.receiving_advice_reference)
    if not credit_note:
        _document_reference(root, "OriginatorDocumentReference", invoice.tender_or_lot_reference)
    _document_reference(root, "ContractDocumentReference", invoice.contract_reference)
    if credit_note and invoice.project_reference is not None:
        project = aggregate(root, "AdditionalDocumentReference")
        basic(project, "ID", invoice.project_reference)
        basic(project, "DocumentTypeCode", PROJECT_DOCUMENT_TYPE)
    if invoice.invoiced_object_identifier is not None:
        invoiced_object = aggregate(root, "AdditionalDocumentReference")
        identifier(invoiced_object, "ID", invoice.invoiced_object_identifier)
        basic(invoiced_object, "DocumentTypeCode", OBJECT_DOCUMENT_TYPE)
    for document in invoice.additional_supporting_documents:
        _supporting_document(aggregate(root, "AdditionalDocumentReference"), document)
    if credit_note:
        _document_reference(root, "OriginatorDocumentReference", invoice.tender_or_lot_reference)
    else:
        _document_reference(root, "ProjectReference", invoice.project_reference)


def _supporting_document(element: etree._Element, document: AdditionalSupportingDocument) -> None:
    """BG-24 entries carry neither ``cbc:DocumentTypeCode`` nor ``@schemeID`` (CEN UBL-SR-43)."""
    basic(element, "ID", document.reference)
    basic(element, "DocumentDescription", document.description)
    attached = document.attached_document
    if attached is None and document.external_location is None:
        return
    attachment = aggregate(element, "Attachment")
    if attached is not None:
        if attached.mime_code is None or attached.filename is None:
            raise cannot_express(
                "BT-125",
                "an attached document needs its mime code and filename: CEN UBL-DT-06 and UBL-DT-07 are fatal "
                "(decision M3 in docs/reference/bt-mapping.md)",
            )
        content = base64.b64encode(attached.content).decode("ascii")
        basic(
            attachment, "EmbeddedDocumentBinaryObject", content, mimeCode=attached.mime_code, filename=attached.filename
        )
    if document.external_location is not None:
        basic(aggregate(attachment, "ExternalReference"), "URI", document.external_location)


def _payment_means(root: etree._Element, invoice: Invoice, credit_note: bool) -> None:
    """Append one ``cac:PaymentMeans`` per credit transfer (at least one) for BG-16.

    UBL repeats ``cac:PaymentMeans`` per account (Peppol upstream structure docs, commit 806866b,
    ``ubl-invoice.xml``: ``cac:PaymentMeans`` 0..n, ``cac:PayeeFinancialAccount`` 0..1). The terms that
    may occur only once across them, BT-82 (UBL-SR-46), the credit note BT-9 (UBL-SR-45), the card
    (UBL-SR-54) and the mandate (UBL-SR-55), go in the first one, as does BT-83 (UBL-SR-44 allows one
    distinct value). BT-81 is repeated in each (UBL-SR-47 requires one code).
    """
    instructions = invoice.payment_instructions
    if instructions is None:
        if credit_note and invoice.payment_due_date is not None:
            raise cannot_express(
                "BT-9",
                "a CreditNote carries the payment due date only in cac:PaymentMeans/cbc:PaymentDueDate, which needs "
                "PAYMENT INSTRUCTIONS (BG-16) with a payment means type code (BT-81, BR-49)",
            )
        return
    for index, account in enumerate(instructions.credit_transfers or (None,)):
        element = aggregate(root, "PaymentMeans")
        first = index == 0
        name = instructions.payment_means_text if first else None
        basic(element, "PaymentMeansCode", instructions.payment_means_type_code, name=name)
        if first:
            basic(element, "PaymentDueDate", date(invoice.payment_due_date if credit_note else None))
            basic(element, "PaymentID", instructions.remittance_information)
            _card(element, instructions)
        if account is not None:
            financial = aggregate(element, "PayeeFinancialAccount")
            basic(financial, "ID", account.payment_account_identifier)
            basic(financial, "Name", account.payment_account_name)
            if account.payment_service_provider_identifier is not None:
                basic(
                    aggregate(financial, "FinancialInstitutionBranch"),
                    "ID",
                    account.payment_service_provider_identifier,
                )
        if first:
            _mandate(element, instructions)


def _card(element: etree._Element, instructions: PaymentInstructions) -> None:
    card = instructions.payment_card
    if card is None:
        return
    if card.primary_account_number is None:
        raise cannot_express(
            "BT-87",
            "PAYMENT CARD INFORMATION (BG-18) needs the primary account number: cbc:PrimaryAccountNumberID is "
            "mandatory in CardAccountType (decision M2 in docs/reference/bt-mapping.md)",
        )
    account = aggregate(element, "CardAccount")
    basic(account, "PrimaryAccountNumberID", card.primary_account_number)
    basic(account, "NetworkID", CARD_NETWORK_ID)
    basic(account, "HolderName", card.holder_name)


def _mandate(element: etree._Element, instructions: PaymentInstructions) -> None:
    """BG-19 without BT-89 and BT-91 writes no ``cac:PaymentMandate``; its BT-90 is a party identifier."""
    debit = instructions.direct_debit
    if debit is None or (debit.mandate_reference_identifier is None and debit.debited_account_identifier is None):
        return
    mandate = aggregate(element, "PaymentMandate")
    basic(mandate, "ID", debit.mandate_reference_identifier)
    if debit.debited_account_identifier is not None:
        basic(aggregate(mandate, "PayerFinancialAccount"), "ID", debit.debited_account_identifier)


def _tax_totals(root: etree._Element, invoice: Invoice) -> None:
    """Append BT-110 with the VAT breakdown, then BT-111 in its own ``cac:TaxTotal``.

    The two ``cbc:TaxAmount`` are told apart by ``currencyID`` (BT-5 vs BT-6; CEN BR-CO-15, BR-53 and
    BR-DEC-13/15); only the BT-5 one carries ``cac:TaxSubtotal`` (bt-mapping.md BG-23).

    Raises:
        ModelError: BT-6 equals BT-5 while BT-111 is set, BT-110 is missing and not implied as 0.00 (see
            :func:`_total_vat`), or BT-111 is set without BT-6.
    """
    totals = invoice.totals
    if (
        totals.total_vat_in_accounting_currency is not None
        and invoice.vat_accounting_currency_code == invoice.currency_code
    ):
        raise cannot_express(
            "BT-6",
            "a VAT accounting currency equal to the invoice currency (BT-5) together with BT-111 gives two "
            "cac:TaxTotal/cbc:TaxAmount with the same currencyID, which CEN BR-CO-15 (exactly one in the invoice "
            "currency) rejects",
        )
    tax_total = aggregate(root, "TaxTotal")
    amount(tax_total, "TaxAmount", _total_vat(invoice), invoice.currency_code)
    for breakdown in invoice.vat_breakdown:
        subtotal = aggregate(tax_total, "TaxSubtotal")
        amount(subtotal, "TaxableAmount", breakdown.taxable_amount, invoice.currency_code)
        amount(subtotal, "TaxAmount", breakdown.tax_amount, invoice.currency_code)
        tax_category(
            subtotal,
            "TaxCategory",
            breakdown.category_code,
            breakdown.rate,
            exemption_code=breakdown.exemption_reason_code,
            exemption_reason=breakdown.exemption_reason,
        )
    if totals.total_vat_in_accounting_currency is not None:
        if invoice.vat_accounting_currency_code is None:
            raise cannot_express(
                "BT-111",
                "the invoice total VAT amount in accounting currency needs the VAT accounting currency code (BT-6), "
                "its currencyID",
            )
        accounting = aggregate(root, "TaxTotal")
        amount(accounting, "TaxAmount", totals.total_vat_in_accounting_currency, invoice.vat_accounting_currency_code)


def _total_vat(invoice: Invoice) -> Decimal:
    """BT-110, or ``0.00`` when it is absent and both identities that define it give 0.

    UBL needs it: ``cbc:TaxAmount`` is mandatory in ``cac:TaxTotal`` (UBL 2.1 XSD ``TaxTotalType``, minOccurs 1)
    and CEN UBL BR-CO-15 requires exactly one in BT-5 (``UBL/EN16931-UBL-model.sch``). CII may omit it when
    BT-112 = BT-109 (second disjunct of CII BR-CO-15). When moreover Σ BT-117 = 0, BR-CO-15 (BT-112 = BT-109 +
    BT-110) and BR-CO-14 (BT-110 = Σ BT-117) both give BT-110 = 0, which is what CEN's twin examples write
    (``ubl-tc434-example7.xml`` 0.00 vs ``CII_example7.xml`` absent; KoSIT ``01.05_minimal_test_ubl.xml`` 0 vs
    ``_uncefact.xml`` absent). bt-mapping.md "Normalizations".

    Raises:
        ModelError: BT-110 is absent and BT-112 differs from BT-109 or Σ BT-117 is not 0.
    """
    totals = invoice.totals
    if totals.total_vat is not None:
        return totals.total_vat
    if totals.total_with_vat != totals.total_without_vat:
        raise cannot_express(
            "BT-110",
            "UBL needs the invoice total VAT amount (UBL 2.1 XSD TaxTotalType; CEN BR-CO-15) and it is only implied "
            "(as 0.00) when BT-112 equals BT-109, which it does not here (BR-CO-15: BT-112 = BT-109 + BT-110)",
        )
    if sum((group.tax_amount for group in invoice.vat_breakdown), Decimal(0)) != 0:
        raise cannot_express(
            "BT-110",
            "UBL needs the invoice total VAT amount (UBL 2.1 XSD TaxTotalType; CEN BR-CO-15) and 0.00 would contradict "
            "the VAT category tax amounts (BR-CO-14: BT-110 = Σ BT-117)",
        )
    return Decimal("0.00")


def _monetary_total(root: etree._Element, invoice: Invoice) -> None:
    totals = invoice.totals
    currency = invoice.currency_code
    element = aggregate(root, "LegalMonetaryTotal")
    amount(element, "LineExtensionAmount", totals.sum_of_line_net_amounts, currency)
    amount(element, "TaxExclusiveAmount", totals.total_without_vat, currency)
    amount(element, "TaxInclusiveAmount", totals.total_with_vat, currency)
    amount(element, "AllowanceTotalAmount", totals.sum_of_allowances, currency)
    amount(element, "ChargeTotalAmount", totals.sum_of_charges, currency)
    amount(element, "PrepaidAmount", totals.paid_amount, currency)
    amount(element, "PayableRoundingAmount", totals.rounding_amount, currency)
    amount(element, "PayableAmount", totals.amount_due, currency)
