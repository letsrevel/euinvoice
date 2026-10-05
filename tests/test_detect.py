"""Tests for :func:`euinvoice.detect.detect` on small synthetic documents."""

import dataclasses

import pytest

from euinvoice import _xml, profiles
from euinvoice.detect import Detection, detect
from euinvoice.errors import ParseError, UnsupportedDocumentError

CORE = "urn:cen.eu:en16931:2017"
PEPPOL = "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"


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
        syntax="ubl", root="Invoice", specification_identifier=CORE, profile=profiles.EN16931
    )


def test_a_ubl_credit_note_is_told_apart_by_its_root() -> None:
    detection = detect(ubl("CreditNote", namespace=_xml.UBL_CREDIT_NOTE))
    assert (detection.syntax, detection.root, detection.profile) == ("ubl", "CreditNote", profiles.EN16931)


def test_a_cii_invoice_with_the_core_bt24_resolves_to_en16931() -> None:
    assert detect(cii(CORE)) == Detection(
        syntax="cii", root="CrossIndustryInvoice", specification_identifier=CORE, profile=profiles.EN16931
    )


def test_bt24_whitespace_is_normalized_like_the_official_rules() -> None:
    # BR-01 and PEPPOL-EN16931-R004 read BT-24 through normalize-space().
    detection = detect(ubl(bt24=f"\n   {CORE}  \n"))
    assert detection.specification_identifier == CORE
    assert detection.profile is profiles.EN16931


@pytest.mark.parametrize(
    "data", [ubl(bt24=PEPPOL), cii(PEPPOL), cii("urn:ferd:CrossIndustryDocument:invoice:1p0:comfort")]
)
def test_a_well_formed_invoice_with_an_unregistered_bt24_is_classified_without_a_profile(data: bytes) -> None:
    detection = detect(data)
    assert detection.profile is None
    assert detection.specification_identifier in {PEPPOL, "urn:ferd:CrossIndustryDocument:invoice:1p0:comfort"}


def test_a_cius_id_never_falls_back_to_the_core_profile() -> None:
    assert detect(ubl(bt24=CORE + "#compliant#urn:example.com:cius")).profile is None


def test_detection_is_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        detect(ubl()).syntax = "cii"  # type: ignore[misc]  # asserting the frozen dataclass rejects this


@pytest.mark.parametrize("bt24", [None, "", "   "])
def test_a_ubl_document_without_bt24_is_rejected(bt24: str | None) -> None:
    with pytest.raises(UnsupportedDocumentError, match=r"BT-24.*BR-01"):
        detect(ubl(bt24=bt24))


def test_a_cii_document_without_bt24_is_rejected() -> None:
    with pytest.raises(UnsupportedDocumentError, match=r"BT-24.*BR-01"):
        detect(cii())


def test_a_cii_document_with_two_bt24_values_is_rejected() -> None:
    with pytest.raises(UnsupportedDocumentError, match="CII-SR-009"):
        detect(cii(CORE, PEPPOL))


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


def test_a_ubl_document_with_two_bt24_values_is_rejected() -> None:
    data = ubl().replace(b"<cbc:ID>", f"<cbc:CustomizationID>{PEPPOL}</cbc:CustomizationID><cbc:ID>".encode())
    with pytest.raises(UnsupportedDocumentError, match=r"UBL 2\.1 XSD"):
        detect(data)
