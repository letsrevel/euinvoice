"""Element builders and value formats shared by the CII D16B writer modules.

Element names and nesting follow the D16B SCRDM subset schema the CEN CII artifacts are written for
(``resources/cii/16b/xsd/CrossIndustryInvoice_*_100pD16B.xsd`` of the pinned
``xrechnung-validator-configuration`` source, the same schema ``euinvoice.validation.xsd`` uses).
"""

import datetime
import re
import typing as t
from decimal import Decimal

from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ModelError
from euinvoice.model import Identifier, InvoiceLineAllowance, InvoiceLineCharge
from euinvoice.model.allowances import DocumentLevelAllowance, DocumentLevelCharge

type Allowance = DocumentLevelAllowance | DocumentLevelCharge | InvoiceLineAllowance | InvoiceLineCharge
"""Any EN 16931 allowance or charge (BG-20, BG-21, BG-27, BG-28)."""

DATE_FORMAT: t.Final = "102"
"""The UNTDID 2379 date format code ``102`` (CCYYMMDD).

Every date is written with ``format="102"``: CII-DT-097 checks the lexical form only for ``@format='102'``
and the CEN BR rules (BR-03, BR-29, BR-30) select ``udt:DateTimeString[@format='102']``, while the D16B
XSD types ``@format`` as a plain ``xs:string``. Any other code would go unchecked (binding note on #13).
"""

VAT: t.Final = "VAT"
"""``ram:TypeCode`` of every VAT trade tax; BR-32, BR-37, BR-47, BR-48 and BR-CO-04 select
``ram:TypeCode = 'VAT'`` and CII-DT-037 allows no other value (``CII/EN16931-CII-{model,syntax}.sch``)."""

# BT-8: the model stores UNTDID 2005 (UBL BR-CL-06); CII BR-CL-06 (``codelist/EN16931-CII-codes.sch``)
# allows only the UNTDID 2475 codes 5, 29 and 72. The pairs are the European Commission's "EN16931 code
# lists values v17b - used from 2026-05-15" (sheet "Time", "UBL and UN/EDIFACT" 2005 code vs "UN/CEFACT
# Cross Industry Invoice" 2475 code): 3 "Invoice document issue date time" = 5 "Date of invoice";
# 35 "Delivery date/time, actual" = 29 "Date of delivery of goods to establishments/domicile/site";
# 432 "Paid to date" = 72 "Payment date". 3 = 5 is also the KoSIT testsuite pair
# 01.02_comprehensive_test_ubl.xml / _uncefact.xml.
VAT_POINT_DATE_CODES: t.Final[t.Mapping[str, str]] = {"3": "5", "35": "29", "432": "72"}
"""UNTDID 2005 (model, BT-8) → UNTDID 2475 (CII ``ram:DueDateTypeCode``)."""
VAT_POINT_DATE_CODES_FROM_CII: t.Final[t.Mapping[str, str]] = {
    cii: model for model, cii in VAT_POINT_DATE_CODES.items()
}
"""UNTDID 2475 (CII ``ram:DueDateTypeCode``) → UNTDID 2005 (model, BT-8), inverse of :data:`VAT_POINT_DATE_CODES`."""

VAT_SCHEME: t.Final = "VA"
"""``@schemeID`` of a VAT identifier (BT-31, BT-48, BT-63): BR-56 and BR-AF-02 select ``ram:ID[@schemeID='VA']``."""
FISCAL_SCHEME: t.Final = "FC"
"""``@schemeID`` of the Seller tax registration identifier (BT-32), selected as ``'FC'`` by BR-AF-02 etc."""
TENDER_TYPE_CODE: t.Final = "50"
"""``ram:TypeCode`` of the ``ram:AdditionalReferencedDocument`` holding BT-17 (CII-DT-018, CII-SR-457)."""
OBJECT_TYPE_CODE: t.Final = "130"
"""``ram:TypeCode`` of the ``ram:AdditionalReferencedDocument`` carrying an invoiced object identifier
(BT-18, BT-128): CII-DT-018, CII-SR-458, CII-SR-474 and the KoSIT binding
``[following-sibling::ram:TypeCode='130']``."""
SUPPORTING_DOCUMENT_TYPE_CODE: t.Final = "916"
"""``ram:TypeCode`` of a BG-24 ``ram:AdditionalReferencedDocument`` (CII-DT-015, -021, -022, CII-SR-475/476)."""
PROJECT_NAME: t.Final = "Project reference"
"""``ram:SpecifiedProcuringProject/ram:Name``, which the D16B XSD requires (``ProcuringProjectType``, minOccurs 1)
but no business term carries; every KoSIT testsuite instance with BT-11 writes this text."""

# The IBAN test of XRechnung 2.6.0 (``schematron/common.sch`` XR-IBAN-REGEX and the ``xr:checkIBAN``
# function of ``schematron/cii/XRechnung-CII-validation.sch``, used by BR-DE-19 / BR-DE-20): whitespace
# removed, the pattern below, then ISO 7064 MOD 97-10 over BBAN + country + check digits = 1.
_IBAN: t.Final = re.compile(r"[A-Z]{2}[0-9]{2}[a-zA-Z0-9]{0,30}")


def ram(name: str) -> str:
    """The Clark name of a ``ram`` element."""
    return f"{{{_xml.CII_RAM}}}{name}"


