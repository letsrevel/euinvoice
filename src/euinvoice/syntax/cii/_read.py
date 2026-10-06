"""The CII reader: a parsed ``rsm:CrossIndustryInvoice`` → :class:`~euinvoice.syntax.result.ParseResult`.

The inverse of ``_write.py``. XPaths per business term are those of ``docs/reference/bt-mapping.md``.
"""

import base64
import binascii

from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ParseError
from euinvoice.model import (
    AdditionalSupportingDocument,
    BinaryObject,
    DeliverToAddress,
    DeliveryInformation,
    Invoice,
    InvoiceNote,
    InvoicingPeriod,
    ProcessControl,
)
from euinvoice.syntax.cii._build import PROJECT_NAME, SUPPORTING_DOCUMENT_TYPE_CODE, TENDER_TYPE_CODE
from euinvoice.syntax.cii._read_common import object_identifier
from euinvoice.syntax.cii._read_lines import line
from euinvoice.syntax.cii._read_parties import address, buyer, seller, single_id, tax_representative
from euinvoice.syntax.cii._read_settlement import settlement
from euinvoice.syntax.cii._reader import XML_SPACE, Reader, content
from euinvoice.syntax.result import ParseResult

_ROOT = f"{{{_xml.CII_RSM}}}CrossIndustryInvoice"


def read(root: etree._Element) -> ParseResult:
    """Read an EN 16931 invoice or credit note from UN/CEFACT CII D16B (CEN/TS 16931-3-3).

    ``root`` must come from :func:`euinvoice._xml.parse` (D10); the reader never parses. Every element and
    attribute that no business term takes is listed in :attr:`ParseResult.unmapped` instead of being dropped. The
    only content consumed without a business term is what the writer itself adds for the syntax, and only when it
    has exactly the writer's value: the ``ram:TypeCode`` ``VAT`` of each tax, the type codes 916 / 50 / 130 of BG-24
    / BT-17 / BT-18 documents, a ``ram:SpecifiedProcuringProject/ram:Name`` equal to ``PROJECT_NAME`` (required by
    the D16B XSD, no business term; any other name stays unmapped), a gross price ``ram:BasisQuantity`` equal to the
    net price's, empty ``ram:IncludedNote`` elements (no child, no text: they carry nothing; the writer skips them)
    and ``@format='102'`` of dates.

    Args:
        root: The ``rsm:CrossIndustryInvoice`` element.

    Returns:
        The invoice and the unmapped XPaths.

    Raises:
        ParseError: ``root`` is not ``rsm:CrossIndustryInvoice``; there is no line (BG-25, BR-16: Factur-X
            MINIMUM and BASIC WL, issue #69); a date is not format 102; BT-8 is not a CII code;
            BT-125 is not base64; or the content does not form a valid model (a required term missing, a code
            outside its list, ...). The message names the BT/BG id, and ``location`` is the XPath of the element
            being read.
    """
    # ponytail: Factur-X MINIMUM and BASIC WL have no lines (BG-25, BR-16; MINIMUM also lacks BT-106 and BG-23), so
    # they raise the ParseError below. Reading them as an EN 16931 subset needs a maintainer decision on D1
    # (needs-human #69); BASIC, EN 16931, EXTENDED and XRECHNUNG read fully.
    if root.tag != _ROOT:
        raise ParseError(f"expected the CII root {_ROOT}, got {root.tag}", location=root.getroottree().getpath(root))
    reader = Reader(root)
    transaction = reader.one(root, "SupplyChainTradeTransaction", _xml.CII_RSM)
    if not reader.children(transaction, "IncludedSupplyChainTradeLineItem"):
        raise ParseError(
            "cannot read Invoice: BG-25 (lines): no invoice line, at least one is required (BR-16); Factur-X MINIMUM "
            "and BASIC WL documents carry none and cannot be read into the EN 16931 model "
            "(https://github.com/letsrevel/euinvoice/issues/69)",
            location=reader.path(root),
        )
    settlement_fields, invoicing_period = settlement(reader, transaction)
    invoice = reader.model(
        Invoice,
        root,
        **_document(reader, root),
        lines=tuple(line(reader, item) for item in reader.each(transaction, "IncludedSupplyChainTradeLineItem")),
        **_agreement(reader, reader.one(transaction, "ApplicableHeaderTradeAgreement")),
        **_delivery(reader, reader.one(transaction, "ApplicableHeaderTradeDelivery"), invoicing_period, root),
        **settlement_fields,
    )
    return ParseResult(invoice=invoice, unmapped=reader.unmapped())


def _document(reader: Reader, root: etree._Element) -> dict[str, object]:
    """``rsm:ExchangedDocumentContext`` (BG-2) and ``rsm:ExchangedDocument``: BT-1, BT-2, BT-3, BG-1."""
    context = reader.one(root, "ExchangedDocumentContext", _xml.CII_RSM)
    document = reader.one(root, "ExchangedDocument", _xml.CII_RSM)
    notes = []
    for element in reader.children(document, "IncludedNote"):
        if len(element) == 0 and not content(element).strip(XML_SPACE):
            reader.use(element)  # empty: it carries nothing (the writer skips empty notes)
            continue
        note = reader.text(element, "Content")
        subject = reader.text(element, "SubjectCode")
        if note is not None or subject is not None:
            notes.append(reader.model(InvoiceNote, reader.use(element), note=note, subject_code=subject))
    return {
        "process_control": None
        if context is None
        else reader.model(
            ProcessControl,
            context,
            business_process_type=reader.text(
                reader.one(context, "BusinessProcessSpecifiedDocumentContextParameter"), "ID"
            ),
            specification_identifier=reader.text(
                reader.one(context, "GuidelineSpecifiedDocumentContextParameter"), "ID"
            ),
        ),
        "number": reader.text(document, "ID"),
        "type_code": reader.text(document, "TypeCode"),
        "issue_date": reader.date(document, "IssueDateTime", "BT-2"),
        "notes": tuple(notes),
    }


