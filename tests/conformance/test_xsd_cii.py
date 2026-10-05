"""CII D16B XSD validation against the official schema and upstream CII corpora (needs ``make artifacts``)."""

import typing as t

import pytest
from conftest import assert_located_xsd_fatal

from euinvoice import _xml
from euinvoice.errors import ArtifactsNotAvailableError
from euinvoice.validate import artifacts, xsd
from euinvoice.validate.report import Finding

pytestmark = pytest.mark.conformance

EXAMPLE1 = "CII_example1.xml"
CII_ROOT = f"{{{_xml.CII_RSM}}}CrossIndustryInvoice"
GUIDELINE = "string(rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID)"
# ZUGFeRD corpus guideline ids (BT-24) of the EN 16931 and XRechnung CII profiles, which use the D16B
# schema. The other Factur-X levels have their own per-profile XSDs (not pinned yet, needs-human #42),
# which are stricter: a MINIMUM / BASIC document with elements its profile forbids still passes the D16B
# schema, so asserting them here would only prove a false accept.
EN16931 = "urn:cen.eu:en16931:2017"
XRECHNUNG_PREFIX = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_"
XRECHNUNG_1_2 = "urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_1.2"

# Corpus files (relative to the source root) that are not well-formed XML, with the reason. Skipped
# before parsing; any other ParseError fails collection.
UNPARSEABLE: t.Final[t.Mapping[str, str]] = {
    "fatturaPA/eigor/valid/con-ritenuta-acconto-e-cassa-previdenziale.xml": (
        "truncated upstream FatturaPA sample (premature end of data at 102:30); not CII"
    ),
}

# Upstream samples marked as invalid (folder or file name) that are nevertheless schema-valid: their
# defects are at business-rule level (Schematron), not XSD. They stay in the asserted set; named here so
# a corpus bump that changes them fails with a clear name.
KNOWN_BAD_BUT_XSD_VALID: t.Final = (
    "ZUGFeRDv2/fail/Mustangproject/noNetPriceValidation.xml",
    "XML-Rechnung/CII/not_validating_full_invoice_based_onTest_EeISI_300_CENfullmodel.cii.xml",
    "other/eicar.cii.xml",
)


def cii_files(source: artifacts.SourceName, subdir: str = "") -> dict[str, str]:
    """Return the CII instances of ``source``: path relative to the source root → guideline id (BT-24)."""
    # Collected at import time, so the cache must be warm; `make conformance` runs after `make artifacts`.
    try:
        root_dir = artifacts.source_dir(source)
    except ArtifactsNotAvailableError:  # collected but deselected by `make test`; the coverage test fails
        return {}
    found = {}
    for path in sorted((root_dir / subdir).rglob("*.xml")):
        relative = path.relative_to(root_dir).as_posix()
        if relative in UNPARSEABLE:
            continue
        root = _xml.parse(path.read_bytes())
        if root.tag == CII_ROOT:
            found[relative] = str(root.xpath(GUIDELINE, namespaces=_xml.CII_NSMAP))
    return found


def zugferd_en16931_and_xrechnung() -> list[str]:
    return [
        relative
        for relative, guideline in cii_files("zugferd-corpus").items()
        if guideline in {EN16931, XRECHNUNG_1_2} or guideline.startswith(XRECHNUNG_PREFIX)
    ]


def validate(source: artifacts.SourceName, relative: str) -> tuple[Finding, ...]:
    return xsd.validate(_xml.parse((artifacts.source_dir(source) / relative).read_bytes()))


def test_corpora_have_the_expected_cii_instance_counts() -> None:
    # Guards the parametrized tests below against silently collecting nothing (pinned corpora).
    assert len(cii_files("cen-cii", "examples")) == 15
    assert len(cii_files("xrechnung-testsuite")) == 41
    assert len(zugferd_en16931_and_xrechnung()) == 39


