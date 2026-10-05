"""The CII writer: :class:`~euinvoice.model.Invoice` → ``rsm:CrossIndustryInvoice`` bytes.

Invoices and credit notes share the root (D4); BT-3 (``ram:TypeCode``) tells them apart. Element order
follows the D16B XSD sequences: ``rsm:ExchangedDocumentContext``, ``rsm:ExchangedDocument``,
``rsm:SupplyChainTradeTransaction`` (lines first, then the header agreement, delivery and settlement).
"""

import base64

from lxml import etree

from euinvoice import _xml
from euinvoice.model import Invoice
from euinvoice.syntax.cii._build import date_time, opt, sub
from euinvoice.syntax.cii._lines import OBJECT_TYPE_CODE, line
from euinvoice.syntax.cii._parties import buyer, seller, ship_to, tax_representative
from euinvoice.syntax.cii._settlement import settlement

TENDER_TYPE_CODE: str = "50"
"""``ram:TypeCode`` of the ``ram:AdditionalReferencedDocument`` holding BT-17 (CII-DT-018, CII-SR-457)."""
SUPPORTING_DOCUMENT_TYPE_CODE: str = "916"
"""``ram:TypeCode`` of a BG-24 ``ram:AdditionalReferencedDocument`` (CII-DT-015, -021, -022, CII-SR-475/476)."""
PROJECT_NAME: str = "Project reference"
"""``ram:SpecifiedProcuringProject/ram:Name``, which the D16B XSD requires (``ProcuringProjectType``, minOccurs 1)
but no business term carries; every KoSIT testsuite instance with BT-11 writes this text."""


def write(invoice: Invoice) -> bytes:
    """Serialize an invoice or credit note as UN/CEFACT CII D16B (CEN/TS 16931-3-3).

    BT-23 and BT-24 are written as they are in the model; profiles (#19) choose them.

    Args:
        invoice: The invoice.

    Returns:
        The UTF-8 encoded XML document, with an XML declaration.

    Raises:
        ModelError: The invoice holds a value CII cannot carry: more than one preceding invoice reference
            (BG-3), an item price discount (BT-147) without gross price (BT-148), a base quantity unit
            (BT-150) without base quantity (BT-149), or BT-111 without BT-6.
    """
    root = etree.Element(f"{{{_xml.CII_RSM}}}CrossIndustryInvoice", nsmap=_xml.CII_NSMAP)
    _context(root, invoice)
    _document(root, invoice)
    transaction = etree.SubElement(root, f"{{{_xml.CII_RSM}}}SupplyChainTradeTransaction")
    for item in invoice.lines:
        line(transaction, item)
    _agreement(transaction, invoice)
    _delivery(transaction, invoice)
    settlement(transaction, invoice)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _context(root: etree._Element, invoice: Invoice) -> None:
    """``rsm:ExchangedDocumentContext`` (BG-2): BT-23 (at most one, CII-SR-003) then BT-24 (CII-SR-009/010)."""
    context = etree.SubElement(root, f"{{{_xml.CII_RSM}}}ExchangedDocumentContext")
    process = invoice.process_control
    if process.business_process_type is not None:
        sub(sub(context, "BusinessProcessSpecifiedDocumentContextParameter"), "ID", process.business_process_type)
    sub(sub(context, "GuidelineSpecifiedDocumentContextParameter"), "ID", process.specification_identifier)


def _document(root: etree._Element, invoice: Invoice) -> None:
    """``rsm:ExchangedDocument``: BT-1, BT-3, BT-2 and the notes BG-1 (``Content`` before ``SubjectCode``)."""
    document = etree.SubElement(root, f"{{{_xml.CII_RSM}}}ExchangedDocument")
    sub(document, "ID", invoice.number)
    sub(document, "TypeCode", invoice.type_code)
    date_time(document, "IssueDateTime", invoice.issue_date)
    for note in invoice.notes:
        element = sub(document, "IncludedNote")
        opt(element, "Content", note.note)
        opt(element, "SubjectCode", note.subject_code)


def _referenced_document(parent: etree._Element, name: str, reference: str | None) -> None:
    if reference is not None:
        sub(sub(parent, name), "IssuerAssignedID", reference)


def _agreement(transaction: etree._Element, invoice: Invoice) -> None:
    """``ram:ApplicableHeaderTradeAgreement`` in ``ram:HeaderTradeAgreementType`` order."""
    element = sub(transaction, "ApplicableHeaderTradeAgreement")
    opt(element, "BuyerReference", invoice.buyer_reference)
    seller(element, invoice.seller)
    buyer(element, invoice.buyer)
    if invoice.seller_tax_representative is not None:
        tax_representative(element, invoice.seller_tax_representative)
    _referenced_document(element, "SellerOrderReferencedDocument", invoice.sales_order_reference)
    _referenced_document(element, "BuyerOrderReferencedDocument", invoice.purchase_order_reference)
    _referenced_document(element, "ContractReferencedDocument", invoice.contract_reference)
    for supporting in invoice.additional_supporting_documents:
        document = sub(element, "AdditionalReferencedDocument")
        sub(document, "IssuerAssignedID", supporting.reference)
        opt(document, "URIID", supporting.external_location)
        sub(document, "TypeCode", SUPPORTING_DOCUMENT_TYPE_CODE)
        opt(document, "Name", supporting.description)
        attached = supporting.attached_document
        if attached is not None:
            attributes = {"mimeCode": attached.mime_code, "filename": attached.filename}
            binary = sub(document, "AttachmentBinaryObject", **{k: v for k, v in attributes.items() if v is not None})
            binary.text = base64.b64encode(attached.content).decode("ascii")
    if invoice.tender_or_lot_reference is not None:
        document = sub(element, "AdditionalReferencedDocument")
        sub(document, "IssuerAssignedID", invoice.tender_or_lot_reference)
        sub(document, "TypeCode", TENDER_TYPE_CODE)
    if invoice.invoiced_object_identifier is not None:
        document = sub(element, "AdditionalReferencedDocument")
        sub(document, "IssuerAssignedID", invoice.invoiced_object_identifier.value)
        sub(document, "TypeCode", OBJECT_TYPE_CODE)
        # BT-18 scheme: ram:ReferenceTypeCode (BR-CL-07; CII-DT-024 allows it only with TypeCode 130).
        opt(document, "ReferenceTypeCode", invoice.invoiced_object_identifier.scheme_id)
    if invoice.project_reference is not None:
        project = sub(element, "SpecifiedProcuringProject")
        sub(project, "ID", invoice.project_reference)
        sub(project, "Name", PROJECT_NAME)


def _delivery(transaction: etree._Element, invoice: Invoice) -> None:
    """``ram:ApplicableHeaderTradeDelivery`` (always present, the XSD requires it): BG-13, BT-15, BT-16."""
    element = sub(transaction, "ApplicableHeaderTradeDelivery")
    delivery = invoice.delivery
    if delivery is not None:
        ship_to(element, delivery)
        if delivery.actual_delivery_date is not None:
            event = sub(element, "ActualDeliverySupplyChainEvent")
            date_time(event, "OccurrenceDateTime", delivery.actual_delivery_date)
    _referenced_document(element, "DespatchAdviceReferencedDocument", invoice.despatch_advice_reference)
    _referenced_document(element, "ReceivingAdviceReferencedDocument", invoice.receiving_advice_reference)
