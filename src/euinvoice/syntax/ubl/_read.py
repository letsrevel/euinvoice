"""The UBL 2.1 reader: an ``Invoice`` or ``CreditNote`` element to :class:`~euinvoice.syntax.result.ParseResult`.

It is the inverse of :mod:`euinvoice.syntax.ubl._write` and reads the XPaths of
``docs/reference/bt-mapping.md``, with the credit note differences listed there (note N3): BT-9 from
``cac:PaymentMeans/cbc:PaymentDueDate`` and BT-11 from ``cac:AdditionalDocumentReference`` with
``cbc:DocumentTypeCode`` 50. Elements the writer fills in without a business term are recognised and not
reported: ``cac:CardAccount/cbc:NetworkID`` (note N2) and the ``NA`` purchase order id beside a sales order
id (note N4). Everything else without a business term is listed in ``ParseResult.unmapped``.
"""

import base64
import binascii
import datetime
import typing as t

from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ParseError
from euinvoice.model import (
    AdditionalSupportingDocument,
    BinaryObject,
    CreditTransfer,
    DirectDebit,
    DocumentLevelAllowance,
    DocumentLevelCharge,
    DocumentTotals,
    Invoice,
    InvoiceNote,
    InvoicingPeriod,
    PaymentCardInformation,
    PaymentInstructions,
    PrecedingInvoiceReference,
    ProcessControl,
    VatBreakdown,
)
from euinvoice.model.codes import UNTDID_4451_TEXT_SUBJECT
from euinvoice.syntax.result import ParseResult
from euinvoice.syntax.ubl._cursor import CAC, CBC, Cursor, build, normalize_space
from euinvoice.syntax.ubl._read_lines import (
    read_allowance_charge,
    read_line,
    read_object_identifier,
    read_period,
    take_vat_scheme,
)
from euinvoice.syntax.ubl._read_parties import Parties, read_delivery, read_parties, take_creditor_id
from euinvoice.syntax.ubl._write import CARD_NETWORK_ID, MISSING_ORDER_REFERENCE, PROJECT_DOCUMENT_TYPE

__all__ = ["read"]

_ROOTS: t.Final = {
    f"{{{_xml.UBL_INVOICE}}}Invoice": False,
    f"{{{_xml.UBL_CREDIT_NOTE}}}CreditNote": True,
}
_XML_SPACE: t.Final = " \t\r\n"


