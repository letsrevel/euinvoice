"""Tests for :func:`euinvoice.detection.detect` on small synthetic documents."""

import dataclasses

import pytest

from euinvoice import _xml, profiles
from euinvoice.detection import Detection, detect, detect_root
from euinvoice.errors import ParseError, UnsupportedDocumentError
from euinvoice.syntax import Syntax

CORE = "urn:cen.eu:en16931:2017"
PEPPOL = "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
XRECHNUNG = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
# A legacy XRechnung id still found in the corpora; no profile declares it.
XRECHNUNG_1_2 = "urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_1.2"


def ubl(root: str = "Invoice", bt24: str | None = CORE, namespace: str = _xml.UBL_INVOICE) -> bytes:
    customization = "" if bt24 is None else f"<cbc:CustomizationID>{bt24}</cbc:CustomizationID>"
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><{root} xmlns="{namespace}" xmlns:cbc="{_xml.UBL_CBC}">'
        f"{customization}<cbc:ID>INV-1</cbc:ID></{root}>"
    ).encode()


def cii(*bt24: str) -> bytes:
    parameters = "".join(
        f"<ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>{value}</ram:ID>"
        "</ram:GuidelineSpecifiedDocumentContextParameter>"
        for value in bt24
    )
    return (
        f'<rsm:CrossIndustryInvoice xmlns:rsm="{_xml.CII_RSM}" xmlns:ram="{_xml.CII_RAM}">'
        f"<rsm:ExchangedDocumentContext>{parameters}</rsm:ExchangedDocumentContext>"
        "<rsm:ExchangedDocument/></rsm:CrossIndustryInvoice>"
    ).encode()


def test_a_ubl_invoice_with_the_core_bt24_resolves_to_en16931() -> None:
    assert detect(ubl()) == Detection(
        syntax=Syntax.UBL, root="Invoice", specification_identifier=CORE, profile=profiles.EN16931
    )


def test_a_ubl_credit_note_is_told_apart_by_its_root() -> None:
    detection = detect(ubl("CreditNote", namespace=_xml.UBL_CREDIT_NOTE))
    assert (detection.syntax, detection.root, detection.profile) == ("ubl", "CreditNote", profiles.EN16931)


def test_a_cii_invoice_with_the_core_bt24_resolves_to_en16931() -> None:
    assert detect(cii(CORE)) == Detection(
        syntax=Syntax.CII, root="CrossIndustryInvoice", specification_identifier=CORE, profile=profiles.EN16931
    )


def test_bt24_whitespace_is_normalized_like_the_official_rules() -> None:
    # BR-01 and PEPPOL-EN16931-R004 read BT-24 through normalize-space().
    detection = detect(ubl(bt24=f"\n   {CORE}  \n"))
    assert detection.specification_identifier == CORE
    assert detection.profile is profiles.EN16931


@pytest.mark.parametrize(
    "data", [ubl(bt24=XRECHNUNG_1_2), cii(XRECHNUNG_1_2), cii("urn:ferd:CrossIndustryDocument:invoice:1p0:comfort")]
)
def test_a_well_formed_invoice_with_an_unregistered_bt24_is_classified_without_a_profile(data: bytes) -> None:
    detection = detect(data)
    assert detection.profile is None
    assert detection.specification_identifier in {XRECHNUNG_1_2, "urn:ferd:CrossIndustryDocument:invoice:1p0:comfort"}


@pytest.mark.parametrize("data", [ubl(bt24=XRECHNUNG), cii(XRECHNUNG)], ids=["ubl", "cii"])
def test_the_xrechnung_bt24_resolves_to_its_profile(data: bytes) -> None:
    assert detect(data).profile is profiles.XRECHNUNG


@pytest.mark.parametrize("data", [ubl(bt24=PEPPOL), cii(PEPPOL)], ids=["ubl", "cii"])
def test_the_peppol_bt24_resolves_to_the_peppol_profile(data: bytes) -> None:
    assert detect(data).profile is profiles.PEPPOL


def test_bt24_normalization_keeps_non_xml_whitespace() -> None:
    # normalize-space() strips only XML whitespace, so a no-break space stays and the match fails.
    detection = detect(ubl(bt24=f"\u00a0{CORE}"))
    assert detection.specification_identifier == f"\u00a0{CORE}"
    assert detection.profile is None


def test_a_cius_id_never_falls_back_to_the_core_profile() -> None:
    assert detect(ubl(bt24=CORE + "#compliant#urn:example.com:cius")).profile is None


def test_detection_is_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        detect(ubl()).syntax = Syntax.CII  # type: ignore[misc]  # asserting the frozen dataclass rejects this


@pytest.mark.parametrize("bt24", [None, "", "   "])
def test_a_ubl_document_without_bt24_is_classified_without_bt24_or_profile(bt24: str | None) -> None:
    # An invalid invoice, not garbage: validate() must still run the official rules (BR-01) on it.
    assert detect(ubl(bt24=bt24)) == Detection(
        syntax=Syntax.UBL, root="Invoice", specification_identifier=None, profile=None
    )


@pytest.mark.parametrize("bt24", [(), ("",), (CORE, PEPPOL), (CORE, CORE)])
def test_a_cii_document_without_exactly_one_bt24_is_classified_without_bt24_or_profile(
    bt24: tuple[str, ...],
) -> None:
    # The CEN rules report these (BR-01, CII-SR-009/010); detection picks no profile.
    assert detect(cii(*bt24)) == Detection(
        syntax=Syntax.CII, root="CrossIndustryInvoice", specification_identifier=None, profile=None
    )


