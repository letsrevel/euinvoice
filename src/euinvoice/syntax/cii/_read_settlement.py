"""Reading ``ram:ApplicableHeaderTradeSettlement``: currencies, payee, payment, VAT, allowances, totals.

The inverse of ``_settlement.py``; XPaths per business term are those of ``docs/reference/bt-mapping.md``.
"""

import datetime

from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ParseError
from euinvoice.model import (
    CreditTransfer,
    DirectDebit,
    DocumentLevelAllowance,
    DocumentLevelCharge,
    DocumentTotals,
    InvoicingPeriod,
    PaymentCardInformation,
    PaymentInstructions,
    PrecedingInvoiceReference,
    VatBreakdown,
)
from euinvoice.syntax._marks import XML_SPACE, normalize_space
from euinvoice.syntax.cii._build import VAT, VAT_POINT_DATE_CODES_FROM_CII
from euinvoice.syntax.cii._read_common import allowance_charge_values, period_dates, vat_category
from euinvoice.syntax.cii._read_parties import payee
from euinvoice.syntax.cii._reader import Reader, content


def settlement(reader: Reader, transaction: etree._Element | None) -> tuple[dict[str, object], InvoicingPeriod | None]:
    """Read the settlement.

    Returns:
        The :class:`~euinvoice.model.Invoice` fields it carries, and the invoicing period BG-14 (which the model
        keeps under BG-13).
    """
    element = reader.one(transaction, "ApplicableHeaderTradeSettlement")
    currency = reader.text(element, "InvoiceCurrencyCode")
    tax_currency = reader.text(element, "TaxCurrencyCode")
    breakdown, point_date, point_code = _vat_breakdown(reader, element)
    terms = reader.one(element, "SpecifiedTradePaymentTerms")
    fields: dict[str, object] = {
        "currency_code": currency,
        "vat_accounting_currency_code": tax_currency,
        "payee": payee(reader, element),
        "payment_instructions": _payment(reader, element, terms),
        "vat_breakdown": breakdown,
        "vat_point_date": point_date,
        "vat_point_date_code": point_code,
        "payment_terms": reader.text(terms, "Description"),
        "payment_due_date": reader.date(terms, "DueDateDateTime", "BT-9"),
        "totals": _totals(reader, element, currency, tax_currency),
        "preceding_invoice_references": tuple(
            reader.model(
                PrecedingInvoiceReference,
                document,
                reference=reader.text(document, "IssuerAssignedID"),
                # BT-26: qdt:FormattedDateTimeType (CII-DT-027).
                issue_date=reader.date(document, "FormattedIssueDateTime", "BT-26", namespace=_xml.CII_QDT),
            )
            for document in reader.each(element, "InvoiceReferencedDocument")
        ),
        "buyer_accounting_reference": reader.text(
            reader.one(element, "ReceivableSpecifiedTradeAccountingAccount"), "ID"
        ),
    }
    allowances: list[DocumentLevelAllowance] = []
    charges: list[DocumentLevelCharge] = []
    for item in reader.children(element, "SpecifiedTradeAllowanceCharge"):
        read = allowance_charge_values(reader, item)
        if read is None:
            continue
        charge, values = read
        tax = vat_category(reader, item, "CategoryTradeTax")
        category, rate = (None, None) if tax is None else tax[1:]
        if charge:
            charges.append(reader.model(DocumentLevelCharge, item, vat_category_code=category, vat_rate=rate, **values))
        else:
            allowances.append(
                reader.model(DocumentLevelAllowance, item, vat_category_code=category, vat_rate=rate, **values)
            )
    fields["allowances"] = tuple(allowances)
    fields["charges"] = tuple(charges)
    period = reader.one(element, "BillingSpecifiedPeriod")
    invoicing_period = (
        None
        if period is None
        else reader.model(InvoicingPeriod, period, **period_dates(reader, period, ("BT-73", "BT-74")))
    )
    return fields, invoicing_period