def read(root: etree._Element) -> ParseResult:
    """Read a UBL 2.1 ``Invoice`` or ``CreditNote`` into the semantic model.

    The element must come from :func:`euinvoice._xml.parse` (D10); the reader never parses. Business
    terms are taken where the CEN UBL binding puts them (``docs/reference/bt-mapping.md``) and are not
    checked against the business rules: validate the document for that. A UBL ``Invoice`` with type code
    81 reads like a ``CreditNote`` would; the model stores no root (D4, bt-mapping.md "Normalizations").

    Args:
        root: The document's root element.

    Returns:
        The invoice, and the XPath of every element or attribute that carries no business term.

    Raises:
        ParseError: ``root`` is not a UBL 2.1 ``Invoice`` or ``CreditNote``; a date is not ``YYYY-MM-DD``; a
            business term does not fit the model (e.g. a code outside its list, a missing
            mandatory term): the message starts with the BT/BG id and the location is the element.
    """
    credit_note = _ROOTS.get(root.tag) if isinstance(root.tag, str) else None
    if credit_note is None:
        raise ParseError(
            f"expected the UBL root Invoice or CreditNote, got {root.tag}", location=root.getroottree().getpath(root)
        )
    cursor = Cursor(root)
    currency = (cursor.text(root, CBC + "DocumentCurrencyCode") or "").strip(_XML_SPACE)
    accounting_currency = cursor.text(root, CBC + "TaxCurrencyCode")
    parties = read_parties(cursor)
    period = cursor.first(root, CAC + "InvoicePeriod")  # BG-14 and BT-8; UBL-SR-08: at most one
    total_vat, accounting_vat, breakdown = _tax_totals(
        cursor, currency, None if accounting_currency is None else accounting_currency.strip(_XML_SPACE)
    )
    instructions, credit_note_due_date = _payment_instructions(cursor, parties, credit_note)
    references = _references(cursor, credit_note)
    entries = [
        entry
        for element in cursor.children(root, CAC + "AllowanceCharge")
        if (entry := read_allowance_charge(cursor, element, currency, line=False)) is not None
    ]
    invoice = build(
        Invoice,
        root,
        "BG-0",
        number=cursor.text(root, CBC + "ID"),
        issue_date=cursor.date(root, CBC + "IssueDate", "BT-2"),
        type_code=cursor.text(root, CBC + ("CreditNoteTypeCode" if credit_note else "InvoiceTypeCode")),
        currency_code=currency or None,
        vat_accounting_currency_code=accounting_currency,
        vat_point_date=cursor.date(root, CBC + "TaxPointDate", "BT-7"),
        vat_point_date_code=cursor.text(period, CBC + "DescriptionCode"),
        payment_due_date=credit_note_due_date if credit_note else cursor.date(root, CBC + "DueDate", "BT-9"),
        buyer_reference=cursor.text(root, CBC + "BuyerReference"),
        buyer_accounting_reference=cursor.text(root, CBC + "AccountingCost"),
        payment_terms=cursor.text(cursor.first(root, CAC + "PaymentTerms"), CBC + "Note"),
        notes=tuple(
            note for element in cursor.children(root, CBC + "Note") if (note := _note(cursor, element)) is not None
        ),
        process_control=build(
            ProcessControl,
            root,
            "BG-2",
            business_process_type=cursor.text(root, CBC + "ProfileID"),
            specification_identifier=cursor.text(root, CBC + "CustomizationID"),
        ),
        seller=parties.seller,
        buyer=parties.buyer,
        payee=parties.payee,
        seller_tax_representative=parties.tax_representative,
        delivery=read_delivery(cursor, _invoicing_period(cursor)),
        payment_instructions=instructions,
        allowances=tuple(entry for entry in entries if isinstance(entry, DocumentLevelAllowance)),
        charges=tuple(entry for entry in entries if isinstance(entry, DocumentLevelCharge)),
        totals=_totals(cursor, currency, total_vat, accounting_vat),
        vat_breakdown=breakdown,
        lines=tuple(
            read_line(cursor, element, currency, credit_note=credit_note)
            for element in cursor.children(root, CAC + ("CreditNoteLine" if credit_note else "InvoiceLine"))
        ),
        **references,
    )
    return ParseResult(invoice=invoice, unmapped=cursor.unmapped())


def _invoicing_period(cursor: Cursor) -> InvoicingPeriod | None:
    """BG-14 from the document-level ``cac:InvoicePeriod`` (bt-mapping.md BG-14), ``None`` without dates.

    The same element carries BT-8 (``cbc:DescriptionCode``), read by :func:`read`; UBL-SR-08 allows one.
    """
    period = cursor.first(cursor.root, CAC + "InvoicePeriod")
    start, end = read_period(cursor, period, ("BT-73", "BT-74"))
    if period is None or (start is None and end is None):
        return None
    return build(InvoicingPeriod, period, "BG-14", start_date=start, end_date=end)


def _note(cursor: Cursor, element: etree._Element) -> InvoiceNote | None:
    """Read one ``cbc:Note`` (BG-1) with the BT-21 decision of issue #11.

    BT-21 is taken only from a **leading** ``#CODE#`` whose CODE is exactly three characters and in the
    UNTDID 4451 list; the rest of the text is BT-22. Any other note (no leading pair, another length, an
    unknown code, a pair further in) is BT-22 verbatim. CEN BR-CL-08 (``UBL/EN16931-UBL-model.sch:181``)
    accepts more (the first ``#…#`` anywhere, unpadded), so this never rejects what the Schematron
    accepts, and writing the note back gives the same text. An empty note carries no business term
    (and the writer never writes one, Peppol PEPPOL-EN16931-R008): it stays unmapped.
    """
    text = element.text or ""
    if not text:
        return None
    cursor.take(element)
    code = text[1:4]
    if len(text) >= 5 and text[0] == "#" and text[4] == "#" and code in UNTDID_4451_TEXT_SUBJECT:
        return build(InvoiceNote, element, "BG-1", subject_code=code, note=text[5:] or None)
    return build(InvoiceNote, element, "BG-1", note=text)


