"""The top-level API: ``to_xml``, ``parse``, ``parse_detailed`` and the package's re-exports (#27)."""

import dataclasses
import pickle  # ruff: ignore[suspicious-pickle-import] - round-trips our own exception
import subprocess  # ruff: ignore[suspicious-subprocess-import] - runs this interpreter on a fixed snippet
import sys
import types
import typing as t

import pytest
from lxml import etree

import euinvoice
from _calc_drafts import with_totals
from _invoices import CEN, minimal_invoice, peppol_invoice, rebuild
from _pdfa import pdf
from _xrechnung_cases import xrechnung_invoice
from euinvoice import _xml, facturx, parse, parse_detailed, profiles, to_xml
from euinvoice.errors import ParseError, PreflightError, UnsupportedDocumentError
from euinvoice.model import Invoice, ProcessControl
from euinvoice.report import Finding, Severity
from euinvoice.syntax import Syntax, cii, ubl


def _core_invoice() -> Invoice:
    return minimal_invoice(process_control=ProcessControl(specification_identifier=CEN))


# --- to_xml -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("syntax", [Syntax.UBL, "ubl"])
def test_to_xml_writes_ubl_under_the_profile_of_the_invoice_bt24_by_default(syntax: Syntax | t.Literal["ubl"]) -> None:
    invoice = _core_invoice()
    assert to_xml(invoice, syntax=syntax) == ubl.write(profiles.EN16931.prepare(invoice))


def test_to_xml_writes_cii() -> None:
    invoice = _core_invoice()
    assert to_xml(invoice, profile=profiles.EN16931, syntax="cii") == cii.write(profiles.EN16931.prepare(invoice))


@pytest.mark.parametrize("syntax", [Syntax.UBL, Syntax.CII])
def test_to_xml_writes_the_prepared_invoice(syntax: Syntax) -> None:
    # XRECHNUNG.prepare sets BT-24 to the XRechnung id, so what reads back is the prepared invoice.
    invoice = rebuild(
        xrechnung_invoice(),
        process_control=ProcessControl(
            business_process_type="urn:fdc:peppol.eu:2017:poacc:billing:01:1.0", specification_identifier=CEN
        ),
    )
    written = to_xml(invoice, profile=profiles.XRECHNUNG, syntax=syntax)
    assert parse(written) == profiles.XRECHNUNG.prepare(invoice)
    assert parse(written) != invoice


def test_to_xml_needs_a_syntax_when_the_profile_has_two() -> None:
    with pytest.raises(ValueError, match="'en16931' supports cii, ubl; pass syntax="):
        to_xml(_core_invoice())


def test_to_xml_uses_the_only_syntax_of_the_profile() -> None:
    invoice = _core_invoice()
    written = to_xml(invoice, profile=profiles.FACTURX_EN16931)
    assert written == cii.write(profiles.FACTURX_EN16931.prepare(invoice))


def test_to_xml_refuses_a_syntax_the_profile_does_not_support() -> None:
    with pytest.raises(UnsupportedDocumentError, match="'facturx-en16931' does not support UBL; it supports cii"):
        to_xml(_core_invoice(), profile=profiles.FACTURX_EN16931, syntax=Syntax.UBL)


def test_to_xml_rejects_an_unknown_syntax() -> None:
    with pytest.raises(ValueError, match="'xml' is not a valid Syntax"):
        to_xml(_core_invoice(), syntax="xml")  # type: ignore[arg-type] # the invalid value is the test


def test_to_xml_without_profile_refuses_an_unregistered_bt24() -> None:
    invoice = minimal_invoice(process_control=ProcessControl(specification_identifier="urn:example.com:unknown"))
    with pytest.raises(UnsupportedDocumentError, match="unsupported specification identifier"):
        to_xml(invoice, syntax="ubl")


@pytest.mark.parametrize(
    "profile",
    [profiles.FACTURX_MINIMUM, profiles.FACTURX_BASIC_WL, profiles.FACTURX_BASIC, profiles.FACTURX_EXTENDED],
)
def test_to_xml_refuses_the_factur_x_levels_that_are_not_generated(profile: profiles.Profile) -> None:
    with pytest.raises(UnsupportedDocumentError, match=f"profile '{profile.id}' is not generated"):
        to_xml(_core_invoice(), profile=profile)
    bt24 = ProcessControl(specification_identifier=profile.specification_identifier)
    with pytest.raises(UnsupportedDocumentError, match="is not generated"):
        to_xml(minimal_invoice(process_control=bt24), syntax="cii")