def _vat_breakdown(
    reader: Reader, settlement: etree._Element | None
) -> tuple[tuple[VatBreakdown, ...], datetime.date | None, str | None]:
    """Every ``ram:ApplicableTradeTax`` with type ``VAT`` (BG-23), plus the document level BT-7 and BT-8.

    BT-7 (``ram:TaxPointDate``) and BT-8 (``ram:DueDateTypeCode``) may sit on any breakdown, with one distinct value
    each: CII-SR-461 allows at most one ``ram:TaxPointDate`` per breakdown and CII-SR-462 one distinct
    ``ram:DueDateTypeCode`` across them. The writer puts both on the first breakdown. A later value that differs
    from the first one read stays unmapped.
    BT-8 is translated from UNTDID 2475 back to the model's UNTDID 2005 (``VAT_POINT_DATE_CODES_FROM_CII``).

    Raises:
        ParseError: A ``ram:DueDateTypeCode`` outside the CII list 5, 29, 72 (CII BR-CL-06).
    """
    breakdowns: list[VatBreakdown] = []
    point_date: datetime.date | None = None
    point_code: str | None = None
    for element in reader.children(settlement, "ApplicableTradeTax"):
        if reader.first_text(element, "TypeCode", normalized=True) != VAT:
            continue
        reader.use(element)
        reader.one(element, "TypeCode")
        holder = reader.children(element, "TaxPointDate")
        value = reader.date(element, "TaxPointDate", "BT-7", string="DateString")
        if value is not None and point_date is None:
            point_date = value
        elif value is not None and value != point_date:
            reader.discard(holder[0])
        code_element = reader.one(element, "DueDateTypeCode")
        if code_element is not None:
            code = _vat_point_date_code(reader, code_element)
            if point_code is None:
                point_code = code
            elif code != point_code:
                reader.discard(code_element)
        breakdowns.append(
            reader.model(
                VatBreakdown,
                element,
                tax_amount=reader.text(element, "CalculatedAmount"),
                exemption_reason=reader.text(element, "ExemptionReason"),
                taxable_amount=reader.text(element, "BasisAmount"),
                category_code=reader.text(element, "CategoryCode"),
                exemption_reason_code=reader.text(element, "ExemptionReasonCode"),
                rate=reader.text(element, "RateApplicablePercent"),
            )
        )
    return tuple(breakdowns), point_date, point_code


def _vat_point_date_code(reader: Reader, element: etree._Element) -> str:
    """BT-8: a UNTDID 2475 ``ram:DueDateTypeCode`` as the model's UNTDID 2005 code."""
    text = normalize_space(content(element))
    code = VAT_POINT_DATE_CODES_FROM_CII.get(text)
    if code is None:
        raise ParseError(
            f"BT-8: VAT point date code {text!r} is not one of the UNTDID 2475 codes CII allows: "
            f"{', '.join(sorted(VAT_POINT_DATE_CODES_FROM_CII, key=int))} (CII BR-CL-06)",
            location=reader.path(element),
        )
    return code


