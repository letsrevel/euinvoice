"""CII D16B XSD validation against the official schema and upstream CII corpora (needs ``make artifacts``)."""

import pathlib

import pytest

from euinvoice import _xml
from euinvoice.errors import ArtifactsNotAvailableError, ParseError
from euinvoice.validate import artifacts, xsd
from euinvoice.validate.report import Severity

pytestmark = pytest.mark.conformance

EXAMPLE1 = "CII_example1.xml"
CII_ROOT = f"{{{_xml.CII_RSM}}}CrossIndustryInvoice"
GUIDELINE = "string(rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID)"
# ZUGFeRD corpus guideline ids (BT-24) of the EN 16931 and XRechnung CII profiles, which use the D16B
# schema. Other Factur-X levels have their own per-profile XSDs (not pinned yet, needs-human #42).
EN16931 = "urn:cen.eu:en16931:2017"
XRECHNUNG_PREFIX = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_"
XRECHNUNG_1_2 = "urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_1.2"


def cii_files(source: artifacts.SourceName, subdir: str = "") -> list[pathlib.Path]:
    # Collected at import time, so the cache must be warm; `make conformance` runs after `make artifacts`.
    try:
        base = artifacts.source_dir(source) / subdir
    except ArtifactsNotAvailableError:  # collected but deselected by `make test`; the coverage test fails
        return []
    found = []
    for path in sorted(base.rglob("*.xml")):
        try:
            root = _xml.parse(path.read_bytes())
        except ParseError:  # the ZUGFeRD corpus also holds broken non-CII samples
            continue
        if root.tag == CII_ROOT:
            found.append(path)
    return found


def guideline(path: pathlib.Path) -> str:
    return str(_xml.parse(path.read_bytes()).xpath(GUIDELINE, namespaces=_xml.CII_NSMAP))


def zugferd_en16931_and_xrechnung() -> list[pathlib.Path]:
    return [
        p
        for p in cii_files("zugferd-corpus")
        if (g := guideline(p)) in {EN16931, XRECHNUNG_1_2} or g.startswith(XRECHNUNG_PREFIX)
    ]


def line_of(data: bytes, needle: bytes) -> int:
    return data[: data.index(needle)].count(b"\n") + 1


def test_corpora_have_the_expected_cii_instance_counts() -> None:
    # Guards the parametrized tests below against silently collecting nothing (pinned corpora).
    assert len(cii_files("cen-cii", "examples")) == 15
    assert len(cii_files("xrechnung-testsuite")) == 41
    assert len(zugferd_en16931_and_xrechnung()) == 39


@pytest.mark.parametrize("path", cii_files("cen-cii", "examples"), ids=lambda p: p.name)
def test_official_cen_cii_example_is_schema_valid(path: pathlib.Path) -> None:
    assert xsd.validate(_xml.parse(path.read_bytes())) == ()


@pytest.mark.parametrize("path", cii_files("xrechnung-testsuite"), ids=lambda p: p.name)
def test_xrechnung_testsuite_cii_instance_is_schema_valid(path: pathlib.Path) -> None:
    assert xsd.validate(_xml.parse(path.read_bytes())) == ()


@pytest.mark.parametrize("path", zugferd_en16931_and_xrechnung(), ids=lambda p: p.name)
def test_zugferd_corpus_en16931_and_xrechnung_cii_is_schema_valid(path: pathlib.Path) -> None:
    assert xsd.validate(_xml.parse(path.read_bytes())) == ()


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

    assert findings, "a mutated example must not be schema-valid"
    first = findings[0]
    assert (first.rule_id, first.severity, first.source) == (
        "XSD",
        Severity.FATAL,
        "xsd:xrechnung-validator-configuration",
    )
    # The first element of the mutation is where the schema stops accepting the document.
    assert first.location == f"{line_of(data, mutated)} {path}"
    assert message in first.message


def test_date_format_code_is_left_to_the_schematron() -> None:
    # The D16B udt schema types DateTimeString/@format as xs:string
    # (CrossIndustryInvoice_UnqualifiedDataType_100pD16B.xsd), so an unknown format code is XSD-valid;
    # the CEN Schematron enforces it (CII-DT-097, BR-03 in EN16931-CII-validation.sch).
    source = (artifacts.source_dir("cen-cii") / "examples" / EXAMPLE1).read_bytes()
    assert source.count(ISSUE_DATE) == 1
    data = source.replace(ISSUE_DATE, ISSUE_DATE.replace(b'format="102"', b'format="999"'))

    assert xsd.validate(_xml.parse(data)) == ()
