"""UBL 2.1 XSD validation against the official OASIS schemas and CEN examples (needs ``make artifacts``)."""

import pathlib

import pytest
from _xsd_helpers import assert_located_xsd_fatal

from euinvoice import _xml
from euinvoice.errors import ArtifactsNotAvailableError
from euinvoice.validation import artifacts, xsd

pytestmark = pytest.mark.conformance

EXAMPLE1 = "ubl-tc434-example1.xml"


def cen_ubl_examples() -> list[pathlib.Path]:
    # Collected at import time, so the cache must be warm; `make conformance` runs after `make artifacts`.
    try:
        examples = artifacts.source_dir("cen-ubl") / "examples"
    except ArtifactsNotAvailableError:  # collected but deselected by `make test`; the coverage test fails
        return []
    return sorted(p for p in examples.iterdir() if p.suffix.lower() == ".xml")


def test_cen_ubl_examples_cover_invoices_and_credit_notes() -> None:
    roots = {_xml.parse(p.read_bytes()).tag for p in cen_ubl_examples()}
    assert roots == {f"{{{_xml.UBL_INVOICE}}}Invoice", f"{{{_xml.UBL_CREDIT_NOTE}}}CreditNote"}


@pytest.mark.parametrize("path", cen_ubl_examples(), ids=lambda p: p.name)
def test_official_cen_ubl_example_is_schema_valid(path: pathlib.Path) -> None:
    assert xsd.validate(_xml.parse(path.read_bytes())) == ()


@pytest.mark.parametrize(
    ("original", "mutated", "path", "message"),
    [
        pytest.param(
            b"<cbc:ID>12115118</cbc:ID>\n    <cbc:IssueDate>2015-01-09</cbc:IssueDate>",
            b"<cbc:IssueDate>2015-01-09</cbc:IssueDate>\n    <cbc:ID>12115118</cbc:ID>",
            "/*/cbc:IssueDate",
            "This element is not expected. Expected is one of",
            id="element-order-swapped",
        ),
        pytest.param(
            b"<cbc:IssueDate>2015-01-09</cbc:IssueDate>",
            b"<cbc:Bogus>x</cbc:Bogus><cbc:IssueDate>2015-01-09</cbc:IssueDate>",
            "/*/cbc:Bogus",
            "This element is not expected. Expected is one of",
            id="unknown-element",
        ),
        pytest.param(
            b"<cbc:IssueDate>2015-01-09</cbc:IssueDate>",
            b"<cbc:IssueDate>09.01.2015</cbc:IssueDate>",
            "/*/cbc:IssueDate",
            "'09.01.2015' is not a valid value of the atomic type 'xs:date'",
            id="bad-date",
        ),
    ],
)
def test_mutated_example_fails_with_a_located_error(original: bytes, mutated: bytes, path: str, message: str) -> None:
    source = (artifacts.source_dir("cen-ubl") / "examples" / EXAMPLE1).read_bytes()
    assert source.count(original) == 1
    data = source.replace(original, mutated)

    findings = xsd.validate(_xml.parse(data))

    assert_located_xsd_fatal(findings, data, mutated, path, message, "xsd:ubl-2_1")
