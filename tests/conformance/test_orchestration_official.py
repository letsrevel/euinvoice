"""validate() orchestration against the pinned official artifacts and upstream corpora (``make conformance``)."""

import copy
import typing as t
from pathlib import Path

import pytest
from lxml import etree

from euinvoice import _xml, profiles
from euinvoice.errors import ArtifactsNotAvailableError, UnsupportedDocumentError
from euinvoice.validate import EUINVOICE_SOURCE, PROFILE_FALLBACK_RULE_ID, artifacts, schematron, validate, xsd
from euinvoice.validate.report import Severity

CII_XSD = "xsd:xrechnung-validator-configuration"

pytestmark = pytest.mark.conformance

# Peppol BIS and XRechnung profile objects do not exist yet (#20, #21): test-local stand-ins with the rule
# sets verified on issue #17 (Peppol: CEN then Peppol; XRechnung: CEN then XRechnung, as in KoSIT
# scenarios.xml). Their BT-24 is irrelevant here because they are passed explicitly.
PEPPOL = profiles.Profile(
    id="test-peppol", title="Peppol BIS (test)", specification_identifier="urn:example.com:peppol",
    syntaxes=frozenset({"ubl", "cii"}), rule_sets=("cen", "peppol"),
)  # fmt: skip
XRECHNUNG = profiles.Profile(
    id="test-xrechnung", title="XRechnung (test)", specification_identifier="urn:example.com:xrechnung",
    syntaxes=frozenset({"ubl", "cii"}), rule_sets=("cen", "xrechnung"),
)  # fmt: skip

EXAMPLE1 = "examples/ubl-tc434-example1.xml"
PEPPOL_BASE = "rules/examples/base-example.xml"
XR_UBL = "instances/standard/01.01a-INVOICE_ubl.xml"
BLOCKING = (Severity.FATAL, Severity.ERROR)


def cached(name: artifacts.SourceName) -> Path | None:
    """The cache entry of ``name`` if present; never fetches (parametrization runs at collection time).

    ``test_corpora_are_complete`` fetches and fails if a cold cache made the parametrized tests vacuous.
    """
    try:
        return artifacts.source_dir(name)
    except ArtifactsNotAvailableError:
        return None


def corpus(name: artifacts.SourceName, subdir: str) -> list[Path]:
    """Every ``*.xml`` / ``*.XML`` under ``subdir`` of a cached source."""
    directory = cached(name)
    return [] if directory is None else sorted(p for p in (directory / subdir).rglob("*") if p.suffix.lower() == ".xml")


CEN_EXAMPLES = corpus("cen-ubl", "examples") + corpus("cen-cii", "examples")
XRECHNUNG_INSTANCES = corpus("xrechnung-testsuite", "instances")


def member(name: artifacts.SourceName, path: str) -> bytes:
    return (artifacts.fetch([name])[name] / path).read_bytes()


def blank_invoice_number(data: bytes) -> bytes:
    """``data`` (UBL) with an empty ``cbc:ID`` (BT-1): XSD-valid, but CEN BR-02 (fatal) requires a value."""
    root = _xml.parse(data)
    number = root.find(f"{{{_xml.UBL_CBC}}}ID")
    assert number is not None
    number.text = ""
    return etree.tostring(root)


# --- which rule sets run, per profile ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("profile", "name", "path", "sources"),
    [
        (profiles.EN16931, "cen-ubl", EXAMPLE1, {"cen-ubl"}),
        (PEPPOL, "peppol-bis", PEPPOL_BASE, {"cen-ubl", "peppol-bis"}),
        (XRECHNUNG, "xrechnung-testsuite", XR_UBL, {"cen-ubl", "xrechnung-schematron"}),
    ],
    ids=["en16931", "peppol", "xrechnung"],
)
def test_each_profile_runs_cen_and_tags_findings_with_their_source(
    profile: profiles.Profile, name: artifacts.SourceName, path: str, sources: set[str]
) -> None:
    # A valid upstream instance passes its profile; blanking BT-1 makes CEN BR-02 (fatal) fire.
    assert validate(member(name, path), profile).ok

    report = validate(blank_invoice_number(member(name, path)), profile)

    assert ("BR-02", Severity.FATAL, "cen-ubl") in {(f.rule_id, f.severity, f.source) for f in report.findings}
    assert {f.source for f in report.findings} <= sources
    assert not report.ok


