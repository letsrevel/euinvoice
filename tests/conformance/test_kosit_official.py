"""The KoSIT verdict (issue #49) against the pinned KoSIT configuration, testsuite and rule sets (``make conformance``).

Pinned: ``xrechnung-validator-configuration`` 2026-08-31 (``scenarios.xml``), ``xrechnung-testsuite`` 2026-08-31,
CEN 1.3.16 and XRechnung Schematron 2.6.0.
"""

import copy
import typing as t
from pathlib import Path

import pytest
from lxml import etree

from _xrechnung_cases import xrechnung_invoice
from euinvoice import _xml, profiles, to_xml
from euinvoice.errors import ArtifactsNotAvailableError
from euinvoice.report import Severity, SeverityOverride
from euinvoice.syntax import Syntax
from euinvoice.validation import artifacts, kosit, validate

pytestmark = pytest.mark.conformance

CAC = f"{{{_xml.UBL_CAC}}}"
RAM = f"{{{_xml.CII_RAM}}}"


def instances() -> list[Path]:
    """Every testsuite instance; never fetches (parametrization runs at collection time)."""
    try:
        directory = artifacts.source_dir("xrechnung-testsuite")
    except ArtifactsNotAvailableError:
        return []
    return sorted(p for p in (directory / "instances").rglob("*") if p.suffix.lower() == ".xml")


INSTANCES = instances()


def member(name: artifacts.SourceName, path: str) -> bytes:
    return (artifacts.fetch([name])[name] / path).read_bytes()


def test_pinned_configuration_has_the_xrechnung_and_core_scenarios() -> None:
    artifacts.fetch([kosit.SOURCE, "xrechnung-testsuite"])
    scenarios = kosit.scenarios()
    # 8 XRechnung scenarios (CIUS, Extension, CVD x UBL Invoice / CII, plus CIUS and CVD UBL CreditNote) running
    # CEN + XRechnung, then 3 EN 16931 scenarios running CEN only.
    xrechnung = [s for s in scenarios if len(s.schematron) == 2]
    assert len(xrechnung) == 8
    assert [s.name for s in scenarios if len(s.schematron) == 1] == [
        "EN16931 (UBL Invoice)",
        "EN16931 (UBL CreditNote)",
        "EN16931 (CII)",
    ]
    assert {s.schematron[1] for s in xrechnung} == {"XRechnung-UBL-validation", "XRechnung-CII-validation"}
    # A spot check of the parsed levels: CIUS UBL Invoice (scenarios.xml lines 74-78).
    assert dict(scenarios[0].levels) == {
        "BR-CL-23": Severity.WARNING,
        "BR-CL-21": Severity.WARNING,
        "UBL-CR-646": Severity.ERROR,
    }
    assert len(INSTANCES) == 86  # the parametrized test below is not vacuous


