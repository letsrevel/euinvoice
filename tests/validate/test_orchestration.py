"""Unit tests for validate() orchestration, offline: the XSD and Schematron steps are spies."""

import itertools
import pathlib
import typing as t

import pytest
from lxml import etree

from euinvoice import _xml, profiles
from euinvoice.errors import ArtifactsNotAvailableError, ParseError, UnsupportedDocumentError
from euinvoice.profiles import _base as profiles_base
from euinvoice.report import Finding, Severity
from euinvoice.syntax import Syntax
from euinvoice.validate import EUINVOICE_SOURCE, PROFILE_FALLBACK_RULE_ID, orchestration, schematron, validate, xsd

CORE = "urn:cen.eu:en16931:2017"
CIUS = "urn:cen.eu:en16931:2017#compliant#urn:example.com:cius"
NBSP = "\N{NO-BREAK SPACE}"
NO_BT24 = "no single non-empty specification identifier (BT-24)"

PEPPOL = profiles.PEPPOL
UBL_ONLY = profiles.Profile(
    id="test-ubl", title="t", specification_identifier="urn:example.com:ubl", syntaxes=frozenset({Syntax.UBL}),
    rule_sets=("cen",),
)  # fmt: skip


def ubl(*bt24: str, root: str = "Invoice", ns: str = _xml.UBL_INVOICE) -> bytes:
    ids = "".join(f"<cbc:CustomizationID>{v}</cbc:CustomizationID>" for v in bt24)
    return f'<{root} xmlns="{ns}" xmlns:cbc="{_xml.UBL_CBC}">{ids}<cbc:ID>1</cbc:ID></{root}>'.encode()


def cii(*bt24: str) -> bytes:
    params = "".join(
        f"<ram:GuidelineSpecifiedDocumentContextParameter><ram:ID> {v} </ram:ID>"
        "</ram:GuidelineSpecifiedDocumentContextParameter>"
        for v in bt24
    )
    return (
        f'<rsm:CrossIndustryInvoice xmlns:rsm="{_xml.CII_RSM}" xmlns:ram="{_xml.CII_RAM}">'
        f"<rsm:ExchangedDocumentContext>{params}</rsm:ExchangedDocumentContext></rsm:CrossIndustryInvoice>"
    ).encode()


def finding(rule_id: str, severity: Severity, source: str) -> Finding:
    return Finding(rule_id, severity, None, rule_id, source)


