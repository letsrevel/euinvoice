"""``calc.check`` agrees with the official CEN CII Schematron on mutated invoices (``make conformance``).

Each invoice in :data:`CASES` breaks one rule (or sits on one UBL/CII asymmetry). It is written with
:func:`euinvoice.syntax.cii.write` and validated with the pinned ``CEN_CII`` rule set; then:

* every ``fatal`` id of ``check(invoice)`` is reported by CEN CII;
* every CII-only portability warning names a rule CEN CII reports;
* no UBL-only portability warning names a rule CEN CII reports;
* ``check(invoice, syntax=Syntax.CII)`` reports only ids CEN CII reports.
"""

# ponytail: CII only. Add the same cross-check against CEN_UBL once the UBL writer (#58) merges: UBL-only
# warnings must then appear in CEN UBL, CII-only ones must not.

import typing as t
from collections.abc import Callable
from decimal import Decimal

import pytest

from _calc_drafts import allowance, charge, draft, group, line, replace, with_breakdown, with_totals
from euinvoice import calc
from euinvoice.model import Invoice, VatBreakdown
from euinvoice.report import Severity
from euinvoice.syntax import Syntax, cii
from euinvoice.validate import schematron

pytestmark = pytest.mark.conformance

E_REASON = {"E": calc.ExemptionReason(code="VATEX-EU-132")}
O_REASON = {"O": calc.ExemptionReason(code="VATEX-EU-O")}


def base() -> Invoice:
    """S 20 % 100.00 - allowance 10.00, S 10 % 50.00 + charge 5.00, E 20.00 (clean in both)."""
    return calc.complete(
        draft(
            line("1", "100", "S", "20", identifier="1"),
            line("1", "50", "S", "10", identifier="2"),
            line("1", "20", "E", "0", identifier="3"),
            allowances=(allowance("10.00", "S", "20"),),
            charges=(charge("5.00", "S", "10"),),
        ),
        exemption_reasons=E_REASON,
    )


def bd(category: str, rate: str | None, taxable: str = "0.00", tax: str = "0.00", **kw: t.Any) -> VatBreakdown:
    return VatBreakdown(
        taxable_amount=Decimal(taxable),
        tax_amount=Decimal(tax),
        category_code=category,
        rate=None if rate is None else Decimal(rate),
        **kw,
    )


def regroup(index: int, **changes: t.Any) -> Invoice:
    invoice = base()
    groups = list(invoice.vat_breakdown)
    groups[index] = group(index, invoice, **changes)
    return with_breakdown(invoice, groups)


def extra(*groups: VatBreakdown, invoice: Invoice | None = None) -> Invoice:
    invoice = invoice or base()
    return with_breakdown(invoice, (*invoice.vat_breakdown, *groups))


def single(category: str, rate: str | None, **kw: t.Any) -> Invoice:
    reasons = {category: calc.ExemptionReason(text="Exemption text")} if category in {"E", "AE", "K", "G", "O"} else {}
    return calc.complete(draft(line("1", "100", category, rate), **kw), exemption_reasons=reasons)


