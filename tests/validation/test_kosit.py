"""Unit tests for the KoSIT verdict (issue #49), offline: a synthetic ``scenarios.xml`` in a fake cache."""

import typing as t
from pathlib import Path

import pytest

from euinvoice import _xml, profiles
from euinvoice.errors import ArtifactIntegrityError, ArtifactsNotAvailableError, ParseError
from euinvoice.report import Finding, KositAssessment, Severity, SeverityOverride
from euinvoice.validation import artifacts, kosit, schematron
from euinvoice.validation.artifacts import Source

S = _xml.KOSIT_SCENARIOS
A_ID = "urn:example.com:a"


def resource(location: str) -> str:
    return (
        "<validateWithSchematron><resource><name>n</name>"
        f"<location>{location}</location></resource></validateWithSchematron>"
    )


# Synthetic, shaped like the pinned KoSIT configuration: scenario A matches one UBL BT-24 and runs CEN + XRechnung;
# B matches every UBL Invoice and runs CEN only; C matches a CII document.
SCENARIOS = f"""<?xml version="1.0" encoding="UTF-8"?>
<scenarios xmlns="{S}" frameworkVersion="1.0.0">
  <name>Synthetic</name>
  <scenario>
    <name>A (UBL Invoice)</name>
    <namespace prefix="cbc">{_xml.UBL_CBC}</namespace>
    <namespace prefix="invoice">{_xml.UBL_INVOICE}</namespace>
    <namespace prefix="rep">http://www.xoev.de/de/validator/varl/1</namespace>
    <match>exists(/invoice:Invoice/cbc:CustomizationID[ . = '{A_ID}']) </match>
    <validateWithXmlSchema><resource><name>x</name><location>resources/x.xsd</location></resource></validateWithXmlSchema>
    {resource("resources/ubl/2.1/xsl/EN16931-UBL-validation.xsl")}
    {resource("resources/xrechnung/3.0.2/xsl/XRechnung-UBL-validation.xsl")}
    <createReport>
      <resource><name>r</name><location>resources/report.xsl</location></resource>
      <customLevel level="warning">BR-CL-23</customLevel>
      <customLevel level="error">
        UBL-CR-646	CII-SR-452
      </customLevel>
      <customLevel level="information">BR-CO-16</customLevel>
    </createReport>
  </scenario>
  <scenario>
    <name>B (UBL Invoice)</name>
    <namespace prefix="invoice">{_xml.UBL_INVOICE}</namespace>
    <match>exists(/invoice:Invoice)</match>
    {resource("resources/ubl/2.1/xsl/EN16931-UBL-validation.xsl")}
    <createReport><resource><name>r</name><location>resources/report.xsl</location></resource></createReport>
  </scenario>
  <scenario>
    <name>C (CII)</name>
    <namespace prefix="rsm">{_xml.CII_RSM}</namespace>
    <match>exists(/rsm:CrossIndustryInvoice)</match>
    {resource("resources/cii/16b/xsl/EN16931-CII-validation.xsl")}
    <createReport><resource><name>r</name><location>resources/report.xsl</location></resource></createReport>
  </scenario>
  <noScenarioReport><resource><name>d</name><location>resources/default-report.xsl</location></resource></noScenarioReport>
</scenarios>"""


def ubl(bt24: str) -> bytes:
    return (
        f'<Invoice xmlns="{_xml.UBL_INVOICE}" xmlns:cbc="{_xml.UBL_CBC}">'
        f"<cbc:CustomizationID>{bt24}</cbc:CustomizationID></Invoice>"
    ).encode()


CII = f'<rsm:CrossIndustryInvoice xmlns:rsm="{_xml.CII_RSM}"/>'.encode()
ORDER = f'<Order xmlns="{_xml.UBL_INVOICE}"/>'.encode()


def finding(rule_id: str, severity: Severity) -> Finding:
    return Finding(rule_id, severity, None, rule_id, "cen-ubl")


@pytest.fixture
def loaded() -> tuple[kosit.Scenario, ...]:
    return kosit.load(SCENARIOS.encode())


def by_name(scenarios: tuple[kosit.Scenario, ...], name: str) -> kosit.Scenario:
    return next(s for s in scenarios if s.name == name)


# --- load ------------------------------------------------------------------------------------------------------


def test_load_reads_every_scenario_in_document_order(loaded: tuple[kosit.Scenario, ...]) -> None:
    assert [s.name for s in loaded] == ["A (UBL Invoice)", "B (UBL Invoice)", "C (CII)"]
    a = loaded[0]
    assert a.match == f"exists(/invoice:Invoice/cbc:CustomizationID[ . = '{A_ID}']) "
    assert a.namespaces == (
        ("cbc", _xml.UBL_CBC),
        ("invoice", _xml.UBL_INVOICE),
        ("rep", "http://www.xoev.de/de/validator/varl/1"),
    )
    # Schematron steps only (not the XSD, not the report), as file stems.
    assert a.schematron == ("EN16931-UBL-validation", "XRechnung-UBL-validation")
    assert loaded[2].schematron == ("EN16931-CII-validation",)


