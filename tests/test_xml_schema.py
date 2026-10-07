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
    with pytest.raises(ParseError, match=r"tried to load 'http://127\.0\.0\.1"):
        _xml.load_trusted_schema(tmp_path / "a.xsd")
    assert hits == []


def test_redirected_http_import_loads_the_local_file_without_network(
    tmp_path: pathlib.Path, http_hits: tuple[str, list[str]]
) -> None:
    # FatturaPA 1.2.3 imports xmldsig by an absolute http URL; the redirect target lives in another source.
    base, hits = http_hits
    (tmp_path / "pkg").mkdir()
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "b.xsd").write_text(B_XSD, encoding="utf-8")
    (tmp_path / "pkg" / "a.xsd").write_text(a_xsd(f"{base}/b.xsd"), encoding="utf-8")

    schema = _xml.load_trusted_schema(
        tmp_path / "pkg" / "a.xsd", redirects={f"{base}/b.xsd": tmp_path / "other" / "b.xsd"}
    )

    assert schema.validate(_xml.parse(b'<a xmlns="urn:test:a"><b xmlns="urn:test:b">x</b></a>'))
    assert hits == []


def test_redirect_applies_to_the_exact_url_only(tmp_path: pathlib.Path, http_hits: tuple[str, list[str]]) -> None:
    base, hits = http_hits
    (tmp_path / "b.xsd").write_text(B_XSD, encoding="utf-8")
    (tmp_path / "a.xsd").write_text(a_xsd(f"{base}/b.xsd"), encoding="utf-8")
    with pytest.raises(ParseError, match=r"tried to load 'http://127\.0\.0\.1"):
        _xml.load_trusted_schema(tmp_path / "a.xsd", redirects={f"{base}/B.xsd": tmp_path / "b.xsd"})
    assert hits == []


def test_schema_with_doctype_is_rejected(tmp_path: pathlib.Path) -> None:
    (tmp_path / "a.xsd").write_text("<!DOCTYPE xs:schema>" + B_XSD, encoding="utf-8")
    with pytest.raises(ParseError, match="DOCTYPE"):
        _xml.load_trusted_schema(tmp_path / "a.xsd")


def test_schema_that_does_not_compile_raises_parse_error(tmp_path: pathlib.Path) -> None:
    (tmp_path / "a.xsd").write_text(
        a_xsd("b.xsd").replace('<xs:import namespace="urn:test:b" schemaLocation="b.xsd"/>', "")
    )
    with pytest.raises(ParseError, match=r"invalid XML Schema a\.xsd"):
        _xml.load_trusted_schema(tmp_path / "a.xsd")


def test_malformed_schema_raises_parse_error(tmp_path: pathlib.Path) -> None:
    (tmp_path / "a.xsd").write_text("<xs:schema", encoding="utf-8")
    with pytest.raises(ParseError, match="malformed XML") as info:
        _xml.load_trusted_schema(tmp_path / "a.xsd")
    assert info.value.location is not None


def test_missing_schema_raises_os_error(tmp_path: pathlib.Path) -> None:
    with pytest.raises(OSError, match="missing"):
        _xml.load_trusted_schema(tmp_path / "missing.xsd")


MARKER = "euinvoice-schema-marker-3c9a"


@pytest.fixture
def package(tmp_path: pathlib.Path) -> pathlib.Path:
    """A schema package: ``pkg/main/`` (root schemas), ``pkg/common/b.xsd``, and a marker file outside ``pkg``."""
    (tmp_path / "pkg" / "main").mkdir(parents=True)
    (tmp_path / "pkg" / "common").mkdir()
    (tmp_path / "pkg" / "common" / "b.xsd").write_text(B_XSD, encoding="utf-8")
    (tmp_path / "outside.xsd").write_text(B_XSD, encoding="utf-8")
    (tmp_path / "marker.txt").write_text(MARKER, encoding="utf-8")
    return tmp_path / "pkg"


