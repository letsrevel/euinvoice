"""Tests for ``facturx.extract`` (#24): the invoice XML out of a Factur-X / ZUGFeRD PDF.

The selection rules (the XMP ``DocumentFileName`` of the one invoice schema names the attachment, the attested
file name per schema and level) are cited in ``src/euinvoice/facturx/_extract.py``; the pinned corpus is exercised
in ``tests/conformance/test_facturx_extract_corpus.py``.
"""

import functools
import io
import re
import typing as t

import pypdf
import pytest
from pypdf.generic import NameObject

from _invoices import minimal_invoice
from _pdfa import PDFA_ID, PRODUCER, pdf, xmp
from euinvoice import _xml, facturx, profiles
from euinvoice.errors import PdfError
from euinvoice.profiles import Profile
from euinvoice.syntax import cii

LEVELS = [
    profiles.FACTURX_MINIMUM,
    profiles.FACTURX_BASIC_WL,
    profiles.FACTURX_BASIC,
    profiles.FACTURX_EN16931,
    profiles.FACTURX_EXTENDED,
    profiles.FACTURX_XRECHNUNG,
]


def _xml_for(profile: Profile) -> bytes:
    return cii.write(profile.prepare(minimal_invoice()))


@functools.cache
def _core_xml() -> bytes:
    return cii.write(profiles.EN16931.prepare(minimal_invoice()))


def _props(namespace: str, **values: str) -> str:
    """An ``rdf:Description`` with the given properties of ``namespace`` as elements."""
    body = "".join(f"<p:{name}>{value}</p:{name}>" for name, value in values.items())
    return f'    <rdf:Description rdf:about="" xmlns:p="{namespace}">{body}</rdf:Description>'


def _fx(filename: str = "factur-x.xml", level: str = "EN 16931") -> str:
    return _props(
        _xml.FACTURX_XMP, DocumentType="INVOICE", DocumentFileName=filename, Version="1.0", ConformanceLevel=level
    )


def _build(descriptions: t.Sequence[str], files: t.Mapping[str, bytes], *, part: int = 3) -> bytes:
    """A PDF whose XMP holds ``descriptions`` (plus ``pdfaid:part``) and with ``files`` as attachments.

    Nothing else of Factur-X is set (no ``/AF``, no ``/AFRelationship``): extract must not need it.
    """
    writer = pypdf.PdfWriter()
    writer.add_blank_page(595, 842)
    writer.xmp_metadata = xmp(PDFA_ID.format(part=part), PRODUCER, *descriptions)
    for name, content in files.items():
        writer.add_attachment(name, content)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# --- the round trip with embed ------------------------------------------------------------------------------------


@pytest.mark.parametrize("profile", LEVELS, ids=[p.id for p in LEVELS])
def test_extract_returns_what_embed_embedded(profile: Profile) -> None:
    xml = _xml_for(profile)

    found = facturx.extract(facturx.embed(pdf(), xml, profile=profile))

    assert found == facturx.Extracted(
        xml=xml,
        filename=t.cast(str, profile.facturx_filename),
        container="factur-x",
        conformance_level=profile.facturx_conformance_level,
        profile=profile,
    )


def test_other_attachments_do_not_matter() -> None:
    xml = _xml_for(profiles.FACTURX_EN16931)
    out = facturx.embed(pdf(attachment="notes.txt"), xml, profile=profiles.FACTURX_EN16931)

    assert facturx.extract(out).xml == xml


# --- what the container says ---------------------------------------------------------------------------------------


def test_pdfa_is_not_required() -> None:
    # A receiver gets whatever it gets: a PDF/A-2 (or no pdfaid at all) still yields its invoice.
    found = facturx.extract(_build([_fx()], {"factur-x.xml": _core_xml()}, part=2))

    assert found.xml == _core_xml()
    assert found.profile is profiles.FACTURX_EN16931


def test_properties_as_attributes_are_read() -> None:
    description = (
        f'    <rdf:Description rdf:about="" xmlns:fx="{_xml.FACTURX_XMP}" fx:DocumentType="INVOICE" '
        'fx:DocumentFileName="factur-x.xml" fx:Version="1.0" fx:ConformanceLevel="EN 16931"/>'
    )

    found = facturx.extract(_build([description], {"factur-x.xml": _core_xml()}))

    assert (found.filename, found.conformance_level) == ("factur-x.xml", "EN 16931")


def test_level_with_another_bt24_takes_the_profile_from_the_xml() -> None:
    # Level EN 16931 carrying a BASIC invoice: the level's profile does not describe the XML, its BT-24 does.
    xml = _xml_for(profiles.FACTURX_BASIC)

    found = facturx.extract(_build([_fx()], {"factur-x.xml": xml}))

    assert found.conformance_level == "EN 16931"
    assert found.profile is profiles.FACTURX_BASIC


def test_level_with_an_unregistered_bt24_has_no_profile() -> None:
    xml = _core_xml().replace(b"urn:cen.eu:en16931:2017<", b"urn:example.com:unregistered<")
    assert xml != _core_xml()

    assert facturx.extract(_build([_fx()], {"factur-x.xml": xml})).profile is None


