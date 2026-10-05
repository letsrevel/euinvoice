"""Tests for ``_xml.load_trusted_schema`` and the parse-totality property of ``_xml.parse``."""

import http.server
import pathlib
import threading
import typing as t

import pytest
from hypothesis import given
from hypothesis import strategies as st
from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ParseError

XS = "http://www.w3.org/2001/XMLSchema"
B_XSD = f'<xs:schema xmlns:xs="{XS}" targetNamespace="urn:test:b"><xs:element name="b" type="xs:string"/></xs:schema>'


def a_xsd(import_location: str) -> str:
    """A root schema whose only element references ``b:b`` from an imported schema."""
    return (
        f'<xs:schema xmlns:xs="{XS}" xmlns:b="urn:test:b" targetNamespace="urn:test:a">'
        f'<xs:import namespace="urn:test:b" schemaLocation="{import_location}"/>'
        '<xs:element name="a"><xs:complexType><xs:sequence><xs:element ref="b:b"/></xs:sequence>'
        "</xs:complexType></xs:element></xs:schema>"
    )


@pytest.fixture
def http_hits() -> t.Iterator[tuple[str, list[str]]]:
    """A local HTTP server that would serve the imported schema; yields (base URL, requested paths)."""
    hits: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            hits.append(self.path)
            body = B_XSD.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # stdlib signature
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", hits
    server.shutdown()
    server.server_close()


def test_local_import_is_followed(tmp_path: pathlib.Path) -> None:
    (tmp_path / "b.xsd").write_text(B_XSD, encoding="utf-8")
    (tmp_path / "a.xsd").write_text(a_xsd("b.xsd"), encoding="utf-8")
    schema = _xml.load_trusted_schema(tmp_path / "a.xsd")
    assert schema.validate(_xml.parse(b'<a xmlns="urn:test:a"><b xmlns="urn:test:b">x</b></a>'))
    assert not schema.validate(_xml.parse(b'<a xmlns="urn:test:a"><c/></a>'))


def test_http_import_is_not_fetched(tmp_path: pathlib.Path, http_hits: tuple[str, list[str]]) -> None:
    base, hits = http_hits
    (tmp_path / "a.xsd").write_text(a_xsd(f"{base}/b.xsd"), encoding="utf-8")
    with pytest.raises(ParseError, match=r"invalid XML Schema a\.xsd"):
        _xml.load_trusted_schema(tmp_path / "a.xsd")
    assert hits == []


def test_schema_with_doctype_is_rejected(tmp_path: pathlib.Path) -> None:
    (tmp_path / "a.xsd").write_text("<!DOCTYPE xs:schema>" + B_XSD, encoding="utf-8")
    with pytest.raises(ParseError, match="DOCTYPE"):
        _xml.load_trusted_schema(tmp_path / "a.xsd")


def test_malformed_schema_raises_parse_error(tmp_path: pathlib.Path) -> None:
    (tmp_path / "a.xsd").write_text("<xs:schema", encoding="utf-8")
    with pytest.raises(ParseError, match="malformed XML") as info:
        _xml.load_trusted_schema(tmp_path / "a.xsd")
    assert info.value.location is not None


def test_missing_schema_raises_os_error(tmp_path: pathlib.Path) -> None:
    with pytest.raises(OSError, match="missing"):
        _xml.load_trusted_schema(tmp_path / "missing.xsd")


# --- parse() is total over bytes: an element or ParseError, nothing else -------------------------

SEED = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"'
    b' xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
    b'<!-- c --><cbc:ID schemeID="0088">1</cbc:ID><cbc:Note>a &amp; b &#233; <![CDATA[<x>]]></cbc:Note></Invoice>'
)
TOKENS = [b"<!DOCTYPE r>", b'<!ENTITY e SYSTEM "file:///x">', b"&e;", b"&", b"<", b"]]>", b"\x00", b"\xff\xfe", b"\xc3"]


@st.composite
def mutated_seed(draw: st.DrawFn) -> bytes:
    """The seed document with a few random insertions, deletions and replacements."""
    data = bytearray(SEED)
    for _ in range(draw(st.integers(min_value=1, max_value=6))):
        index = draw(st.integers(min_value=0, max_value=len(data)))
        chunk = draw(st.one_of(st.sampled_from(TOKENS), st.binary(min_size=1, max_size=8)))
        operation = draw(st.sampled_from(["insert", "delete", "replace"]))
        if operation == "insert":
            data[index:index] = chunk
        elif operation == "delete":
            del data[index : index + len(chunk)]
        else:
            data[index : index + len(chunk)] = chunk
    return bytes(data)


@given(st.one_of(st.binary(), mutated_seed()))
def test_parse_returns_element_or_raises_parse_error(data: bytes) -> None:
    try:
        root = _xml.parse(data)
    except ParseError:
        return
    assert isinstance(root, etree._Element)
