"""Reading CII invoice lines: ``ram:IncludedSupplyChainTradeLineItem`` (BG-25 with BG-26..BG-32).

The inverse of ``_lines.py``; XPaths per business term are those of ``docs/reference/bt-mapping.md``.
"""

from decimal import Decimal

from lxml import etree

from euinvoice.model import (
    InvoiceLine,
    InvoiceLineAllowance,
    InvoiceLineCharge,
    InvoiceLinePeriod,
    ItemAttribute,
    ItemClassificationIdentifier,
    ItemInformation,
    LineVatInformation,
    PriceDetails,
)
from euinvoice.syntax.cii._read_common import allowance_charge_values, object_identifier, period_dates, vat_category
from euinvoice.syntax.cii._reader import Reader, content


def line(reader: Reader, element: etree._Element) -> InvoiceLine:
    """One ``ram:IncludedSupplyChainTradeLineItem`` (BG-25)."""
    document = reader.one(element, "AssociatedDocumentLineDocument")
    delivery = reader.one(element, "SpecifiedLineTradeDelivery")
    quantity = reader.one(delivery, "BilledQuantity")
    settlement = reader.one(element, "SpecifiedLineTradeSettlement")
    agreement = reader.one(element, "SpecifiedLineTradeAgreement")
    allowances, charges = _allowances_and_charges(reader, settlement)
    period = reader.one(settlement, "BillingSpecifiedPeriod")
    tax = vat_category(reader, settlement, "ApplicableTradeTax")
    return reader.model(
        InvoiceLine,
        element,
        identifier=reader.text(document, "LineID"),
        # BT-127: the first ram:Content of the first note (one note, one content: CII-SR-039..041).
        note=reader.text(reader.one(document, "IncludedNote"), "Content"),
        item=_item(reader, element),
        purchase_order_line_reference=reader.text(reader.one(agreement, "BuyerOrderReferencedDocument"), "LineID"),
        price_details=_price(reader, agreement),
        invoiced_quantity=None if quantity is None else content(quantity),
        invoiced_quantity_unit_code=None if quantity is None else reader.attribute(quantity, "unitCode"),
        vat_information=None
        if tax is None
        else reader.model(LineVatInformation, tax[0], category_code=tax[1], rate=tax[2]),
        period=None
        if period is None
        else reader.model(InvoiceLinePeriod, period, **period_dates(reader, period, ("BT-134", "BT-135"))),
        allowances=allowances,
        charges=charges,
        net_amount=reader.text(
            reader.one(settlement, "SpecifiedTradeSettlementLineMonetarySummation"), "LineTotalAmount"
        ),
        object_identifier=object_identifier(reader, settlement),
        buyer_accounting_reference=reader.text(
            reader.one(settlement, "ReceivableSpecifiedTradeAccountingAccount"), "ID"
        ),
    )


def _item(reader: Reader, line_item: etree._Element) -> ItemInformation | None:
    """``ram:SpecifiedTradeProduct`` (BG-31, BG-32)."""
    element = reader.one(line_item, "SpecifiedTradeProduct")
    if element is None:
        return None
    standard = reader.one(element, "GlobalID")
    attributes = [
        reader.model(
            ItemAttribute,
            characteristic,
            name=reader.text(characteristic, "Description"),
            value=reader.text(characteristic, "Value"),
        )
        for characteristic in reader.each(element, "ApplicableProductCharacteristic")
    ]
    classifications = [
        reader.model(
            ItemClassificationIdentifier,
            code,
            "BT-158",
            value=content(code),
            scheme_id=reader.attribute(code, "listID"),
            scheme_version_id=reader.attribute(code, "listVersionID"),
        )
        for classification in reader.each(element, "DesignatedProductClassification")
        if (code := reader.one(classification, "ClassCode")) is not None
    ]
    origin = reader.one(element, "OriginTradeCountry")
    return reader.model(
        ItemInformation,
        element,
        standard_identifier=None if standard is None else reader.identifier(standard),
        sellers_identifier=reader.text(element, "SellerAssignedID"),
        buyers_identifier=reader.text(element, "BuyerAssignedID"),
        name=reader.text(element, "Name"),
        description=reader.text(element, "Description"),
        attributes=tuple(attributes),
        classification_identifiers=tuple(classifications),
        country_of_origin=reader.text(origin, "ID"),
    )


def _price(reader: Reader, agreement: etree._Element | None) -> PriceDetails | None:
    """BG-29 from ``ram:NetPriceProductTradePrice`` and ``ram:GrossPriceProductTradePrice``.

    The gross price's ``ram:BasisQuantity`` has no business term of its own: the writer repeats BT-149/BT-150 there
    (as CEN's ``CII_example2.xml`` does), so it is consumed when it equals the net price's and left unmapped when
    it differs. BT-147 is the first gross price ``ram:AppliedTradeAllowanceCharge`` with ``ChargeIndicator`` false
    (CII-SR-119); a charge or an allowance without an indicator has no business term and stays unmapped.
    """
    net = reader.one(agreement, "NetPriceProductTradePrice")
    if net is None:
        return None
    basis = reader.one(net, "BasisQuantity")
    base_quantity = None if basis is None else content(basis)
    unit = None if basis is None else reader.attribute(basis, "unitCode")
    gross = reader.one(agreement, "GrossPriceProductTradePrice")
    discount = None
    for candidate in reader.children(gross, "BasisQuantity")[:1]:
        if _same_quantity(candidate, base_quantity, unit):
            reader.use(candidate)
            reader.attribute(candidate, "unitCode")
    for allowance in reader.children(gross, "AppliedTradeAllowanceCharge"):
        # BT-147 is the first allowance with ChargeIndicator false. A charge, an allowance without an xs:boolean
        # indicator (CII-SR-119 allows one without amount) and any later allowance stay unmapped as a whole
        # (marking the indicator inside an unmarked parent is harmless).
        if discount is None and reader.indicator(allowance, "ChargeIndicator") is False:
            discount = reader.text(reader.use(allowance), "ActualAmount")
    return reader.model(
        PriceDetails,
        net,
        item_net_price=reader.text(net, "ChargeAmount"),
        base_quantity=base_quantity,
        base_quantity_unit_code=unit,
        item_gross_price=reader.text(gross, "ChargeAmount"),
        item_price_discount=discount,
    )


def _same_quantity(element: etree._Element, quantity: str | None, unit: str | None) -> bool:
    """Whether a gross price ``ram:BasisQuantity`` repeats the net price's BT-149 and BT-150."""
    if quantity is None or element.get("unitCode") != unit:
        return False
    try:
        return Decimal(content(element).strip()) == Decimal(quantity.strip())
    except ArithmeticError:
        return False


def _allowances_and_charges(
    reader: Reader, settlement: etree._Element | None
) -> tuple[tuple[InvoiceLineAllowance, ...], tuple[InvoiceLineCharge, ...]]:
    """``ram:SpecifiedTradeAllowanceCharge`` of a line: BG-27 (``ChargeIndicator`` false) and BG-28 (true)."""
    allowances: list[InvoiceLineAllowance] = []
    charges: list[InvoiceLineCharge] = []
    for element in reader.children(settlement, "SpecifiedTradeAllowanceCharge"):
        read = allowance_charge_values(reader, element)
        if read is None:
            continue
        charge, values = read
        if charge:
            charges.append(reader.model(InvoiceLineCharge, element, **values))
        else:
            allowances.append(reader.model(InvoiceLineAllowance, element, **values))
    return tuple(allowances), tuple(charges)