def test_peppol_rules_run_only_under_a_peppol_profile() -> None:
    # CEN example1 is core-valid but has no BT-23, which PEPPOL-EN16931-R001 (fatal, Peppol BIS 3.0.21
    # PEPPOL-EN16931-UBL.sch) requires.
    data = member("cen-ubl", EXAMPLE1)
    assert validate(data, profiles.EN16931).findings == ()

    report = validate(data, PEPPOL)

    assert "PEPPOL-EN16931-R001" in {f.rule_id for f in report.findings}
    assert {f.source for f in report.findings} == {"peppol-bis"}
    assert not report.ok


def test_xrechnung_rules_run_only_under_an_xrechnung_profile() -> None:
    # Under XRechnung, example1's core BT-24 fails BR-DE-21 (XRechnung 3.0.2 XRechnung-UBL-validation.xsl);
    # Peppol does not run alongside (issue #17: never Peppol and XRechnung together).
    report = validate(member("cen-ubl", EXAMPLE1), XRECHNUNG)

    assert "BR-DE-21" in {f.rule_id for f in report.findings}
    assert {f.source for f in report.findings} == {"xrechnung-schematron"}
    assert not report.ok


# --- XSD short-circuit --------------------------------------------------------------------------------


def test_schema_invalid_document_stops_after_the_xsd_step() -> None:
    # An element the UBL 2.1 Invoice XSD does not allow, and BT-1 blanked: only XSD findings, no BR-02.
    root = _xml.parse(blank_invoice_number(member("cen-ubl", EXAMPLE1)))
    root.insert(0, root.makeelement(f"{{{_xml.UBL_CBC}}}NotAnElement"))

    report = validate(etree.tostring(root), PEPPOL)

    assert report.findings
    assert {(f.rule_id, f.severity, f.source) for f in report.findings} == {
        (xsd.RULE_ID, Severity.FATAL, "xsd:ubl-2_1")
    }


def test_wrong_root_in_a_supported_namespace_is_rejected() -> None:
    with pytest.raises(UnsupportedDocumentError, match="unsupported root element"):
        validate(f'<Order xmlns="{_xml.UBL_INVOICE}"/>'.encode())


# --- a missing or repeated BT-24 is reported by the official steps, after the core fallback -----------

CBC = f"{{{_xml.UBL_CBC}}}"
RAM = f"{{{_xml.CII_RAM}}}"
CONTEXT = f"{{{_xml.CII_RSM}}}ExchangedDocumentContext"
PARAMETER = f"{CONTEXT}/{RAM}GuidelineSpecifiedDocumentContextParameter"


def ubl_example1() -> etree._Element:
    return _xml.parse(member("cen-ubl", EXAMPLE1))


def cii_example1() -> etree._Element:
    return _xml.parse(member("cen-cii", "examples/CII_example1.xml"))


def found(element: etree._Element | None) -> etree._Element:
    assert element is not None
    return element


def without(root: etree._Element, path: str) -> etree._Element:
    element = found(root.find(path))
    found(element.getparent()).remove(element)
    return root


