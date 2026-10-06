"""The Peppol BIS Billing 3.0 profile against the pinned peppol-bis 3.0.21 artifacts (``make conformance``).

* The upstream examples (``rules/examples``) pass ``validate()`` under the profile, given or detected.
* The ``rules/unit-UBL-PEPPOL`` vefa cases hold for the rule set ``validate()`` selects for the profile.
* Every pre-flight rule agrees with the official Schematron: an invoice that violates it, written by our
  writer, fails the same rule id in ``validate()``, and the pre-flight never reports a rule there that
  the Schematron does not (D8). R003 with only BT-14 in UBL, which passes officially, is a warning.
"""

import datetime
import typing as t
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest
from test_schematron_official import VEFA, check_vefa_test, expectations

import _xrechnung_cases as xr
from _calc_drafts import not_subject_to_vat
from _invoices import TEST_IBAN, peppol_invoice, rebuild, simple_line
from euinvoice import _xml, profiles
from euinvoice.errors import ArtifactsNotAvailableError
from euinvoice.model import (
    Buyer,
    BuyerPostalAddress,
    CreditTransfer,
    DeliveryInformation,
    DirectDebit,
    DocumentLevelAllowance,
    DocumentLevelCharge,
    DocumentTotals,
    Identifier,
    Invoice,
    InvoiceLineAllowance,
    InvoiceLineCharge,
    InvoiceLinePeriod,
    InvoiceNote,
    InvoicingPeriod,
    PaymentInstructions,
    PriceDetails,
    ProcessControl,
    Seller,
    SellerPostalAddress,
    VatBreakdown,
)
from euinvoice.profiles import peppol
from euinvoice.report import Severity
from euinvoice.syntax import Syntax, cii, ubl
from euinvoice.validate import artifacts, orchestration, schematron, validate

pytestmark = pytest.mark.conformance

PEPPOL = profiles.PEPPOL
WRITERS: t.Final[dict[Syntax, Callable[[Invoice], bytes]]] = {Syntax.UBL: ubl.write, Syntax.CII: cii.write}
UBL, CII = Syntax.UBL, Syntax.CII
PREFIX = "PEPPOL-EN16931-"


def cached_files(pattern: str) -> list[Path]:
    """Files of the cached peppol-bis source matching ``pattern``; never fetches (collection time)."""
    try:
        directory = artifacts.source_dir("peppol-bis")
    except ArtifactsNotAvailableError:
        return []
    return sorted(directory.glob(pattern))


EXAMPLES = cached_files("rules/examples/*.xml")
UNIT_UBL_PEPPOL = cached_files("rules/unit-UBL-PEPPOL/*.xml")


def test_parametrized_inputs_are_complete() -> None:
    directory = artifacts.fetch(["peppol-bis"])["peppol-bis"]
    assert (len(EXAMPLES), len(UNIT_UBL_PEPPOL)) == (10, 62)
    assert sorted(directory.glob("rules/examples/*.xml")) == EXAMPLES
    assert sorted(directory.glob("rules/unit-UBL-PEPPOL/*.xml")) == UNIT_UBL_PEPPOL


# --- upstream examples and vefa unit tests -----------------------------------------------------------


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_every_peppol_example_passes_under_the_profile(path: Path) -> None:
    data = path.read_bytes()

    report = validate(data, PEPPOL)

    assert report.findings == (), report.findings
    # Auto-detection resolves the Peppol BT-24 to this profile: same run, no fallback note.
    assert validate(data) == report


def test_the_profile_selects_the_peppol_ubl_rule_set() -> None:
    assert [orchestration._RULE_SETS[name, "ubl"] for name in PEPPOL.rule_sets] == [
        schematron.CEN_UBL,
        schematron.PEPPOL_UBL,
    ]


@pytest.mark.parametrize("path", UNIT_UBL_PEPPOL, ids=lambda p: p.name)
def test_unit_ubl_peppol_cases_hold_under_the_profile_rule_set(path: Path) -> None:
    # The fragments are not XSD-valid invoices, so they go through the Peppol rule set validate() selects
    # for the profile, not through validate() itself (which would stop at the XSD step).
    (rule_set,) = [orchestration._RULE_SETS[name, "ubl"] for name in PEPPOL.rule_sets if name != "cen"]
    tests = [t for t in _xml.parse(path.read_bytes()).iter(f"{VEFA}test") if expectations(t)]
    assert tests
    assert {i: m for i, test in enumerate(tests) if (m := check_vefa_test(test, rule_set))} == {}