def _reference(reader: Reader, parent: etree._Element | None, name: str) -> str | None:
    return reader.text(reader.one(parent, name), "IssuerAssignedID")


def _agreement(reader: Reader, agreement: etree._Element | None) -> dict[str, object]:
    """``ram:ApplicableHeaderTradeAgreement``: BT-10..BT-14, BT-17, BT-18, the parties and BG-24."""
    project = reader.one(agreement, "SpecifiedProcuringProject")
    # ram:Name is required by the D16B XSD but carries no business term: the writer's own PROJECT_NAME is consumed,
    # any other name is content the model cannot hold and stays unmapped.
    names = reader.children(project, "Name")
    if names and content(names[0]) == PROJECT_NAME:
        reader.use(names[0])
    return {
        "buyer_reference": reader.text(agreement, "BuyerReference"),
        "seller": seller(reader, agreement),
        "buyer": buyer(reader, agreement),
        "seller_tax_representative": tax_representative(reader, agreement),
        "sales_order_reference": _reference(reader, agreement, "SellerOrderReferencedDocument"),
        "purchase_order_reference": _reference(reader, agreement, "BuyerOrderReferencedDocument"),
        "contract_reference": _reference(reader, agreement, "ContractReferencedDocument"),
        **_referenced_documents(reader, agreement),
        "invoiced_object_identifier": object_identifier(reader, agreement),
        "project_reference": reader.text(project, "ID"),
    }


def _referenced_documents(reader: Reader, agreement: etree._Element | None) -> dict[str, object]:
    """``ram:AdditionalReferencedDocument`` by ``ram:TypeCode``: 916 is a BG-24 entry, 50 is BT-17 (N1).

    Type code 130 (BT-18) is read by ``object_identifier``; other type codes have no business term and stay unmapped.
    """
    supporting: list[AdditionalSupportingDocument] = []
    tender: str | None = None
    for element in reader.children(agreement, "AdditionalReferencedDocument"):
        code = reader.first_text(element, "TypeCode", normalized=True)
        if code == SUPPORTING_DOCUMENT_TYPE_CODE:
            reader.use(element)
            reader.one(element, "TypeCode")
            supporting.append(
                reader.model(
                    AdditionalSupportingDocument,
                    element,
                    reference=reader.text(element, "IssuerAssignedID"),
                    external_location=reader.text(element, "URIID"),
                    description=reader.text(element, "Name"),
                    attached_document=_attachment(reader, element),
                )
            )
        elif code == TENDER_TYPE_CODE and tender is None and reader.children(element, "IssuerAssignedID"):
            reader.use(element)
            reader.one(element, "TypeCode")
            tender = reader.text(element, "IssuerAssignedID")
    return {"additional_supporting_documents": tuple(supporting), "tender_or_lot_reference": tender}


def _attachment(reader: Reader, document: etree._Element) -> BinaryObject | None:
    """BT-125: ``ram:AttachmentBinaryObject`` (base64 content, ``@mimeCode``, ``@filename``)."""
    element = reader.one(document, "AttachmentBinaryObject")
    if element is None:
        return None
    try:
        # xs:base64Binary allows whitespace between the characters; nothing else outside the alphabet.
        data = base64.b64decode("".join(content(element).split()), validate=True)
    except binascii.Error as exc:
        raise ParseError(f"BT-125: the attached document is not base64: {exc}", location=reader.path(element)) from exc
    return reader.model(
        BinaryObject,
        element,
        "BT-125",
        content=data,
        mime_code=reader.attribute(element, "mimeCode"),
        filename=reader.attribute(element, "filename"),
    )


def _delivery(
    reader: Reader, delivery: etree._Element | None, invoicing_period: InvoicingPeriod | None, root: etree._Element
) -> dict[str, object]:
    """``ram:ApplicableHeaderTradeDelivery`` (BT-15, BT-16 and BG-13, which the model gives BG-14 too)."""
    ship_to = reader.one(delivery, "ShipToTradeParty")
    event = reader.one(delivery, "ActualDeliverySupplyChainEvent")
    values = {
        "deliver_to_location_identifier": None if ship_to is None else single_id(reader, ship_to),
        "deliver_to_party_name": reader.text(ship_to, "Name"),
        "deliver_to_address": None if ship_to is None else address(reader, ship_to, DeliverToAddress),
        "actual_delivery_date": reader.date(event, "OccurrenceDateTime", "BT-72"),
        "invoicing_period": invoicing_period,
    }
    information = None
    if any(value is not None for value in values.values()):
        information = reader.model(DeliveryInformation, root if delivery is None else delivery, **values)
    return {
        "delivery": information,
        "despatch_advice_reference": _reference(reader, delivery, "DespatchAdviceReferencedDocument"),
        "receiving_advice_reference": _reference(reader, delivery, "ReceivingAdviceReferencedDocument"),
    }
