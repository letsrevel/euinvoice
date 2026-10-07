"""Unit tests for validate() on FatturaPA (#121), offline: the XSD step is a stub, the SdI checks are real."""

import pytest
from lxml import etree

from _fatturapa import Doc, body, summary
from euinvoice import profiles
from euinvoice.errors import UnsupportedDocumentError
from euinvoice.report import Finding, Severity, ValidationReport
from euinvoice.validation import EUINVOICE_SOURCE, FPA12_NOTE_RULE_ID, kosit, schematron, validate, xsd

WRONG_TAX = Doc(bodies=body(summaries=summary(tax="22.02")))  # fails SdI 00421


class XsdStub:
    """Stands in for the FatturaPA XSD step and fails the test if a Schematron or KoSIT step runs."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, findings: tuple[Finding, ...] = ()) -> None:
        self.findings = findings
        self.calls = 0
        monkeypatch.setattr(xsd, "validate", self._validate)
        monkeypatch.setattr(schematron, "run", self._refuse)
        monkeypatch.setattr(kosit, "verdict", self._refuse)

    def _validate(self, element: etree._Element) -> tuple[Finding, ...]:
        self.calls += 1
        return self.findings

    def _refuse(self, *args: object) -> object:
        raise AssertionError("no Schematron rule set or KoSIT scenario applies to FatturaPA")


def test_an_fpr12_document_runs_the_xsd_then_the_sdi_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = XsdStub(monkeypatch)

    report = validate(WRONG_TAX.xml())

    assert stub.calls == 1
    assert [(f.rule_id, f.severity, f.source) for f in report.findings] == [("00421", Severity.ERROR, "sdi")]
    assert not report.ok
    assert report.kosit is None


def test_a_valid_fpr12_document_is_ok_with_no_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    XsdStub(monkeypatch)

    assert validate(Doc().xml()) == ValidationReport()


@pytest.mark.parametrize("severity", [Severity.FATAL, Severity.ERROR])
def test_a_blocking_xsd_finding_skips_the_sdi_checks(monkeypatch: pytest.MonkeyPatch, severity: Severity) -> None:
    failure = Finding(xsd.RULE_ID, severity, "1", "boom", "xsd:fatturapa-xsd")
    XsdStub(monkeypatch, (failure,))

    assert validate(WRONG_TAX.xml()).findings == (failure,)


def test_an_xsd_warning_does_not_skip_the_sdi_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    warning = Finding(xsd.RULE_ID, Severity.WARNING, "1", "hmm", "xsd:fatturapa-xsd")
    XsdStub(monkeypatch, (warning,))

    assert [f.rule_id for f in validate(WRONG_TAX.xml()).findings] == [xsd.RULE_ID, "00421"]


def test_an_fpa12_document_gets_the_same_checks_after_a_note(monkeypatch: pytest.MonkeyPatch) -> None:
    XsdStub(monkeypatch)
    fpa12 = Doc(version="FPA12", format="FPA12", recipient="ABC123", bodies=body(summaries=summary(tax="22.02")))

    note, *rest = validate(fpa12.xml()).findings

    assert (note.rule_id, note.severity, note.source) == (FPA12_NOTE_RULE_ID, Severity.INFORMATION, EUINVOICE_SOURCE)
    assert "00398 and 00399" in note.message
    assert [f.rule_id for f in rest] == ["00421"]


@pytest.mark.parametrize("profile", [profiles.EN16931, profiles.PEPPOL, profiles.FACTURX_EN16931])
def test_no_profile_supports_fatturapa(monkeypatch: pytest.MonkeyPatch, profile: profiles.Profile) -> None:
    stub = XsdStub(monkeypatch)

    with pytest.raises(UnsupportedDocumentError, match=f"profile '{profile.id}' does not support FATTURAPA"):
        validate(Doc().xml(), profile)
    assert stub.calls == 0