# --- pre-flight agrees with the Schematron ------------------------------------------------------------


def official(invoice: Invoice, syntax: Syntax) -> set[str]:
    """The rule ids the Peppol Schematron reports ``fatal`` for ``invoice`` written in ``syntax``."""
    report = validate(WRITERS[syntax](invoice), PEPPOL)
    assert not [f for f in report.findings if f.source.startswith("xsd:")], "the XSD step must pass"
    return {f.rule_id for f in report.findings if f.source == "peppol-bis" and f.severity is Severity.FATAL}


def preflighted(invoice: Invoice, syntax: Syntax) -> set[str]:
    """The ``fatal`` rule ids of the pre-flight (its ``EUINV-*`` warnings are not official rules)."""
    return {f.rule_id for f in PEPPOL.preflight(invoice, syntax) if f.severity is Severity.FATAL}


def with_countries(invoice: Invoice, country: str) -> Invoice:
    seller = Seller.model_validate(
        {**dict(invoice.seller), "postal_address": SellerPostalAddress(country_code=country)}
    )
    buyer = Buyer.model_validate({**dict(invoice.buyer), "postal_address": BuyerPostalAddress(country_code=country)})
    return rebuild(invoice, seller=seller, buyer=buyer)


def without_addresses(invoice: Invoice) -> Invoice:
    seller = Seller.model_validate({**dict(invoice.seller), "electronic_address": None})
    buyer = Buyer.model_validate({**dict(invoice.buyer), "electronic_address": None})
    return rebuild(invoice, seller=seller, buyer=buyer)


def allowance_and_charge(**allowance: t.Any) -> Invoice:
    """A document level allowance and charge of 0.00 each (totals unchanged) with the given base/percentage."""
    common: dict[str, t.Any] = {"amount": Decimal("0.00"), "vat_category_code": "S", "vat_rate": Decimal("19")}
    return peppol_invoice(
        allowances=(DocumentLevelAllowance(**common, **allowance, reason="Discount"),),
        charges=(DocumentLevelCharge(**common, **allowance, reason="Freight"),),
        totals=DocumentTotals(
            sum_of_line_net_amounts=Decimal("100.00"),
            sum_of_allowances=Decimal("0.00"),
            sum_of_charges=Decimal("0.00"),
            total_without_vat=Decimal("100.00"),
            total_vat=Decimal("19.00"),
            total_with_vat=Decimal("119.00"),
            amount_due=Decimal("119.00"),
        ),
        vat_breakdown=(
            VatBreakdown(
                taxable_amount=Decimal("100.00"), tax_amount=Decimal("19.00"), category_code="S", rate=Decimal("19")
            ),
        ),
    )


JAN = [datetime.date(2026, 1, day) for day in (1, 10, 20, 31)]


def outside_period(end: datetime.date | None = JAN[2]) -> Invoice:
    return peppol_invoice(
        delivery=DeliveryInformation(invoicing_period=InvoicingPeriod(start_date=JAN[1], end_date=end)),
        lines=(simple_line(period=InvoiceLinePeriod(start_date=JAN[0], end_date=JAN[3])),),
    )


def line_allowance_and_charge(**entry: t.Any) -> Invoice:
    """A line with a 0.00 allowance and charge (line net amount unchanged) with the given base/percentage."""
    common: dict[str, t.Any] = {"amount": Decimal("0.00"), **entry}
    line = simple_line(
        allowances=(InvoiceLineAllowance(**common, reason="Discount"),),
        charges=(InvoiceLineCharge(**common, reason="Packing"),),
    )
    return peppol_invoice(lines=(line,))


def direct_debit(transfers: int, mandate: str | None) -> Invoice:
    accounts = tuple(CreditTransfer(payment_account_identifier=TEST_IBAN) for _ in range(transfers))
    payment = PaymentInstructions(
        payment_means_type_code="59",
        credit_transfers=accounts,
        direct_debit=DirectDebit(mandate_reference_identifier=mandate, debited_account_identifier=TEST_IBAN),
    )
    return peppol_invoice(payment_instructions=payment)