def test_to_xml_refuses_an_invoice_with_blocking_preflight_findings() -> None:
    # PEPPOL-EN16931-R003 / R010 / R020: the minimal invoice has no BT-10, BT-49 or BT-34.
    with pytest.raises(PreflightError) as caught:
        to_xml(_core_invoice(), profile=profiles.PEPPOL, syntax="ubl")
    assert [f.rule_id for f in caught.value.findings] == [
        "PEPPOL-EN16931-R003",
        "PEPPOL-EN16931-R010",
        "PEPPOL-EN16931-R020",
    ]
    message = str(caught.value)
    assert message.startswith(
        "invoice fails the peppol pre-flight and calculation checks for ubl: PEPPOL-EN16931-R003 (fatal) at"
    )
    assert "PEPPOL-EN16931-R020 (fatal) at seller.electronic_address" in message


def test_to_xml_passes_a_preflight_clean_invoice() -> None:
    assert to_xml(peppol_invoice(), profile=profiles.PEPPOL, syntax="ubl")


def _finding(severity: Severity) -> Finding:
    return Finding(rule_id="EUINV-TEST", severity=severity, location="note", message="test", source="test")


@pytest.mark.parametrize("severity", [Severity.WARNING, Severity.INFORMATION])
def test_to_xml_writes_despite_non_blocking_preflight_findings(severity: Severity) -> None:
    profile = dataclasses.replace(profiles.EN16931, preflight=lambda invoice, syntax: (_finding(severity),))
    invoice = _core_invoice()
    assert to_xml(invoice, profile=profile, syntax="ubl") == ubl.write(invoice)


def test_preflight_error_keeps_every_finding_and_names_only_the_blocking_ones() -> None:
    findings = (_finding(Severity.WARNING), dataclasses.replace(_finding(Severity.ERROR), rule_id="EUINV-BLOCK"))
    profile = dataclasses.replace(profiles.EN16931, preflight=lambda invoice, syntax: findings)
    with pytest.raises(PreflightError) as caught:
        to_xml(_core_invoice(), profile=profile, syntax="cii")
    assert caught.value.findings == findings
    assert str(caught.value) == (
        "invoice fails the en16931 pre-flight and calculation checks for cii: EUINV-BLOCK (error) at note: test"
    )
    assert (caught.value.profile_id, caught.value.syntax) == ("en16931", "cii")


@pytest.mark.parametrize("syntax", [Syntax.UBL, Syntax.CII])
def test_to_xml_refuses_a_wrong_total_with_vat(syntax: Syntax) -> None:
    # BT-112 != BT-109 + BT-110: BR-CO-15 (fatal in both CEN bindings; calc.check is oracle-tested against them).
    invoice = with_totals(_core_invoice(), total_with_vat="999.99")
    with pytest.raises(PreflightError) as caught:
        to_xml(invoice, profile=profiles.EN16931, syntax=syntax)
    assert "BR-CO-15" in {f.rule_id for f in caught.value.findings}
    assert all(f.source == "calc" for f in caught.value.findings)


def test_to_xml_refuses_a_vat_breakdown_with_a_wrong_tax_amount() -> None:
    # BT-117 off by more than 1 from BT-116 x BT-119: BR-CO-17.
    invoice = _core_invoice()
    group = invoice.vat_breakdown[0]
    tampered = type(group).model_validate({**dict(group), "tax_amount": group.tax_amount + 5})
    with pytest.raises(PreflightError) as caught:
        to_xml(rebuild(invoice, vat_breakdown=(tampered,)), profile=profiles.EN16931, syntax="cii")
    assert "BR-CO-17" in {f.rule_id for f in caught.value.findings}


def test_preflight_error_pickles() -> None:
    findings = (dataclasses.replace(_finding(Severity.FATAL), rule_id="BR-CO-15"),)
    error = PreflightError("en16931", "ubl", findings)
    again = pickle.loads(pickle.dumps(error))  # ruff: ignore[suspicious-pickle-usage] - our own object
    assert (type(again), str(again), again.profile_id, again.syntax, again.findings) == (
        PreflightError,
        str(error),
        "en16931",
        "ubl",
        findings,
    )


def test_preflight_error_needs_a_blocking_finding() -> None:
    with pytest.raises(ValueError, match="at least one fatal or error finding"):
        PreflightError("en16931", "ubl", (_finding(Severity.WARNING),))


# --- parse / parse_detailed --------------------------------------------------------------------------------------


@pytest.mark.parametrize("syntax", [Syntax.UBL, Syntax.CII])
def test_parse_reads_both_syntaxes(syntax: Syntax) -> None:
    invoice = _core_invoice()
    written = to_xml(invoice, syntax=syntax)
    assert parse(written) == invoice
    assert parse_detailed(written) == euinvoice.ParseResult(invoice=invoice)


def test_parse_discards_unmapped_input_that_parse_detailed_lists() -> None:
    root = _xml.parse(to_xml(_core_invoice(), syntax="ubl"))
    root.set("unknown", "value")
    data = etree.tostring(root)
    assert parse_detailed(data).unmapped == ("/*/@unknown",)
    assert parse(data) == parse_detailed(data).invoice