def test_listed_corpus_exceptions_still_exist() -> None:
    corpus = artifacts.source_dir("zugferd-corpus")
    for relative in UNPARSEABLE:
        assert (corpus / relative).is_file(), f"stale UNPARSEABLE entry {relative}"
    assert set(KNOWN_BAD_BUT_XSD_VALID) <= set(zugferd_en16931_and_xrechnung())


@pytest.mark.parametrize("relative", cii_files("cen-cii", "examples"))
def test_official_cen_cii_example_is_schema_valid(relative: str) -> None:
    assert validate("cen-cii", relative) == ()


@pytest.mark.parametrize("relative", cii_files("xrechnung-testsuite"))
def test_xrechnung_testsuite_cii_instance_is_schema_valid(relative: str) -> None:
    assert validate("xrechnung-testsuite", relative) == ()


@pytest.mark.parametrize("relative", zugferd_en16931_and_xrechnung())
def test_zugferd_corpus_en16931_and_xrechnung_cii_is_schema_valid(relative: str) -> None:
    assert validate("zugferd-corpus", relative) == ()


ISSUE_DATE = b'<udt:DateTimeString format="102">20150109</udt:DateTimeString>\n        </ram:IssueDateTime>'
DATE_PATH = "/rsm:CrossIndustryInvoice/rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString"


@pytest.mark.parametrize(
    ("original", "mutated", "path", "message"),
    [
        pytest.param(
            b"<ram:ID>12115118</ram:ID>\n        <ram:TypeCode>380</ram:TypeCode>",
            b"<ram:TypeCode>380</ram:TypeCode>\n        <ram:ID>12115118</ram:ID>",
            "/rsm:CrossIndustryInvoice/rsm:ExchangedDocument/ram:TypeCode",
            f"This element is not expected. Expected is ( {{{_xml.CII_RAM}}}ID )",
            id="element-order-swapped",
        ),
        pytest.param(
            b"<ram:TypeCode>380</ram:TypeCode>",
            b"<ram:Bogus>x</ram:Bogus><ram:TypeCode>380</ram:TypeCode>",
            "/rsm:CrossIndustryInvoice/rsm:ExchangedDocument/ram:Bogus",
            "This element is not expected. Expected is one of",
            id="unknown-element",
        ),
        pytest.param(
            ISSUE_DATE,
            ISSUE_DATE.replace(b"format=", b"dateFormat="),
            DATE_PATH,
            "The attribute 'dateFormat' is not allowed",
            id="bad-date-format-attribute",
        ),
    ],
)
def test_mutated_example_fails_with_a_located_error(original: bytes, mutated: bytes, path: str, message: str) -> None:
    source = (artifacts.source_dir("cen-cii") / "examples" / EXAMPLE1).read_bytes()
    assert source.count(original) == 1
    data = source.replace(original, mutated)

    findings = xsd.validate(_xml.parse(data))

    assert_located_xsd_fatal(findings, data, mutated, path, message, "xsd:xrechnung-validator-configuration")


def test_date_format_code_is_left_to_the_schematron() -> None:
    # The D16B udt schema types DateTimeString/@format as xs:string
    # (CrossIndustryInvoice_UnqualifiedDataType_100pD16B.xsd line 57), so an unknown format code is
    # XSD-valid. The CEN Schematron does not check the code either: CII-DT-097 only checks the value when
    # @format='102', and on BT-2 an unknown code surfaces only as BR-03 (no
    # IssueDateTime/DateTimeString[@format='102']; EN16931-CII-validation-preprocessed.sch lines 84 and
    # 987-988). Other dates with a bad code pass both XSD and CEN Schematron, so the CII writer must
    # always emit 102.
    source = (artifacts.source_dir("cen-cii") / "examples" / EXAMPLE1).read_bytes()
    assert source.count(ISSUE_DATE) == 1
    data = source.replace(ISSUE_DATE, ISSUE_DATE.replace(b'format="102"', b'format="999"'))

    assert xsd.validate(_xml.parse(data)) == ()