def _references(cursor: Cursor, credit_note: bool) -> dict[str, t.Any]:
    """Read the document references: BT-11..BT-18, BG-3 and BG-24.

    ``cac:AdditionalDocumentReference`` carries BT-18 (``cbc:DocumentTypeCode`` 130), the credit note
    BT-11 (code 50) and BG-24 (no code); CEN UBL-SR-43 (fatal) allows nothing else, so an entry with
    another code stays unmapped. ``cac:OrderReference/cbc:ID`` ``NA`` next to a ``cbc:SalesOrderID`` is
    the writer's placeholder for a missing BT-13 (issue #11); a genuine purchase order "NA" next to a
    sales order reference cannot be told apart and is read as no BT-13.
    """
    root = cursor.root
    order = cursor.first(root, CAC + "OrderReference")
    sales_order = cursor.text(order, CBC + "SalesOrderID")
    purchase_order = cursor.text(order, CBC + "ID")
    if sales_order is not None and purchase_order == MISSING_ORDER_REFERENCE:
        purchase_order = None
    additional = cursor.children(root, CAC + "AdditionalDocumentReference")
    project = cursor.first(cursor.root, CAC + "ProjectReference")
    if credit_note:
        project = next((ref for ref in additional if _type_code(ref) == PROJECT_DOCUMENT_TYPE), None)
        cursor.text(project, CBC + "DocumentTypeCode")
    return {
        "purchase_order_reference": purchase_order,
        "sales_order_reference": sales_order,
        "preceding_invoice_references": tuple(
            _preceding(cursor, reference)
            for element in cursor.children(root, CAC + "BillingReference")
            if (reference := cursor.first(element, CAC + "InvoiceDocumentReference")) is not None
        ),
        "despatch_advice_reference": _reference_id(cursor, "DespatchDocumentReference"),
        "receiving_advice_reference": _reference_id(cursor, "ReceiptDocumentReference"),
        "tender_or_lot_reference": _reference_id(cursor, "OriginatorDocumentReference"),
        "contract_reference": _reference_id(cursor, "ContractDocumentReference"),
        "project_reference": cursor.text(project, CBC + "ID"),
        "invoiced_object_identifier": read_object_identifier(cursor, additional),
        "additional_supporting_documents": tuple(
            _supporting_document(cursor, element) for element in additional if _type_code(element) is None
        ),
    }


def _type_code(reference: etree._Element) -> str | None:
    code = next(reference.iterchildren(CBC + "DocumentTypeCode"), None)
    return None if code is None else (code.text or "")


def _reference_id(cursor: Cursor, name: str) -> str | None:
    return cursor.text(cursor.first(cursor.root, CAC + name), CBC + "ID")


def _preceding(cursor: Cursor, element: etree._Element) -> PrecedingInvoiceReference:
    return build(
        PrecedingInvoiceReference,
        element,
        "BG-3",
        reference=cursor.text(element, CBC + "ID"),
        issue_date=cursor.date(element, CBC + "IssueDate", "BT-26"),
    )


def _supporting_document(cursor: Cursor, element: etree._Element) -> AdditionalSupportingDocument:
    """Read one BG-24 entry; BT-125's base64 content may contain XML whitespace (``xs:base64Binary``)."""
    attachment = cursor.first(element, CAC + "Attachment")
    embedded = cursor.first(attachment, CBC + "EmbeddedDocumentBinaryObject")
    attached = None
    if embedded is not None:
        encoded = "".join((cursor.value(embedded) or "").split())
        try:
            content = base64.b64decode(encoded, validate=True)
        except binascii.Error as exc:
            raise ParseError(
                f"BT-125: not base64 content ({exc})", location=embedded.getroottree().getpath(embedded)
            ) from exc
        attached = build(
            BinaryObject,
            embedded,
            "BT-125",
            content=content,
            mime_code=cursor.attribute(embedded, "mimeCode"),
            filename=cursor.attribute(embedded, "filename"),
        )
    return build(
        AdditionalSupportingDocument,
        element,
        "BG-24",
        reference=cursor.text(element, CBC + "ID"),
        description=cursor.text(element, CBC + "DocumentDescription"),
        external_location=cursor.text(cursor.first(attachment, CAC + "ExternalReference"), CBC + "URI"),
        attached_document=attached,
    )