# The XRechnung testsuite is the configuration's acceptance corpus ("Full automatic test against
# xrechnung-testsuite", validator-configuration CHANGELOG.md), so KoSIT accepts every instance. That includes the
# 4 that the raw official flags reject (expected_invalid.toml: BR-CO-16, BR-CL-10 / BR-CL-21, BR-CL-13).
@pytest.mark.parametrize("path", INSTANCES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_kosit_accepts_every_xrechnung_testsuite_instance(path: Path) -> None:
    report = validate(path.read_bytes())

    assert report.kosit is not None
    assert "XRechnung" in report.kosit.scenario
    assert report.kosit.accepted, report.kosit.blocking


# --- synthetic invoices, one per direction (fake parties, example.com, test IBAN) -----------------------------


def synthetic(syntax: Syntax, **changes: str) -> bytes:
    return to_xml(xrechnung_invoice(**changes), profile=profiles.XRECHNUNG, syntax=syntax)


@pytest.mark.parametrize("syntax", [Syntax.UBL, Syntax.CII])
def test_cen_fatal_rule_kosit_downgrades_is_not_ok_but_accepted(syntax: Syntax) -> None:
    # BR-CL-23 (fatal, CEN 1.3.16): BT-130 must be a UN/ECE Rec 20/21 code; QQQ is not in the rule's list.
    # Every XRechnung scenario sets <customLevel level="warning">BR-CL-23</customLevel>.
    data = synthetic(syntax).replace(b'unitCode="C62"', b'unitCode="QQQ"')

    report = validate(data)

    assert not report.ok
    assert report.kosit is not None
    assert report.kosit.scenario == f"EN16931 XRechnung ({'UBL Invoice' if syntax is Syntax.UBL else 'CII'})"
    assert [(o.finding.rule_id, o.finding.severity, o.severity) for o in report.kosit.overrides] == [
        ("BR-CL-23", Severity.FATAL, Severity.WARNING)
    ]
    assert report.kosit.accepted


def with_sub_invoice_line() -> bytes:
    # UBL-CR-646 (warning, CEN 1.3.16 EN16931-UBL-syntax.sch): no cac:SubInvoiceLine. cac:SubInvoiceLine follows
    # cac:Price in the UBL 2.1 InvoiceLineType sequence.
    root = _xml.parse(synthetic(Syntax.UBL))
    line = root.find(f"{CAC}InvoiceLine")
    assert line is not None
    sub = copy.deepcopy(line)
    sub.tag = f"{CAC}SubInvoiceLine"
    price = line.find(f"{CAC}Price")
    assert price is not None
    price.addnext(sub)
    return etree.tostring(root)


def with_repeated_payment_terms() -> bytes:
    # CII-SR-452 / CII-SR-453 (warning, CEN 1.3.16 EN16931-CII-syntax.sch lines 529-530): one payment terms.
    root = _xml.parse(synthetic(Syntax.CII, payment_terms="Payable within 30 days."))
    terms = root.find(f".//{RAM}SpecifiedTradePaymentTerms")
    assert terms is not None
    terms.addnext(copy.deepcopy(terms))
    return etree.tostring(root)


@pytest.mark.parametrize(
    ("document", "scenario", "upgraded"),
    [
        (with_sub_invoice_line, "EN16931 XRechnung (UBL Invoice)", ["UBL-CR-646"]),
        (with_repeated_payment_terms, "EN16931 XRechnung (CII)", ["CII-SR-452", "CII-SR-453"]),
    ],
    ids=["ubl-sub-invoice-line", "cii-repeated-payment-terms"],
)
def test_warning_kosit_upgrades_is_ok_but_rejected(
    document: t.Callable[[], bytes], scenario: str, upgraded: list[str]
) -> None:
    report = validate(document())

    assert report.ok
    assert report.kosit is not None
    assert report.kosit.scenario == scenario
    assert [(o.finding.rule_id, o.finding.severity, o.severity) for o in report.kosit.overrides] == [
        (rule_id, Severity.WARNING, Severity.ERROR) for rule_id in upgraded
    ]
    assert [f.rule_id for f in report.kosit.blocking] == upgraded
    assert not report.kosit.accepted


# --- when report.kosit is set -------------------------------------------------------------------------------------


def test_schema_invalid_xrechnung_document_is_rejected() -> None:
    root = _xml.parse(synthetic(Syntax.UBL))
    root.insert(0, root.makeelement(f"{{{_xml.UBL_CBC}}}NotAnElement"))

    report = validate(etree.tostring(root))

    assert report.kosit is not None
    assert {f.rule_id for f in report.kosit.blocking} == {"XSD"}
    assert not report.kosit.accepted


def test_cii_document_matching_two_scenarios_is_rejected() -> None:
    # ram:GuidelineSpecifiedDocumentContextParameter is maxOccurs="unbounded" (CII D16B RABIE XSD line 224), so a
    # second parameter with the core BT-24 is schema-valid and matches both "EN16931 XRechnung (CII)" and
    # "EN16931 (CII)". The CEN CII stylesheet cannot evaluate BR-01 on two IDs (SCHEMATRON-RUNTIME, fatal) and no
    # scenario overrides it, so KoSIT rejects whichever scenario it takes.
    root = _xml.parse(synthetic(Syntax.CII))
    parameter = root.find(f"{{{_xml.CII_RSM}}}ExchangedDocumentContext/{RAM}GuidelineSpecifiedDocumentContextParameter")
    assert parameter is not None
    core = copy.deepcopy(parameter)
    core_id = core.find(f"{RAM}ID")
    assert core_id is not None
    core_id.text = profiles.EN16931.specification_identifier
    parameter.addnext(core)

    # Explicit profile: with two BT-24s auto-detection falls back to EN 16931 core, which gets no verdict.
    report = validate(etree.tostring(root), profiles.XRECHNUNG)

    assert "XSD" not in {f.rule_id for f in report.findings}
    assert report.kosit is not None
    assert report.kosit.scenario == "EN16931 XRechnung (CII)"  # the first match
    assert "SCHEMATRON-RUNTIME" in {f.rule_id for f in report.kosit.blocking}
    assert not report.kosit.accepted


def test_explicit_xrechnung_profile_follows_the_scenario_kosit_selects() -> None:
    # An Extension instance under the CIUS profile: KoSIT matches the Extension scenario, which runs the same rule
    # sets, so its levels apply (BR-CO-16 fatal -> information).
    report = validate(member("xrechnung-testsuite", "instances/extension/05.01a-INVOICE_ubl.xml"), profiles.XRECHNUNG)

    assert report.kosit is not None
    assert report.kosit.scenario == "EN16931 XRechnung Extension (UBL Invoice)"
    assert ("BR-CO-16", Severity.INFORMATION) in {(o.finding.rule_id, o.severity) for o in report.kosit.overrides}
    assert report.kosit.accepted


def test_explicit_xrechnung_profile_on_a_core_document_gets_no_verdict() -> None:
    # KoSIT routes a core BT-24 to "EN16931 (UBL Invoice)", which does not run the XRechnung rules that ran here.
    report = validate(member("cen-ubl", "examples/ubl-tc434-example1.xml"), profiles.XRECHNUNG)

    assert report.kosit is None


@pytest.mark.parametrize(
    ("name", "path", "profile"),
    [
        ("cen-ubl", "examples/ubl-tc434-example1.xml", None),
        ("peppol-bis", "rules/examples/base-example.xml", None),
        ("xrechnung-testsuite", "instances/standard/01.01a-INVOICE_ubl.xml", profiles.PEPPOL),
        ("xrechnung-testsuite", "instances/standard/01.01a-INVOICE_ubl.xml", profiles.EN16931),
    ],
    ids=["en16931", "peppol", "xrechnung-doc-as-peppol", "xrechnung-doc-as-en16931"],
)
def test_non_xrechnung_profiles_get_no_verdict(
    name: artifacts.SourceName, path: str, profile: profiles.Profile | None
) -> None:
    assert validate(member(name, path), profile).kosit is None


def test_override_pairs_keep_the_official_finding() -> None:
    report = validate(synthetic(Syntax.UBL).replace(b'unitCode="C62"', b'unitCode="QQQ"'))

    assert report.kosit is not None
    (override,) = report.kosit.overrides
    assert override == SeverityOverride(next(f for f in report.findings if f.rule_id == "BR-CL-23"), Severity.WARNING)