def _payment(
    reader: Reader, settlement: etree._Element | None, terms: etree._Element | None
) -> PaymentInstructions | None:
    """BG-16 with BG-17, BG-18 and BG-19, from every ``ram:SpecifiedTradeSettlementPaymentMeans``.

    BT-81 and BT-82 are the first ``ram:TypeCode`` and the first ``ram:Information`` across the payment means, as
    CII-SR-467 and CII-SR-468 (``EN16931-CII-syntax.sch``) take them: each present one must equal it under
    ``normalize-space``, and a missing one does not count. The writer repeats the payment means once per credit
    transfer, so each matching means adds its ``ram:PayeePartyCreditorFinancialAccount`` (BT-84 from
    ``ram:IBANID``, else ``ram:ProprietaryID``) as one BG-17; a means whose own code or text differs stays unmapped
    as a whole. The first card (BG-18) and the first debited account (BT-91) are mapped. BT-83, BT-89 and BT-90
    belong to BG-16, which needs BT-81 (BR-49): without any payment means they stay unmapped instead of being
    invented or refused.
    """
    means = reader.children(settlement, "SpecifiedTradeSettlementPaymentMeans")
    if not means:
        return None
    code = next((c for m in means if (c := reader.first_text(m, "TypeCode")) is not None), None)
    text = next((i for m in means if (i := reader.first_text(m, "Information")) is not None), None)
    card: PaymentCardInformation | None = None
    debited: str | None = None
    transfers: list[CreditTransfer] = []
    accepted: list[etree._Element] = []
    for element in means:
        if not (_matches(reader, element, "TypeCode", code) and _matches(reader, element, "Information", text)):
            continue
        reader.one(element, "TypeCode")
        reader.one(element, "Information")
        accepted.append(reader.use(element))
        financial_card = reader.children(element, "ApplicableTradeSettlementFinancialCard")
        if card is None and financial_card:
            reader.use(financial_card[0])
            card = reader.model(
                PaymentCardInformation,
                financial_card[0],
                primary_account_number=reader.text(financial_card[0], "ID"),
                holder_name=reader.text(financial_card[0], "CardholderName"),
            )
        debtor = reader.children(element, "PayerPartyDebtorFinancialAccount")
        if debited is None and debtor:
            # BT-91: IBANID only (CII-SR-444 warns that ProprietaryID should not be present; one stays unmapped).
            debited = reader.text(reader.use(debtor[0]), "IBANID")
        account = reader.one(element, "PayeePartyCreditorFinancialAccount")
        if account is not None:
            identifier = reader.text(account, "IBANID")
            transfers.append(
                reader.model(
                    CreditTransfer,
                    account,
                    payment_account_identifier=reader.text(account, "ProprietaryID")
                    if identifier is None
                    else identifier,
                    payment_account_name=reader.text(account, "AccountName"),
                    payment_service_provider_identifier=reader.text(
                        reader.one(element, "PayeeSpecifiedCreditorFinancialInstitution"), "BICID"
                    ),
                )
            )
    mandate = reader.text(terms, "DirectDebitMandateID")
    creditor = reader.text(settlement, "CreditorReferenceID")
    debit = None
    if (mandate, creditor, debited) != (None, None, None):
        debit = reader.model(
            DirectDebit,
            accepted[0],
            mandate_reference_identifier=mandate,
            bank_assigned_creditor_identifier=creditor,
            debited_account_identifier=debited,
        )
    return reader.model(
        PaymentInstructions,
        accepted[0],
        payment_means_type_code=code,
        payment_means_text=text,
        # BT-83: one ram:PaymentReference (CII-SR-469).
        remittance_information=reader.text(settlement, "PaymentReference"),
        credit_transfers=tuple(transfers),
        payment_card=card,
        direct_debit=debit,
    )


def _matches(reader: Reader, means: etree._Element, name: str, first: str | None) -> bool:
    """Whether the ``ram:<name>`` of a payment means is absent or equals ``first`` under ``normalize-space``."""
    own = reader.first_text(means, name, normalized=True)
    return own is None or first is None or own == normalize_space(first)


def _totals(
    reader: Reader, settlement: etree._Element | None, currency: str | None, tax_currency: str | None
) -> DocumentTotals | None:
    """``ram:SpecifiedTradeSettlementHeaderMonetarySummation`` (BG-22).

    ``ram:TaxTotalAmount`` is BT-110 when its ``@currencyID`` is the invoice currency BT-5 and BT-111 when it is the
    VAT accounting currency BT-6 (KoSIT binding; BR-53, BR-CO-15, BR-DEC-13, BR-DEC-15). One without either currency
    has no business term and stays unmapped.
    """
    element = reader.one(settlement, "SpecifiedTradeSettlementHeaderMonetarySummation")
    if element is None:
        return None
    total_vat: str | None = None
    total_vat_accounting: str | None = None
    for amount in reader.children(element, "TaxTotalAmount"):
        unit = amount.get("currencyID")
        if total_vat is None and _same_code(unit, currency):
            total_vat = content(amount)
        elif total_vat_accounting is None and _same_code(unit, tax_currency):
            total_vat_accounting = content(amount)
        else:
            continue
        reader.use(amount)
        reader.attribute(amount, "currencyID")
    return reader.model(
        DocumentTotals,
        element,
        sum_of_line_net_amounts=reader.text(element, "LineTotalAmount"),
        sum_of_charges=reader.text(element, "ChargeTotalAmount"),
        sum_of_allowances=reader.text(element, "AllowanceTotalAmount"),
        total_without_vat=reader.text(element, "TaxBasisTotalAmount"),
        total_vat=total_vat,
        total_vat_in_accounting_currency=total_vat_accounting,
        rounding_amount=reader.text(element, "RoundingAmount"),
        total_with_vat=reader.text(element, "GrandTotalAmount"),
        paid_amount=reader.text(element, "TotalPrepaidAmount"),
        amount_due=reader.text(element, "DuePayableAmount"),
    )


def _same_code(left: str | None, right: str | None) -> bool:
    """Whether two codes are present and equal once stripped of XML whitespace (as the model stores codes)."""
    return left is not None and right is not None and left.strip(XML_SPACE) == right.strip(XML_SPACE)
