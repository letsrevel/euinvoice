"""Real fetch of every pinned source (network on a cold cache). Run with ``make conformance``."""

from pathlib import Path

import pytest

from euinvoice.validate import artifacts

pytestmark = pytest.mark.conformance


def test_every_pinned_source_fetches_verifies_and_is_complete() -> None:
    sources = artifacts.load_manifest()

    fetched = artifacts.fetch()

    assert set(fetched) == set(sources)
    for name, path in fetched.items():
        assert artifacts.source_dir(name) == path
        assert any(p.is_file() and p.name != artifacts.MARKER for p in path.rglob("*")), name


@pytest.mark.parametrize(
    ("name", "member"),
    [
        ("cen-ubl", "xslt/EN16931-UBL-validation.xslt"),
        ("cen-cii", "xslt/EN16931-CII-validation.xslt"),
        ("cen-cii", "examples/CII-BR-CO-10-RoundingIssue.xml"),
        ("peppol-bis", "rules/sch/PEPPOL-EN16931-UBL.sch"),
        ("peppol-bis", "rules/sch/PEPPOL-EN16931-UBL.xslt"),
        ("peppol-bis", "rules/sch/PEPPOL-EN16931-CII.xslt"),
        ("xrechnung-schematron", "schematron/ubl/XRechnung-UBL-validation.xsl"),
        ("xrechnung-schematron", "schematron/cii/XRechnung-CII-validation.xsl"),
        ("xrechnung-validator-configuration", "resources/cii/16b/xsd/CrossIndustryInvoice_100pD16B.xsd"),
        ("ubl-2_1", "xsd/maindoc/UBL-Invoice-2.1.xsd"),
        ("ubl-2_1", "xsd/maindoc/UBL-CreditNote-2.1.xsd"),
        ("schxslt", artifacts.SCHXSLT_PIPELINE),
        ("zugferd-corpus", "LICENSE"),
    ],
)
def test_expected_members_are_present(name: str, member: str) -> None:
    artifacts.fetch([name])
    assert (artifacts.source_dir(name) / member).is_file()


def test_precompiled_peppol_xslt_is_an_svrl_producing_stylesheet() -> None:
    xslt = (artifacts.fetch(["peppol-bis"])["peppol-bis"] / "rules/sch/PEPPOL-EN16931-UBL.xslt").read_text("utf-8")
    assert "http://www.w3.org/1999/XSL/Transform" in xslt
    assert "http://purl.oclc.org/dsdl/svrl" in xslt
    assert "PEPPOL-EN16931-R001" in xslt


def test_cold_fetch_downloads_verifies_and_precompiles(tmp_path: Path) -> None:
    # Always exercises the real network path (the shared cache is usually warm in CI). Kept to the
    # small sources; peppol-bis also pulls in schxslt and runs the SchXslt precompile on Saxon.
    fetched = artifacts.fetch(["xrechnung-schematron", "peppol-bis"], root=tmp_path)

    assert list(fetched) == ["schxslt", "xrechnung-schematron", "peppol-bis"]
    assert (fetched["peppol-bis"] / "rules/sch/PEPPOL-EN16931-CII.xslt").is_file()
    assert (tmp_path / "schxslt" / "1.10.1" / artifacts.MARKER).is_file()
