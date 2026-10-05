"""Unit tests of euinvoice.validate.xsd against tiny synthetic schemas in a fake artifact cache."""

import concurrent.futures
import dataclasses
import pathlib
import typing as t

import pytest

from euinvoice import _xml
from euinvoice.errors import ArtifactsNotAvailableError, UnsupportedDocumentError
from euinvoice.validate import artifacts, xsd
from euinvoice.validate.report import Finding, Severity

# Synthetic stand-ins for the UBL 2.1 maindoc schemas. Like the real ones, they import a sibling
# directory (../common), so the confinement root must be the whole xsd/ directory.
COMMON_XSD = f"""<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="{_xml.UBL_CBC}"
  elementFormDefault="qualified">
  <xs:element name="ID" type="xs:string"/>
  <xs:element name="IssueDate" type="xs:date"/>
  <xs:element name="Note" type="xs:string"/>
</xs:schema>"""


def maindoc_xsd(namespace: str, root: str, last: str) -> str:
    return f"""<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:cbc="{_xml.UBL_CBC}"
  targetNamespace="{namespace}" elementFormDefault="qualified">
  <xs:import namespace="{_xml.UBL_CBC}" schemaLocation="../common/cbc.xsd"/>
  <xs:element name="{root}">
    <xs:complexType><xs:sequence>
      <xs:element ref="cbc:ID"/>
      <xs:element ref="cbc:{last}"/>
    </xs:sequence></xs:complexType>
  </xs:element>
</xs:schema>"""


def doc(namespace: str, root: str, body: str, attrs: str = "") -> bytes:
    return f'<{root} xmlns="{namespace}" xmlns:cbc="{_xml.UBL_CBC}"{attrs}>\n{body}\n</{root}>'.encode()


VALID_INVOICE = doc(_xml.UBL_INVOICE, "Invoice", "<cbc:ID>INV-1</cbc:ID>\n<cbc:IssueDate>2026-01-31</cbc:IssueDate>")


