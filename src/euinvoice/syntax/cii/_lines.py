"""CII invoice lines: ``ram:IncludedSupplyChainTradeLineItem`` (BG-25 with BG-26..BG-32).

Children follow ``ram:SupplyChainTradeLineItemType`` (``AssociatedDocumentLineDocument``,
``SpecifiedTradeProduct``, ``SpecifiedLineTradeAgreement``, ``SpecifiedLineTradeDelivery``,
``SpecifiedLineTradeSettlement``) and the sequences of their D16B types; XPaths per business term are
those of ``docs/reference/bt-mapping.md``.
"""

from lxml import etree

from euinvoice.model import InvoiceLine, ItemInformation, PriceDetails
from euinvoice.syntax.cii._build import (
    allowance_charge,
    cannot_express,
    date_time,
    decimal,
    identifier,
    indicator,
    opt,
    sub,
    vat_category,
)

OBJECT_TYPE_CODE: str = "130"
"""``ram:TypeCode`` of the ``ram:AdditionalReferencedDocument`` carrying an invoiced object identifier
(BT-18, BT-128): CII-DT-018, CII-SR-458, CII-SR-474 and the KoSIT binding
``[following-sibling::ram:TypeCode='130']``."""


def line(parent: etree._Element, value: InvoiceLine) -> None:
    """Append one ``ram:IncludedSupplyChainTradeLineItem`` (BG-25)."""
    element = sub(parent, "IncludedSupplyChainTradeLineItem")
    document = sub(element, "AssociatedDocumentLineDocument")
    sub(document, "LineID", value.identifier)
    if value.note is not None:
        # BT-127: one note with one ram:Content and no subject code (CII-SR-039, -040, -041).
        sub(sub(document, "IncludedNote"), "Content", value.note)
    _product(element, value.item)
    _agreement(element, value)
    delivery = sub(element, "SpecifiedLineTradeDelivery")
    sub(delivery, "BilledQuantity", decimal(value.invoiced_quantity), unitCode=value.invoiced_quantity_unit_code)
    _settlement(element, value)


def _product(parent: etree._Element, item: ItemInformation) -> None:
    """``ram:SpecifiedTradeProduct`` (BG-31, BG-32) in ``ram:TradeProductType`` order."""
    element = sub(parent, "SpecifiedTradeProduct")
    if item.standard_identifier is not None:
        # BT-157: GlobalID with its mandatory scheme (BR-64, CII-SR-046, BR-CL-21).
        identifier(element, "GlobalID", item.standard_identifier)
    opt(element, "SellerAssignedID", item.sellers_identifier)
    opt(element, "BuyerAssignedID", item.buyers_identifier)
    sub(element, "Name", item.name)
    opt(element, "Description", item.description)
    for attribute in item.attributes:
        characteristic = sub(element, "ApplicableProductCharacteristic")
        sub(characteristic, "Description", attribute.name)
        sub(characteristic, "Value", attribute.value)
    for classification in item.classification_identifiers:
        # BT-158 scheme and version as ClassCode/@listID and @listVersionID (BR-65, BR-CL-13; the KoSIT
        # testsuite writes ``<ram:ClassCode listID="IB" listVersionID="88">``).
        attributes = {"listID": classification.scheme_id}
        if classification.scheme_version_id is not None:
            attributes["listVersionID"] = classification.scheme_version_id
        sub(sub(element, "DesignatedProductClassification"), "ClassCode", classification.value, **attributes)
    if item.country_of_origin is not None:
        sub(sub(element, "OriginTradeCountry"), "ID", item.country_of_origin)


def _agreement(parent: etree._Element, value: InvoiceLine) -> None:
    """``ram:SpecifiedLineTradeAgreement``: BT-132 and the prices of BG-29."""
    element = sub(parent, "SpecifiedLineTradeAgreement")
    if value.purchase_order_line_reference is not None:
        # BT-132 is the LineID; CII-SR-108 forbids an IssuerAssignedID here.
        sub(sub(element, "BuyerOrderReferencedDocument"), "LineID", value.purchase_order_line_reference)
    price: PriceDetails = value.price_details
    if price.item_gross_price is not None:
        gross = sub(element, "GrossPriceProductTradePrice")
        sub(gross, "ChargeAmount", decimal(price.item_gross_price))
        if price.item_price_discount is not None:
            # BT-147: an allowance (CII-SR-119) with only its amount (CII-SR-120..131).
            discount = sub(gross, "AppliedTradeAllowanceCharge")
            indicator(discount, "ChargeIndicator", False)
            sub(discount, "ActualAmount", decimal(price.item_price_discount))
    elif price.item_price_discount is not None:
        raise cannot_express(
            "BT-147 (item price discount)",
            "it is an allowance on ram:GrossPriceProductTradePrice, whose ram:ChargeAmount (BT-148, item "
            f"gross price) the D16B XSD requires; set BT-148 on line {value.identifier!r}",
        )
    net = sub(element, "NetPriceProductTradePrice")
    sub(net, "ChargeAmount", decimal(price.item_net_price))
    if price.base_quantity is not None:
        attributes = {} if price.base_quantity_unit_code is None else {"unitCode": price.base_quantity_unit_code}
        sub(net, "BasisQuantity", decimal(price.base_quantity), **attributes)
    elif price.base_quantity_unit_code is not None:
        raise cannot_express(
            "BT-150 (item price base quantity unit of measure code)",
            f"it is the @unitCode of BT-149 (item price base quantity); set BT-149 on line {value.identifier!r}",
        )


def _settlement(parent: etree._Element, value: InvoiceLine) -> None:
    """``ram:SpecifiedLineTradeSettlement`` in ``ram:LineTradeSettlementType`` order."""
    element = sub(parent, "SpecifiedLineTradeSettlement")
    vat_category(element, "ApplicableTradeTax", value.vat_information.category_code, value.vat_information.rate)
    if value.period is not None:
        period = sub(element, "BillingSpecifiedPeriod")
        if value.period.start_date is not None:
            date_time(period, "StartDateTime", value.period.start_date)
        if value.period.end_date is not None:
            date_time(period, "EndDateTime", value.period.end_date)
    for allowance in value.allowances:
        allowance_charge(element, "SpecifiedTradeAllowanceCharge", allowance, charge=False)
    for charge in value.charges:
        allowance_charge(element, "SpecifiedTradeAllowanceCharge", charge, charge=True)
    summation = sub(element, "SpecifiedTradeSettlementLineMonetarySummation")
    sub(summation, "LineTotalAmount", decimal(value.net_amount))
    if value.object_identifier is not None:
        document = sub(element, "AdditionalReferencedDocument")
        sub(document, "IssuerAssignedID", value.object_identifier.value)
        sub(document, "TypeCode", OBJECT_TYPE_CODE)
        # BT-128 scheme: ram:ReferenceTypeCode (BR-CL-07; CII-DT-024 allows it only with TypeCode 130).
        opt(document, "ReferenceTypeCode", value.object_identifier.scheme_id)
    if value.buyer_accounting_reference is not None:
        sub(sub(element, "ReceivableSpecifiedTradeAccountingAccount"), "ID", value.buyer_accounting_reference)
