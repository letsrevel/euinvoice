"""Pull the amounts ``calc`` needs out of an upstream UBL or CII example into a synthetic draft.

XPaths: UBL per Peppol BIS 3.0 syntax binding, CII per the XRechnung 3.0.2 specification §11, as
listed in ``docs/reference/bt-mapping.md``. Only amounts, quantities, VAT categories, rates and
exemption reasons are taken; every party, name and identifier in the draft is synthetic.
"""

import dataclasses
import datetime
import typing as t
from decimal import Decimal

from lxml import etree

from euinvoice import _xml, calc
from euinvoice.model import (
    Buyer,
    BuyerPostalAddress,
    DocumentLevelAllowance,
    DocumentLevelCharge,
    InvoiceDraft,
    InvoiceLineAllowance,
    InvoiceLineCharge,
    ItemInformation,
    LineDraft,
    LineVatInformation,
    PriceDetails,
    ProcessControl,
    Seller,
    SellerPostalAddress,
)

Group = tuple[str, Decimal | None, Decimal, Decimal]


@dataclasses.dataclass
class Extracted:
    """What an example says: the draft inputs and the values ``complete()`` must reproduce."""

    draft: InvoiceDraft
    line_net_amounts: list[Decimal]
    totals: dict[str, Decimal]
    breakdown: list[Group]
    exemption_reasons: dict[str, calc.ExemptionReason]

    def with_file_line_nets(self) -> InvoiceDraft:
        """The draft with each line reduced to quantity ±1 at net price |BT-131| of the file.

        EN 16931 has no rule for BT-131 and several CEN examples do not follow Peppol R120 (e.g.
        ``guide-example3.xml``: quantity 2 at 800.00 with BT-131 400.00), so the totals and the VAT
        breakdown are derived from the file's own line net amounts.
        """
        lines = tuple(
            LineDraft.model_validate(
                {
                    **dict(line),
                    "invoiced_quantity": Decimal(-1 if net < 0 else 1),
                    "allowances": (),
                    "charges": (),
                    "price_details": PriceDetails(item_net_price=abs(net)),
                }
            )
            for line, net in zip(self.draft.lines, self.line_net_amounts, strict=True)
        )
        return InvoiceDraft.model_validate({**dict(self.draft), "lines": lines})


def _dec(node: etree._Element, path: str, ns: dict[str, str]) -> Decimal | None:
    found = node.xpath(f"string({path})", namespaces=ns)
    text = str(found).strip()
    return Decimal(text) if text else None


def _amounts(node: etree._Element, path: str, ns: dict[str, str]) -> list[Decimal]:
    return [Decimal(str(found.text).strip()) for found in _nodes(node, path, ns)]


def _text(node: etree._Element, path: str, ns: dict[str, str]) -> str | None:
    text = str(node.xpath(f"string({path})", namespaces=ns)).strip()
    return text or None


def _nodes(node: etree._Element, path: str, ns: dict[str, str]) -> list[etree._Element]:
    return t.cast(list[etree._Element], node.xpath(path, namespaces=ns))


def _shell(currency: str, tax_currency: str | None, lines: list[LineDraft], **kwargs: t.Any) -> InvoiceDraft:
    return InvoiceDraft(
        number="EXAMPLE-1",
        issue_date=datetime.date(2026, 1, 1),
        type_code="380",
        currency_code=currency,
        vat_accounting_currency_code=tax_currency if tax_currency != currency else None,
        process_control=ProcessControl(specification_identifier="urn:cen.eu:en16931:2017"),
        seller=Seller(name="Seller Example", postal_address=SellerPostalAddress(country_code="DE")),
        buyer=Buyer(name="Buyer Example", postal_address=BuyerPostalAddress(country_code="DE")),
        lines=tuple(lines),
        **kwargs,
    )


def _line(
    index: int,
    quantity: Decimal,
    price: Decimal,
    base: Decimal | None,
    allowances: list[Decimal],
    charges: list[Decimal],
    category: str,
    rate: Decimal | None,
) -> LineDraft:
    return LineDraft(
        identifier=str(index),
        invoiced_quantity=quantity,
        invoiced_quantity_unit_code="C62",
        allowances=tuple(InvoiceLineAllowance(amount=a, reason="Discount") for a in allowances),
        charges=tuple(InvoiceLineCharge(amount=c, reason="Charge") for c in charges),
        price_details=PriceDetails(item_net_price=price, base_quantity=base),
        vat_information=LineVatInformation(category_code=category, rate=rate),
        item=ItemInformation(name="Item"),
    )


