"""Tests for the ``python -m euinvoice`` CLI (#28): ``validate``, ``convert``, ``info`` and ``artifacts fetch``."""

import dataclasses
import io
import json
import logging
import runpy
import sys
import typing as t
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import etree

from _invoices import CEN, minimal_invoice, rebuild
from _pdfa import pdf
from euinvoice import __main__ as cli
from euinvoice import _xml, facturx, parse_detailed, profiles, to_xml
from euinvoice.errors import ArtifactIntegrityError, ArtifactsNotAvailableError
from euinvoice.model import Invoice, ProcessControl
from euinvoice.report import Finding, KositAssessment, Severity, SeverityOverride, ValidationReport
from euinvoice.syntax import Syntax, cii, ubl
from euinvoice.syntax.result import ParseResult
from euinvoice.validation import artifacts


def test_artifacts_fetch_passes_only_and_prints_paths(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[t.Any] = []

    def fake_fetch(names: t.Any) -> dict[str, Path]:
        calls.append(names)
        return {"cen-ubl": Path("/cache/cen-ubl/1.3.16")}

    monkeypatch.setattr(artifacts, "fetch", fake_fetch)
    assert cli.main(["artifacts", "fetch", "--only", "cen-ubl", "--only", "cen-cii"]) == 0
    assert calls == [["cen-ubl", "cen-cii"]]
    assert capsys.readouterr().out == "cen-ubl: /cache/cen-ubl/1.3.16\n"


def test_artifacts_fetch_without_only_fetches_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[t.Any] = []

    def fake_fetch(names: t.Any) -> dict[str, Path]:
        calls.append(names)
        return {}

    monkeypatch.setattr(artifacts, "fetch", fake_fetch)
    assert cli.main(["artifacts", "fetch"]) == 0
    assert calls == [None]


def test_fetch_error_exits_1_with_message(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def boom(names: t.Any) -> dict[str, Path]:
        raise ArtifactIntegrityError("sha256 mismatch")

    monkeypatch.setattr(artifacts, "fetch", boom)
    assert cli.main(["artifacts", "fetch"]) == 1
    assert capsys.readouterr().err == "error: sha256 mismatch\n"


@pytest.mark.parametrize("argv", [[], ["artifacts"], ["artifacts", "fetch", "--only", "nope"]])
def test_usage_errors_exit_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2


def test_module_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(artifacts, "fetch", lambda names: {})
    monkeypatch.setattr(sys, "argv", ["euinvoice", "artifacts", "fetch"])
    monkeypatch.delitem(sys.modules, "euinvoice.__main__")
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("euinvoice", run_name="__main__")
    assert exc.value.code == 0


# --- shared fixtures ------------------------------------------------------------------------------------------------


def _core_invoice() -> Invoice:
    return minimal_invoice(process_control=ProcessControl(specification_identifier=CEN))


def _write(tmp_path: Path, name: str, data: bytes) -> str:
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


_ERROR = Finding("BR-02", Severity.FATAL, "/Invoice", "An Invoice shall have an Invoice number (BT-1).", "cen-ubl")
_WARNING = Finding("UBL-CR-001", Severity.WARNING, None, "A UBL invoice should not include extensions", "cen-ubl")


def _fake_validate(
    monkeypatch: pytest.MonkeyPatch, report: ValidationReport
) -> list[tuple[bytes, profiles.Profile | None]]:
    calls: list[tuple[bytes, profiles.Profile | None]] = []

    def fake(data: bytes, profile: profiles.Profile | None = None) -> ValidationReport:
        calls.append((data, profile))
        return report

    monkeypatch.setattr(cli, "validate", fake)
    return calls


# --- validate -------------------------------------------------------------------------------------------------------


def test_validate_ok_exits_0_and_prints_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    xml = ubl.write(_core_invoice())
    calls = _fake_validate(monkeypatch, ValidationReport((_WARNING,)))
    assert cli.main(["validate", _write(tmp_path, "a.xml", xml)]) == 0
    assert calls == [(xml, None)]
    out = capsys.readouterr().out
    assert "warning UBL-CR-001 [cen-ubl]: A UBL invoice should not include extensions\n" in out
    assert out.endswith("ok: 0 fatal/error, 1 warning/information\n")


def test_validate_findings_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_validate(monkeypatch, ValidationReport((_ERROR, _WARNING)))
    assert cli.main(["validate", _write(tmp_path, "a.xml", ubl.write(_core_invoice()))]) == 1
    out = capsys.readouterr().out
    assert "fatal BR-02 [cen-ubl] at /Invoice: An Invoice shall have an Invoice number (BT-1).\n" in out
    assert out.endswith("invalid: 1 fatal/error, 1 warning/information\n")


@pytest.mark.parametrize(("report", "code"), [(ValidationReport((_WARNING,)), 0), (ValidationReport((_ERROR,)), 1)])
def test_validate_json(
    report: ValidationReport,
    code: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _fake_validate(monkeypatch, report)
    assert cli.main(["validate", "--json", _write(tmp_path, "a.xml", ubl.write(_core_invoice()))]) == code
    assert json.loads(capsys.readouterr().out) == {
        "ok": report.ok,
        "findings": [
            {
                "rule_id": f.rule_id,
                "severity": str(f.severity),
                "location": f.location,
                "message": f.message,
                "source": f.source,
            }
            for f in report.findings
        ],
        "kosit": None,
    }


_DOWNGRADED = Finding("BR-CL-23", Severity.FATAL, "/Invoice/cac:InvoiceLine[1]", "unit code", "cen-ubl")
_KOSIT = KositAssessment(
    "EN16931 XRechnung (UBL Invoice)",
    overrides=(SeverityOverride(_DOWNGRADED, Severity.WARNING), SeverityOverride(_WARNING, Severity.ERROR)),
    blocking=(_WARNING, _ERROR),
)


def test_validate_json_carries_the_kosit_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The exit code stays tied to ok (here not ok), whatever KoSIT says.
    _fake_validate(monkeypatch, ValidationReport((_DOWNGRADED, _WARNING, _ERROR), kosit=_KOSIT))
    assert cli.main(["validate", "--json", _write(tmp_path, "a.xml", b"<x/>")]) == 1
    assert json.loads(capsys.readouterr().out)["kosit"] == {
        "scenario": "EN16931 XRechnung (UBL Invoice)",
        "accepted": False,
        "overrides": [
            {"rule_id": "BR-CL-23", "severity": "fatal", "effective_severity": "warning"},
            {"rule_id": "UBL-CR-001", "severity": "warning", "effective_severity": "error"},
        ],
        # Why KoSIT rejects: an upgraded warning (its override) and a fatal finding no customLevel touches.
        "blocking": [
            {"rule_id": "UBL-CR-001", "severity": "warning", "effective_severity": "error"},
            {"rule_id": "BR-02", "severity": "fatal", "effective_severity": "fatal"},
        ],
    }


def test_validate_json_matches_a_hand_built_override_by_equality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # #112: a hand-built KositAssessment may hold equal but distinct Finding objects in overrides and blocking.
    copy = dataclasses.replace(_WARNING)
    assert copy == _WARNING
    assert copy is not _WARNING
    kosit = KositAssessment("s", overrides=(SeverityOverride(_WARNING, Severity.ERROR),), blocking=(copy,))
    _fake_validate(monkeypatch, ValidationReport((_WARNING,), kosit=kosit))
    cli.main(["validate", "--json", _write(tmp_path, "a.xml", b"<x/>")])
    assert json.loads(capsys.readouterr().out)["kosit"]["blocking"] == [
        {"rule_id": "UBL-CR-001", "severity": "warning", "effective_severity": "error"}
    ]


@pytest.mark.parametrize(
    ("kosit", "line"),
    [
        (_KOSIT, "kosit: rejected under scenario 'EN16931 XRechnung (UBL Invoice)' (2 severity overrides)\n"),
        (
            KositAssessment("EN16931 XRechnung (CII)"),
            "kosit: accepted under scenario 'EN16931 XRechnung (CII)' (0 severity overrides)\n",
        ),
        (
            KositAssessment("EN16931 XRechnung (CII)", (SeverityOverride(_DOWNGRADED, Severity.WARNING),)),
            "kosit: accepted under scenario 'EN16931 XRechnung (CII)' (1 severity override)\n",
        ),
    ],
    ids=["rejected", "accepted", "one-override"],
)
def test_validate_text_adds_one_kosit_line_before_the_verdict(
    kosit: KositAssessment,
    line: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _fake_validate(monkeypatch, ValidationReport((_WARNING,), kosit=kosit))
    assert cli.main(["validate", _write(tmp_path, "a.xml", b"<x/>")]) == 0
    out = capsys.readouterr().out
    assert out.endswith(line + "ok: 0 fatal/error, 1 warning/information\n")
    assert out.count("kosit:") == 1


def test_validate_text_has_no_kosit_line_without_a_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_validate(monkeypatch, ValidationReport((_WARNING,)))
    assert cli.main(["validate", _write(tmp_path, "a.xml", b"<x/>")]) == 0
    assert "kosit" not in capsys.readouterr().out


def test_validate_passes_the_profile_by_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_validate(monkeypatch, ValidationReport())
    assert cli.main(["validate", "--profile", "xrechnung", _write(tmp_path, "a.xml", b"<x/>")]) == 0
    assert calls == [(b"<x/>", profiles.XRECHNUNG)]


def test_every_profile_is_a_choice() -> None:
    assert set(cli.PROFILES) == {"en16931", "peppol", "xrechnung", "xrechnung-extension", "xrechnung-cvd"} | {
        f"facturx-{level}" for level in ("minimum", "basic-wl", "basic", "en16931", "xrechnung", "extended")
    }
    assert all(cli.PROFILES[key].id == key for key in cli.PROFILES)


def test_validate_extracts_the_xml_of_a_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    invoice = _core_invoice()
    hybrid = facturx.embed(pdf(), invoice, profile=profiles.FACTURX_EN16931)
    calls = _fake_validate(monkeypatch, ValidationReport())
    assert cli.main(["validate", _write(tmp_path, "a.pdf", hybrid)]) == 0
    # The XMP level selects the profile, as in ``info``.
    assert calls == [(facturx.extract(hybrid).xml, profiles.FACTURX_EN16931)]


def test_validate_reads_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_validate(monkeypatch, ValidationReport())
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"<x/>")))
    assert cli.main(["validate", "-"]) == 0
    assert calls == [(b"<x/>", None)]


def test_validate_builds_the_fallback_hint_from_the_attribute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # #108: the CLI spells the fallback from ``fallback_profile_id``, whatever the library's wording of the reason.
    def unpinned(data: bytes, profile: profiles.Profile | None = None) -> ValidationReport:
        raise ArtifactsNotAvailableError("some new wording", fallback_profile_id="en16931")

    monkeypatch.setattr(cli, "validate", unpinned)
    assert cli.main(["validate", _write(tmp_path, "a.xml", b"<x/>")]) == 2
    assert capsys.readouterr().err == (
        "error: some new wording. To run only the EN 16931 core rules, pass --profile en16931\n"
    )


def test_validate_missing_artifacts_exit_2_with_the_fix_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def missing(data: bytes, profile: profiles.Profile | None = None) -> ValidationReport:
        raise ArtifactsNotAvailableError("cen-ubl is missing; run: python -m euinvoice artifacts fetch")

    monkeypatch.setattr(cli, "validate", missing)
    assert cli.main(["validate", _write(tmp_path, "a.xml", b"<x/>")]) == 2
    assert capsys.readouterr().err == "error: cen-ubl is missing; run: python -m euinvoice artifacts fetch\n"


def test_unreadable_file_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["validate", str(tmp_path / "nope.xml")]) == 2
    assert capsys.readouterr().err.startswith("error: [Errno 2] No such file or directory")


