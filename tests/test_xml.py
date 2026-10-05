"""Tests for the hardened XML parser (IMPLEMENTATION_PLAN.md D10)."""

import contextlib
import pathlib
import re

import pytest
from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ParseError

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "euinvoice"


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
    original = _xml.new_parser

    def instrumented() -> etree.XMLParser:
        parser = original()
        parser.resolvers.add(recorder)
        return parser

    monkeypatch.setattr(_xml, "new_parser", instrumented)
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

XXE_FILE = b'<!DOCTYPE r [<!ENTITY e SYSTEM "file:///etc/passwd">]><r>&e;</r>'
XXE_HTTP = b'<!DOCTYPE r [<!ENTITY e SYSTEM "http://127.0.0.1:9/xxe">]><r>&e;</r>'
EXTERNAL_DTD = b'<!DOCTYPE r SYSTEM "http://127.0.0.1:9/evil.dtd"><r/>'
EXTERNAL_DTD_FILE = b'<!DOCTYPE r SYSTEM "file:///etc/passwd"><r/>'
PARAMETER_ENTITY = b'<!DOCTYPE r [<!ENTITY % p SYSTEM "http://127.0.0.1:9/p.dtd"> %p;]><r/>'
PARAMETER_ENTITY_FILE = b'<!DOCTYPE r [<!ENTITY % p SYSTEM "file:///etc/passwd"> %p;]><r/>'
BILLION_LAUGHS = (
    b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
    + b"".join(
        b'<!ENTITY lol%d "%s">' % (i, b"".join(b"&lol%s;" % (str(i - 1).encode() if i > 1 else b"") for _ in range(10)))
        for i in range(1, 10)
    )
    + b"]><lolz>&lol9;</lolz>"
)
QUADRATIC_BLOWUP = b'<!DOCTYPE r [<!ENTITY a "' + b"x" * 50_000 + b'">]><r>' + b"&a;" * 50_000 + b"</r>"

EXTERNAL_LOADS = [XXE_FILE, XXE_HTTP, EXTERNAL_DTD, EXTERNAL_DTD_FILE, PARAMETER_ENTITY, PARAMETER_ENTITY_FILE]
ALL_ATTACKS = [*EXTERNAL_LOADS, BILLION_LAUGHS, QUADRATIC_BLOWUP, b"<!DOCTYPE r><r/>"]


@pytest.mark.parametrize("payload", ALL_ATTACKS)
def test_attacks_raise_parse_error_and_load_nothing(payload: bytes, resolver: RecordingResolver) -> None:
    with pytest.raises(ParseError):
        _xml.parse(payload)
    assert resolver.requested == []


@pytest.mark.parametrize("payload", [*EXTERNAL_LOADS, b"<!DOCTYPE r><r/>", b'<!DOCTYPE r [<!ENTITY a "x">]><r>&a;</r>'])
def test_doctype_is_rejected(payload: bytes) -> None:
    with pytest.raises(ParseError, match="DOCTYPE"):
        _xml.parse(payload)


@pytest.mark.parametrize("payload", EXTERNAL_LOADS)
def test_payload_would_load_external_resource_without_hardening(payload: bytes) -> None:
    # Control for the test above: proves the recorder sees loads when a parser is not hardened,
    # so an empty `requested` list really means "nothing was read or fetched".
    recorder = RecordingResolver()
    # The load itself fails (nothing listens on port 9; /etc/passwd is no DTD), but it is attempted.
    with contextlib.suppress(etree.XMLSyntaxError):
        etree.fromstring(payload, permissive_parser(recorder))
    assert recorder.requested


@pytest.mark.parametrize("payload", EXTERNAL_LOADS)
def test_hardened_parser_alone_loads_nothing(payload: bytes) -> None:
    # Defence in depth: even before the DOCTYPE check, the D10 parser itself loads nothing.
    recorder = RecordingResolver()
    parser = _xml.new_parser()
    parser.resolvers.add(recorder)
    root = etree.fromstring(payload, parser)
    assert recorder.requested == []
    assert "root:" not in etree.tostring(root).decode()


@pytest.mark.parametrize("payload", [BILLION_LAUGHS, QUADRATIC_BLOWUP])
def test_hardened_parser_alone_aborts_entity_bombs(payload: bytes) -> None:
    # Defence in depth: libxml2's amplification guard stops the bomb before our DOCTYPE check runs.
    with pytest.raises(etree.XMLSyntaxError, match="amplification"):
        etree.fromstring(payload, _xml.new_parser())


# --- oversized input (huge_tree=False limits) ---------------------------------------------------


def test_excessive_depth_is_rejected() -> None:
    with pytest.raises(ParseError, match="depth"):
        _xml.parse(b"<a>" * 10_000 + b"</a>" * 10_000)


def test_oversized_text_node_is_rejected() -> None:
    with pytest.raises(ParseError, match="limit"):
        _xml.parse(b"<a>" + b"x" * 10_000_001 + b"</a>")


# --- namespace constants (verified against the CEN validation-1.3.16 Schematron <ns> decls) -----


def test_namespace_maps() -> None:
    assert _xml.UBL_NSMAP == {"cac": _xml.UBL_CAC, "cbc": _xml.UBL_CBC}
    assert _xml.CII_NSMAP == {"rsm": _xml.CII_RSM, "ram": _xml.CII_RAM, "udt": _xml.CII_UDT, "qdt": _xml.CII_QDT}
    assert _xml.UBL_INVOICE == "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
    assert _xml.UBL_CREDIT_NOTE == "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
    assert _xml.CII_RSM == "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"


# --- AC: no XML parsing outside _xml.py ---------------------------------------------------------

FORBIDDEN = re.compile(
    r"etree\.fromstring|etree\.parse\b|etree\.XML\b|XMLParser\(|\bfromstring\(|\biterparse\(|XMLPullParser\("
    r"|\bxml\.(?:etree|dom|sax)\b|\bparseString\("
)


def forbidden_parser_uses(source: str) -> list[str]:
    """Return the forbidden parser calls found in `source`."""
    return FORBIDDEN.findall(source)


@pytest.mark.parametrize(
    "snippet",
    [
        "etree.fromstring(b)",
        "etree.parse(f)",
        "etree.XML(b)",
        "lxml.etree.XMLParser(load_dtd=True)",
        "from lxml.etree import fromstring\nfromstring(b)",
        "etree.iterparse(f)",
        "import xml.etree.ElementTree",
        "minidom.parseString(b)",
    ],
)
def test_forbidden_pattern_detects(snippet: str) -> None:
    assert forbidden_parser_uses(snippet)


def test_xml_is_parsed_only_in_xml_module() -> None:
    offenders: dict[str, list[str]] = {}
    for path in SRC.rglob("*.py"):
        if path == SRC / "_xml.py":
            continue
        found = forbidden_parser_uses(path.read_text(encoding="utf-8"))
        if found:
            offenders[str(path.relative_to(SRC))] = found
    assert offenders == {}, "XML must be parsed only via euinvoice._xml (D10)"
