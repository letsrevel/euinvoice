"""The Schematron runner against the pinned official rule sets and upstream examples (``make conformance``)."""

import collections
from pathlib import Path

import pytest
from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ArtifactsNotAvailableError
from euinvoice.validate import artifacts, schematron
from euinvoice.validate.report import Severity, ValidationReport

pytestmark = pytest.mark.conformance


def cached(name: artifacts.SourceName) -> Path | None:
    """The cache entry of ``name`` if it is there; never fetches.

    Parametrization runs at collection time, also in ``make test`` where these tests are deselected,
    so it must not touch the network. ``test_parametrized_corpora_are_complete`` fetches and fails if a
    cold cache made the parametrized tests vacuous.
    """
    try:
        return artifacts.source_dir(name)
    except ArtifactsNotAvailableError:
        return None


def examples(name: artifacts.SourceName) -> list[Path]:
    """Every official example of a CEN source (``*.xml`` and ``*.XML``), if cached."""
    directory = cached(name)
    if directory is None:
        return []
    return sorted(p for p in (directory / "examples").iterdir() if p.suffix.lower() == ".xml")


CEN_UBL_EXAMPLES = examples("cen-ubl")
CEN_CII_EXAMPLES = examples("cen-cii")


def cen_example(name: str) -> bytes:
    return (artifacts.fetch(["cen-ubl"])["cen-ubl"] / "examples" / name).read_bytes()


# --- AC of #16: the scoping facts (IMPLEMENTATION_PLAN.md §3) --------------------------------------


def test_cen_ubl_example1_has_no_findings() -> None:
    assert schematron.run(schematron.CEN_UBL, cen_example("ubl-tc434-example1.xml")) == ()


def test_dropping_the_invoice_number_yields_exactly_br02_fatal() -> None:
    root = _xml.parse(cen_example("ubl-tc434-example1.xml"))
    invoice_number = root.find(f"{{{_xml.UBL_CBC}}}ID")
    assert invoice_number is not None
    root.remove(invoice_number)

    findings = schematron.run(schematron.CEN_UBL, root)

    # BR-02 in EN16931-UBL-validation.xslt (CEN 1.3.16): assert normalize-space(cbc:ID) != '', flag fatal.
    assert [(f.rule_id, f.severity, f.source) for f in findings] == [("BR-02", Severity.FATAL, "cen-ubl")]
    assert findings[0].message == "[BR-02]-An Invoice shall have an Invoice number (BT-1)."
    assert findings[0].location is not None
    assert findings[0].location.startswith("/*:Invoice[")
    assert not ValidationReport(findings).ok


def test_amount_the_rules_cannot_evaluate_is_a_blocking_finding_not_an_exception() -> None:
    # CEN's BR-CO rules cast cbc:PayableAmount to xs:decimal; "abc" makes the stylesheet fail (FORG0001).
    root = _xml.parse(cen_example("ubl-tc434-example1.xml"))
    payable = next(root.iter(f"{{{_xml.UBL_CBC}}}PayableAmount"))
    payable.text = "abc"

    findings = schematron.run(schematron.CEN_UBL, root)

    assert [(f.rule_id, f.severity) for f in findings] == [(schematron.RUNTIME_ERROR_RULE_ID, Severity.FATAL)]
    assert 'Cannot convert string "abc" to xs:decimal' in findings[0].message
    assert not ValidationReport(findings).ok


@pytest.mark.parametrize("path", CEN_UBL_EXAMPLES, ids=lambda p: p.name)
def test_every_cen_ubl_example_passes_the_cen_ubl_rules(path: Path) -> None:
    assert ValidationReport(schematron.run(schematron.CEN_UBL, path.read_bytes())).ok


@pytest.mark.parametrize("path", CEN_CII_EXAMPLES, ids=lambda p: p.name)
def test_every_cen_cii_example_passes_the_cen_cii_rules(path: Path) -> None:
    assert ValidationReport(schematron.run(schematron.CEN_CII, path.read_bytes())).ok


# --- every exposed rule set compiles and runs ------------------------------------------------------


@pytest.mark.parametrize(
    ("rule_set", "name", "member"),
    [
        (schematron.PEPPOL_UBL, "peppol-bis", "rules/examples/base-example.xml"),
        (schematron.XRECHNUNG_UBL, "xrechnung-testsuite", "instances/standard/01.01a-INVOICE_ubl.xml"),
        (schematron.XRECHNUNG_CII, "xrechnung-testsuite", "instances/standard/01.01a-INVOICE_uncefact.xml"),
    ],
    ids=lambda v: v.stylesheet if isinstance(v, schematron.RuleSet) else "",
)
def test_profile_rule_sets_pass_an_upstream_valid_instance(
    rule_set: schematron.RuleSet, name: artifacts.SourceName, member: str
) -> None:
    findings = schematron.run(rule_set, (artifacts.fetch([name])[name] / member).read_bytes())
    assert ValidationReport(findings).ok, findings
    assert {f.source for f in findings} <= {rule_set.source}


