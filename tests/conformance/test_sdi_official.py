"""validate() on FatturaPA: the pinned XSD 1.2.3, then the offline SdI checks (#121; needs ``make artifacts``).

Two things are proved here: every synthetic document of tests/_fatturapa.py is valid against the official schema
(so the SdI unit tests exercise documents SdI would get to check), and the official fatturapa.gov.it examples get the
expected verdicts.
"""

import json
import pathlib
import typing as t

import pytest

from _fatturapa import CASES, Case
from euinvoice import __main__ as cli
from euinvoice import detect, validate
from euinvoice.errors import ArtifactsNotAvailableError, UnsupportedDocumentError
from euinvoice.profiles import EN16931
from euinvoice.report import Severity
from euinvoice.syntax import Syntax
from euinvoice.validation import FPA12_NOTE_RULE_ID, artifacts

pytestmark = pytest.mark.conformance

# The verdict of each official example (fatturapa.gov.it, as shipped in the pinned ZUGFeRD corpus): the rule ids of
# its blocking findings.
# * FPR02 fails the XSD (ContattiTrasmittente after PECDestinatario; tests/conformance/test_xsd_fatturapa.py), so the
#   SdI checks do not run.
# * FPR03 fails 00422 in its first body: its two lines (5.00 + 20.00, AliquotaIVA 22.00) add up to 25.00, but the
#   DatiRiepilogo declares ImponibileImporto 27.00, beyond the ±1 tolerance of Allegato A 1.9.1 (DatiRiepilogo /
#   ImponibileImporto, Appendix 1 code 00422). No DatiCassaPrevidenziale or Arrotondamento makes up the difference.
#   Its Imposta 5.95 is 27.00 * 22 % = 5.94 within the ±0.01 of 00421, so the example was built on 27.00.
EXPECTED: t.Final[t.Mapping[str, tuple[str, ...]]] = {
    "IT01234567890_FPA01.xml": (),
    "IT01234567890_FPA02.xml": (),
    "IT01234567890_FPA03.xml": (),
    "IT01234567890_FPR01.xml": (),
    "IT01234567890_FPR02.xml": ("XSD",),
    "IT01234567890_FPR03.xml": ("00422",),
}


def official_examples() -> list[pathlib.Path]:
    try:
        directory = artifacts.source_dir("zugferd-corpus") / "fatturaPA" / "official" / "valid"
    except ArtifactsNotAvailableError:  # collected but deselected by `make test`
        return []
    return sorted(directory.glob("*.xml"))


def test_every_official_example_has_an_expected_verdict() -> None:
    assert [p.name for p in official_examples()] == sorted(EXPECTED)


@pytest.mark.parametrize("path", official_examples(), ids=lambda p: p.name)
def test_official_example_verdict(path: pathlib.Path) -> None:
    data = path.read_bytes()

    report = validate(data)

    blocking = tuple(f.rule_id for f in report.findings if f.severity in (Severity.FATAL, Severity.ERROR))
    assert blocking == EXPECTED[path.name], report.findings
    assert report.ok is (not blocking)
    assert report.kosit is None
    detection = detect(data)
    assert detection.syntax is Syntax.FATTURAPA
    # FPA12 reports open with the note on the public-administration checks; FPR12 reports have none.
    notes = [f.rule_id for f in report.findings if f.severity is Severity.INFORMATION]
    assert notes == ([FPA12_NOTE_RULE_ID] if detection.fatturapa_version == "FPA12" else [])


def test_fpr03_fails_00422_on_its_first_body_only() -> None:
    (path,) = [p for p in official_examples() if p.name == "IT01234567890_FPR03.xml"]

    (finding,) = validate(path.read_bytes()).findings

    assert finding.location == "/p:FatturaElettronica/FatturaElettronicaBody[1]/DatiBeniServizi/DatiRiepilogo"
    assert "ImponibileImporto 27.00, computed 25.00" in finding.message


@pytest.mark.parametrize(("code", "case"), CASES.items(), ids=list(CASES))
def test_synthetic_documents_pass_the_xsd_and_get_their_sdi_codes(code: str, case: Case) -> None:
    for doc in case.passing:
        report = validate(doc.xml())
        assert [f for f in report.findings if f.severity is not Severity.INFORMATION] == [], doc
    failing = validate(case.failing.xml())
    assert all(f.source == "sdi" for f in failing.findings if f.severity is not Severity.INFORMATION)
    assert {f.rule_id for f in failing.findings if f.source == "sdi"} == case.codes
    assert not failing.ok


def test_a_profile_is_refused_for_fatturapa() -> None:
    (path,) = [p for p in official_examples() if p.name == "IT01234567890_FPR01.xml"]

    with pytest.raises(UnsupportedDocumentError, match="does not support FATTURAPA"):
        validate(path.read_bytes(), EN16931)


def test_cli_validate_reports_fatturapa_findings(capsys: pytest.CaptureFixture[str]) -> None:
    by_name = {p.name: str(p) for p in official_examples()}

    assert cli.main(["validate", by_name["IT01234567890_FPR01.xml"]]) == 0
    assert capsys.readouterr().out == "ok: 0 fatal/error, 0 warning/information\n"
    assert cli.main(["validate", "--json", by_name["IT01234567890_FPR03.xml"]]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert (payload["ok"], [f["rule_id"] for f in payload["findings"]], payload["kosit"]) == (False, ["00422"], None)
    assert cli.main(["validate", "--profile", "en16931", by_name["IT01234567890_FPR01.xml"]]) == 1
    assert "does not support FATTURAPA" in capsys.readouterr().err