def test_custom_level_codes_are_whitespace_tokenized(loaded: tuple[kosit.Scenario, ...]) -> None:
    # rep:custom-level matches tokenize(., '\s+') (default-report.xsl): newlines and tabs separate codes too.
    assert dict(loaded[0].levels) == {
        "BR-CL-23": Severity.WARNING,
        "UBL-CR-646": Severity.ERROR,
        "CII-SR-452": Severity.ERROR,
        "BR-CO-16": Severity.INFORMATION,
    }
    assert dict(loaded[1].levels) == {}


def test_levels_are_read_only(loaded: tuple[kosit.Scenario, ...]) -> None:
    # Parsed scenarios are cached and shared between validate() calls.
    levels = t.cast(dict[str, Severity], loaded[0].levels)
    with pytest.raises(TypeError):
        levels["BR-02"] = Severity.INFORMATION


@pytest.mark.parametrize(
    "data",
    [
        SCENARIOS.replace('level="warning"', 'level="fatal"'),  # VARL levels are error, warning and information
        SCENARIOS.replace(">BR-CO-16<", ">BR-CL-23<"),  # a code twice in one scenario: KoSIT's lookup fails
        SCENARIOS.replace("<name>A (UBL Invoice)</name>", ""),
        f'<other xmlns="{S}"/>',
    ],
    ids=["unknown-level", "code-twice", "no-name", "wrong-root"],
)
def test_malformed_configuration_is_an_integrity_error(data: str) -> None:
    with pytest.raises(ArtifactIntegrityError, match=r"scenarios\.xml"):
        kosit.load(data.encode())


# --- select: XPath on Saxon, first match wins --------------------------------------------------------------------


def test_first_matching_scenario_wins(loaded: tuple[kosit.Scenario, ...]) -> None:
    # A and B both match; A comes first.
    assert kosit.select(loaded, _xml.parse(ubl(A_ID))) is loaded[0]
    assert kosit.select(loaded, _xml.parse(ubl("urn:example.com:other"))) is loaded[1]
    assert kosit.select(loaded, _xml.parse(CII)) is loaded[2]


def test_no_matching_scenario_selects_none(loaded: tuple[kosit.Scenario, ...]) -> None:
    assert kosit.select(loaded, _xml.parse(ORDER)) is None
    assert kosit.select((), _xml.parse(ubl(A_ID))) is None


def test_match_saxon_cannot_evaluate_is_an_integrity_error(loaded: tuple[kosit.Scenario, ...]) -> None:
    broken = kosit.Scenario(name="X", match="exists(/q:a)", namespaces=(), schematron=(), levels={})
    with pytest.raises(ArtifactIntegrityError, match="'X'"):
        kosit.select((broken,), _xml.parse(ORDER))


# --- assess: overrides and the verdict ------------------------------------------------------------------------


def test_assess_applies_the_scenario_levels(loaded: tuple[kosit.Scenario, ...]) -> None:
    downgraded = finding("BR-CL-23", Severity.FATAL)
    upgraded = finding("UBL-CR-646", Severity.WARNING)
    kept = finding("BR-02", Severity.FATAL)
    info = finding("BR-CO-16", Severity.FATAL)
    warning = finding("UBL-CR-001", Severity.WARNING)

    assessment = kosit.assess(loaded[0], (downgraded, upgraded, kept, info, warning))

    assert assessment == KositAssessment(
        scenario="A (UBL Invoice)",
        overrides=(
            SeverityOverride(downgraded, Severity.WARNING),
            SeverityOverride(upgraded, Severity.ERROR),
            SeverityOverride(info, Severity.INFORMATION),
        ),
        blocking=(upgraded, kept),
    )
    assert not assessment.accepted


def test_downgraded_fatal_findings_alone_are_accepted(loaded: tuple[kosit.Scenario, ...]) -> None:
    assert kosit.assess(loaded[0], (finding("BR-CL-23", Severity.FATAL),)).accepted
    assert kosit.assess(loaded[0], ()).accepted


def test_codes_of_other_scenarios_do_not_apply(loaded: tuple[kosit.Scenario, ...]) -> None:
    # B has no customLevel: BR-CL-23 keeps its official fatal flag (VARL error, default-report.xsl line 251).
    fatal = finding("BR-CL-23", Severity.FATAL)
    assert kosit.assess(loaded[1], (fatal,)) == KositAssessment("B (UBL Invoice)", (), (fatal,))


def test_blocking_xsd_finding_rejects(loaded: tuple[kosit.Scenario, ...]) -> None:
    xsd_error = Finding("XSD", Severity.FATAL, "1: /Invoice", "bad", "xsd:ubl-2_1")
    xsd_warning = Finding("XSD", Severity.WARNING, None, "meh", "xsd:ubl-2_1")
    assert not kosit.assess(loaded[0], (xsd_error,)).accepted
    assert kosit.assess(loaded[0], (xsd_warning,)).accepted


