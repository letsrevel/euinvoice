"""The pinned FatturaPA 1.2.3 XSD compiles offline and accepts the official examples (needs ``make artifacts``).

``validate()`` does not select FatturaPA yet (#121), so these tests drive ``xsd._load(xsd._FATTURAPA)``.
"""

import pathlib
import re
import socket
import typing as t

import pytest
from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ArtifactsNotAvailableError, ParseError
from euinvoice.validation import artifacts, xsd

pytestmark = pytest.mark.conformance

# Upstream examples that the 1.2.3 XSD rejects, with the first libxml2 message. FPR02 (fatturapa.gov.it; the ZUGFeRD
# corpus copy is content-identical to the current download except for CRLF line endings) has ContattiTrasmittente
# after PECDestinatario, but DatiTrasmissioneType is a sequence that puts ContattiTrasmittente first
# (Schema_VFPR12_v1.2.3.xsd).
KNOWN_INVALID: t.Final = {
    "IT01234567890_FPR02.xml": "Element 'ContattiTrasmittente': This element is not expected.",
}


def official_examples() -> list[pathlib.Path]:
    # The fatturapa.gov.it examples (FPA01..03, FPR01..03) as shipped in the pinned ZUGFeRD corpus.
    try:
        directory = artifacts.source_dir("zugferd-corpus") / "fatturaPA" / "official" / "valid"
    except ArtifactsNotAvailableError:  # collected but deselected by `make test`
        return []
    return sorted(directory.glob("*.xml"))


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail on any Python-level socket use; libxml2 loads are covered by the confining resolver."""

    def refuse(*args: object, **kwargs: object) -> t.NoReturn:
        raise AssertionError("network access while compiling the FatturaPA schema")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.fixture
def schema(no_network: None, monkeypatch: pytest.MonkeyPatch) -> etree._Validator:
    monkeypatch.setattr(xsd, "_cache", {})  # compile now, under no_network, not from an earlier test's cache
    return xsd._load(xsd._FATTURAPA).schema


def test_pinned_xsd_compiles_offline_with_xmldsig_from_the_ubl_copy(schema: etree._Validator) -> None:
    # ds:Signature is a global element of the redirected xmldsig import, so the compiled schema knows its content.
    assert not schema.validate(_xml.parse(b'<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#"/>'))
    messages = [entry.message for entry in t.cast(t.Iterable[t.Any], schema.error_log)]
    assert messages == [
        "Element '{http://www.w3.org/2000/09/xmldsig#}Signature': Missing child element(s). "
        "Expected is ( {http://www.w3.org/2000/09/xmldsig#}SignedInfo )."
    ]


def test_without_the_redirect_the_w3c_import_is_refused_not_fetched(no_network: None) -> None:
    path = artifacts.source_dir("fatturapa-xsd") / xsd._FATTURAPA.path
    with pytest.raises(ParseError, match=re.escape(f"tried to load {xsd.XMLDSIG_W3C_LOCATION!r}")):
        _xml.load_trusted_schema(path)


def test_official_examples_cover_fpa12_and_fpr12() -> None:
    versions = {_xml.parse(p.read_bytes()).get("versione") for p in official_examples()}
    assert versions == {"FPA12", "FPR12"}


@pytest.mark.parametrize("path", official_examples(), ids=lambda p: p.name)
def test_official_example_against_the_pinned_xsd(path: pathlib.Path, schema: etree._Validator) -> None:
    valid = schema.validate(_xml.parse(path.read_bytes()))
    messages = [entry.message for entry in t.cast(t.Iterable[t.Any], schema.error_log)]
    if path.name in KNOWN_INVALID:
        assert not valid
        assert messages[0].startswith(KNOWN_INVALID[path.name]), messages
    else:
        assert valid, messages