def _same(cursor: Cursor, elements: list[etree._Element], *, text: bool = False) -> None:
    """Take the repeats of a term that UBL repeats per ``cac:PaymentMeans`` when they equal the first one.

    Codes and dates are compared after ``normalize-space`` (the model normalizes them); free ``text`` (BT-83)
    exactly, as UBL-SR-44 does. A repeat that differs is information the model cannot hold and stays unmapped.
    """
    key: t.Callable[[str | None], str] = (lambda value: value or "") if text else normalize_space
    for element in elements[1:]:
        if key(element.text) == key(elements[0].text):
            cursor.take(element)


def _payment_instructions(
    cursor: Cursor, parties: Parties, credit_note: bool
) -> tuple[PaymentInstructions | None, datetime.date | None]:
    """Read PAYMENT INSTRUCTIONS (BG-16) from every ``cac:PaymentMeans``, and the credit note BT-9.

    UBL repeats ``cac:PaymentMeans`` per account (one credit transfer, BG-17, each). The terms the model
    holds once, BT-81 (UBL-SR-47: one distinct code), BT-82 (UBL-SR-46: at most one), BT-83 (UBL-SR-44: one
    distinct value) and the credit note BT-9 (UBL-SR-45: at most one), are read from their first
    occurrence; a repeat with the same value is taken, a different one stays unmapped. So do a second
    card (BG-18, UBL-SR-54) or mandate (BG-19, UBL-SR-55).
    """
    means = cursor.children(cursor.root, CAC + "PaymentMeans")
    if not means:
        return None, None
    codes = [code for element in means if (code := cursor.first(element, CBC + "PaymentMeansCode")) is not None]
    type_code = cursor.value(codes[0]) if codes else None
    _same(cursor, codes)
    names = [code for code in codes if "name" in code.attrib]
    text = cursor.attribute(names[0], "name") if names else None
    for code in names:  # UBL-SR-46 allows one; a missing @name on a repeat is no difference
        if code.get("name") == text:
            cursor.attribute(code, "name")
    due_dates = [date for element in means if (date := cursor.first(element, CBC + "PaymentDueDate")) is not None]
    if not credit_note:
        due_dates = []  # an Invoice has cbc:DueDate (BT-9); this element is no business term there
    due_date = cursor.parse_date(due_dates[0], "BT-9") if due_dates else None
    _same(cursor, due_dates)
    payment_ids = [pid for element in means if (pid := cursor.first(element, CBC + "PaymentID")) is not None]
    remittance = cursor.value(payment_ids[0]) if payment_ids else None
    _same(cursor, payment_ids, text=True)
    cards = [card for element in means if (card := cursor.first(element, CAC + "CardAccount")) is not None]
    mandates = [mandate for element in means if (mandate := cursor.first(element, CAC + "PaymentMandate")) is not None]
    instructions = build(
        PaymentInstructions,
        means[0],
        "BG-16",
        payment_means_type_code=type_code,
        payment_means_text=text,
        remittance_information=remittance,
        credit_transfers=tuple(
            _credit_transfer(cursor, account)
            for element in means
            if (account := cursor.first(element, CAC + "PayeeFinancialAccount")) is not None
        ),
        payment_card=_card(cursor, cards[0]) if cards else None,
        direct_debit=_direct_debit(cursor, mandates[0] if mandates else None, parties),
    )
    return instructions, due_date


def _credit_transfer(cursor: Cursor, account: etree._Element) -> CreditTransfer:
    return build(
        CreditTransfer,
        account,
        "BG-17",
        payment_account_identifier=cursor.text(account, CBC + "ID"),
        payment_account_name=cursor.text(account, CBC + "Name"),
        payment_service_provider_identifier=cursor.text(
            cursor.first(account, CAC + "FinancialInstitutionBranch"), CBC + "ID"
        ),
    )


def _card(cursor: Cursor, card: etree._Element) -> PaymentCardInformation:
    """Read PAYMENT CARD INFORMATION (BG-18).

    ``cbc:NetworkID`` is mandatory in ``CardAccountType`` but carries no business term (bt-mapping.md N2). Only
    the writer's filler ``NA`` is taken; any other value is information the model cannot hold and stays
    unmapped.
    """
    network = cursor.first(card, CBC + "NetworkID")
    if network is not None and network.text == CARD_NETWORK_ID:
        cursor.take(network)
    return build(
        PaymentCardInformation,
        card,
        "BG-18",
        primary_account_number=cursor.text(card, CBC + "PrimaryAccountNumberID"),
        holder_name=cursor.text(card, CBC + "HolderName"),
    )


