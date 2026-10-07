"""The FPR12 writer: :class:`euinvoice.model.Invoice` (with ``Invoice.it``) to one FatturaPA 1.2.3 file (#119).

Scope (plan M11): FPR12 only, one ``FatturaElettronicaBody``, TipoDocumento TD01, TD04, TD24 and TD17, unsigned.
The mapping is App. 4.1 of the SdI "Regole tecniche fatture europee" v2.6 (FatturaPA ↔ EN 16931, written for
UBL/CII to public administrations and applied to FPR12 by analogy, plan §3) with the code tables of its App. 5;
the element order is the pinned XSD 1.2.3 (``Schema_VFPR12_v1.2.3.xsd``): ``FatturaElettronicaType``,
``FatturaElettronicaHeaderType``, ``DatiTrasmissioneType``, ``FatturaElettronicaBodyType``, ``DatiGeneraliType``,
``DatiGeneraliDocumentoType``, ``DatiBolloType``, ``DatiDocumentiCorrelatiType``, ``DatiPagamentoType`` and
``DettaglioPagamentoType`` here, the parties and lines in their modules.

Nothing is dropped silently (plan §1): :func:`preflight` reports what is missing, and :func:`write` refuses with
:class:`~euinvoice.errors.ModelError` whatever FatturaPA cannot carry (see :mod:`._write_refuse`) or carry exactly
(see :mod:`._write_format`).
"""

import typing as t
from decimal import Decimal

from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ModelError
from euinvoice.model import Invoice, PaymentInstructions
from euinvoice.model.it import ItalianExtension, ItalianPayment, ModalitaPagamento, TipoDocumento
from euinvoice.report import Severity, ValidationReport
from euinvoice.syntax.fatturapa._write_codes import PAYMENT_METHOD_OF_MEANS
from euinvoice.syntax.fatturapa._write_format import BASIC, amount2, cannot_express, child, date, matching, text
from euinvoice.syntax.fatturapa._write_lines import write_goods
from euinvoice.syntax.fatturapa._write_parties import write_buyer, write_seller
from euinvoice.syntax.fatturapa._write_preflight import preflight
from euinvoice.syntax.fatturapa._write_refuse import refuse_unwritten
from euinvoice.syntax.fatturapa.options import WriterOptions

__all__ = ["FORMAT", "STAMP_DUTY_ALLOWANCE", "STAMP_DUTY_CHARGE", "STAMP_DUTY_REASON", "write"]

FORMAT: t.Final = "FPR12"
"""``FormatoTrasmissione`` (1.1.3) and the root's ``versione`` (SdI 00428 requires them equal)."""
STAMP_DUTY_CHARGE: t.Final = "SAE"
"""BT-105 of the document level charge that is the stamp duty of an invoice (App. 4.1 row 2.1.1.6)."""
STAMP_DUTY_ALLOWANCE: t.Final = "95"
"""BT-98 of the document level allowance that is the stamp duty of a credit note (App. 4.1 row 2.1.1.6)."""
STAMP_DUTY_REASON: t.Final = "BOLLO"
"""The reason text BR-IT-DC-480 of the Regole tecniche v2.6 (App. 2) gives the stamp duty charge."""


def write(invoice: Invoice, options: WriterOptions) -> bytes:
    """Serialize an invoice as an FPR12 FatturaPA 1.2.3 document with one body.

    Args:
        invoice: The invoice, with ``Invoice.it`` set.
        options: The transmission header (:class:`~euinvoice.syntax.fatturapa.WriterOptions`).

    Returns:
        The UTF-8 encoded document with an XML declaration, unsigned.

    Raises:
        ModelError: :func:`preflight` reports an ``error`` (the message lists them), or the invoice holds something
            FPR12 cannot carry: a business term outside the mapping, a value that does not fit its XSD type (length,
            characters, decimals), a document level allowance or charge other than the stamp duty, VAT category O, L
            or M, a VAT BREAKDOWN its lines do not add up to, or an ``it.vat_summaries`` entry no line matches. The
            message starts with the business term or extension path.
    """
    report = ValidationReport(preflight(invoice))
    if not report.ok:
        raise ModelError(
            "invoice fails the FatturaPA pre-flight: "
            + "; ".join(
                f"{f.rule_id} at {f.location}: {f.message}"
                for f in report.findings
                if f.severity in (Severity.FATAL, Severity.ERROR)
            )
        )
    it = t.cast(ItalianExtension, invoice.it)  # preflight requires it
    refuse_unwritten(invoice)
    stamp_duty = _stamp_duty(invoice, it)
    root = etree.Element(f"{{{_xml.FATTURAPA}}}FatturaElettronica", nsmap={"p": _xml.FATTURAPA})
    root.set("versione", FORMAT)
    header = child(root, "FatturaElettronicaHeader")
    _transmission(header, options)
    write_seller(header, invoice, it)
    write_buyer(header, invoice)
    if it.issuer is not None:
        child(header, "SoggettoEmittente", it.issuer)
    body = child(root, "FatturaElettronicaBody")
    _general(body, invoice, it, stamp_duty)
    write_goods(body, invoice, it)
    if it.payment is not None:
        _payment(body, invoice, it.payment)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _transmission(header: etree._Element, options: WriterOptions) -> None:
    """1.1 DatiTrasmissione from the writer options (``ContattiTrasmittente`` is not written)."""
    transmission = child(header, "DatiTrasmissione")
    transmitter = child(transmission, "IdTrasmittente")
    child(transmitter, "IdPaese", options.transmitter_country)
    child(transmitter, "IdCodice", options.transmitter_code)
    child(transmission, "ProgressivoInvio", options.progressive)
    child(transmission, "FormatoTrasmissione", FORMAT)
    child(transmission, "CodiceDestinatario", options.recipient_code)
    if options.recipient_pec is not None:
        child(transmission, "PECDestinatario", options.recipient_pec)


