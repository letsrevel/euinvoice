"""Unit tests for the report data types (IMPLEMENTATION_PLAN.md D9)."""

import dataclasses

import pytest

from euinvoice.report import Finding, KositAssessment, Severity, SeverityOverride, ValidationReport


def finding(severity: Severity) -> Finding:
    return Finding(rule_id="BR-02", severity=severity, location="/Invoice", message="m", source="cen-ubl")


def test_severity_values_are_the_schematron_flags() -> None:
    assert [s.value for s in Severity] == ["fatal", "error", "warning", "information"]
    assert Severity("fatal") is Severity.FATAL


def test_empty_report_is_ok() -> None:
    assert ValidationReport().ok
    assert ValidationReport().findings == ()


@pytest.mark.parametrize(
    ("severities", "ok"),
    [
        ((Severity.WARNING, Severity.INFORMATION), True),
        ((Severity.WARNING, Severity.ERROR), False),
        ((Severity.FATAL,), False),
        ((Severity.ERROR,), False),
    ],
)
def test_report_is_ok_only_without_fatal_or_error(severities: tuple[Severity, ...], ok: bool) -> None:
    assert ValidationReport(tuple(finding(s) for s in severities)).ok is ok


def test_findings_and_reports_are_immutable_and_comparable() -> None:
    a, b = finding(Severity.FATAL), finding(Severity.FATAL)
    assert a == b
    assert hash(a) == hash(b)
    assert ValidationReport((a,)) == ValidationReport((b,))
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.rule_id = "BR-01"  # type: ignore[misc]  # asserting that the frozen dataclass rejects it


# --- KoSIT assessment (issue #49) ------------------------------------------------------------------------------------


def test_report_has_no_kosit_assessment_by_default() -> None:
    assert ValidationReport().kosit is None
    assert ValidationReport((finding(Severity.FATAL),)).kosit is None


def test_severity_override_keeps_the_finding_unchanged() -> None:
    original = finding(Severity.FATAL)
    override = SeverityOverride(original, Severity.WARNING)
    assert override.finding is original
    assert override.finding.severity is Severity.FATAL
    assert override.severity is Severity.WARNING


@pytest.mark.parametrize(
    ("blocking", "accepted"),
    [((), True), ((finding(Severity.FATAL),), False), ((finding(Severity.ERROR),), False)],
    ids=["nothing-blocking", "fatal", "error"],
)
def test_kosit_assessment_is_accepted_only_without_blocking_findings(
    blocking: tuple[Finding, ...], accepted: bool
) -> None:
    assessment = KositAssessment("EN16931 XRechnung (UBL Invoice)", blocking=blocking)
    assert assessment.accepted is accepted
    assert assessment.overrides == ()


def test_kosit_verdict_is_independent_of_ok() -> None:
    # A downgraded fatal finding: the raw-flag report is not ok, KoSIT accepts.
    fatal = finding(Severity.FATAL)
    assessment = KositAssessment("s", overrides=(SeverityOverride(fatal, Severity.INFORMATION),))
    report = ValidationReport((fatal,), kosit=assessment)
    assert not report.ok
    assert report.kosit is not None
    assert report.kosit.accepted


def test_kosit_types_are_immutable_and_comparable() -> None:
    a = KositAssessment(
        "s", (SeverityOverride(finding(Severity.WARNING), Severity.ERROR),), (finding(Severity.WARNING),)
    )
    b = KositAssessment(
        "s", (SeverityOverride(finding(Severity.WARNING), Severity.ERROR),), (finding(Severity.WARNING),)
    )
    assert a == b
    assert hash(a) == hash(b)
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.scenario = "t"  # type: ignore[misc]  # asserting that the frozen dataclass rejects it
