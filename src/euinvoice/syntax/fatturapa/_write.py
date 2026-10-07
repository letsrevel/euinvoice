"""The FPR12 writer: :class:`euinvoice.model.Invoice` (with ``Invoice.it``) to one FatturaPA 1.2.3 file (#119).

Scope (plan M11): FPR12 only, one ``FatturaElettronicaBody``, TipoDocumento TD01, TD04, TD24 and TD17, unsigned.
The mapping is App. 4.1 of the SdI "Regole tecniche fatture europee" v2.6 (FatturaPA ↔ EN 16931, written for
UBL/CII to public administrations and applied to FPR12 by analogy, plan §3) with the code tables of its App. 5;
the element order is the pinned XSD 1.2.3 (``Schema_VFPR12_v1.2.3.xsd``): ``FatturaElettronicaType``,
``FatturaElettronicaHeaderType``, ``DatiTrasmissioneType``, ``FatturaElettronicaBodyType``, ``DatiGeneraliType``,
``DatiGeneraliDocumentoType``, ``DatiBolloType``, ``DatiDocumentiCorrelatiType``, ``DatiPagamentoType`` and
``DettaglioPagamentoType`` here, the parties and lines in their modules.

Nothing is dropped silently (plan §1): :func:`~._write_preflight.preflight` reports what is missing and what FPR12
cannot carry, and :func:`serialize` refuses with :class:`~euinvoice.errors.ModelError` a value that does not fit its
XSD type (see :mod:`._write_format`).
"""

import typing as t
from decimal import Decimal

from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ModelError
from euinvoice.model import Invoice, PaymentInstructions
from euinvoice.model.it import ItalianExtension, ItalianPayment, ModalitaPagamento
from euinvoice.report import Severity
from euinvoice.syntax.fatturapa._write_codes import PAYMENT_METHOD_OF_MEANS
from euinvoice.syntax.fatturapa._write_format import BASIC, amount2, child, date, matching, text
from euinvoice.syntax.fatturapa._write_lines import summarize, write_goods
from euinvoice.syntax.fatturapa._write_parties import write_buyer, write_seller
from euinvoice.syntax.fatturapa._write_preflight import preflight
from euinvoice.syntax.fatturapa._write_refuse import stamp_duty
from euinvoice.syntax.fatturapa.transmission import Transmission

__all__ = ["FORMAT", "serialize", "write"]

FORMAT: t.Final = "FPR12"
"""``FormatoTrasmissione`` (1.1.3) and the root's ``versione`` (SdI 00428 requires them equal)."""


def write(invoice: Invoice, transmission: Transmission) -> bytes:
    """Serialize an invoice as an FPR12 FatturaPA 1.2.3 document with one body.

    The pre-flight (:func:`~euinvoice.syntax.fatturapa.preflight`) runs first. The SdI checks of Allegato A 1.9.1 do
    not: run :func:`euinvoice.validate` on the result, or write through :func:`euinvoice.to_xml`, which runs them.

    Args:
        invoice: The invoice, with ``Invoice.it`` set.
        transmission: The transmission header (:class:`~euinvoice.syntax.fatturapa.Transmission`).

    Returns:
        The UTF-8 encoded document with an XML declaration, unsigned.

    Raises:
        ModelError: The pre-flight reports an ``error`` (the message lists every one), or a value does not fit its XSD
            type (length, characters, decimals, CAP, Provincia, line number, IBAN, …); that message starts with the
            business term and its model path.
    """
    blocking = [f for f in preflight(invoice) if f.severity in (Severity.FATAL, Severity.ERROR)]
    if blocking:
        raise ModelError(
            "invoice fails the FatturaPA pre-flight: "
            + "; ".join(f"{f.rule_id} at {f.location}: {f.message}" for f in blocking)
        )
    return serialize(invoice, transmission)