def test_parse_reads_the_invoice_of_a_factur_x_pdf() -> None:
    invoice = _core_invoice()
    hybrid = facturx.embed(pdf(), invoice, profile=profiles.FACTURX_EN16931)
    assert parse(hybrid) == profiles.FACTURX_EN16931.prepare(invoice)
    assert parse_detailed(hybrid).unmapped == ()


def test_parse_refuses_input_that_is_not_bytes() -> None:
    with pytest.raises(TypeError):
        parse("<Invoice/>")  # type: ignore[arg-type] # a str, not bytes, is the test


def test_parse_refuses_an_unsupported_root() -> None:
    with pytest.raises(UnsupportedDocumentError, match="unsupported root element"):
        parse(b"<Invoice/>")


def test_parse_refuses_fatturapa_until_its_reader_exists() -> None:
    fatturapa = f'<p:FatturaElettronica xmlns:p="{_xml.FATTURAPA}" versione="FPR12"/>'.encode()
    with pytest.raises(UnsupportedDocumentError, match="reading FatturaPA is not implemented yet"):
        parse(fatturapa)


def test_to_xml_refuses_fatturapa_as_no_profile_supports_it() -> None:
    with pytest.raises(UnsupportedDocumentError, match="'en16931' does not support FATTURAPA"):
        to_xml(_core_invoice(), syntax=Syntax.FATTURAPA)  # writing it is #119


def test_parse_refuses_malformed_xml() -> None:
    with pytest.raises(ParseError):
        parse(b"<Invoice>")


def test_parse_of_a_pdf_without_the_pdf_extra_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [m for m in sys.modules if m == "euinvoice.facturx" or m.startswith("euinvoice.facturx.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.delattr(euinvoice, "facturx", raising=False)
    monkeypatch.setitem(sys.modules, "pypdf", None)  # makes `import pypdf` raise ImportError
    with pytest.raises(ImportError, match=r"euinvoice\[pdf\]"):
        parse(pdf())


# --- package ------------------------------------------------------------------------------------------------------


def test_every_name_in_all_resolves_and_star_imports_without_pypdf() -> None:
    snippet = (
        "import sys\n"
        "sys.modules['pypdf'] = None\n"  # makes `import pypdf` raise ImportError
        "import euinvoice\n"
        "from euinvoice import *\n"
        "assert all(getattr(euinvoice, name) is not None for name in euinvoice.__all__)\n"
        "assert 'facturx' not in euinvoice.__all__\n"
        "print('ok')\n"
    )
    out = subprocess.run([sys.executable, "-c", snippet], capture_output=True, text=True, check=True)  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv
    assert out.stdout == "ok\n"


def test_the_reexports_are_the_functions() -> None:
    from euinvoice.detection import detect
    from euinvoice.validation.orchestration import validate

    assert euinvoice.validate is validate
    assert euinvoice.detect is detect
    assert euinvoice.facturx.extract is facturx.extract


def test_the_functions_do_not_shadow_their_modules() -> None:
    # #93: the modules are named ``detection`` / ``validation`` so the top-level functions hide nothing.
    import euinvoice.detection as detection
    import euinvoice.validation.artifacts as artifacts

    assert isinstance(detection, types.ModuleType)
    assert detection.Detection.__module__ == "euinvoice.detection"
    assert artifacts.__name__ == "euinvoice.validation.artifacts"
    assert euinvoice.validation.artifacts.source_dir is artifacts.source_dir
    assert euinvoice.detection.is_pdf is detection.is_pdf
    assert euinvoice.detect is detection.detect
    assert euinvoice.validate is euinvoice.validation.validate
    assert not isinstance(euinvoice.detect, types.ModuleType)
    assert not isinstance(euinvoice.validate, types.ModuleType)


def test_an_unknown_attribute_raises_attribute_error() -> None:
    with pytest.raises(AttributeError, match="has no attribute 'nope'"):
        euinvoice.nope  # type: ignore[attr-defined] # ruff: ignore[useless-expression] - the bad access is the test


def test_import_euinvoice_loads_neither_pypdf_nor_saxonche() -> None:
    snippet = (
        "import sys, euinvoice\n"
        "euinvoice.to_xml, euinvoice.parse, euinvoice.validate\n"
        "print(sorted(m for m in ('pypdf', 'saxonche', 'euinvoice.facturx') if m in sys.modules))\n"
        "euinvoice.facturx\n"
        "print('pypdf' in sys.modules)\n"
    )
    out = subprocess.run([sys.executable, "-c", snippet], capture_output=True, text=True, check=True)  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv
    assert out.stdout.split("\n") == ["[]", "True", ""]