# --- verdict: when validate() sets report.kosit -----------------------------------------------------------------

XR_UBL_RULES = (schematron.CEN_UBL, schematron.XRECHNUNG_UBL)


@pytest.fixture
def pinned(monkeypatch: pytest.MonkeyPatch, loaded: tuple[kosit.Scenario, ...]) -> None:
    monkeypatch.setattr(kosit, "scenarios", lambda: loaded)


@pytest.mark.parametrize("profile", [profiles.XRECHNUNG, profiles.XRECHNUNG_EXTENSION, profiles.XRECHNUNG_CVD])
@pytest.mark.usefixtures("pinned")
def test_xrechnung_profiles_get_the_matching_scenario(profile: profiles.Profile) -> None:
    fatal = finding("BR-CL-23", Severity.FATAL)
    assessment = kosit.verdict(_xml.parse(ubl(A_ID)), profile, XR_UBL_RULES, (fatal,))
    assert assessment == KositAssessment("A (UBL Invoice)", (SeverityOverride(fatal, Severity.WARNING),))


@pytest.mark.parametrize(
    "profile", [profiles.EN16931, profiles.PEPPOL, profiles.FACTURX_EN16931, profiles.FACTURX_XRECHNUNG]
)
def test_other_profiles_get_none_without_reading_the_configuration(
    profile: profiles.Profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    def cold() -> t.NoReturn:
        raise AssertionError("scenarios.xml must not be read")

    monkeypatch.setattr(kosit, "scenarios", cold)
    rule_sets = tuple(schematron.CEN_UBL if n == "cen" else schematron.XRECHNUNG_UBL for n in profile.rule_sets)
    assert kosit.verdict(_xml.parse(ubl(A_ID)), profile, rule_sets, ()) is None


@pytest.mark.usefixtures("pinned")
def test_scenario_that_runs_other_rule_sets_gives_none() -> None:
    # Explicit XRECHNUNG on a document KoSIT routes to B (CEN only): its verdict is not about the rules that ran.
    assert kosit.verdict(_xml.parse(ubl("urn:example.com:other")), profiles.XRECHNUNG, XR_UBL_RULES, ()) is None


@pytest.mark.usefixtures("pinned")
def test_no_matching_scenario_gives_none() -> None:
    assert kosit.verdict(_xml.parse(ORDER), profiles.XRECHNUNG, XR_UBL_RULES, ()) is None


# --- scenarios(): the pinned file, cached ------------------------------------------------------------------------

NAME: artifacts.SourceName = "xrechnung-validator-configuration"


def install(root: Path, content: str = SCENARIOS, *, sha: str = "0" * 64) -> dict[str, Source]:
    """Lay out a complete fake cache entry for the KoSIT configuration and return its manifest."""
    source = Source(
        name=NAME, version="1.0", url="https://example.com/x.zip", sha256=sha, license="MIT", members=("*",)
    )
    sources: dict[str, Source] = {NAME: source}
    target = root / NAME / "1.0"
    target.mkdir(parents=True, exist_ok=True)
    (target / "scenarios.xml").write_text(content, encoding="utf-8")
    (target / artifacts.MARKER).write_text(artifacts._fingerprint(source, sources) + "\n", encoding="ascii")
    return sources


def test_scenarios_reads_the_cached_configuration_once(tmp_path: Path) -> None:
    sources = install(tmp_path)
    first = kosit.scenarios(root=tmp_path, sources=sources)
    assert [s.name for s in first] == ["A (UBL Invoice)", "B (UBL Invoice)", "C (CII)"]
    # Same fingerprint: the parsed configuration is reused, the edited file is not re-read.
    install(tmp_path, SCENARIOS.replace("A (UBL Invoice)", "edited"))
    assert kosit.scenarios(root=tmp_path, sources=sources) is first
    # A new recipe (new fingerprint) reads it again.
    other = install(tmp_path, SCENARIOS.replace("A (UBL Invoice)", "edited"), sha="1" * 64)
    assert kosit.scenarios(root=tmp_path, sources=other)[0].name == "edited"


def test_scenarios_on_a_cold_cache_names_the_fetch_command(tmp_path: Path) -> None:
    with pytest.raises(ArtifactsNotAvailableError, match=r"artifacts fetch"):
        kosit.scenarios(root=tmp_path, sources=install(tmp_path / "elsewhere"))


def test_scenarios_file_goes_through_the_hardened_parser(tmp_path: Path) -> None:
    sources = install(tmp_path, '<!DOCTYPE x [<!ENTITY e "boom">]><scenarios>&e;</scenarios>', sha="2" * 64)
    with pytest.raises(ParseError, match="DOCTYPE"):
        kosit.scenarios(root=tmp_path, sources=sources)