def serialize(invoice: Invoice, transmission: Transmission) -> bytes:
    """Write an invoice whose pre-flight has no ``error`` (:func:`write` without that gate, for ``to_xml``).

    Raises:
        ModelError: A value does not fit its XSD type.
    """
    it = t.cast(ItalianExtension, invoice.it)  # the pre-flight requires it
    blocks, _ = summarize(invoice, it)
    root = etree.Element(f"{{{_xml.FATTURAPA}}}FatturaElettronica", nsmap={"p": _xml.FATTURAPA})
    root.set("versione", FORMAT)
    header = child(root, "FatturaElettronicaHeader")
    _transmission(header, transmission)
    write_seller(header, invoice, it)
    write_buyer(header, invoice)
    if it.issuer is not None:
        child(header, "SoggettoEmittente", it.issuer)
    body = child(root, "FatturaElettronicaBody")
    _general(body, invoice, it, stamp_duty(invoice, it))
    write_goods(body, invoice, blocks)
    if it.payment is not None:
        _payment(body, invoice, it.payment)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _transmission(header: etree._Element, transmission: Transmission) -> None:
    """1.1 DatiTrasmissione from the transmission header (``ContattiTrasmittente`` is not written)."""
    data = child(header, "DatiTrasmissione")
    transmitter = child(data, "IdTrasmittente")
    child(transmitter, "IdPaese", transmission.transmitter_country)
    child(transmitter, "IdCodice", transmission.transmitter_code)
    child(data, "ProgressivoInvio", transmission.transmission_number)
    child(data, "FormatoTrasmissione", FORMAT)
    child(data, "CodiceDestinatario", transmission.recipient_code)
    if transmission.recipient_pec is not None:
        child(data, "PECDestinatario", transmission.recipient_pec)


def _general(body: etree._Element, invoice: Invoice, it: ItalianExtension, stamp_duty: Decimal | None) -> None:
    """2.1 DatiGenerali (rows 2.1.1.1-2.1.1.11, 2.1.2.2, 2.1.3.2, 2.1.5.2, 2.1.6)."""
    general = child(body, "DatiGenerali")
    document = child(general, "DatiGeneraliDocumento")
    child(document, "TipoDocumento", it.document_type)
    child(
        document, "Divisa", matching(invoice.currency_code, "[A-Z]{3}", "BT-5 (currency_code)", "Divisa (DivisaType)")
    )
    # ponytail: Data is BT-2. Row 2.1.1.3 also names BT-72 "nel caso in cui la data operazione sia differente"; BT-72 is
    # refused (#133).
    child(document, "Data", date(invoice.issue_date, "BT-2 (issue_date)", "2.1.1.3 Data", invoice_date=True))
    child(
        document,
        "Numero",
        text(invoice.number, "BT-1 (number)", "2.1.1.4 Numero (String20Type)", maximum=20, charset=BASIC),
    )
    if stamp_duty is not None:
        bollo = child(document, "DatiBollo")
        child(bollo, "BolloVirtuale", "SI")
        child(bollo, "ImportoBollo", amount2(stamp_duty, "BT-99/BT-92", "2.1.1.6.2 ImportoBollo"))
    totals = invoice.totals
    child(
        document,
        "ImportoTotaleDocumento",
        amount2(totals.total_with_vat, "BT-112 (totals.total_with_vat)", "2.1.1.9 ImportoTotaleDocumento"),
    )
    if totals.rounding_amount is not None:
        child(
            document,
            "Arrotondamento",
            amount2(totals.rounding_amount, "BT-114 (totals.rounding_amount)", "2.1.1.10 Arrotondamento"),
        )
    for index, note in enumerate(invoice.notes):
        if note.note is not None:
            child(
                document,
                "Causale",
                text(note.note, f"BT-22 (notes[{index}].note)", "2.1.1.11 Causale (String200LatinType)", maximum=200),
            )
    references = (
        ("DatiOrdineAcquisto", "BT-13 (purchase_order_reference)", invoice.purchase_order_reference),
        ("DatiContratto", "BT-12 (contract_reference)", invoice.contract_reference),
        ("DatiRicezione", "BT-15 (receiving_advice_reference)", invoice.receiving_advice_reference),
    )
    for tag, term, value in references:
        if value is not None:
            child(child(general, tag), "IdDocumento", _document_id(value, term))
    for index, preceding in enumerate(invoice.preceding_invoice_references):
        linked = child(general, "DatiFattureCollegate")
        child(
            linked, "IdDocumento", _document_id(preceding.reference, f"BT-25 (preceding_invoice_references[{index}])")
        )
        if preceding.issue_date is not None:
            child(
                linked,
                "Data",
                date(preceding.issue_date, f"BT-26 (preceding_invoice_references[{index}])", "2.1.6.3 Data"),
            )


