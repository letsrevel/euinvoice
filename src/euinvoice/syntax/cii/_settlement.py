"""CII ``ram:ApplicableHeaderTradeSettlement``: currencies, payee, payment, VAT, allowances, totals.

Children follow the D16B ``ram:HeaderTradeSettlementType`` sequence: ``CreditorReferenceID`` (BT-90),
``PaymentReference`` (BT-83), ``TaxCurrencyCode`` (BT-6), ``InvoiceCurrencyCode`` (BT-5),
``PayeeTradeParty`` (BG-10), ``SpecifiedTradeSettlementPaymentMeans`` (BG-16), ``ApplicableTradeTax``
(BG-23), ``BillingSpecifiedPeriod`` (BG-14), ``SpecifiedTradeAllowanceCharge`` (BG-20, BG-21),
``SpecifiedTradePaymentTerms`` (BT-20, BT-9, BT-89), ``SpecifiedTradeSettlementHeaderMonetarySummation``
(BG-22), ``InvoiceReferencedDocument`` (BG-3), ``ReceivableSpecifiedTradeAccountingAccount`` (BT-19).
"""

from lxml import etree

from euinvoice.model import DocumentTotals, Invoice, PaymentInstructions, VatBreakdown
from euinvoice.syntax.cii._build import (
    VAT,
    VAT_POINT_DATE_CODES,
    allowance_charge,
    cannot_express,
    date,
    date_time,
    decimal,
    is_iban,
    opt,
    sub,
    vat_category,
)
from euinvoice.syntax.cii._parties import payee


def settlement(parent: etree._Element, invoice: Invoice) -> None:
    """Append ``ram:ApplicableHeaderTradeSettlement``."""
    element = sub(parent, "ApplicableHeaderTradeSettlement")
    payment = invoice.payment_instructions
    debit = None if payment is None else payment.direct_debit
    if debit is not None:
        opt(element, "CreditorReferenceID", debit.bank_assigned_creditor_identifier)
    if payment is not None:
        # BT-83: at most one ram:PaymentReference (CII-SR-469).
        opt(element, "PaymentReference", payment.remittance_information)
    opt(element, "TaxCurrencyCode", invoice.vat_accounting_currency_code)
    sub(element, "InvoiceCurrencyCode", invoice.currency_code)
    if invoice.payee is not None:
        payee(element, invoice.payee)
    if payment is not None:
        _payment_means(element, payment)
    for index, breakdown in enumerate(invoice.vat_breakdown):
        _vat_breakdown(element, breakdown, invoice if index == 0 else None)
    period = None if invoice.delivery is None else invoice.delivery.invoicing_period
    if period is not None:
        billing = sub(element, "BillingSpecifiedPeriod")
        if period.start_date is not None:
            date_time(billing, "StartDateTime", period.start_date)
        if period.end_date is not None:
            date_time(billing, "EndDateTime", period.end_date)
    _allowances_and_charges(element, invoice)
    _payment_terms(element, invoice)
    _totals(element, invoice.totals, invoice)
    _preceding_invoice(element, invoice)
    if invoice.buyer_accounting_reference is not None:
        sub(sub(element, "ReceivableSpecifiedTradeAccountingAccount"), "ID", invoice.buyer_accounting_reference)


def _allowances_and_charges(parent: etree._Element, invoice: Invoice) -> None:
    """``ram:SpecifiedTradeAllowanceCharge`` (BG-20, BG-21), each with its VAT ``ram:CategoryTradeTax``."""
    items = [(a, False) for a in invoice.allowances] + [(c, True) for c in invoice.charges]
    for item, charge in items:
        element = allowance_charge(parent, "SpecifiedTradeAllowanceCharge", item, charge=charge)
        vat_category(element, "CategoryTradeTax", item.vat_category_code, item.vat_rate)


def _payment_means(parent: etree._Element, payment: PaymentInstructions) -> None:
    """``ram:SpecifiedTradeSettlementPaymentMeans`` (BG-16 with BG-17, BG-18 and BT-91).

    The model holds one BG-16 with 0..n credit transfers; CII repeats the payment means once per payee
    account (``ram:PayeePartyCreditorFinancialAccount`` is 0..1 per means), so one means is written per
    credit transfer (at least one), each with the same BT-81 and BT-82 (CII-SR-467, CII-SR-468). The card
    (BG-18) and the debited account (BT-91) go into the first.

    BT-84 is written as ``ram:IBANID`` when it passes XRechnung's IBAN check (the check BR-DE-19 runs on
    ``ram:IBANID``), else as ``ram:ProprietaryID``; BR-50 / BR-61 accept either.
    """
    # ponytail: a non-IBAN account a CIUS wants in ram:IBANID (Peppol DK-R-008's Danish giro numbers)
    # lands in ram:ProprietaryID; a profile hook (#19) is the upgrade path if that is ever needed.
    for index, transfer in enumerate(payment.credit_transfers or (None,)):
        element = sub(parent, "SpecifiedTradeSettlementPaymentMeans")
        sub(element, "TypeCode", payment.payment_means_type_code)
        opt(element, "Information", payment.payment_means_text)
        if index == 0:
            card = payment.payment_card
            if card is not None:
                financial_card = sub(element, "ApplicableTradeSettlementFinancialCard")
                opt(financial_card, "ID", card.primary_account_number)
                opt(financial_card, "CardholderName", card.holder_name)
            debit = payment.direct_debit
            if debit is not None and debit.debited_account_identifier is not None:
                # BT-91: IBANID only (CII-SR-444 warns against ProprietaryID, CII-SR-382 against AccountName).
                sub(sub(element, "PayerPartyDebtorFinancialAccount"), "IBANID", debit.debited_account_identifier)
        if transfer is None:
            continue
        account = sub(element, "PayeePartyCreditorFinancialAccount")
        iban = is_iban(transfer.payment_account_identifier)
        if iban:
            sub(account, "IBANID", transfer.payment_account_identifier)
        opt(account, "AccountName", transfer.payment_account_name)
        if not iban:
            sub(account, "ProprietaryID", transfer.payment_account_identifier)
        if transfer.payment_service_provider_identifier is not None:
            institution = sub(element, "PayeeSpecifiedCreditorFinancialInstitution")
            sub(institution, "BICID", transfer.payment_service_provider_identifier)


