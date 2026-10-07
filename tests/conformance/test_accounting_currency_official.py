"""BT-6 = BT-5 with BT-111 against the official CEN Schematron of both syntaxes (#71).

Both writers refuse the case, so the documents here are written with BT-6 = SEK and then have every SEK
(``TaxCurrencyCode`` and BT-111's ``@currencyID``) rewritten to the invoice currency EUR. The pinned rules
reject the result whatever the amounts:

* CII: BR-53 requires ``not(ram:TaxCurrencyCode = ram:InvoiceCurrencyCode)`` whenever BT-6 is present
  (schematron/CII/EN16931-CII-model.sch), so it alone rejects even a zero-VAT invoice. BR-CO-15 requires
  exactly one ``ram:TaxTotalAmount`` in BT-5 unless BT-112 = BT-109, and BR-CO-14's context is *every*
  ``ram:TaxTotalAmount`` in BT-5, so the binding reads both amounts as BT-110.
* UBL: BR-CO-15 requires exactly one ``cac:TaxTotal/cbc:TaxAmount`` in BT-5, with no escape
  (schematron/UBL/EN16931-UBL-model.sch).
"""

import typing as t
from collections.abc import Callable

import pytest
from lxml import etree

from _calc_drafts import draft, line, replace, with_totals
from euinvoice import _xml, calc
from euinvoice.errors import ModelError
from euinvoice.model import Invoice
from euinvoice.report import Severity
from euinvoice.syntax import Syntax, cii, ubl
from euinvoice.validation import schematron

pytestmark = pytest.mark.conformance

WRITERS: t.Final[dict[Syntax, tuple[Callable[[Invoice], bytes], schematron.RuleSet, str, dict[str, str]]]] = {
    Syntax.CII: (
        cii.write,
        schematron.CEN_CII,
        "//ram:TaxCurrencyCode | //ram:TaxTotalAmount/@currencyID",
        _xml.CII_NSMAP,
    ),
    Syntax.UBL: (ubl.write, schematron.CEN_UBL, "/*/cbc:TaxCurrencyCode | //cbc:TaxAmount/@currencyID", _xml.UBL_NSMAP),
}
EXPECTED: t.Final[dict[tuple[Syntax, str], set[str]]] = {
    (Syntax.CII, "bt111-differs"): {"BR-53", "BR-CO-14", "BR-CO-15"},
    (Syntax.CII, "bt111-equals-bt110"): {"BR-53", "BR-CO-15"},
    (Syntax.CII, "zero-vat"): {"BR-53"},  # BT-112 = BT-109: BR-CO-15's second disjunct
    (Syntax.UBL, "bt111-differs"): {"BR-CO-15"},
    (Syntax.UBL, "bt111-equals-bt110"): {"BR-CO-15"},
    (Syntax.UBL, "zero-vat"): {"BR-CO-15"},
}


def _sek(bt111: str, category: str = "S", rate: str = "20") -> Invoice:
    """One line of 100.00 in EUR (BT-5) with BT-6 SEK and the given BT-111."""
    invoice = replace(calc.complete(draft(line("1", "100", category, rate))), vat_accounting_currency_code="SEK")
    return with_totals(invoice, total_vat_in_accounting_currency=bt111)


CASES: t.Final[dict[str, Callable[[], Invoice]]] = {
    "bt111-differs": lambda: _sek("210.00"),
    "bt111-equals-bt110": lambda: _sek("20.00"),
    "zero-vat": lambda: _sek("0.00", "Z", "0"),
}


def _in_eur(document: bytes, xpath: str, namespaces: dict[str, str]) -> bytes:
    """``document`` with BT-6 and every amount in SEK moved to EUR (BT-5)."""
    root = _xml.parse(document)
    for node in t.cast(list[t.Any], root.xpath(xpath, namespaces=namespaces)):
        if isinstance(node, etree._Element):
            assert node.text == "SEK"
            node.text = "EUR"
        elif node == "SEK":  # an @currencyID; BT-110's is already EUR
            node.getparent().set("currencyID", "EUR")
    return etree.tostring(root)


@pytest.mark.parametrize("syntax", [Syntax.UBL, Syntax.CII])
@pytest.mark.parametrize("name", list(CASES))
def test_official_rules_reject_bt6_equal_to_bt5_with_bt111(name: str, syntax: Syntax) -> None:
    write, rule_set, xpath, namespaces = WRITERS[syntax]
    invoice = CASES[name]()
    assert schematron.run(rule_set, write(invoice)) == ()  # clean while BT-6 is SEK
    document = _in_eur(write(invoice), xpath, namespaces)
    fatal = {f.rule_id for f in schematron.run(rule_set, document) if f.severity is Severity.FATAL}
    assert fatal == EXPECTED[syntax, name]
    with pytest.raises(ModelError, match=rf"^BT-6 cannot be written in {syntax.name}: "):
        write(replace(invoice, vat_accounting_currency_code="EUR"))