@pytest.mark.parametrize("location", ["../outside.xsd", "{abs}"])
def test_import_outside_root_is_refused(tmp_path: pathlib.Path, location: str) -> None:
    (tmp_path / "outside.xsd").write_text(B_XSD, encoding="utf-8")
    (tmp_path / "sub").mkdir()
    root = tmp_path / "sub" / "a.xsd"
    root.write_text(a_xsd(location.replace("{abs}", (tmp_path / "outside.xsd").as_uri())), encoding="utf-8")
    with pytest.raises(ParseError, match=r"outside\.xsd"):
        _xml.load_trusted_schema(root)


def test_sibling_import_inside_explicit_root_is_followed(package: pathlib.Path) -> None:
    # UBL 2.1 layout: maindoc/*.xsd imports ../common/*.xsd.
    main = package / "main" / "a.xsd"
    main.write_text(a_xsd("../common/b.xsd"), encoding="utf-8")
    schema = _xml.load_trusted_schema(main, root=package)
    assert schema.validate(_xml.parse(b'<a xmlns="urn:test:a"><b xmlns="urn:test:b">x</b></a>'))
    with pytest.raises(ParseError, match=r"b\.xsd"):
        _xml.load_trusted_schema(main)  # default root is main/, so ../common is outside


def test_path_outside_root_is_misuse(package: pathlib.Path) -> None:
    with pytest.raises(ValueError, match="not inside"):
        _xml.load_trusted_schema(package.parent / "outside.xsd", root=package)


@pytest.fixture
def loaded(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every URL the confining resolver lets libxml2 load."""
    urls: list[str] = []

    class Recording(_xml._ConfiningResolver):
        def resolve(self, system_url: str, public_id: str, context: object) -> t.Any:  # type: ignore[override]  # lxml-stubs omit `context`
            result = super().resolve(system_url, public_id, context)
            urls.append(system_url)
            return result

    monkeypatch.setattr(_xml, "_ConfiningResolver", Recording)
    return urls


def write_import_with_doctype(package: pathlib.Path, doctype: str) -> pathlib.Path:
    """Make ``common/b.xsd`` carry ``doctype`` (using ``&e;`` if it declares it); return the root schema."""
    marker = (package.parent / "marker.txt").as_uri()
    note = "<xs:annotation><xs:documentation>&e;</xs:documentation></xs:annotation>" if "ENTITY" in doctype else ""
    imported = doctype.replace("{marker}", marker) + B_XSD.replace("<xs:element", f"{note}<xs:element", 1)
    (package / "common" / "b.xsd").write_text(imported, encoding="utf-8")
    main = package / "main" / "a.xsd"
    main.write_text(a_xsd("../common/b.xsd"), encoding="utf-8")
    return main


@pytest.mark.parametrize(
    "doctype",
    [
        '<!DOCTYPE xs:schema [<!ENTITY e SYSTEM "{marker}">]>',
        '<!DOCTYPE xs:schema [<!ENTITY e SYSTEM "http://127.0.0.1:9/e">]>',
    ],
)
def test_imported_schema_entity_outside_root_is_refused(package: pathlib.Path, doctype: str, loaded: list[str]) -> None:
    # The imported document is parsed by libxml2 with its own options, which do load external
    # entities; the confining resolver still sees the load and refuses it, so the marker is never read.
    main = write_import_with_doctype(package, doctype)
    with pytest.raises(ParseError, match="tried to load"):
        _xml.load_trusted_schema(main, root=package)
    assert not [url for url in loaded if "marker" in url or url.startswith("http")]


def test_imported_schema_external_dtd_is_not_loaded(package: pathlib.Path, loaded: list[str]) -> None:
    # libxml2 does not load an imported schema's external DTD at all; nothing outside root is touched.
    main = write_import_with_doctype(package, '<!DOCTYPE xs:schema SYSTEM "{marker}">')
    _xml.load_trusted_schema(main, root=package)
    assert loaded
    assert all(pathlib.Path(url).resolve().is_relative_to(package.resolve()) for url in loaded)


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