def test_missing_extra_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_pypdf(data: bytes) -> ParseResult:
        raise ImportError("euinvoice.facturx needs the [pdf] extra: uv add 'euinvoice[pdf]'")

    monkeypatch.setattr(cli, "parse_detailed", no_pypdf)
    assert cli.main(["convert", "--to", "ubl", _write(tmp_path, "a.xml", b"<x/>")]) == 2
    assert capsys.readouterr().err == "error: euinvoice.facturx needs the [pdf] extra: uv add 'euinvoice[pdf]'\n"


@pytest.mark.parametrize("data", [b"<x", b"<Other/>", b"%PDF-1.7\nnot really"])
def test_unreadable_documents_exit_1(data: bytes, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for command in (["validate"], ["convert", "--to", "cii"], ["info"]):
        assert cli.main([*command, _write(tmp_path, "a.xml", data)]) == 1
        assert capsys.readouterr().err.startswith("error: ")


@pytest.mark.parametrize(
    "argv",
    [
        ["validate"],
        ["validate", "--profile", "nope", "a.xml"],
        ["convert", "a.xml"],
        ["convert", "--to", "pdf", "a.xml"],
        ["convert", "--to", "fatturapa", "a.xml"],  # writing FatturaPA is #119 / #122
        ["info"],
    ],
)
def test_subcommand_usage_errors_exit_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2


# --- convert --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("source", "target"), [(Syntax.UBL, Syntax.CII), (Syntax.CII, Syntax.UBL)])
def test_convert_writes_the_other_syntax_to_stdout(
    source: Syntax, target: Syntax, tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    invoice = _core_invoice()
    written = (ubl.write if source is Syntax.UBL else cii.write)(invoice)
    assert cli.main(["convert", "--to", str(target), _write(tmp_path, "a.xml", written)]) == 0
    captured = capsysbinary.readouterr()
    assert captured.out == to_xml(invoice, syntax=target)
    assert captured.err == b""


def test_convert_writes_to_a_file_under_a_profile(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    invoice = _core_invoice()
    out = tmp_path / "out.xml"
    source = _write(tmp_path, "a.xml", ubl.write(invoice))
    assert cli.main(["convert", "--to", "cii", "--profile", "facturx-en16931", "-o", str(out), source]) == 0
    assert out.read_bytes() == to_xml(invoice, profile=profiles.FACTURX_EN16931)
    assert capsys.readouterr().out == ""


def test_convert_reports_unmapped_input_on_stderr(tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    root = _xml.parse(ubl.write(_core_invoice()))
    etree.SubElement(root, f"{{{_xml.UBL_CBC}}}UBLVersionID").text = "2.1"
    root.insert(0, root[-1])  # UBLVersionID goes first in the UBL 2.1 Invoice sequence
    data = etree.tostring(root)
    assert cli.main(["convert", "--to", "cii", _write(tmp_path, "a.xml", data)]) == 0
    captured = capsysbinary.readouterr()
    (unmapped,) = parse_detailed(data).unmapped
    assert unmapped.endswith("cbc:UBLVersionID")
    assert captured.err == f"warning: not converted, no business term: {unmapped}\n".encode()
    assert captured.out == to_xml(_core_invoice(), syntax="cii")


def test_convert_refuses_on_preflight_findings_exit_1(
    tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    # BR-CO-15: total with VAT = total without VAT + total VAT; 119.00 != 100.00 + 20.00.
    invoice = rebuild(_core_invoice(), totals=_core_invoice().totals.model_copy(update={"total_vat": Decimal("20.00")}))
    source = _write(tmp_path, "a.xml", ubl.write(invoice))
    assert cli.main(["convert", "--to", "cii", source]) == 1
    captured = capsysbinary.readouterr()
    assert captured.out == b""
    assert b"error: invoice fails the en16931 pre-flight and calculation checks for cii\n" in captured.err
    assert b"fatal BR-CO-15 [calc]" in captured.err


def test_convert_profile_without_the_target_syntax_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Checked before reading FILE, so the missing file is never opened.
    assert cli.main(["convert", "--to", "ubl", "--profile", "facturx-en16931", str(tmp_path / "nope.xml")]) == 2
    assert capsys.readouterr().err == "error: profile 'facturx-en16931' does not support --to ubl; it supports cii\n"


def test_convert_unwritable_output_exits_2_naming_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = _write(tmp_path, "a.xml", ubl.write(_core_invoice()))
    target = tmp_path / "out"
    target.mkdir()  # a directory cannot be written as a file
    assert cli.main(["convert", "--to", "cii", "-o", str(target), source]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert str(target) in err


@pytest.mark.parametrize(
    "bt24",
    [
        profiles.FACTURX_BASIC.specification_identifier,
        # ZUGFeRD 2.0 BASIC (#98): no profile, but the same unpinned level, so the same refusal.
        "urn:cen.eu:en16931:2017#compliant#urn:zugferd.de:2p0:basic",
    ],
    ids=["facturx-basic", "zugferd-2.0-basic"],
)
def test_validate_unpinned_facturx_level_hints_at_the_cli_flag(
    bt24: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The Factur-X / ZUGFeRD BASIC Schematron is not pinned (#42): validate() raises before running anything.
    invoice = minimal_invoice(process_control=ProcessControl(specification_identifier=bt24))
    assert cli.main(["validate", _write(tmp_path, "a.xml", cii.write(invoice))]) == 2
    err = capsys.readouterr().err
    assert "issues/42" in err
    assert err.endswith("pass --profile en16931\n")


# --- info -----------------------------------------------------------------------------------------------------------


def _summary() -> dict[str, t.Any]:
    return {
        "BT-1": "INV-1",
        "BT-2": "2026-01-15",
        "BT-3": "380",
        "BT-5": "EUR",
        "BT-106": "100.00",
        "BT-107": None,
        "BT-108": None,
        "BT-109": "100.00",
        "BT-110": "19.00",
        "BT-111": None,
        "BT-112": "119.00",
        "BT-113": None,
        "BT-114": None,
        "BT-115": "119.00",
    }


def test_info_json_of_xml(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    invoice = _core_invoice()
    assert cli.main(["info", "--json", _write(tmp_path, "a.xml", cii.write(invoice))]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "syntax": "cii",
        "root": "CrossIndustryInvoice",
        "specification_identifier": CEN,
        "profile": "en16931",
        "pdf": None,
        "invoice": _summary(),
        "unmapped": [],
    }


def test_info_json_of_a_facturx_pdf(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    invoice = _core_invoice()
    hybrid = facturx.embed(pdf(), invoice, profile=profiles.FACTURX_EN16931)
    assert cli.main(["info", "--json", _write(tmp_path, "a.pdf", hybrid)]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["profile"] == "facturx-en16931"
    assert info["pdf"] == {"container": "factur-x", "conformance_level": "EN 16931", "filename": "factur-x.xml"}
    assert info["invoice"] == _summary()


def test_info_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["info", _write(tmp_path, "a.xml", ubl.write(_core_invoice()))]) == 0
    out = capsys.readouterr().out
    assert "syntax: ubl\n" in out
    assert "profile: en16931\n" in out
    assert "BT-1: INV-1\n" in out
    assert "BT-112: 119.00\n" in out
    assert "BT-107" not in out  # absent terms are left out of the text form


def test_info_of_an_unregistered_bt24(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    invoice = minimal_invoice(process_control=ProcessControl(specification_identifier="urn:example.com:cius"))
    assert cli.main(["info", "--json", _write(tmp_path, "a.xml", ubl.write(invoice))]) == 0
    info = json.loads(capsys.readouterr().out)
    assert (info["specification_identifier"], info["profile"]) == ("urn:example.com:cius", None)


def test_text_the_terminal_cannot_encode_is_escaped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    german = Finding("BR-DE-1", Severity.FATAL, None, "Eine Rechnung muss übermittelt werden.", "xrechnung-ubl")
    _fake_validate(monkeypatch, ValidationReport((german,)))
    buffer = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(buffer, encoding="ascii"))
    assert cli.main(["validate", _write(tmp_path, "a.xml", b"<x/>")]) == 1
    sys.stdout.flush()
    assert b"Eine Rechnung muss \\xfcbermittelt werden." in buffer.getvalue()


def test_artifacts_fetch_download_failure_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def offline(names: t.Any) -> dict[str, Path]:
        raise ArtifactsNotAvailableError("cen-ubl 1.3.16: could not download https://example.com/x.zip")

    monkeypatch.setattr(artifacts, "fetch", offline)
    assert cli.main(["artifacts", "fetch"]) == 2
    assert capsys.readouterr().err == "error: cen-ubl 1.3.16: could not download https://example.com/x.zip\n"


@pytest.mark.parametrize("command", ["validate", "convert", "info"])
def test_subcommand_help_lists_the_exit_codes(command: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main([command, "--help"])
    assert "exit codes: 0 ok, 1 document rejected" in capsys.readouterr().out


def test_a_damaged_pdf_is_one_error_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    # pypdf logs "EOF marker not found" for this input before failing; outside pytest that warning reaches stderr.
    assert cli.main(["validate", _write(tmp_path, "a.pdf", b"%PDF-1.7\nnot really")]) == 1
    assert capsys.readouterr().err.startswith("error: cannot read the PDF: ")
    assert [r.getMessage() for r in caplog.records if r.name.startswith("pypdf")] == []
    assert logging.getLogger("pypdf").level == logging.NOTSET  # restored after the run


def test_a_plain_text_stdout_is_left_as_is(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_validate(monkeypatch, ValidationReport())
    out = io.StringIO()  # no encoding to reconfigure, e.g. a redirected stream in an embedding application
    monkeypatch.setattr(sys, "stdout", out)
    assert cli.main(["validate", _write(tmp_path, "a.xml", b"<x/>")]) == 0
    assert out.getvalue() == "ok: 0 fatal/error, 0 warning/information\n"
