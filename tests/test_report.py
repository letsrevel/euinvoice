"""Unit tests for the report data types (IMPLEMENTATION_PLAN.md D9)."""

import dataclasses

import pytest

from euinvoice.report import Finding, Severity, ValidationReport


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