CASES: dict[str, Callable[[], Invoice]] = {
    "clean": base,
    "BR-CO-10": lambda: with_totals(
        base(),
        sum_of_line_net_amounts="171.00",
        total_without_vat="166.00",
        total_with_vat="189.50",
        amount_due="189.50",
    ),
    "BR-CO-11": lambda: with_totals(
        base(), sum_of_allowances="11.00", total_without_vat="164.00", total_with_vat="187.50", amount_due="187.50"
    ),
    "BR-CO-11 absent": lambda: with_totals(
        base(), sum_of_allowances=None, total_without_vat="175.00", total_with_vat="198.50", amount_due="198.50"
    ),
    "BR-CO-12": lambda: with_totals(
        base(), sum_of_charges="6.00", total_without_vat="166.00", total_with_vat="189.50", amount_due="189.50"
    ),
    "BR-CO-13": lambda: with_totals(base(), total_without_vat="166.00", total_with_vat="189.50", amount_due="189.50"),
    "BR-CO-14": lambda: with_totals(base(), total_vat="23.51", total_with_vat="188.51", amount_due="188.51"),
    "BR-CO-15": lambda: with_totals(base(), total_with_vat="188.51", amount_due="188.51"),
    "BR-CO-15 BT-110 absent, BT-112 = BT-109": lambda: with_totals(
        base(), total_vat=None, total_with_vat="165.00", amount_due="165.00"
    ),
    "BR-CO-15 BT-110 absent": lambda: with_totals(base(), total_vat=None),
    "BR-CO-15 BT-112 = BT-109": lambda: with_totals(base(), total_with_vat="165.00", amount_due="165.00"),
    "BR-CO-16": lambda: with_totals(base(), amount_due="188.00"),
    "BR-53 no BT-111": lambda: replace(base(), vat_accounting_currency_code="SEK"),
    "BR-53 BT-6 = BT-5": lambda: replace(base(), vat_accounting_currency_code="EUR"),
    "BR-53 BT-6 = BT-5 with BT-111": lambda: with_totals(
        replace(base(), vat_accounting_currency_code="EUR"), total_vat_in_accounting_currency="23.50"
    ),
    "BR-CO-17 within 1": lambda: regroup(0, tax_amount="18.99"),
    "BR-CO-17 exactly 1": lambda: regroup(0, tax_amount="19.00"),
    "BR-CO-17 rate rounds to 0": lambda: calc.complete(draft(line("1", "200", "S", "0.4"))),
    "BR-48": lambda: regroup(1, rate=None),
    "BR-S-08 below 1": lambda: regroup(0, taxable_amount="90.50"),
    "BR-S-08 by 1": lambda: regroup(0, taxable_amount="91.00"),
    "BR-S-08 document level only": lambda: regroup(1, taxable_amount="5.00", tax_amount="0.50"),
    "BR-S-08 unused rate": lambda: extra(bd("S", "7")),
    "BR-S-08 unused rate with amount": lambda: extra(bd("S", "7", "5.00", "0.35")),
    "BR-E-08 below 1": lambda: regroup(2, taxable_amount="20.50"),
    "BR-E-08 by 1": lambda: regroup(2, taxable_amount="21.00"),
    "BR-E-09": lambda: regroup(2, tax_amount="0.01"),
    "BR-E-10": lambda: regroup(2, exemption_reason_code=None),
    "BR-S-10": lambda: regroup(0, exemption_reason="Not exempt"),
    "BR-E-01 missing": lambda: with_breakdown(base(), base().vat_breakdown[:2]),
    "BR-E-01 twice": lambda: extra(bd("E", "0", exemption_reason="x")),
    "BR-Z-01 lone": lambda: extra(bd("Z", "0")),
    "BR-Z-01 two": lambda: extra(bd("Z", "0"), bd("Z", "0")),
    "BR-S-01 unused": lambda: extra(bd("S", "20"), invoice=calc.complete(draft(line("1", "10", "Z", "0")))),
    "BR-S-01 one line": lambda: (lambda i: with_breakdown(i, i.vat_breakdown[1:]))(
        calc.complete(draft(line("1", "10", "S", "20", identifier="1"), line("1", "10", "Z", "0", identifier="2")))
    ),
    "BR-S-01 two lines": lambda: (lambda i: with_breakdown(i, i.vat_breakdown[1:]))(
        calc.complete(
            draft(
                line("1", "10", "S", "20", identifier="1"),
                line("1", "10", "S", "20", identifier="2"),
                line("1", "10", "Z", "0", identifier="3"),
            )
        )
    ),
    "BR-O-01 items without breakdown": lambda: (lambda i: with_breakdown(i, i.vat_breakdown[:1]))(
        calc.complete(draft(line("1", "10", "Z", "0"), allowances=(allowance("1.00", "O", None),)))
    ),
    "BR-O-11/12": lambda: calc.complete(
        draft(line("1", "100", "O", None, identifier="1"), line("1", "10", "S", "20", identifier="2")),
        exemption_reasons=O_REASON,
    ),
    "BR-O-13": lambda: calc.complete(
        draft(line("1", "100", "O", None), allowances=(allowance("1.00", "S", "20"),)), exemption_reasons=O_REASON
    ),
    "BR-O-14": lambda: calc.complete(
        draft(line("1", "100", "O", None), charges=(charge("1.00", "Z", "0"),)), exemption_reasons=O_REASON
    ),
    "BR-O-08": lambda: (lambda i: with_breakdown(i, (group(0, i, taxable_amount="100.50"),)))(single("O", None)),
    "BR-B-02": lambda: calc.complete(
        draft(line("1", "100", "B", "22", identifier="1"), line("1", "10", "S", "22", identifier="2"))
    ),
    "BR-S-05": lambda: single("S", "0"),
    "BR-Z-05": lambda: single("Z", "5"),
    "BR-O-05": lambda: single("O", "0"),
    "BR-AF-05 rate 0": lambda: single(
        "L", "0", allowances=(allowance("1.00", "L", "0"),), charges=(charge("2.00", "L", "0"),)
    ),
    "BR-AF-09 by 1": lambda: (lambda i: with_breakdown(i, (group(0, i, tax_amount="8.00"),)))(single("L", "7")),
    "BR-AF-09 by 5": lambda: (lambda i: with_breakdown(i, (group(0, i, tax_amount="12.00"),)))(single("L", "7")),
    "BR-48 on IGIC": lambda: (lambda i: with_breakdown(i, (group(0, i, rate=None, tax_amount="0.00"),)))(
        single("L", "7")
    ),
    "BR-AG-08 unused rate": lambda: extra(bd("M", "3"), invoice=single("M", "7")),
}


@pytest.mark.parametrize("name", list(CASES))
def test_check_agrees_with_cen_cii(name: str) -> None:
    invoice = CASES[name]()
    official = {
        f.rule_id
        for f in schematron.run(schematron.CEN_CII, cii.write(invoice))
        if f.severity in {Severity.FATAL, Severity.ERROR}
    }
    findings = calc.check(invoice)

    fatal = {f.rule_id for f in findings if f.severity is Severity.FATAL}
    warned = {f.message.split(" fails in the ", 1)[0]: f.message for f in findings if f.rule_id == calc.PORTABILITY}
    cii_only = {rule for rule, message in warned.items() if " the CII binding only " in message}
    ubl_only = {rule for rule, message in warned.items() if " the UBL binding only " in message}

    assert fatal <= official, (name, fatal - official, official)
    assert cii_only <= official, (name, cii_only - official, official)
    assert not ubl_only & official, (name, ubl_only & official)
    assert {f.rule_id for f in calc.check(invoice, syntax=Syntax.CII)} <= official
    assert bool(findings) == (name not in {"clean", "BR-CO-17 within 1", "BR-AG-08 unused rate"})