def _stamp_duty(invoice: Invoice, it: ItalianExtension) -> Decimal | None:
    """ImportoBollo of 2.1.1.6 DatiBollo, from the one allowance or charge that is the stamp duty (row 2.1.1.6).

    Every other document level allowance or charge is refused: FatturaPA's 2.1.1.8 ScontoMaggiorazione does not
    reduce the summaries' taxable amount (SdI 00422), so it cannot carry BG-20 / BG-21 (#133).
    """
    credit_note = it.document_type is TipoDocumento.TD04
    found: Decimal | None = None
    entries = [
        (
            f"allowances[{i}]",
            "BG-20",
            "BT-97",
            e.amount,
            e.reason,
            credit_note and e.reason_code == STAMP_DUTY_ALLOWANCE,
        )
        for i, e in enumerate(invoice.allowances)
    ] + [
        (f"charges[{i}]", "BG-21", "BT-104", e.amount, e.reason, not credit_note and e.reason_code == STAMP_DUTY_CHARGE)
        for i, e in enumerate(invoice.charges)
    ]
    for path, group, reason_term, amount, reason, is_stamp_duty in entries:
        term = f"{group} ({path})"
        if not is_stamp_duty:
            raise cannot_express(
                term,
                "only the stamp duty is written (2.1.1.6 DatiBollo: BT-105 = SAE on an invoice, BT-98 = 95 on a "
                "credit note, App. 4.1); 2.1.1.8 ScontoMaggiorazione does not reduce the DatiRiepilogo taxable amount "
                "(SdI 00422), so other document level allowances and charges are refused (#133)",
            )
        if found is not None:
            raise cannot_express(term, "2.1.1.6 DatiBollo occurs at most once (DatiGeneraliDocumentoType)")
        if amount != 0:
            raise cannot_express(
                f"{group} ({path}.amount)",
                "a stamp duty charged to the buyer is not written: its amount would be in the VAT BREAKDOWN, which "
                "DatiRiepilogo cannot carry (SdI 00422), and BR-IT-DC-480 sets it to 0 (#133)",
            )
        if reason is not None and reason != STAMP_DUTY_REASON:
            raise cannot_express(
                f"{reason_term} ({path}.reason)",
                f"2.1.1.6 DatiBollo has no reason; only {STAMP_DUTY_REASON!r} (BR-IT-DC-480) is implied by it",
            )
        found = amount
    return found


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
    """2.4.2.2 ModalitaPagamento: ``it.payment.method``, else BT-81 through App. 5.6 (preflight checks one exists)."""
    instructions: PaymentInstructions | None = invoice.payment_instructions
    means = None if instructions is None else instructions.payment_means_type_code
    mapped = None if means is None else PAYMENT_METHOD_OF_MEANS.get(means)
    if payment.method is None:
        return t.cast(ModalitaPagamento, mapped)
    if means is not None and mapped is not payment.method:
        found = "no ModalitaPagamento" if mapped is None else f"ModalitaPagamento {mapped}"
        raise cannot_express(
            "BT-81 (payment_instructions.payment_means_type_code)",
            f"App. 5.6 gives BT-81 {means} {found}, but it.payment.method is {payment.method}; 2.4.2.2 holds one code",
        )
    return payment.method


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
    transfers = instructions.credit_transfers
    if len(transfers) > 1:
        raise cannot_express(
            "BG-17 (payment_instructions.credit_transfers)",
            "one DettaglioPagamento has one IBAN; the v1 writer writes one DettaglioPagamento",
        )
    if transfers:
        transfer = transfers[0]
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
