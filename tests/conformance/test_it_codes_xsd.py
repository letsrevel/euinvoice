"""The ``Invoice.it`` code enums and facets equal the pinned FatturaPA XSD 1.2.3 (needs ``make artifacts``)."""

import enum
import typing as t

import pytest
from lxml import etree

from euinvoice import _xml
from euinvoice.model import it
from euinvoice.validation import artifacts, xsd

pytestmark = pytest.mark.conformance

_XS: t.Final = "{http://www.w3.org/2001/XMLSchema}"

SIMPLE_TYPES: t.Final[dict[type[enum.StrEnum], str]] = {
    it.TipoDocumento: "TipoDocumentoType",
    it.RegimeFiscale: "RegimeFiscaleType",
    it.SoggettoEmittente: "SoggettoEmittenteType",
    it.Natura: "NaturaType",
    it.TipoCessionePrestazione: "TipoCessionePrestazioneType",
    it.EsigibilitaIVA: "EsigibilitaIVAType",
    it.CondizioniPagamento: "CondizioniPagamentoType",
    it.ModalitaPagamento: "ModalitaPagamentoType",
}


@pytest.fixture(scope="module")
def schema() -> etree._Element:
    path = artifacts.source_dir("fatturapa-xsd") / xsd._FATTURAPA.path
    return _xml.parse(path.read_bytes())


def _restriction(schema: etree._Element, name: str) -> etree._Element:
    (restriction,) = schema.iterfind(f"{_XS}simpleType[@name='{name}']/{_XS}restriction")
    return restriction


@pytest.mark.parametrize(("codes", "type_name"), SIMPLE_TYPES.items(), ids=SIMPLE_TYPES.values())
def test_enum_equals_the_xsd_enumeration(schema: etree._Element, codes: type[enum.StrEnum], type_name: str) -> None:
    values = [e.get("value") for e in _restriction(schema, type_name).iterfind(f"{_XS}enumeration")]
    assert [member.value for member in codes] == values


def test_rate_type_facets(schema: etree._Element) -> None:
    facets = {child.tag.removeprefix(_XS): child.get("value") for child in _restriction(schema, "RateType")}
    assert facets == {"maxInclusive": "100.00", "pattern": r"[0-9]{1,3}\.[0-9]{2}"}


def test_string100_latin_type_facets(schema: etree._Element) -> None:
    restriction = _restriction(schema, "String100LatinType")
    assert restriction.get("base") == "xs:normalizedString"
    facets = {child.tag.removeprefix(_XS): child.get("value") for child in restriction}
    assert facets == {"pattern": r"[\p{IsBasicLatin}\p{IsLatin-1Supplement}]{1,100}"}


@pytest.mark.parametrize(
    ("parent", "element", "type_name"),
    [
        ("DatiAnagraficiCedenteType", "RegimeFiscale", "RegimeFiscaleType"),
        ("FatturaElettronicaHeaderType", "SoggettoEmittente", "SoggettoEmittenteType"),
        ("DatiGeneraliDocumentoType", "TipoDocumento", "TipoDocumentoType"),
        ("DettaglioLineeType", "TipoCessionePrestazione", "TipoCessionePrestazioneType"),
        ("DettaglioLineeType", "Natura", "NaturaType"),
        ("DatiRiepilogoType", "AliquotaIVA", "RateType"),
        ("DatiRiepilogoType", "Natura", "NaturaType"),
        ("DatiRiepilogoType", "EsigibilitaIVA", "EsigibilitaIVAType"),
        ("DatiRiepilogoType", "RiferimentoNormativo", "String100LatinType"),
        ("DatiPagamentoType", "CondizioniPagamento", "CondizioniPagamentoType"),
        ("DettaglioPagamentoType", "ModalitaPagamento", "ModalitaPagamentoType"),
    ],
)
def test_elements_use_these_types(schema: etree._Element, parent: str, element: str, type_name: str) -> None:
    (found,) = schema.iterfind(f"{_XS}complexType[@name='{parent}']/{_XS}sequence/{_XS}element[@name='{element}']")
    assert found.get("type") == type_name