def process(bt23: str | None, bt24: str = PEPPOL.specification_identifier) -> ProcessControl:
    return ProcessControl(business_process_type=bt23, specification_identifier=bt24)


TWO_NOTES = (InvoiceNote(note="One"), InvoiceNote(note="Two"))
BOTH = (UBL, CII)

# (case id, builder, syntaxes, the PEPPOL-EN16931 rules the pre-flight reports there)
CASES: t.Final[list[tuple[str, Callable[[], Invoice], tuple[Syntax, ...], set[str]]]] = [
    ("valid", peppol_invoice, BOTH, set()),
    ("R001-R007-no-bt23", lambda: peppol_invoice(process_control=process(None)), BOTH, {"R001", "R007"}),
    ("R007-unapproved", lambda: peppol_invoice(process_control=process("urn:example.com:p")), BOTH, {"R007"}),
    ("R007-france-ubl", lambda: peppol_invoice(process_control=process("urn:peppol:france:billing:regulated")),
     (UBL,), set()),
    ("R007-france-cii", lambda: peppol_invoice(process_control=process("urn:peppol:france:billing:regulated")),
     (CII,), {"R007"}),
    ("R004", lambda: peppol_invoice(process_control=process(profiles.PEPPOL.business_process_type, "urn:x::y")),
     BOTH, {"R004"}),
    ("R002-two-notes", lambda: peppol_invoice(notes=TWO_NOTES), BOTH, {"R002"}),
    ("R002-german-ubl", lambda: with_countries(peppol_invoice(notes=TWO_NOTES), "DE"), (UBL,), set()),
    ("R002-subject-code", lambda: peppol_invoice(notes=(InvoiceNote(subject_code="AAI", note="x"),)), BOTH,
     set()),
    ("R003", lambda: peppol_invoice(buyer_reference=None), BOTH, {"R003"}),
    # Only BT-14: UBL writes cbc:ID "NA" and passes R003 (the pre-flight warns, EUINV-PEPPOL-R003-NA).
    ("R003-only-bt14-ubl", lambda: peppol_invoice(buyer_reference=None, sales_order_reference="SO-1"), (UBL,),
     set()),
    ("R003-only-bt14-cii", lambda: peppol_invoice(buyer_reference=None, sales_order_reference="SO-1"), (CII,),
     {"R003"}),
    # Without BT-111: with it, the UBL writer refuses BT-6 = BT-5 (CEN BR-CO-15); CEN BR-53 fires as well.
    ("R005", lambda: peppol_invoice(vat_accounting_currency_code="EUR"), BOTH, {"R005"}),
    ("R010-R020", lambda: without_addresses(peppol_invoice()), BOTH, {"R010", "R020"}),
    ("R041", lambda: allowance_and_charge(percentage=Decimal("10")), BOTH, {"R041"}),
    ("R042", lambda: allowance_and_charge(base_amount=Decimal("10.00")), BOTH, {"R042"}),
    ("R041-line", lambda: line_allowance_and_charge(percentage=Decimal("10")), BOTH, {"R041"}),
    ("R042-line", lambda: line_allowance_and_charge(base_amount=Decimal("10.00")), BOTH, {"R042"}),
    ("R061-no-mandate", lambda: direct_debit(0, None), BOTH, {"R061"}),
    ("R061-two-means-ubl", lambda: direct_debit(2, "M-1"), (UBL,), {"R061"}),
    ("R061-two-means-cii", lambda: direct_debit(2, "M-1"), (CII,), set()),
    ("R110-R111", outside_period, BOTH, {"R110", "R111"}),
    ("R110-start-only-period", lambda: outside_period(end=None), BOTH, {"R110"}),
    ("R121", lambda: peppol_invoice(lines=(simple_line(price_details=PriceDetails(
        item_net_price=Decimal("50"), base_quantity=Decimal("0"))),)), BOTH, {"R121"}),
    ("R008", lambda: peppol_invoice(buyer_reference=" ", notes=(InvoiceNote(note="\t"),)), BOTH, set()),
    # Issue #79: an empty BT-13 is written empty, as in the ZUGFeRD corpus file UBL/EN16931_Elektron.ubl.xml.
    ("R008-empty-bt13", lambda: peppol_invoice(purchase_order_reference="", sales_order_reference="SO-1"), BOTH,
        set()),
]  # fmt: skip

