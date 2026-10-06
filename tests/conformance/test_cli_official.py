"""The CLI (#28) against the official artifacts: its verdict and exit code are those of ``validate()`` (D8)."""

import dataclasses
import json
import typing as t
from pathlib import Path

import pytest
from _corpus import Sample, samples

from _invoices import minimal_invoice
from _pdfa import pdf
from euinvoice import __main__ as cli
from euinvoice import facturx, profiles, to_xml, validate
from euinvoice.validation import artifacts

pytestmark = pytest.mark.conformance

CEN_EXAMPLES: t.Final = [s for s in samples() if s.source in ("cen-ubl", "cen-cii")]


def _json_validate(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, t.Any]]:
    code = cli.main(["validate", "--json", *argv])
    return code, json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("sample", CEN_EXAMPLES, ids=[s.id for s in CEN_EXAMPLES])
def test_validate_matches_the_library_on_the_cen_examples(sample: Sample, capsys: pytest.CaptureFixture[str]) -> None:
    path = artifacts.source_dir(sample.source) / sample.file
    report = validate(path.read_bytes())
    code, payload = _json_validate([str(path)], capsys)
    assert code == (0 if report.ok else 1)
    assert payload == {
        "ok": report.ok,
        "findings": [json.loads(json.dumps(dataclasses.asdict(f))) for f in report.findings],
        "kosit": None,
    }


def test_validate_prints_the_kosit_verdict_and_exits_on_ok(capsys: pytest.CaptureFixture[str]) -> None:
    # XRechnung Extension instance 05.01a fails BR-CO-16 (fatal), which KoSIT's Extension UBL scenario downgrades
    # to information (issue #49): not ok, exit 1, but KoSIT accepts it.
    testsuite = artifacts.fetch(["xrechnung-testsuite"])["xrechnung-testsuite"]
    path = testsuite / "instances/extension/05.01a-INVOICE_ubl.xml"
    code, payload = _json_validate([str(path)], capsys)
    assert code == 1
    assert payload["ok"] is False
    assert payload["kosit"]["scenario"] == "EN16931 XRechnung Extension (UBL Invoice)"
    assert payload["kosit"]["accepted"] is True
    assert payload["kosit"]["blocking"] == []
    override = {"rule_id": "BR-CO-16", "severity": "fatal", "effective_severity": "information"}
    assert override in payload["kosit"]["overrides"]
    assert cli.main(["validate", str(path)]) == 1
    line = "kosit: accepted under scenario 'EN16931 XRechnung Extension (UBL Invoice)' (2 severity overrides)\n"
    assert line in capsys.readouterr().out


def test_validate_written_invoice_exits_0_and_a_broken_total_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = to_xml(minimal_invoice(), syntax="ubl")
    (tmp_path / "good.xml").write_bytes(good)
    assert _json_validate([str(tmp_path / "good.xml")], capsys)[0] == 0
    # BR-CO-15 (CEN EN16931-UBL-model.sch): BT-112 = BT-109 + BT-110; 119.00 becomes 120.00 in BT-112 and BT-115.
    (tmp_path / "bad.xml").write_bytes(good.replace(b">119.00<", b">120.00<"))
    code, payload = _json_validate([str(tmp_path / "bad.xml")], capsys)
    assert code == 1
    assert "BR-CO-15" in {f["rule_id"] for f in payload["findings"] if f["severity"] in ("fatal", "error")}


def test_convert_output_validates_under_its_profile(tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    source = tmp_path / "in.xml"
    source.write_bytes(to_xml(minimal_invoice(), syntax="ubl"))
    out = tmp_path / "out.xml"
    assert cli.main(["convert", "--to", "cii", "-o", str(out), str(source)]) == 0
    assert capsysbinary.readouterr().err == b""
    assert cli.main(["validate", "--profile", "en16931", str(out)]) == 0


def test_validate_facturx_pdf(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    hybrid = facturx.embed(pdf(), minimal_invoice(), profile=profiles.FACTURX_EN16931)
    (tmp_path / "a.pdf").write_bytes(hybrid)
    code, payload = _json_validate([str(tmp_path / "a.pdf")], capsys)
    assert (code, payload["ok"]) == (0, True)


@pytest.mark.parametrize(
    ("file", "core_exit"),
    [
        ("ZUGFeRDv2/correct/intarsys/BASIC/zugferd_2p0_BASIC_Einfach.pdf", 0),
        ("ZUGFeRDv2/correct/symtrax/Beispiele/BASIC/zugferd_2p1_BASIC_Einfach.pdf", 0),
        # Fails the CEN rules (expected_invalid.toml lists its findings).
        ("ZUGFeRDv2/correct/FNFE-factur-x-examples/Avoir_FR_type381_BASIC.pdf", 1),
    ],
    ids=["zugferd-2.0", "zugferd-2.1", "fnfe-colon-bt24"],
)
def test_validate_basic_pdf_exits_2_whatever_its_version(
    file: str, core_exit: int, capsys: pytest.CaptureFixture[str]
) -> None:
    # #98: the BASIC Schematron is not pinned (#42), so no BASIC PDF gets the EN 16931 core verdict unasked.
    path = artifacts.fetch(["zugferd-corpus"])["zugferd-corpus"] / file
    assert cli.main(["validate", str(path)]) == 2
    err = capsys.readouterr().err
    assert "issues/42" in err
    assert err.endswith("pass --profile en16931\n")
    assert cli.main(["validate", "--profile", "en16931", str(path)]) == core_exit
