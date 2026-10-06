"""The Peppol BIS Billing 3.0 profile against the pinned peppol-bis 3.0.21 artifacts (``make conformance``).

* The upstream examples (``rules/examples``) pass ``validate()`` under the profile, given or detected.
* The ``rules/unit-UBL-PEPPOL`` vefa cases hold for the rule set ``validate()`` selects for the profile.
* Every pre-flight rule agrees with the official Schematron: an invoice that violates it, written by our
  writer, fails the same rule id in ``validate()``, and the pre-flight never reports a rule there that
  the Schematron does not (D8). The single documented exception is R003 with only BT-14 in UBL.
"""

import datetime
import typing as t
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest
from test_schematron_official import VEFA, check_vefa_test, expectations

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
    Invoice,
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
from euinvoice.report import Severity
from euinvoice.syntax import cii, ubl
from euinvoice.validate import artifacts, orchestration, schematron, validate

pytestmark = pytest.mark.conformance

PEPPOL = profiles.PEPPOL
WRITERS: t.Final[dict[str, Callable[[Invoice], bytes]]] = {"ubl": ubl.write, "cii": cii.write}
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


def official(invoice: Invoice, syntax: str) -> set[str]:
    """The rule ids the Peppol Schematron reports ``fatal`` for ``invoice`` written in ``syntax``."""
    report = validate(WRITERS[syntax](invoice), PEPPOL)
    assert not [f for f in report.findings if f.source.startswith("xsd:")], "the XSD step must pass"
    return {f.rule_id for f in report.findings if f.source == "peppol-bis" and f.severity is Severity.FATAL}


def preflighted(invoice: Invoice, syntax: str) -> set[str]:
    return {f.rule_id for f in PEPPOL.preflight(invoice, syntax)}


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


def outside_period() -> Invoice:
    jan = [datetime.date(2026, 1, day) for day in (1, 10, 20, 31)]
    return peppol_invoice(
        delivery=DeliveryInformation(invoicing_period=InvoicingPeriod(start_date=jan[1], end_date=jan[2])),
        lines=(simple_line(period=InvoiceLinePeriod(start_date=jan[0], end_date=jan[3])),),
    )


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
BOTH = ("ubl", "cii")

# (case id, builder, syntaxes, the PEPPOL-EN16931 rules the pre-flight reports there)
CASES: t.Final[list[tuple[str, Callable[[], Invoice], tuple[str, ...], set[str]]]] = [
    ("valid", peppol_invoice, BOTH, set()),
    ("R001-R007-no-bt23", lambda: peppol_invoice(process_control=process(None)), BOTH, {"R001", "R007"}),
    ("R007-unapproved", lambda: peppol_invoice(process_control=process("urn:example.com:p")), BOTH, {"R007"}),
    ("R007-france-ubl", lambda: peppol_invoice(process_control=process("urn:peppol:france:billing:regulated")),
     ("ubl",), set()),
    ("R007-france-cii", lambda: peppol_invoice(process_control=process("urn:peppol:france:billing:regulated")),
     ("cii",), {"R007"}),
    ("R004", lambda: peppol_invoice(process_control=process(profiles.PEPPOL.business_process_type, "urn:x::y")),
     BOTH, {"R004"}),
    ("R002-two-notes", lambda: peppol_invoice(notes=TWO_NOTES), BOTH, {"R002"}),
    ("R002-german-ubl", lambda: with_countries(peppol_invoice(notes=TWO_NOTES), "DE"), ("ubl",), set()),
    ("R002-subject-code", lambda: peppol_invoice(notes=(InvoiceNote(subject_code="AAI", note="x"),)), BOTH,
     set()),
    ("R003", lambda: peppol_invoice(buyer_reference=None), BOTH, {"R003"}),
    # Without BT-111: with it, the UBL writer refuses BT-6 = BT-5 (CEN BR-CO-15); CEN BR-53 fires as well.
    ("R005", lambda: peppol_invoice(vat_accounting_currency_code="EUR"), BOTH, {"R005"}),
    ("R010-R020", lambda: without_addresses(peppol_invoice()), BOTH, {"R010", "R020"}),
    ("R041", lambda: allowance_and_charge(percentage=Decimal("10")), BOTH, {"R041"}),
    ("R042", lambda: allowance_and_charge(base_amount=Decimal("10.00")), BOTH, {"R042"}),
    ("R061-no-mandate", lambda: direct_debit(0, None), BOTH, {"R061"}),
    ("R061-two-means-ubl", lambda: direct_debit(2, "M-1"), ("ubl",), {"R061"}),
    ("R061-two-means-cii", lambda: direct_debit(2, "M-1"), ("cii",), set()),
    ("R110-R111", outside_period, BOTH, {"R110", "R111"}),
    ("R121", lambda: peppol_invoice(lines=(simple_line(price_details=PriceDetails(
        item_net_price=Decimal("50"), base_quantity=Decimal("0"))),)), BOTH, {"R121"}),
    ("R008", lambda: peppol_invoice(buyer_reference=" ", notes=(InvoiceNote(note="\t"),)), BOTH, set()),
]  # fmt: skip

# R002 with a subject code fires in CII only; R008 in UBL only (the CII rules have no R008).
EXTRA: t.Final[dict[tuple[str, str], set[str]]] = {
    ("R002-subject-code", "cii"): {"R002"},
    ("R008", "ubl"): {"R008"},
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
    syntax: str, build: Callable[[], Invoice], expected: set[str]
) -> None:
    invoice = build()
    fired = official(invoice, syntax)

    assert preflighted(invoice, syntax) == expected
    # Each pre-flight rule fires officially, and every official R-rule the pre-flight covers is reported.
    assert expected <= fired
    covered = {PREFIX + r for r in ("R001", "R002", "R003", "R004", "R005", "R007", "R008", "R010", "R020", "R041",
                                     "R042", "R061", "R110", "R111", "R121")}  # fmt: skip
    assert fired & covered == expected


def test_r003_with_only_bt14_is_stricter_than_the_ubl_binding() -> None:
    # Binding decision on issue #20: the UBL writer's cac:OrderReference/cbc:ID "NA" satisfies the UBL test
    # of R003, but no purchase order reference was given, and CII (no fill-in) fails R003.
    invoice = peppol_invoice(buyer_reference=None, sales_order_reference="SO-1")

    assert PREFIX + "R003" not in official(invoice, "ubl")
    assert PREFIX + "R003" in official(invoice, "cii")
    assert preflighted(invoice, "ubl") == preflighted(invoice, "cii") == {PREFIX + "R003"}