def _reasons(groups: list[tuple[str, str | None, str | None]]) -> dict[str, calc.ExemptionReason]:
    return {
        category: calc.ExemptionReason(text=text, code=code)
        for category, text, code in groups
        if text is not None or code is not None
    }


def extract_ubl(root: etree._Element) -> Extracted:
    """Extract a UBL ``Invoice`` or ``CreditNote``."""
    ns = _xml.UBL_NSMAP
    currency = t.cast(str, _text(root, "cbc:DocumentCurrencyCode", ns))
    tax_currency = _text(root, "cbc:TaxCurrencyCode", ns)
    lines, nets = [], []
    for index, node in enumerate(_nodes(root, "cac:InvoiceLine | cac:CreditNoteLine", ns)):
        ac = "cac:AllowanceCharge[normalize-space(cbc:ChargeIndicator) = '{}']/cbc:Amount"
        lines.append(
            _line(
                index,
                t.cast(Decimal, _dec(node, "cbc:InvoicedQuantity | cbc:CreditedQuantity", ns)),
                t.cast(Decimal, _dec(node, "cac:Price/cbc:PriceAmount", ns)),
                _dec(node, "cac:Price/cbc:BaseQuantity", ns),
                _amounts(node, ac.format("false"), ns),
                _amounts(node, ac.format("true"), ns),
                t.cast(str, _text(node, "cac:Item/cac:ClassifiedTaxCategory/cbc:ID", ns)),
                _dec(node, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent", ns),
            )
        )
        nets.append(t.cast(Decimal, _dec(node, "cbc:LineExtensionAmount", ns)))
    allowances, charges = [], []
    for node in _nodes(root, "cac:AllowanceCharge", ns):
        amount = t.cast(Decimal, _dec(node, "cbc:Amount", ns))
        category = t.cast(str, _text(node, "cac:TaxCategory/cbc:ID", ns))
        rate = _dec(node, "cac:TaxCategory/cbc:Percent", ns)
        if _text(node, "cbc:ChargeIndicator", ns) == "true":
            charges.append(DocumentLevelCharge(amount=amount, vat_category_code=category, vat_rate=rate, reason="x"))
        else:
            allowances.append(
                DocumentLevelAllowance(amount=amount, vat_category_code=category, vat_rate=rate, reason="x")
            )
    subtotals = _nodes(root, f"cac:TaxTotal[cbc:TaxAmount/@currencyID = '{currency}']/cac:TaxSubtotal", ns)
    breakdown = [
        (
            t.cast(str, _text(s, "cac:TaxCategory/cbc:ID", ns)),
            _dec(s, "cac:TaxCategory/cbc:Percent", ns),
            t.cast(Decimal, _dec(s, "cbc:TaxableAmount", ns)),
            t.cast(Decimal, _dec(s, "cbc:TaxAmount", ns)),
        )
        for s in subtotals
    ]
    reasons = [
        (
            t.cast(str, _text(s, "cac:TaxCategory/cbc:ID", ns)),
            _text(s, "cac:TaxCategory/cbc:TaxExemptionReason", ns),
            _text(s, "cac:TaxCategory/cbc:TaxExemptionReasonCode", ns),
        )
        for s in subtotals
    ]
    m = "cac:LegalMonetaryTotal/cbc:"
    totals = {
        "sum_of_line_net_amounts": _dec(root, m + "LineExtensionAmount", ns),
        "sum_of_allowances": _dec(root, m + "AllowanceTotalAmount", ns),
        "sum_of_charges": _dec(root, m + "ChargeTotalAmount", ns),
        "total_without_vat": _dec(root, m + "TaxExclusiveAmount", ns),
        "total_vat": _dec(root, f"cac:TaxTotal/cbc:TaxAmount[@currencyID = '{currency}']", ns),
        "total_vat_in_accounting_currency": (
            _dec(root, f"cac:TaxTotal/cbc:TaxAmount[@currencyID = '{tax_currency}']", ns)
            if tax_currency not in (None, currency)
            else None
        ),
        "total_with_vat": _dec(root, m + "TaxInclusiveAmount", ns),
        "paid_amount": _dec(root, m + "PrepaidAmount", ns),
        "rounding_amount": _dec(root, m + "PayableRoundingAmount", ns),
        "amount_due": _dec(root, m + "PayableAmount", ns),
    }
    return Extracted(
        draft=_shell(currency, tax_currency, lines, allowances=tuple(allowances), charges=tuple(charges)),
        line_net_amounts=nets,
        totals={k: v for k, v in totals.items() if v is not None},
        breakdown=breakdown,
        exemption_reasons=_reasons(reasons),
    )


def extract_cii(root: etree._Element) -> Extracted:
    """Extract a CII ``CrossIndustryInvoice``."""
    ns = _xml.CII_NSMAP
    tx = "rsm:SupplyChainTradeTransaction/"
    hs = tx + "ram:ApplicableHeaderTradeSettlement/"
    currency = t.cast(str, _text(root, hs + "ram:InvoiceCurrencyCode", ns))
    tax_currency = _text(root, hs + "ram:TaxCurrencyCode", ns)
    lines, nets = [], []
    for index, node in enumerate(_nodes(root, tx + "ram:IncludedSupplyChainTradeLineItem", ns)):
        st = "ram:SpecifiedLineTradeSettlement/"
        ac = st + "ram:SpecifiedTradeAllowanceCharge[ram:ChargeIndicator/udt:Indicator = '{}']/ram:ActualAmount"
        price = "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/"
        lines.append(
            _line(
                index,
                t.cast(Decimal, _dec(node, "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity", ns)),
                t.cast(Decimal, _dec(node, price + "ram:ChargeAmount", ns)),
                _dec(node, price + "ram:BasisQuantity", ns),
                _amounts(node, ac.format("false"), ns),
                _amounts(node, ac.format("true"), ns),
                t.cast(str, _text(node, st + "ram:ApplicableTradeTax/ram:CategoryCode", ns)),
                _dec(node, st + "ram:ApplicableTradeTax/ram:RateApplicablePercent", ns),
            )
        )
        nets.append(
            t.cast(
                Decimal, _dec(node, st + "ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount", ns)
            )
        )
    allowances, charges = [], []
    for node in _nodes(root, hs + "ram:SpecifiedTradeAllowanceCharge", ns):
        amount = t.cast(Decimal, _dec(node, "ram:ActualAmount", ns))
        category = t.cast(str, _text(node, "ram:CategoryTradeTax/ram:CategoryCode", ns))
        rate = _dec(node, "ram:CategoryTradeTax/ram:RateApplicablePercent", ns)
        if _text(node, "ram:ChargeIndicator/udt:Indicator", ns) == "true":
            charges.append(DocumentLevelCharge(amount=amount, vat_category_code=category, vat_rate=rate, reason="x"))
        else:
            allowances.append(
                DocumentLevelAllowance(amount=amount, vat_category_code=category, vat_rate=rate, reason="x")
            )
    taxes = _nodes(root, hs + "ram:ApplicableTradeTax", ns)
    breakdown = [
        (
            t.cast(str, _text(s, "ram:CategoryCode", ns)),
            _dec(s, "ram:RateApplicablePercent", ns),
            t.cast(Decimal, _dec(s, "ram:BasisAmount", ns)),
            t.cast(Decimal, _dec(s, "ram:CalculatedAmount", ns)),
        )
        for s in taxes
    ]
    reasons = [
        (
            t.cast(str, _text(s, "ram:CategoryCode", ns)),
            _text(s, "ram:ExemptionReason", ns),
            _text(s, "ram:ExemptionReasonCode", ns),
        )
        for s in taxes
    ]
    m = hs + "ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:"
    totals = {
        "sum_of_line_net_amounts": _dec(root, m + "LineTotalAmount", ns),
        "sum_of_allowances": _dec(root, m + "AllowanceTotalAmount", ns),
        "sum_of_charges": _dec(root, m + "ChargeTotalAmount", ns),
        "total_without_vat": _dec(root, m + "TaxBasisTotalAmount", ns),
        "total_vat": _dec(root, m + f"TaxTotalAmount[@currencyID = '{currency}']", ns),
        "total_vat_in_accounting_currency": (
            _dec(root, m + f"TaxTotalAmount[@currencyID = '{tax_currency}']", ns)
            if tax_currency not in (None, currency)
            else None
        ),
        "total_with_vat": _dec(root, m + "GrandTotalAmount", ns),
        "paid_amount": _dec(root, m + "TotalPrepaidAmount", ns),
        "rounding_amount": _dec(root, m + "RoundingAmount", ns),
        "amount_due": _dec(root, m + "DuePayableAmount", ns),
    }
    return Extracted(
        draft=_shell(currency, tax_currency, lines, allowances=tuple(allowances), charges=tuple(charges)),
        line_net_amounts=nets,
        totals={k: v for k, v in totals.items() if v is not None},
        breakdown=breakdown,
        exemption_reasons=_reasons(reasons),
    )