def _vat_breakdown(parent: etree._Element, value: VatBreakdown, invoice: Invoice | None) -> None:
    """One ``ram:ApplicableTradeTax`` (BG-23) in ``ram:TradeTaxType`` order.

    ``invoice`` is given for the first breakdown only, which also carries the document level BT-7
    (``ram:TaxPointDate``, at most once in the settlement: CII-SR-461) and BT-8 (``ram:DueDateTypeCode``,
    one distinct value: CII-SR-462), as in the KoSIT testsuite.
    """
    element = sub(parent, "ApplicableTradeTax")
    sub(element, "CalculatedAmount", decimal(value.tax_amount))
    sub(element, "TypeCode", VAT)
    opt(element, "ExemptionReason", value.exemption_reason)
    sub(element, "BasisAmount", decimal(value.taxable_amount))
    sub(element, "CategoryCode", value.category_code)
    opt(element, "ExemptionReasonCode", value.exemption_reason_code)
    if invoice is not None:
        if invoice.vat_point_date is not None:
            date(element, "TaxPointDate", invoice.vat_point_date)
        if invoice.vat_point_date_code is not None:
            sub(element, "DueDateTypeCode", VAT_POINT_DATE_CODES[invoice.vat_point_date_code])
    if value.rate is not None:
        sub(element, "RateApplicablePercent", decimal(value.rate))


def _payment_terms(parent: etree._Element, invoice: Invoice) -> None:
    """``ram:SpecifiedTradePaymentTerms`` (at most one, CII-SR-452): BT-20, BT-9 and BT-89."""
    payment = invoice.payment_instructions
    debit = None if payment is None else payment.direct_debit
    mandate = None if debit is None else debit.mandate_reference_identifier
    if invoice.payment_terms is None and invoice.payment_due_date is None and mandate is None:
        return
    element = sub(parent, "SpecifiedTradePaymentTerms")
    opt(element, "Description", invoice.payment_terms)
    if invoice.payment_due_date is not None:
        date_time(element, "DueDateDateTime", invoice.payment_due_date)
    opt(element, "DirectDebitMandateID", mandate)


def _totals(parent: etree._Element, totals: DocumentTotals, invoice: Invoice) -> None:
    """``ram:SpecifiedTradeSettlementHeaderMonetarySummation`` (BG-22).

    ``ram:TaxTotalAmount`` is the only amount with a ``@currencyID`` (the CEN ``AmountType`` context excludes
    it from CII-DT-031): BT-110 in the invoice currency (BT-5), BT-111 in the VAT accounting currency
    (BT-6), as bound by BR-53, BR-CO-15, BR-DEC-13 and BR-DEC-15.
    """
    element = sub(parent, "SpecifiedTradeSettlementHeaderMonetarySummation")
    sub(element, "LineTotalAmount", decimal(totals.sum_of_line_net_amounts))
    if totals.sum_of_charges is not None:
        sub(element, "ChargeTotalAmount", decimal(totals.sum_of_charges))
    if totals.sum_of_allowances is not None:
        sub(element, "AllowanceTotalAmount", decimal(totals.sum_of_allowances))
    sub(element, "TaxBasisTotalAmount", decimal(totals.total_without_vat))
    if totals.total_vat is not None:
        sub(element, "TaxTotalAmount", decimal(totals.total_vat), currencyID=invoice.currency_code)
    if totals.total_vat_in_accounting_currency is not None:
        if invoice.vat_accounting_currency_code is None:
            raise cannot_express(
                "BT-111 (invoice total VAT amount in accounting currency)",
                "its ram:TaxTotalAmount/@currencyID is the VAT accounting currency code BT-6, which is not set",
            )
        currency = invoice.vat_accounting_currency_code
        sub(element, "TaxTotalAmount", decimal(totals.total_vat_in_accounting_currency), currencyID=currency)
    if totals.rounding_amount is not None:
        sub(element, "RoundingAmount", decimal(totals.rounding_amount))
    sub(element, "GrandTotalAmount", decimal(totals.total_with_vat))
    if totals.paid_amount is not None:
        sub(element, "TotalPrepaidAmount", decimal(totals.paid_amount))
    sub(element, "DuePayableAmount", decimal(totals.amount_due))


def _preceding_invoice(parent: etree._Element, invoice: Invoice) -> None:
    """``ram:InvoiceReferencedDocument`` (BG-3), which the D16B XSD allows at most once."""
    references = invoice.preceding_invoice_references
    if not references:
        return
    if len(references) > 1:
        raise cannot_express(
            "BG-3 (preceding invoice reference)",
            f"the D16B XSD allows one ram:InvoiceReferencedDocument, the invoice has {len(references)}",
        )
    element = sub(parent, "InvoiceReferencedDocument")
    sub(element, "IssuerAssignedID", references[0].reference)
    if references[0].issue_date is not None:
        # BT-26: qdt:FormattedDateTimeType (CII-DT-027 allows it only here).
        date_time(element, "FormattedIssueDateTime", references[0].issue_date, qualified=True)