def test_ubl_inside_a_factur_x_level_has_the_profile_of_the_xml() -> None:
    # ZUGFeRDv2/fail/FX-With-UBL-REC50304330.pdf: level EN 16931 with a UBL invoice. Factur-X levels are CII only.
    ubl = (
        f'<Invoice xmlns="{_xml.UBL_INVOICE}" xmlns:cbc="{_xml.UBL_CBC}">'
        "<cbc:CustomizationID>urn:cen.eu:en16931:2017</cbc:CustomizationID></Invoice>"
    ).encode()

    found = facturx.extract(_build([_fx()], {"factur-x.xml": ubl}))

    assert found.xml == ubl
    assert found.profile is profiles.EN16931


@pytest.mark.parametrize("xml", [b"<unclosed", b'<?xml version="1.0"?><!DOCTYPE x><x/>', b"<other/>"])
def test_xml_that_is_not_a_supported_invoice_is_returned_without_profile(xml: bytes) -> None:
    # e.g. ZUGFeRDv2/fail/Mustangproject/factur-x-invalid-xml-encoding-attribute.pdf; parse() / validate() report it.
    found = facturx.extract(_build([_fx()], {"factur-x.xml": xml}))

    assert (found.xml, found.profile) == (xml, None)


def test_zugferd_2_0() -> None:
    description = _props(
        _xml.ZUGFERD_2_XMP,
        DocumentType="INVOICE",
        DocumentFileName="zugferd-invoice.xml",
        Version="1.0",
        ConformanceLevel="EN 16931",
    )

    found = facturx.extract(_build([description], {"zugferd-invoice.xml": _core_xml()}))

    # The ZUGFeRD 2.0 level is not a Factur-X profile; the core BT-24 gives the core profile.
    assert found == facturx.Extracted(
        xml=_core_xml(),
        filename="zugferd-invoice.xml",
        container="zugferd-2.0",
        conformance_level="EN 16931",
        profile=profiles.EN16931,
    )


@pytest.mark.parametrize("namespace", [_xml.ZUGFERD_1_XMP, _xml.ZUGFERD_1_RC_XMP])
def test_zugferd_1_0(namespace: str) -> None:
    xml = b'<rsm:CrossIndustryDocument xmlns:rsm="urn:ferd:CrossIndustryDocument:invoice:1p0"/>'
    description = _props(namespace, DocumentType="INVOICE", DocumentFileName="ZUGFeRD-invoice.xml", Version="1.0")

    found = facturx.extract(_build([description], {"ZUGFeRD-invoice.xml": xml}))

    # No ConformanceLevel (ZUGFeRDv1/correct/Mustangproject/MustangGnuaccountingBeispielRE-20170509_505.pdf).
    assert found == facturx.Extracted(
        xml=xml, filename="ZUGFeRD-invoice.xml", container="zugferd-1.0", conformance_level=None, profile=None
    )


def test_xmp_names_the_invoice_among_several_xml_files() -> None:
    # ZUGFeRDv2/fail/MustangRE-20171118_506_ZUGFeRD1and2.pdf: both file names attached, the XMP names factur-x.xml.
    files = {"ZUGFeRD-invoice.xml": b"<old/>", "factur-x.xml": _core_xml()}

    assert facturx.extract(_build([_fx()], files)).xml == _core_xml()


def test_signed_pdf_is_read() -> None:
    writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(_build([_fx()], {"factur-x.xml": _core_xml()}))))
    writer.root_object[NameObject("/Perms")] = pypdf.generic.DictionaryObject()
    out = io.BytesIO()
    writer.write(out)

    assert facturx.extract(out.getvalue()).xml == _core_xml()


# --- refusals ------------------------------------------------------------------------------------------------------