@pytest.fixture
def cache(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """A warm fake ``ubl-2_1`` cache entry holding the synthetic schemas."""
    sources = artifacts.load_manifest()
    target = tmp_path / "ubl-2_1" / sources["ubl-2_1"].version
    (target / "xsd" / "common").mkdir(parents=True)
    (target / "xsd" / "maindoc").mkdir()
    (target / "xsd" / "common" / "cbc.xsd").write_text(COMMON_XSD)
    (target / "xsd" / "maindoc" / "UBL-Invoice-2.1.xsd").write_text(
        maindoc_xsd(_xml.UBL_INVOICE, "Invoice", "IssueDate")
    )
    (target / "xsd" / "maindoc" / "UBL-CreditNote-2.1.xsd").write_text(
        maindoc_xsd(_xml.UBL_CREDIT_NOTE, "CreditNote", "Note")
    )
    (target / artifacts.MARKER).write_text(artifacts._fingerprint(sources["ubl-2_1"], sources))
    monkeypatch.setenv(artifacts.ENV_VAR, str(tmp_path))
    return target


@pytest.mark.usefixtures("cache")
def test_valid_invoice_has_no_findings() -> None:
    assert xsd.validate(_xml.parse(VALID_INVOICE)) == ()


@pytest.mark.usefixtures("cache")
def test_unknown_element_becomes_a_located_fatal_xsd_finding() -> None:
    data = doc(
        _xml.UBL_INVOICE, "Invoice", "<cbc:ID>INV-1</cbc:ID>\n<cbc:Bogus/>\n<cbc:IssueDate>2026-01-31</cbc:IssueDate>"
    )

    (finding,) = xsd.validate(_xml.parse(data))

    assert finding.rule_id == "XSD"
    assert finding.severity is Severity.FATAL
    assert finding.source == "xsd:ubl-2_1"
    assert finding.location == "3:0 /*/cbc:Bogus"  # line 3; libxml2 tracks no column while validating
    assert "Bogus" in finding.message
    assert "This element is not expected" in finding.message


@pytest.mark.usefixtures("cache")
def test_every_error_is_reported_in_document_order() -> None:
    data = doc(_xml.UBL_INVOICE, "Invoice", "<cbc:ID><x/></cbc:ID>\n<cbc:IssueDate>31.01.2026</cbc:IssueDate>")

    findings = xsd.validate(_xml.parse(data))

    assert [f.location for f in findings] == ["2:0 /*/cbc:ID", "3:0 /*/cbc:IssueDate"]
    assert "'31.01.2026' is not a valid value of the atomic type 'xs:date'" in findings[1].message


@pytest.mark.usefixtures("cache")
def test_credit_note_is_validated_against_the_credit_note_schema() -> None:
    credit_note = doc(_xml.UBL_CREDIT_NOTE, "CreditNote", "<cbc:ID>CN-1</cbc:ID><cbc:Note>refund</cbc:Note>")
    invoice_shaped = doc(
        _xml.UBL_CREDIT_NOTE, "CreditNote", "<cbc:ID>CN-1</cbc:ID><cbc:IssueDate>2026-01-31</cbc:IssueDate>"
    )

    assert xsd.validate(_xml.parse(credit_note)) == ()
    assert len(xsd.validate(_xml.parse(invoice_shaped))) == 1


@pytest.mark.usefixtures("cache")
def test_root_element_of_the_wrong_name_is_an_error() -> None:
    data = doc(_xml.UBL_INVOICE, "CreditNote", "<cbc:ID>INV-1</cbc:ID>")

    (finding,) = xsd.validate(_xml.parse(data))

    assert "No matching global declaration" in finding.message


@pytest.mark.usefixtures("cache")
def test_xsi_schema_location_hints_are_ignored() -> None:
    attrs = (
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        f' xsi:schemaLocation="{_xml.UBL_INVOICE} http://example.com/evil.xsd"'
    )
    data = doc(_xml.UBL_INVOICE, "Invoice", "<cbc:ID>INV-1</cbc:ID><cbc:IssueDate>2026-01-31</cbc:IssueDate>", attrs)

    assert xsd.validate(_xml.parse(data)) == ()


@pytest.mark.parametrize(
    "data",
    [
        f'<rsm:CrossIndustryInvoice xmlns:rsm="{_xml.CII_RSM}"/>'.encode(),
        b'<Invoice xmlns="urn:example:not-ubl"/>',
        b"<Invoice/>",
    ],
)
def test_unknown_root_namespace_is_unsupported_without_touching_the_cache(
    data: bytes, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(artifacts.ENV_VAR, str(tmp_path))  # cold cache

    with pytest.raises(UnsupportedDocumentError, match="no XML Schema for root element"):
        xsd.validate(_xml.parse(data))


def test_cold_cache_raises_artifacts_not_available(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(artifacts.ENV_VAR, str(tmp_path))

    with pytest.raises(ArtifactsNotAvailableError, match="artifacts fetch"):
        xsd.validate(_xml.parse(VALID_INVOICE))


def spy_on_schema_loads(monkeypatch: pytest.MonkeyPatch) -> list[pathlib.Path]:
    calls: list[pathlib.Path] = []
    real = _xml.load_trusted_schema

    def spy(path: pathlib.Path, *, root: pathlib.Path | None = None) -> t.Any:
        calls.append(path)
        return real(path, root=root)

    monkeypatch.setattr(_xml, "load_trusted_schema", spy)
    return calls


def test_compiled_schema_is_cached_per_path_and_fingerprint(
    cache: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = spy_on_schema_loads(monkeypatch)

    xsd.validate(_xml.parse(VALID_INVOICE))
    xsd.validate(_xml.parse(VALID_INVOICE))
    assert calls == [cache / "xsd/maindoc/UBL-Invoice-2.1.xsd"]

    path, root = cache / "xsd/maindoc/UBL-Invoice-2.1.xsd", cache / "xsd"
    assert xsd._compiled(path, root, "other recipe") is not xsd._compiled(path, root, "another recipe")
    assert len(calls) == 3


@pytest.mark.usefixtures("cache")
def test_concurrent_validations_keep_their_own_findings() -> None:
    invalid = doc(_xml.UBL_INVOICE, "Invoice", "<cbc:ID>INV-1</cbc:ID>\n<cbc:IssueDate>nope</cbc:IssueDate>")
    inputs = [VALID_INVOICE, invalid] * 50

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda data: xsd.validate(_xml.parse(data)), inputs))

    for data, findings in zip(inputs, results, strict=True):
        if data == VALID_INVOICE:
            assert findings == ()
        else:
            assert [f.location for f in findings] == ["3:0 /*/cbc:IssueDate"]
            assert all(isinstance(f, Finding) for f in findings)


@dataclasses.dataclass
class FakeLogEntry:
    line: int
    column: int
    path: str | None
    message: str


def test_entry_without_element_path_is_located_by_line_and_column_only() -> None:
    finding = xsd._finding(FakeLogEntry(7, 3, None, "boom"), "xsd:ubl-2_1")

    assert finding == Finding("XSD", Severity.FATAL, "7:3", "boom", "xsd:ubl-2_1")