@pytest.mark.parametrize(
    "data",
    [
        b'<testSet xmlns="http://difi.no/xsd/vefa/validator/1.0"/>',
        b"<Invoice><CustomizationID>urn:cen.eu:en16931:2017</CustomizationID></Invoice>",  # no namespace
        f'<CreditNote xmlns="{_xml.UBL_INVOICE}"/>'.encode(),  # root does not match its namespace
        f'<Invoice xmlns="{_xml.UBL_CBC}"/>'.encode(),
    ],
)
def test_an_unknown_root_element_is_rejected(data: bytes) -> None:
    with pytest.raises(UnsupportedDocumentError, match="root element"):
        detect(data)


def test_a_pdf_is_rejected_with_a_pointer_to_facturx_extract() -> None:
    with pytest.raises(UnsupportedDocumentError, match=r"facturx\.extract"):
        detect(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n")


@pytest.mark.parametrize("prefix", [b"\xef\xbb\xbf", b"\n", b"\r\n  ", b"x" * 1018])
def test_a_pdf_header_after_leading_bytes_is_still_sniffed(prefix: bytes) -> None:
    # Readers accept leading bytes before %PDF- within the first 1024 bytes; 1018 + len(b"%PDF-") is 1023.
    with pytest.raises(UnsupportedDocumentError, match=r"facturx\.extract"):
        detect(prefix + b"%PDF-1.7\n")


def test_pdf_magic_inside_xml_text_is_not_a_pdf() -> None:
    # Regression (spec-audit of #56): "%PDF-" in a note within the first 1024 bytes is invoice text.
    data = ubl().replace(b"<cbc:ID>", b"<cbc:Note>%PDF-1.7 attached</cbc:Note><cbc:ID>")
    assert data.find(b"%PDF-") < 1024
    assert detect(data) == Detection(
        syntax=Syntax.UBL, root="Invoice", specification_identifier=CORE, profile=profiles.EN16931
    )


def test_a_pdf_header_beyond_the_first_1024_bytes_is_not_sniffed() -> None:
    with pytest.raises(ParseError):
        detect(b"x" * 1024 + b"%PDF-1.7\n")


@pytest.mark.parametrize("data", [b"", b"not xml at all", b"\x00\x01\x02", b"<Invoice>"])
def test_malformed_input_is_a_parse_error(data: bytes) -> None:
    with pytest.raises(ParseError):
        detect(data)


def test_a_doctype_is_rejected_by_the_hardened_parser() -> None:
    data = b'<?xml version="1.0"?><!DOCTYPE Invoice [<!ENTITY x "y">]>' + ubl().split(b"?>", 1)[1]
    with pytest.raises(ParseError, match="DOCTYPE"):
        detect(data)


def test_non_bytes_input_is_a_type_error() -> None:
    with pytest.raises(TypeError):
        detect(ubl().decode())  # type: ignore[arg-type]  # asserting str input is rejected


def test_a_ubl_document_with_two_bt24_values_is_classified_without_bt24_or_profile() -> None:
    data = ubl().replace(b"<cbc:ID>", f"<cbc:CustomizationID>{CORE}</cbc:CustomizationID><cbc:ID>".encode())
    detection = detect(data)
    assert (detection.specification_identifier, detection.profile) == (None, None)


def test_detect_root_classifies_an_already_parsed_tree() -> None:
    assert detect_root(_xml.parse(cii(CORE))) == detect(cii(CORE))


def test_detect_root_rejects_an_unknown_root() -> None:
    with pytest.raises(UnsupportedDocumentError, match="root element"):
        detect_root(_xml.parse(b"<html/>"))


def fatturapa(attributes: str = ' versione="FPR12"', namespace: str = _xml.FATTURAPA) -> bytes:
    header = "<FatturaElettronicaHeader/>"
    return f'<p:FatturaElettronica xmlns:p="{namespace}"{attributes}>{header}</p:FatturaElettronica>'.encode()


@pytest.mark.parametrize("version", ["FPR12", "FPA12"])
def test_fatturapa_is_detected_by_root_namespace_with_its_versione(version: str) -> None:
    assert detect(fatturapa(f' versione="{version}"')) == Detection(
        syntax=Syntax.FATTURAPA,
        root="FatturaElettronica",
        specification_identifier=None,
        profile=None,
        fatturapa_version=version,
    )


@pytest.mark.parametrize(("attributes", "version"), [("", None), (' versione="FSM10"', "FSM10")])
def test_fatturapa_with_a_missing_or_unknown_versione_is_still_detected_for_the_xsd_to_report(
    attributes: str, version: str | None
) -> None:
    detection = detect(fatturapa(attributes))
    assert (detection.syntax, detection.fatturapa_version) == (Syntax.FATTURAPA, version)


def test_ubl_and_cii_carry_no_fatturapa_version() -> None:
    assert detect(ubl()).fatturapa_version is None
    assert detect(cii(CORE)).fatturapa_version is None


def test_the_simplified_invoice_namespace_is_not_fatturapa() -> None:
    # FSM10 (fattura semplificata) has its own namespace, .../docs/xsd/fatture/v1.0; it is out of scope.
    with pytest.raises(UnsupportedDocumentError, match=r"or a FatturaPA 1\.2 FatturaElettronica"):
        detect(fatturapa(namespace="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.0"))