def sub(parent: etree._Element, name: str, text: str | None = None, **attributes: str) -> etree._Element:
    """Append a ``ram`` child.

    Args:
        parent: The parent element.
        name: Local name in the ``ram`` namespace.
        text: Text content, if any.
        **attributes: Unqualified attributes (``schemeID``, ``currencyID``, ...).

    Returns:
        The new element.
    """
    element = etree.SubElement(parent, ram(name), attributes)
    element.text = text
    return element


def opt(parent: etree._Element, name: str, text: str | None) -> None:
    """Append a ``ram`` child with ``text`` unless ``text`` is ``None``."""
    if text is not None:
        sub(parent, name, text)


def decimal(value: Decimal) -> str:
    """Fixed-point text of a decimal (never exponent notation, CLAUDE.md "Money and numbers")."""
    return format(value, "f")


def date_time(parent: etree._Element, name: str, value: datetime.date, *, qualified: bool = False) -> None:
    """Append ``ram:<name>/udt:DateTimeString[@format='102']`` (``qdt:`` when ``qualified``).

    ``qualified`` is for ``qdt:FormattedDateTimeType`` (BT-26, ``ram:FormattedIssueDateTime``), whose
    ``DateTimeString`` is declared in the qdt schema.
    """
    namespace = _xml.CII_QDT if qualified else _xml.CII_UDT
    string = etree.SubElement(sub(parent, name), f"{{{namespace}}}DateTimeString", format=DATE_FORMAT)
    string.text = value.strftime("%Y%m%d")


def date(parent: etree._Element, name: str, value: datetime.date) -> None:
    """Append ``ram:<name>/udt:DateString[@format='102']`` (``udt:DateType``, BT-7)."""
    string = etree.SubElement(sub(parent, name), f"{{{_xml.CII_UDT}}}DateString", format=DATE_FORMAT)
    string.text = value.strftime("%Y%m%d")


def indicator(parent: etree._Element, name: str, value: bool) -> None:
    """Append ``ram:<name>/udt:Indicator`` (``xs:boolean``; CII-SR-183 forbids ``udt:IndicatorString``)."""
    etree.SubElement(sub(parent, name), f"{{{_xml.CII_UDT}}}Indicator").text = "true" if value else "false"


def identifier(parent: etree._Element, name: str, value: Identifier) -> None:
    """Append ``ram:<name>`` with an optional ``@schemeID``."""
    if value.scheme_id is None:
        sub(parent, name, value.value)
    else:
        sub(parent, name, value.value, schemeID=value.scheme_id)


def party_id(parent: etree._Element, value: Identifier) -> None:
    """Append a party identifier: ``ram:GlobalID[@schemeID]`` with a scheme, else ``ram:ID``.

    The KoSIT XRechnung visualization binds BT-29, BT-46, BT-60 and BT-71 to ``ram:ID`` or
    ``ram:GlobalID[exists(@schemeID)]`` (``docs/reference/bt-mapping.md``); the CEN code-list rules check
    ``ram:GlobalID/@schemeID`` against ISO 6523 ICD (BR-CL-10, BR-CL-26).
    """
    identifier(parent, "ID" if value.scheme_id is None else "GlobalID", value)


def vat_category(parent: etree._Element, name: str, code: str, rate: Decimal | None) -> None:
    """Append a ``ram:TradeTaxType`` with type ``VAT``, a category and an optional rate (XSD order)."""
    tax = sub(parent, name)
    sub(tax, "TypeCode", VAT)
    sub(tax, "CategoryCode", code)
    if rate is not None:
        sub(tax, "RateApplicablePercent", decimal(rate))


def allowance_charge(parent: etree._Element, name: str, item: Allowance, *, charge: bool) -> etree._Element:
    """Append a ``ram:TradeAllowanceChargeType`` (BG-20/21/27/28) in XSD order.

    Args:
        parent: The settlement element.
        name: ``SpecifiedTradeAllowanceCharge``.
        item: The allowance or charge.
        charge: ``ChargeIndicator``: ``True`` for a charge (BG-21, BG-28).

    Returns:
        The new element, for document level ones to append ``ram:CategoryTradeTax``.
    """
    element = sub(parent, name)
    indicator(element, "ChargeIndicator", charge)
    if item.percentage is not None:
        sub(element, "CalculationPercent", decimal(item.percentage))
    if item.base_amount is not None:
        sub(element, "BasisAmount", decimal(item.base_amount))
    sub(element, "ActualAmount", decimal(item.amount))
    opt(element, "ReasonCode", item.reason_code)
    opt(element, "Reason", item.reason)
    return element


def is_iban(value: str) -> bool:
    """Whether ``value`` passes XRechnung's IBAN check (``xr:checkIBAN``, see ``_IBAN``)."""
    normal = re.sub(r"\s", "", value)
    if _IBAN.fullmatch(normal) is None:
        return False
    rearranged = normal[4:] + normal[:2].upper() + normal[2:4]
    return int("".join(str(ord(c) - 55 if ord(c) > 64 else ord(c) - 48) for c in rearranged)) % 97 == 1


def cannot_express(term: str, reason: str) -> ModelError:
    """The error for a model value the CII D16B syntax has no place for."""
    return ModelError(f"{term} cannot be written in CII: {reason}")