# R002 with a subject code fires in CII only; R008 in UBL only (the CII rules have no R008).
EXTRA: t.Final[dict[tuple[str, Syntax], set[str]]] = {
    ("R002-subject-code", CII): {"R002"},
    ("R008", UBL): {"R008"},
    ("R008-empty-bt13", UBL): {"R008"},
}


@pytest.mark.parametrize(
    ("syntax", "build", "expected"),
    [
        pytest.param(
            syntax, build, {PREFIX + r for r in rules | EXTRA.get((case, syntax), set())}, id=f"{case}-{syntax}"
        )
        for case, build, syntaxes, rules in CASES
        for syntax in syntaxes
    ],
)
def test_preflight_agrees_with_the_official_rules(
    syntax: Syntax, build: Callable[[], Invoice], expected: set[str]
) -> None:
    invoice = build()
    fired = official(invoice, syntax)

    assert preflighted(invoice, syntax) == expected
    # Every covered official rule that fires is pre-flighted, and the pre-flight raises nothing else (D8).
    assert fired & peppol._RULES == expected


def test_r003_with_only_bt14_warns_in_ubl_and_is_fatal_in_cii() -> None:
    # The UBL writer's cac:OrderReference/cbc:ID "NA" satisfies the UBL test of R003 although no purchase
    # order reference was given; CII (no fill-in) fails R003.
    invoice = peppol_invoice(buyer_reference=None, sales_order_reference="SO-1")

    assert PREFIX + "R003" not in official(invoice, UBL)
    assert PREFIX + "R003" in official(invoice, CII)
    ubl_findings = {(f.rule_id, f.severity) for f in PEPPOL.preflight(invoice, UBL)}
    assert ubl_findings == {(peppol.R003_NA_WARNING, Severity.WARNING)}
    assert {(f.rule_id, f.severity) for f in PEPPOL.preflight(invoice, CII)} == {(PREFIX + "R003", Severity.FATAL)}


# --- prepare() defaults ------------------------------------------------------------------------------


def german_o_invoice() -> Invoice:
    """A "Not subject to VAT" (O) invoice between German parties, from ``complete()`` (no BT-119; issue #75).

    The parties carry what the DE-R rules of the UBL file ask of German seller and buyer (BG-6, city, post
    code, BG-16, BT-10), and GLN electronic addresses (R010, R020).
    """
    return not_subject_to_vat(
        process_control=ProcessControl(
            business_process_type=peppol.BILLING_PROCESS, specification_identifier=peppol.SPECIFICATION_IDENTIFIER
        ),
        buyer_reference="BUYER-REF-1",
        seller=xr.seller(
            vat_identifier=None,
            legal_registration_identifier=Identifier(value="HRB 00000"),
            electronic_address=Identifier(value="4000001000005", scheme_id="0088"),
        ),
        buyer=xr.buyer(electronic_address=Identifier(value="4000001000036", scheme_id="0088")),
        payment_instructions=xr.payment(),
    )


@pytest.mark.parametrize(("syntax", "unprepared"), [(UBL, {"DE-R-014"}), (CII, set())])
def test_prepare_writes_bt119_on_a_german_o_breakdown(syntax: Syntax, unprepared: set[str]) -> None:
    # DE-R-014 (PEPPOL-EN16931-UBL.sch:799-800) requires BT-119 when seller and buyer are in Germany; the CII
    # file has no DE-R rules. BT-119 = 0 passes the CEN and Peppol rules in both syntaxes.
    invoice = german_o_invoice()
    blocking = (Severity.FATAL, Severity.ERROR)
    before = validate(WRITERS[syntax](invoice), PEPPOL)
    assert {f.rule_id for f in before.findings if f.severity in blocking} == unprepared

    prepared = PEPPOL.prepare(invoice)
    report = validate(WRITERS[syntax](prepared), PEPPOL)

    assert prepared.vat_breakdown[0].rate == Decimal("0")
    assert report.ok, report.findings
    assert preflighted(prepared, syntax) == set()