def _direct_debit(cursor: Cursor, mandate: etree._Element | None, parties: Parties) -> DirectDebit | None:
    """BG-19 from ``cac:PaymentMandate`` (BT-89, BT-91) and the party SEPA id (BT-90)."""
    creditor_id = take_creditor_id(cursor, parties.creditor_ids) if parties.creditor_ids else None
    if mandate is None and creditor_id is None:
        return None
    return build(
        DirectDebit,
        cursor.root if mandate is None else mandate,
        "BG-19",
        mandate_reference_identifier=cursor.text(mandate, CBC + "ID"),
        bank_assigned_creditor_identifier=creditor_id,
        debited_account_identifier=cursor.text(cursor.first(mandate, CAC + "PayerFinancialAccount"), CBC + "ID"),
    )


def _tax_totals(
    cursor: Cursor, currency: str, accounting_currency: str | None
) -> tuple[str | None, str | None, tuple[VatBreakdown, ...]]:
    """Read BT-110, BT-111 and the VAT breakdown (BG-23) from the ``cac:TaxTotal`` elements.

    The two totals are told apart by ``currencyID``: BT-5 for BT-110, BT-6 for BT-111 (CEN BR-CO-15,
    BR-53; bt-mapping.md). BG-23 is read from the BT-110 ``cac:TaxTotal`` only: a ``cac:TaxSubtotal`` in
    another currency is no VAT breakdown and stays unmapped, as does any further ``cac:TaxTotal``.
    """
    total_vat: str | None = None
    accounting_vat: str | None = None
    breakdown: tuple[VatBreakdown, ...] = ()
    for tax_total in cursor.children(cursor.root, CAC + "TaxTotal"):
        tax_amount = cursor.first(tax_total, CBC + "TaxAmount")
        found = None if tax_amount is None else tax_amount.get("currencyID")
        if found == currency and total_vat is None:
            total_vat = cursor.amount(tax_total, CBC + "TaxAmount", currency)
            breakdown = tuple(
                _breakdown(cursor, subtotal, currency) for subtotal in cursor.children(tax_total, CAC + "TaxSubtotal")
            )
        elif found is not None and found == accounting_currency and accounting_vat is None:
            accounting_vat = cursor.amount(tax_total, CBC + "TaxAmount", accounting_currency)
    return total_vat, accounting_vat, breakdown


def _breakdown(cursor: Cursor, subtotal: etree._Element, currency: str) -> VatBreakdown:
    category = cursor.first(subtotal, CAC + "TaxCategory")
    take_vat_scheme(cursor, category)
    return build(
        VatBreakdown,
        subtotal,
        "BG-23",
        taxable_amount=cursor.amount(subtotal, CBC + "TaxableAmount", currency),
        tax_amount=cursor.amount(subtotal, CBC + "TaxAmount", currency),
        category_code=cursor.text(category, CBC + "ID"),
        rate=cursor.text(category, CBC + "Percent"),
        exemption_reason=cursor.text(category, CBC + "TaxExemptionReason"),
        exemption_reason_code=cursor.text(category, CBC + "TaxExemptionReasonCode"),
    )


def _totals(cursor: Cursor, currency: str, total_vat: str | None, accounting_vat: str | None) -> DocumentTotals | None:
    element = cursor.first(cursor.root, CAC + "LegalMonetaryTotal")
    if element is None:
        return None
    return build(
        DocumentTotals,
        element,
        "BG-22",
        sum_of_line_net_amounts=cursor.amount(element, CBC + "LineExtensionAmount", currency),
        sum_of_allowances=cursor.amount(element, CBC + "AllowanceTotalAmount", currency),
        sum_of_charges=cursor.amount(element, CBC + "ChargeTotalAmount", currency),
        total_without_vat=cursor.amount(element, CBC + "TaxExclusiveAmount", currency),
        total_vat=total_vat,
        total_vat_in_accounting_currency=accounting_vat,
        total_with_vat=cursor.amount(element, CBC + "TaxInclusiveAmount", currency),
        paid_amount=cursor.amount(element, CBC + "PrepaidAmount", currency),
        rounding_amount=cursor.amount(element, CBC + "PayableRoundingAmount", currency),
        amount_due=cursor.amount(element, CBC + "PayableAmount", currency),
    )