def _metadata_less() -> bytes:
    return pdf(None)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (_metadata_less, "no XMP metadata"),
        (lambda: _build([], {"factur-x.xml": _core_xml()}), "no Factur-X / ZUGFeRD XMP"),
        (
            lambda: _build(
                [_fx(), _props(_xml.ZUGFERD_2_XMP, DocumentFileName="zugferd-invoice.xml", ConformanceLevel="BASIC")],
                {"factur-x.xml": _core_xml(), "zugferd-invoice.xml": _core_xml()},
            ),
            "more than one",
        ),
        (lambda: _build([_fx(), _fx()], {"factur-x.xml": _core_xml()}), "exactly one DocumentFileName"),
        (
            lambda: _build([_props(_xml.FACTURX_XMP, ConformanceLevel="EN 16931")], {"factur-x.xml": _core_xml()}),
            "exactly one DocumentFileName",
        ),
        (lambda: _build([_fx()], {"other.xml": _core_xml()}), "no attachment named 'factur-x.xml'"),
        # ZUGFeRDv2/fail/Mustangproject/wrongFilename.pdf: XMP and attachment agree on a name no level uses.
        (lambda: _build([_fx("factur-y.xml")], {"factur-y.xml": _core_xml()}), "'factur-y.xml'"),
        (lambda: _build([_fx(level="XRECHNUNG")], {"factur-x.xml": _core_xml()}), "'xrechnung.xml'"),
        (lambda: _build([_fx(level="COMFORT")], {"factur-x.xml": _core_xml()}), "unknown Factur-X conformance level"),
        (
            lambda: _build([_props(_xml.FACTURX_XMP, DocumentFileName="factur-x.xml")], {"factur-x.xml": _core_xml()}),
            "exactly one ConformanceLevel",
        ),
        (
            lambda: _build(
                [_props(_xml.ZUGFERD_2_XMP, DocumentFileName="factur-x.xml")], {"factur-x.xml": _core_xml()}
            ),
            "'zugferd-invoice.xml'",
        ),
        (lambda: pdf(_fx().encode()), "not well-formed"),
        (lambda: pdf(xmp(_fx()), encrypt=True), "encrypted"),
    ],
    ids=[
        "no-xmp",
        "no-invoice-schema",
        "two-schemas",
        "two-filenames",
        "no-filename",
        "not-attached",
        "wrong-filename",
        "filename-not-the-levels",
        "unknown-level",
        "factur-x-without-level",
        "zugferd-2-wrong-filename",
        "malformed-xmp",
        "encrypted",
    ],
)
def test_refused(source: t.Callable[[], bytes], message: str) -> None:
    with pytest.raises(PdfError, match=re.escape(message)):
        facturx.extract(source())


def test_doctype_in_xmp_is_refused() -> None:
    packet = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "e">]>' + xmp(_fx())
    with pytest.raises(PdfError, match="not well-formed"):
        facturx.extract(pdf(packet))


def _bomb() -> pypdf.generic.StreamObject:
    """A FlateDecode stream that decodes to one byte over pypdf's default ``zlib_maximum_output_length``."""
    limit = pypdf.Configuration().zlib_maximum_output_length
    plain = pypdf.generic.DecodedStreamObject()
    plain.set_data(bytes(limit + 1))
    return plain.flate_encode()


@pytest.mark.parametrize("duplicate", ["plain", "bomb", "corrupt"])
def test_two_attachments_with_the_invoice_name_are_refused_before_decoding(duplicate: str) -> None:
    # Entries are counted before any is decoded: a duplicate that is a decompression bomb or unreadable gives the
    # "2 attachments" refusal, not pypdf's LimitReachedError (or another decoding failure).
    writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(_build([_fx()], {"factur-x.xml": _core_xml()}))))
    embedded = writer.add_attachment("factur-x.xml", b"<other/>")
    ef = t.cast(pypdf.generic.DictionaryObject, embedded.pdf_object["/EF"])
    if duplicate == "bomb":
        ef[NameObject("/F")] = writer._add_object(_bomb())
    elif duplicate == "corrupt":
        ef[NameObject("/F")] = NameObject("/NotAStream")
    out = io.BytesIO()
    writer.write(out)

    with pytest.raises(PdfError, match=r"2 attachments named 'factur-x\.xml'"):
        facturx.extract(out.getvalue())


def test_the_bomb_alone_hits_the_pypdf_limit() -> None:
    # The control for the test above: decoding the bomb does raise LimitReachedError, mapped to PdfError.
    writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(_build([_fx()], {"factur-x.xml": b"<x/>"}))))
    for embedded in writer.attachment_list:
        t.cast(pypdf.generic.DictionaryObject, embedded.pdf_object["/EF"])[NameObject("/F")] = writer._add_object(
            _bomb()
        )
    out = io.BytesIO()
    writer.write(out)

    with pytest.raises(PdfError, match="LimitReachedError"):
        facturx.extract(out.getvalue())


def test_attachment_matches_by_its_file_spec_name() -> None:
    # pypdf lists an attachment under its name-tree key and its /UF (else /F) name; extract matches either.
    writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(_build([_fx()], {"key.bin": _core_xml()}))))
    for embedded in writer.attachment_list:
        embedded.alternative_name = pypdf.generic.TextStringObject("factur-x.xml")
    out = io.BytesIO()
    writer.write(out)

    assert facturx.extract(out.getvalue()).xml == _core_xml()


def test_non_stream_metadata_is_refused() -> None:
    writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(_build([_fx()], {"factur-x.xml": _core_xml()}))))
    writer.root_object[NameObject("/Metadata")] = NameObject("/NotAStream")
    out = io.BytesIO()
    writer.write(out)

    with pytest.raises(PdfError, match="not a stream"):
        facturx.extract(out.getvalue())


def test_unreadable_invoice_attachment_is_a_pdf_error() -> None:
    writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(_build([_fx()], {"factur-x.xml": _core_xml()}))))
    for embedded in writer.attachment_list:
        ef = t.cast(pypdf.generic.DictionaryObject, embedded.pdf_object["/EF"])
        ef[NameObject("/F")] = NameObject("/NotAStream")
    out = io.BytesIO()
    writer.write(out)

    with pytest.raises(PdfError, match="cannot read the PDF") as excinfo:
        facturx.extract(out.getvalue())
    assert excinfo.value.__cause__ is not None
