"""Tests for the hardened XML parser (IMPLEMENTATION_PLAN.md D10)."""

import contextlib
import pathlib

import pytest
from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ParseError


class RecordingResolver(etree.Resolver):
    """Records every external resource libxml2 asks for, and loads none of them."""

    def __init__(self) -> None:
        super().__init__()
        self.requested: list[str] = []

    def resolve(self, system_url: str, public_id: str, context: object) -> None:  # type: ignore[override]
        # lxml-stubs types resolve() as returning _InputDocument; None means "fall through".
        self.requested.append(system_url)


@pytest.fixture
def resolver(monkeypatch: pytest.MonkeyPatch) -> RecordingResolver:
    """Attach a recording resolver to every parser `_xml.parse` creates."""
    recorder = RecordingResolver()
    original = _xml._new_parser

    def instrumented() -> etree.XMLParser:
        parser = original()
        parser.resolvers.add(recorder)
        return parser

    monkeypatch.setattr(_xml, "_new_parser", instrumented)
    return recorder


def permissive_parser(recorder: RecordingResolver) -> etree.XMLParser:
    """An unhardened parser, used to prove the attack payloads really do trigger loads."""
    parser = etree.XMLParser(resolve_entities=True, no_network=False, load_dtd=True)
    parser.resolvers.add(recorder)
    return parser


# --- happy path ---------------------------------------------------------------------------------


def test_parse_returns_root_element() -> None:
    root = _xml.parse(b'<?xml version="1.0" encoding="UTF-8"?><Invoice xmlns="' + _xml.UBL_INVOICE.encode() + b'"/>')
    assert root.tag == f"{{{_xml.UBL_INVOICE}}}Invoice"


def test_parse_keeps_whitespace_and_comments() -> None:
    root = _xml.parse(b"<!-- c --><r>\n  <a> x </a>\n</r>")
    assert root.text == "\n  "
    assert root[0].text == " x "


# --- misuse and malformed input -----------------------------------------------------------------


@pytest.mark.parametrize("data", ["<r/>", None, bytearray(b"<r/>"), pathlib.Path("x.xml")])
def test_non_bytes_input_is_rejected(data: object) -> None:
    with pytest.raises(TypeError, match="bytes"):
        _xml.parse(data)  # type: ignore[arg-type]  # deliberately wrong type


@pytest.mark.parametrize(
    ("data", "location"),
    [(b"", "1:1"), (b"<r>", "1:4"), (b"<r>\n<a></b></r>", "2:8")],
)
def test_malformed_xml_raises_parse_error_with_location(data: bytes, location: str) -> None:
    with pytest.raises(ParseError) as info:
        _xml.parse(data)
    assert info.value.location == location
    assert str(info.value).count(location) == 1
    assert isinstance(info.value.__cause__, etree.XMLSyntaxError)


# --- DOCTYPE / entity attacks -------------------------------------------------------------------

# External-load payloads; "{file}" is a file:// URL of a marker file in tmp_path.
EXTERNAL_LOADS = {
    "xxe-file": '<!DOCTYPE r [<!ENTITY e SYSTEM "{file}">]><r>&e;</r>',
    "xxe-http": '<!DOCTYPE r [<!ENTITY e SYSTEM "http://127.0.0.1:9/xxe">]><r>&e;</r>',
    "dtd-http": '<!DOCTYPE r SYSTEM "http://127.0.0.1:9/evil.dtd"><r/>',
    "dtd-file": '<!DOCTYPE r SYSTEM "{file}"><r/>',
    "param-entity-http": '<!DOCTYPE r [<!ENTITY % p SYSTEM "http://127.0.0.1:9/p.dtd"> %p;]><r/>',
    "param-entity-file": '<!DOCTYPE r [<!ENTITY % p SYSTEM "{file}"> %p;]><r/>',
}
BILLION_LAUGHS = (
    b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
    + b"".join(
        b'<!ENTITY lol%d "%s">' % (i, b"".join(b"&lol%s;" % (str(i - 1).encode() if i > 1 else b"") for _ in range(10)))
        for i in range(1, 10)
    )
    + b"]><lolz>&lol9;</lolz>"
)
QUADRATIC_BLOWUP = b'<!DOCTYPE r [<!ENTITY a "' + b"x" * 50_000 + b'">]><r>' + b"&a;" * 50_000 + b"</r>"
MARKER = "euinvoice-xxe-marker-6b1f"