@pytest.mark.parametrize("rule_set", schematron.RULE_SETS, ids=lambda r: r.stylesheet)
def test_every_assert_in_the_pinned_stylesheets_has_a_known_flag(rule_set: schematron.RuleSet) -> None:
    # Backs the "missing or unknown flag → error" fallback in svrl_findings: no pinned rule relies on it.
    # CEN writes the flag as <xsl:attribute name="flag">, SchXslt (Peppol, XRechnung) as a literal attribute.
    xsl = f"{{{_xml.XSLT}}}"
    path = artifacts.fetch([rule_set.source])[rule_set.source] / rule_set.stylesheet
    stylesheet = _xml.parse(path.read_bytes())
    flags: collections.Counter[str | None] = collections.Counter()
    for result in stylesheet.iter(f"{{{_xml.SVRL}}}failed-assert", f"{{{_xml.SVRL}}}successful-report"):
        attribute = result.find(f"{xsl}attribute[@name='flag']")
        flags[result.get("flag") if attribute is None else attribute.text] += 1
    assert flags
    assert set(flags) <= {s.value for s in Severity}, flags


# --- Peppol vefa unit tests (rules/unit-*) through the runner --------------------------------------

VEFA = f"{{{_xml.VEFA}}}"


def vefa_files() -> list[Path]:
    """Every vefa test file of the Peppol rules (``rules/unit-UBL-*``, ``rules/unit-CII-*``), if cached."""
    directory = cached("peppol-bis")
    return [] if directory is None else sorted((directory / "rules").glob("unit-*/*.xml"))


def expectations(test: etree._Element) -> list[tuple[str, str, int | None]]:
    """The ``(kind, rule id, number)`` expectations of one vefa ``<test>`` (``success|error|warning``)."""
    expect = test.find(f"{VEFA}assert")
    if expect is None:
        return []
    return [
        (etree.QName(e).localname, (e.text or "").strip(), int(n) if (n := e.get("number")) else None)
        for e in expect
        if isinstance(e.tag, str) and etree.QName(e).localname in {"success", "error", "warning"}
    ]


def check_vefa_test(test: etree._Element, rule_set: schematron.RuleSet) -> list[str]:
    """Return the expectations of one vefa ``<test>`` that our findings do not meet.

    vefa semantics (difi.no vefa-validator, as used by the Peppol rules repository): ``<success>`` means
    the rule does not fire; ``<error>`` / ``<warning>`` mean it fires with flag ``fatal`` / ``warning``,
    exactly ``@number`` times when given, else at least once.
    """
    document = next(c for c in test if isinstance(c.tag, str) and not c.tag.startswith(VEFA))
    findings = schematron.run(rule_set, document)
    fired = collections.Counter((f.rule_id, f.severity) for f in findings)
    misses = []
    for kind, rule, number in expectations(test):
        if kind == "success":
            ok = all(f.rule_id != rule for f in findings)
        else:
            count = fired[rule, Severity.FATAL if kind == "error" else Severity.WARNING]
            ok = count > 0 if number is None else count == number
        if not ok:
            misses.append(f"{kind} {rule} number={number} fired={dict(fired)}")
    return misses


VEFA_FILES = vefa_files()


@pytest.mark.parametrize("path", VEFA_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_peppol_vefa_unit_tests_hold(path: Path) -> None:
    rule_set = schematron.PEPPOL_UBL if path.parent.name.startswith("unit-UBL-") else schematron.PEPPOL_CII
    tests = [t for t in _xml.parse(path.read_bytes()).iter(f"{VEFA}test") if expectations(t)]
    assert tests
    misses = {i: m for i, test in enumerate(tests) if (m := check_vefa_test(test, rule_set))}
    assert misses == {}


def test_parametrized_corpora_are_complete() -> None:
    # Fetches (the parametrization above never does), then checks that collection saw every input.
    # 1033 vefa expectations is the spec-auditor's reference count on Peppol 3.0.21 (issue #16), so a
    # cold cache, a glob or a parsing slip cannot silently shrink the suite.
    artifacts.fetch(["cen-ubl", "cen-cii", "peppol-bis"])
    assert (len(examples("cen-ubl")), len(examples("cen-cii"))) == (19, 15)
    total = sum(len(expectations(t)) for p in vefa_files() for t in _xml.parse(p.read_bytes()).iter(f"{VEFA}test"))
    assert total == 1033
    assert (len(CEN_UBL_EXAMPLES), len(CEN_CII_EXAMPLES), len(VEFA_FILES)) == (19, 15, len(vefa_files()))