def repeated(root: etree._Element, path: str) -> etree._Element:
    element = found(root.find(path))
    element.addnext(copy.deepcopy(element))
    return root


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        # BR-01 (fatal, CEN 1.3.16 EN16931-UBL-model.sch): BT-24 required.
        (lambda: without(ubl_example1(), f"{CBC}CustomizationID"), [("BR-01", "cen-ubl")]),
        # BR-01 plus CII-SR-009 / CII-SR-010 (fatal, EN16931-CII-syntax.sch): exactly one parameter and ID.
        (
            lambda: without(cii_example1(), PARAMETER),
            [("BR-01", "cen-cii"), ("CII-SR-009", "cen-cii"), ("CII-SR-010", "cen-cii")],
        ),
        # cbc:CustomizationID and ram:ID are 0..1 in the UBL 2.1 / CII D16B XSDs.
        (lambda: repeated(ubl_example1(), f"{CBC}CustomizationID"), [(xsd.RULE_ID, "xsd:ubl-2_1")]),
        (lambda: repeated(cii_example1(), f"{PARAMETER}/{RAM}ID"), [(xsd.RULE_ID, CII_XSD)]),
        # The parameter itself may repeat in the XSD; CEN's compiled BR-01 then fails at run time (XPTY0004).
        (lambda: repeated(cii_example1(), PARAMETER), [(schematron.RUNTIME_ERROR_RULE_ID, "cen-cii")]),
    ],
    ids=["ubl-missing", "cii-missing", "ubl-repeated", "cii-repeated-id", "cii-repeated-parameter"],
)
def test_bt24_problems_fall_back_to_core_and_fail_the_official_rules(
    document: t.Callable[[], etree._Element], expected: list[tuple[str, str]]
) -> None:
    report = validate(etree.tostring(document()))

    note, *official = report.findings
    assert (note.rule_id, note.severity, note.source) == (
        PROFILE_FALLBACK_RULE_ID,
        Severity.INFORMATION,
        EUINVOICE_SOURCE,
    )
    assert sorted({(f.rule_id, f.source) for f in official}) == expected
    assert all(f.severity is Severity.FATAL for f in official)
    assert not report.ok


# --- corpora ------------------------------------------------------------------------------------------


def test_corpora_are_complete() -> None:
    artifacts.fetch(["cen-ubl", "cen-cii", "xrechnung-testsuite"])
    # 15 UBL + 12 CII core-BT-24 examples (test_profiles_official), plus 4 UBL + 3 CII with another BT-24.
    assert len(CEN_EXAMPLES) == 34
    assert len(XRECHNUNG_INSTANCES) == 86
    instances = artifacts.source_dir("xrechnung-testsuite") / "instances"
    assert set(CUSTOM_LEVEL_GAP) <= {p.relative_to(instances).as_posix() for p in XRECHNUNG_INSTANCES}


@pytest.mark.parametrize("path", CEN_EXAMPLES, ids=lambda p: p.name)
def test_every_cen_example_is_ok_with_auto_detection(path: Path) -> None:
    report = validate(path.read_bytes())

    assert report.ok, [f for f in report.findings if f.severity in BLOCKING]
    # Examples with a non-core BT-24 (BIS3_*, an Italian CIUS, ...) are checked against core only, and say so.
    assert {f.rule_id for f in report.findings if f.source == EUINVOICE_SOURCE} <= {PROFILE_FALLBACK_RULE_ID}


# KoSIT customLevel overrides (issue #49, needs-human) are not applied; validate() reports the raw official
# flags (D8). These tests pin the gap in both directions so a change on either side is noticed.
#
# Downgrades: these instances fail raw CEN flags. KoSIT's scenarios.xml (xrechnung-validator-configuration
# 2026-08-31) downgrades exactly these rules with <customLevel level="information"> in the scenario each
# instance matches (Extension UBL: BR-CO-16; Extension CII: BR-CL-10, BR-CL-21; CVD UBL and CII: BR-CL-13).
CUSTOM_LEVEL_GAP = {
    "extension/04.05a-INVOICE_uncefact.xml": {"BR-CL-10", "BR-CL-21"},
    "extension/05.01a-INVOICE_ubl.xml": {"BR-CO-16"},
    "technical-cases/cvd/02.01a-cvd_INVOICE_ubl.xml": {"BR-CL-13"},
    "technical-cases/cvd/02.01a-cvd_INVOICE_uncefact.xml": {"BR-CL-13"},
}


@pytest.mark.parametrize("path", XRECHNUNG_INSTANCES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_xrechnung_testsuite_instance_validates_under_xrechnung(path: Path) -> None:
    relative = path.relative_to(artifacts.source_dir("xrechnung-testsuite") / "instances").as_posix()

    report = validate(path.read_bytes(), XRECHNUNG)

    blocking = {f.rule_id for f in report.findings if f.severity in BLOCKING}
    assert blocking == CUSTOM_LEVEL_GAP.get(relative, set()), report.findings
    assert {f.source for f in report.findings} <= {"cen-ubl", "cen-cii", "xrechnung-schematron"}