@pytest.fixture
def marker_url(tmp_path: pathlib.Path) -> str:
    """A file:// URL of a file whose content must never show up in a parse result."""
    path = tmp_path / "secret.txt"
    path.write_text(MARKER, encoding="utf-8")
    return path.as_uri()


def payload(name: str, marker_url: str) -> bytes:
    """Build one of the EXTERNAL_LOADS payloads."""
    return EXTERNAL_LOADS[name].replace("{file}", marker_url).encode()


@pytest.mark.parametrize("name", EXTERNAL_LOADS)
def test_external_loads_raise_parse_error_and_load_nothing(
    name: str, marker_url: str, resolver: RecordingResolver
) -> None:
    with pytest.raises(ParseError, match="DOCTYPE"):
        _xml.parse(payload(name, marker_url))
    assert resolver.requested == []


@pytest.mark.parametrize("data", [BILLION_LAUGHS, QUADRATIC_BLOWUP])
def test_entity_bombs_raise_parse_error(data: bytes, resolver: RecordingResolver) -> None:
    with pytest.raises(ParseError):
        _xml.parse(data)
    assert resolver.requested == []


@pytest.mark.parametrize("data", [b"<!DOCTYPE r><r/>", b'<!DOCTYPE r [<!ENTITY a "x">]><r>&a;</r>'])
def test_doctype_is_rejected(data: bytes) -> None:
    with pytest.raises(ParseError, match="DOCTYPE"):
        _xml.parse(data)


def test_xxe_file_would_leak_without_hardening(marker_url: str) -> None:
    # Control: an unhardened parser really does read the marker file, so the tests above are not vacuous.
    recorder = RecordingResolver()
    root = etree.fromstring(payload("xxe-file", marker_url), permissive_parser(recorder))
    assert MARKER in (root.text or "")
    assert recorder.requested


@pytest.mark.parametrize("name", EXTERNAL_LOADS)
def test_payload_would_load_external_resource_without_hardening(name: str, marker_url: str) -> None:
    # Control: the recorder sees loads when a parser is not hardened, so an empty `requested` list
    # really means "nothing was read or fetched".
    recorder = RecordingResolver()
    # Some loads fail (nothing listens on port 9; the marker is no DTD), but each one is attempted.
    with contextlib.suppress(etree.XMLSyntaxError):
        etree.fromstring(payload(name, marker_url), permissive_parser(recorder))
    assert recorder.requested


@pytest.mark.parametrize("name", EXTERNAL_LOADS)
def test_hardened_parser_alone_loads_nothing(name: str, marker_url: str) -> None:
    # Defence in depth: even before the DOCTYPE check, the D10 parser itself loads nothing.
    recorder = RecordingResolver()
    parser = _xml._new_parser()
    parser.resolvers.add(recorder)
    root = etree.fromstring(payload(name, marker_url), parser)
    assert recorder.requested == []
    assert MARKER not in etree.tostring(root).decode()


@pytest.mark.parametrize("payload", [BILLION_LAUGHS, QUADRATIC_BLOWUP])
def test_hardened_parser_alone_aborts_entity_bombs(payload: bytes) -> None:
    # Defence in depth: libxml2's entity guard stops the bomb before our DOCTYPE check runs.
    with pytest.raises(etree.XMLSyntaxError):
        etree.fromstring(payload, _xml._new_parser())


# --- oversized input (huge_tree=False limits) ---------------------------------------------------


def test_excessive_depth_is_rejected() -> None:
    with pytest.raises(ParseError, match="depth"):
        _xml.parse(b"<a>" * 10_000 + b"</a>" * 10_000)


def test_oversized_text_node_is_rejected() -> None:
    with pytest.raises(ParseError):  # the libxml2 message differs between versions
        _xml.parse(b"<a>" + b"x" * 10_000_001 + b"</a>")


# --- namespace constants (verified against the CEN validation-1.3.16 Schematron <ns> decls) -----


def test_namespace_maps() -> None:
    assert _xml.UBL_NSMAP == {"cac": _xml.UBL_CAC, "cbc": _xml.UBL_CBC, "ext": _xml.UBL_EXT}
    assert _xml.CII_NSMAP == {"rsm": _xml.CII_RSM, "ram": _xml.CII_RAM, "udt": _xml.CII_UDT, "qdt": _xml.CII_QDT}
    assert _xml.UBL_INVOICE == "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
    assert _xml.UBL_CREDIT_NOTE == "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
    assert _xml.CII_RSM == "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