class Spy:
    """Records which rule sets ran; each produces one information finding tagged with its source."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, xsd_findings: tuple[Finding, ...] = ()) -> None:
        self.ran: list[schematron.RuleSet] = []
        self.xsd_findings = xsd_findings
        monkeypatch.setattr(xsd, "validate", self._xsd)
        monkeypatch.setattr(schematron, "run", self._run)

    def _xsd(self, element: etree._Element) -> tuple[Finding, ...]:
        return self.xsd_findings

    def _run(self, rule_set: schematron.RuleSet, document: bytes | etree._Element) -> tuple[Finding, ...]:
        self.ran.append(rule_set)
        return (finding(rule_set.stylesheet, Severity.INFORMATION, rule_set.source),)


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    return Spy(monkeypatch)


# --- rule sets per profile and syntax --------------------------------------------------------------


@pytest.mark.parametrize(
    ("profile", "data", "expected"),
    [
        (profiles.EN16931, ubl(CORE), [schematron.CEN_UBL]),
        (profiles.EN16931, cii(CORE), [schematron.CEN_CII]),
        (PEPPOL, ubl(CORE), [schematron.CEN_UBL, schematron.PEPPOL_UBL]),
        (PEPPOL, cii(CORE), [schematron.CEN_CII, schematron.PEPPOL_CII]),
        (
            profiles.XRECHNUNG,
            ubl(CORE, root="CreditNote", ns=_xml.UBL_CREDIT_NOTE),
            [schematron.CEN_UBL, schematron.XRECHNUNG_UBL],
        ),
        (profiles.XRECHNUNG, cii(CORE), [schematron.CEN_CII, schematron.XRECHNUNG_CII]),
    ],
    ids=["core-ubl", "core-cii", "peppol-ubl", "peppol-cii", "xrechnung-ubl-creditnote", "xrechnung-cii"],
)
def test_runs_the_profile_rule_sets_in_order_for_the_syntax(
    spy: Spy, profile: profiles.Profile, data: bytes, expected: list[schematron.RuleSet]
) -> None:
    report = validate(data, profile)

    assert spy.ran == expected
    assert [f.source for f in report.findings] == [r.source for r in expected]


def test_xsd_findings_come_first_and_keep_their_source(monkeypatch: pytest.MonkeyPatch) -> None:
    warning = finding(xsd.RULE_ID, Severity.WARNING, "xsd:ubl-2_1")
    spy = Spy(monkeypatch, (warning,))

    report = validate(ubl(CORE), profiles.EN16931)

    # A warning does not short-circuit: the rules still run (see the module docstring).
    assert spy.ran == [schematron.CEN_UBL]
    assert report.findings[0] == warning
    assert report.ok


@pytest.mark.parametrize("severity", [Severity.FATAL, Severity.ERROR])
def test_blocking_xsd_finding_short_circuits(monkeypatch: pytest.MonkeyPatch, severity: Severity) -> None:
    failure = finding(xsd.RULE_ID, severity, "xsd:ubl-2_1")
    spy = Spy(monkeypatch, (failure,))

    report = validate(ubl(CORE), PEPPOL)

    assert spy.ran == []
    assert report.findings == (failure,)
    assert not report.ok


# --- profile auto-detection -------------------------------------------------------------------------


@pytest.mark.parametrize("data", [ubl(CORE), cii(CORE)], ids=["ubl", "cii"])
def test_registered_bt24_selects_its_profile_without_a_note(spy: Spy, data: bytes) -> None:
    report = validate(data)

    assert len(spy.ran) == 1
    assert all(f.source != EUINVOICE_SOURCE for f in report.findings)


@pytest.mark.parametrize("syntax", ["ubl", "cii"])
@pytest.mark.parametrize(
    "profile",
    [profiles.XRECHNUNG, profiles.XRECHNUNG_EXTENSION, profiles.XRECHNUNG_CVD],
    ids=lambda p: p.id,
)
def test_each_xrechnung_bt24_selects_cen_then_xrechnung(spy: Spy, profile: profiles.Profile, syntax: str) -> None:
    data = ubl(profile.specification_identifier) if syntax == "ubl" else cii(profile.specification_identifier)

    report = validate(data)

    expected = {
        "ubl": [schematron.CEN_UBL, schematron.XRECHNUNG_UBL],
        "cii": [schematron.CEN_CII, schematron.XRECHNUNG_CII],
    }
    assert spy.ran == expected[syntax]
    assert all(f.source != EUINVOICE_SOURCE for f in report.findings)


@pytest.mark.parametrize(
    ("data", "ran"),
    [
        (ubl(PEPPOL.specification_identifier), [schematron.CEN_UBL, schematron.PEPPOL_UBL]),
        (cii(PEPPOL.specification_identifier), [schematron.CEN_CII, schematron.PEPPOL_CII]),
    ],
    ids=["ubl", "cii"],
)
def test_peppol_bt24_selects_the_peppol_rules(spy: Spy, data: bytes, ran: list[schematron.RuleSet]) -> None:
    report = validate(data)

    assert spy.ran == ran
    assert all(f.source != EUINVOICE_SOURCE for f in report.findings)


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (ubl(CIUS), f"{CIUS!r} is not a registered profile"),
        (cii(CIUS), f"{CIUS!r} is not a registered profile"),
        # normalize-space() keeps U+00A0, so this is not the core BT-24.
        (ubl(f"{NBSP}{CORE}"), f"{NBSP + CORE!r} is not a registered profile"),
        (ubl(), NO_BT24),
        (ubl("  "), NO_BT24),
        (cii(), NO_BT24),
        (cii(CORE, CORE), NO_BT24),
    ],
    ids=["ubl-cius", "cii-cius", "ubl-nbsp", "ubl-missing", "ubl-blank", "cii-missing", "cii-repeated"],
)
def test_unrecognised_bt24_falls_back_to_core_and_says_so(spy: Spy, data: bytes, reason: str) -> None:
    report = validate(data)

    assert spy.ran in ([schematron.CEN_UBL], [schematron.CEN_CII])
    assert_fallback_note(report.findings[0], reason)
    assert report.ok  # the note never blocks; the official rules decide (BR-01 etc.)


def test_detected_profile_without_the_document_syntax_falls_back(spy: Spy, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profiles, "get", lambda bt24: UBL_ONLY)

    report = validate(cii(UBL_ONLY.specification_identifier))

    assert spy.ran == [schematron.CEN_CII]
    assert_fallback_note(report.findings[0], "profile 'test-ubl' of BT-24 'urn:example.com:ubl' does not support CII")


def assert_fallback_note(note: Finding, reason: str) -> None:
    assert (note.rule_id, note.severity, note.source) == (
        PROFILE_FALLBACK_RULE_ID,
        Severity.INFORMATION,
        EUINVOICE_SOURCE,
    )
    assert reason in note.message
    assert "EN 16931 core only" in note.message


def test_explicit_profile_wins_over_bt24(spy: Spy) -> None:
    validate(ubl(CORE), profiles.XRECHNUNG)

    assert spy.ran == [schematron.CEN_UBL, schematron.XRECHNUNG_UBL]


# --- misuse is an exception (D9) --------------------------------------------------------------------


def test_profile_without_the_document_syntax_is_rejected(spy: Spy) -> None:
    with pytest.raises(UnsupportedDocumentError, match="'test-ubl' does not support CII"):
        validate(cii(CORE), UBL_ONLY)
    assert spy.ran == []


def test_unknown_root_namespace_is_rejected(spy: Spy) -> None:
    with pytest.raises(UnsupportedDocumentError, match="unsupported root element"):
        validate(b'<Invoice xmlns="urn:example.com:not-ubl"/>')


def test_malformed_xml_raises_parse_error(spy: Spy) -> None:
    with pytest.raises(ParseError):
        validate(b"<Invoice")


def test_non_bytes_input_raises_type_error(spy: Spy) -> None:
    with pytest.raises(TypeError):
        validate(t.cast(bytes, "<Invoice/>"))


def test_missing_artifacts_surface(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    monkeypatch.setenv("EUINVOICE_ARTIFACTS_DIR", str(tmp_path))
    with pytest.raises(ArtifactsNotAvailableError, match="artifacts fetch"):
        validate(ubl(CORE))


def test_every_rule_set_name_maps_for_every_syntax() -> None:
    assert set(orchestration._RULE_SETS) == set(itertools.product(profiles_base.RULE_SETS, profiles_base.SYNTAXES))