def _document_id(value: str, term: str) -> str:
    return text(value, term, "IdDocumento (String20Type)", maximum=20, charset=BASIC)


def _method(invoice: Invoice, payment: ItalianPayment) -> ModalitaPagamento:
    """2.4.2.2 ModalitaPagamento: ``it.payment.method``, else BT-81 through App. 5.6 (the pre-flight checks them)."""
    if payment.method is not None:
        return payment.method
    instructions = t.cast(PaymentInstructions, invoice.payment_instructions)
    return PAYMENT_METHOD_OF_MEANS[instructions.payment_means_type_code]


def _payment(body: etree._Element, invoice: Invoice, payment: ItalianPayment) -> None:
    """2.4 DatiPagamento with one DettaglioPagamento.

    Rows 2.4.1, 2.4.2.1, 2.4.2.2, 2.4.2.5, 2.4.2.6, 2.4.2.13, 2.4.2.16 and 2.4.2.21.
    """
    data = child(body, "DatiPagamento")
    child(data, "CondizioniPagamento", payment.conditions)
    detail = child(data, "DettaglioPagamento")
    if invoice.payee is not None:
        child(
            detail,
            "Beneficiario",
            text(invoice.payee.name, "BT-59 (payee.name)", "2.4.2.1 Beneficiario (String200LatinType)", maximum=200),
        )
    child(detail, "ModalitaPagamento", _method(invoice, payment))
    if invoice.payment_due_date is not None:
        child(
            detail,
            "DataScadenzaPagamento",
            date(invoice.payment_due_date, "BT-9 (payment_due_date)", "2.4.2.5 DataScadenzaPagamento"),
        )
    child(
        detail,
        "ImportoPagamento",
        amount2(invoice.totals.amount_due, "BT-115 (totals.amount_due)", "2.4.2.6 ImportoPagamento"),
    )
    instructions = invoice.payment_instructions
    if instructions is None:
        return
    for transfer in instructions.credit_transfers[:1]:  # the pre-flight refuses a second one
        path = "payment_instructions.credit_transfers[0]"
        child(
            detail,
            "IBAN",
            matching(
                transfer.payment_account_identifier,
                "[a-zA-Z]{2}[0-9]{2}[a-zA-Z0-9]{11,30}",
                f"BT-84 ({path}.payment_account_identifier)",
                "2.4.2.13 IBAN (IBANType)",
            ),
        )
        if transfer.payment_service_provider_identifier is not None:
            child(
                detail,
                "BIC",
                matching(
                    transfer.payment_service_provider_identifier,
                    "[A-Z]{6}[A-Z2-9][A-NP-Z0-9]([A-Z0-9]{3}){0,1}",
                    f"BT-86 ({path}.payment_service_provider_identifier)",
                    "2.4.2.16 BIC (BICType)",
                ),
            )
    if instructions.remittance_information is not None:
        child(
            detail,
            "CodicePagamento",
            text(
                instructions.remittance_information,
                "BT-83 (payment_instructions.remittance_information)",
                "2.4.2.21 CodicePagamento (String60Type)",
                maximum=60,
                charset=BASIC,
            ),
        )
