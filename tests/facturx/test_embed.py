"""Tests for ``facturx.embed`` (#23): the CII XML into a PDF/A-3, with the file spec and XMP of plan §5.

The expected values are the ones every Factur-X PDF of the pinned ZUGFeRD corpus carries; the evidence is cited in
``src/euinvoice/facturx/_embed.py`` and ``src/euinvoice/facturx/xmp.py``. PDF/A-3B validity of the output is
checked by veraPDF in ``tests/conformance/test_facturx_verapdf.py``.
"""

import datetime
import importlib
import io
import sys
import typing as t
from collections.abc import Callable

import pypdf
import pytest
from lxml import etree
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject

from _invoices import minimal_invoice
from _pdfa import PDFA_ID, PRODUCER, pdf, xmp
from _xrechnung_cases import xrechnung_invoice
from euinvoice import _xml, facturx, profiles
from euinvoice.detect import detect
from euinvoice.errors import ParseError, PdfError, UnsupportedDocumentError
from euinvoice.model import ProcessControl
from euinvoice.profiles import Profile
from euinvoice.syntax import Syntax, cii, ubl

_PDFAEXT = "http://www.aiim.org/pdfa/ns/extension/"
_PDFASCHEMA = "http://www.aiim.org/pdfa/ns/schema#"
_PDFAPROP = "http://www.aiim.org/pdfa/ns/property#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

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


def _catalog(data: bytes) -> pypdf.generic.DictionaryObject:
    return t.cast(pypdf.generic.DictionaryObject, pypdf.PdfReader(io.BytesIO(data)).trailer["/Root"])


def _filespecs(data: bytes) -> dict[str, pypdf.generic.DictionaryObject]:
    """The catalog's ``/AF`` file specifications by ``/F``."""
    af = t.cast(pypdf.generic.ArrayObject, _catalog(data)["/AF"])
    specs = (t.cast(pypdf.generic.DictionaryObject, ref.get_object()) for ref in af)
    return {str(spec["/F"]): spec for spec in specs}


def _xmp(data: bytes) -> etree._Element:
    stream = t.cast(pypdf.generic.StreamObject, _catalog(data)["/Metadata"].get_object())
    return _xml.parse(stream.get_data())


def _texts(root: etree._Element, namespace: str, name: str) -> list[str]:
    return [element.text or "" for element in root.iter(f"{{{namespace}}}{name}")]


@pytest.mark.parametrize("profile", LEVELS, ids=[p.id for p in LEVELS])
def test_embedded_xml_is_byte_identical_under_the_level_file_name(profile: Profile) -> None:
    xml = _xml_for(profile)

    out = facturx.embed(pdf(), xml, profile=profile)

    assert pypdf.PdfReader(io.BytesIO(out)).attachments == {profile.facturx_filename: [xml]}


@pytest.mark.parametrize("profile", LEVELS, ids=[p.id for p in LEVELS])
def test_file_spec_carries_af_relationship_mime_type_and_dates(profile: Profile) -> None:
    before = datetime.datetime.now(datetime.UTC).replace(microsecond=0)

    out = facturx.embed(pdf(), _xml_for(profile), profile=profile)

    name = t.cast(str, profile.facturx_filename)
    spec = _filespecs(out)[name]
    assert str(spec["/Type"]) == "/Filespec"
    assert str(spec["/F"]) == str(spec["/UF"]) == str(spec["/Desc"]) == name
    assert str(spec["/AFRelationship"]) == ("/Source" if profile is profiles.FACTURX_XRECHNUNG else "/Data")
    ef = t.cast(pypdf.generic.DictionaryObject, spec["/EF"])
    stream = t.cast(pypdf.generic.StreamObject, ef["/F"].get_object())
    params = t.cast(pypdf.generic.DictionaryObject, stream["/Params"])
    assert str(stream["/Type"]) == "/EmbeddedFile"
    assert str(stream["/Subtype"]) == "/text/xml"
    assert t.cast(int, params["/Size"]) == len(stream.get_data())
    embedded = next(iter(pypdf.PdfReader(io.BytesIO(out)).attachment_list)).modification_date
    assert embedded is not None
    assert embedded >= before


@pytest.mark.parametrize("relationship", ["Data", "Source", "Alternative"])
def test_relationship_override(relationship: facturx.Relationship) -> None:
    out = facturx.embed(
        pdf(), _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931, relationship=relationship
    )

    assert str(_filespecs(out)["factur-x.xml"]["/AFRelationship"]) == f"/{relationship}"


def test_unknown_relationship_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"'Supplement'.*'Data', 'Source', 'Alternative'"):
        facturx.embed(
            pdf(),
            _xml_for(profiles.FACTURX_EN16931),
            profile=profiles.FACTURX_EN16931,
            relationship=t.cast(facturx.Relationship, "Supplement"),
        )


@pytest.mark.parametrize(
    ("profile", "version"),
    [(p, "3.0" if p is profiles.FACTURX_XRECHNUNG else "1.0") for p in LEVELS],
    ids=[p.id for p in LEVELS],
)
def test_xmp_declares_the_factur_x_properties(profile: Profile, version: str) -> None:
    out = facturx.embed(pdf(), _xml_for(profile), profile=profile)

    root = _xmp(out)
    fx = _xml.FACTURX_XMP
    assert _texts(root, fx, "DocumentType") == ["INVOICE"]
    assert _texts(root, fx, "DocumentFileName") == [profile.facturx_filename]
    assert _texts(root, fx, "Version") == [version]
    assert _texts(root, fx, "ConformanceLevel") == [profile.facturx_conformance_level]
    # Everything about one resource: every rdf:Description shares the input's rdf:about.
    assert {d.get(f"{{{_RDF}}}about") for d in root.iter(f"{{{_RDF}}}Description")} == {""}


def test_xmp_declares_the_extension_schema() -> None:
    out = facturx.embed(pdf(), _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931)

    root = _xmp(out)
    assert len(list(root.iter(f"{{{_PDFAEXT}}}schemas"))) == 1
    assert _texts(root, _PDFASCHEMA, "schema") == ["Factur-X PDFA Extension Schema"]
    assert _texts(root, _PDFASCHEMA, "namespaceURI") == [_xml.FACTURX_XMP]
    assert _texts(root, _PDFASCHEMA, "prefix") == ["fx"]
    assert _texts(root, _PDFAPROP, "name") == ["DocumentFileName", "DocumentType", "Version", "ConformanceLevel"]
    assert _texts(root, _PDFAPROP, "valueType") == ["Text"] * 4
    assert _texts(root, _PDFAPROP, "category") == ["external"] * 4
    assert len(_texts(root, _PDFAPROP, "description")) == 4


def test_xmp_keeps_the_input_packet() -> None:
    out = facturx.embed(pdf(), _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931)

    stream = t.cast(pypdf.generic.StreamObject, _catalog(out)["/Metadata"].get_object()).get_data()
    assert stream.startswith(b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>')
    assert stream.rstrip().endswith(b'<?xpacket end="w"?>')
    root = _xmp(out)
    assert _texts(root, "http://www.aiim.org/pdfa/ns/id/", "part") == ["3"]
    assert _texts(root, "http://ns.adobe.com/pdf/1.3/", "Producer") == ["pypdf"]


def test_an_existing_extension_schema_bag_gets_the_factur_x_schema() -> None:
    other = """    <rdf:Description rdf:about="" xmlns:pdfaExtension="http://www.aiim.org/pdfa/ns/extension/"
        xmlns:pdfaSchema="http://www.aiim.org/pdfa/ns/schema#">
      <pdfaExtension:schemas><rdf:Bag><rdf:li rdf:parseType="Resource">
        <pdfaSchema:schema>Other</pdfaSchema:schema>
        <pdfaSchema:namespaceURI>urn:example:other#</pdfaSchema:namespaceURI>
        <pdfaSchema:prefix>other</pdfaSchema:prefix>
      </rdf:li></rdf:Bag></pdfaExtension:schemas>
    </rdf:Description>"""

    out = facturx.embed(
        pdf(xmp(PDFA_ID.format(part=3), other)), _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931
    )

    root = _xmp(out)
    assert len(list(root.iter(f"{{{_PDFAEXT}}}schemas"))) == 1
    assert _texts(root, _PDFASCHEMA, "namespaceURI") == ["urn:example:other#", _xml.FACTURX_XMP]


def test_a_declared_factur_x_extension_schema_is_not_repeated() -> None:
    declared = facturx.embed(pdf(), _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931)
    description = next(
        d for d in _xmp(declared).iter(f"{{{_RDF}}}Description") if d.find(f"{{{_PDFAEXT}}}schemas") is not None
    )
    template = xmp(PDFA_ID.format(part=3), PRODUCER, etree.tostring(description).decode())

    out = facturx.embed(pdf(template), _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931)

    assert _texts(_xmp(out), _PDFASCHEMA, "namespaceURI") == [_xml.FACTURX_XMP]


def test_pdfaid_part_as_attribute_is_accepted() -> None:
    attribute = (
        '<rdf:Description rdf:about="" xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/" pdfaid:part="3"'
        ' pdfaid:conformance="B"/>'
    )

    out = facturx.embed(pdf(xmp(attribute)), _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931)

    assert _texts(_xmp(out), _xml.FACTURX_XMP, "ConformanceLevel") == ["EN 16931"]


def test_other_attachments_and_af_entries_are_kept() -> None:
    out = facturx.embed(
        pdf(attachment="notes.txt"), _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931
    )

    assert set(_filespecs(out)) == {"notes.txt", "factur-x.xml"}
    assert set(pypdf.PdfReader(io.BytesIO(out)).attachments) == {"notes.txt", "factur-x.xml"}


def test_document_info_and_first_file_identifier_are_kept() -> None:
    source = pdf()

    out = facturx.embed(source, _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931)

    before, after = pypdf.PdfReader(io.BytesIO(source)), pypdf.PdfReader(io.BytesIO(out))
    assert after.metadata == before.metadata
    first, second = (t.cast(pypdf.generic.ArrayObject, r.trailer["/ID"]) for r in (before, after))
    assert second[0] == first[0]
    assert second[1] != first[1]  # ISO 32000-1 §14.4: the second identifier changes with the content


def test_invoice_is_written_as_cii_under_the_profile() -> None:
    invoice = xrechnung_invoice()

    out = facturx.embed(pdf(), invoice, profile=profiles.FACTURX_XRECHNUNG)

    xml = pypdf.PdfReader(io.BytesIO(out)).attachments["xrechnung.xml"][0]
    assert xml == cii.write(profiles.FACTURX_XRECHNUNG.prepare(invoice))
    found = detect(xml)
    assert found.syntax is Syntax.CII
    assert found.profile is profiles.XRECHNUNG  # BT-24 alone names XRechnung; the XMP level picks the Factur-X one


def test_extracted_xml_is_detected_and_the_pdf_is_recognised_as_pdf() -> None:
    out = facturx.embed(pdf(), _xml_for(profiles.FACTURX_BASIC), profile=profiles.FACTURX_BASIC)

    xml = pypdf.PdfReader(io.BytesIO(out)).attachments["factur-x.xml"][0]
    assert detect(xml).profile is profiles.FACTURX_BASIC
    with pytest.raises(UnsupportedDocumentError, match=r"facturx\.extract"):
        detect(out)


@pytest.mark.parametrize(
    "profile",
    [profiles.FACTURX_MINIMUM, profiles.FACTURX_BASIC_WL, profiles.FACTURX_BASIC, profiles.FACTURX_EXTENDED],
    ids=lambda p: p.id,
)
def test_invoice_input_only_for_the_generated_levels(profile: Profile) -> None:
    with pytest.raises(UnsupportedDocumentError, match=f"{profile.id}.*plan §1"):
        facturx.embed(pdf(), minimal_invoice(), profile=profile)


@pytest.mark.parametrize("profile", [profiles.EN16931, profiles.PEPPOL, profiles.XRECHNUNG], ids=lambda p: p.id)
def test_non_factur_x_profile_is_rejected(profile: Profile) -> None:
    with pytest.raises(UnsupportedDocumentError, match=f"{profile.id}.*not a Factur-X"):
        facturx.embed(pdf(), _xml_for(profiles.FACTURX_EN16931), profile=profile)


def test_ubl_xml_is_rejected() -> None:
    xml = ubl.write(minimal_invoice())

    with pytest.raises(UnsupportedDocumentError, match="CII"):
        facturx.embed(pdf(), xml, profile=profiles.FACTURX_EN16931)


_XRECHNUNG_2_1 = "urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_2.1"


@pytest.mark.parametrize(
    ("bt24", "profile"),
    [
        (profiles.FACTURX_MINIMUM.specification_identifier, profiles.FACTURX_EXTENDED),
        (profiles.FACTURX_BASIC.specification_identifier, profiles.FACTURX_MINIMUM),
        (_XRECHNUNG_2_1, profiles.FACTURX_XRECHNUNG),
        (profiles.FACTURX_EN16931.specification_identifier, profiles.FACTURX_XRECHNUNG),
    ],
    ids=["minimum-as-extended", "basic-as-minimum", "xrechnung-2.1", "core-as-xrechnung"],
)
def test_xml_bt24_must_be_the_level_bt24(bt24: str, profile: Profile) -> None:
    xml = cii.write(minimal_invoice(process_control=ProcessControl(specification_identifier=bt24)))

    with pytest.raises(UnsupportedDocumentError, match="BT-24") as excinfo:
        facturx.embed(pdf(), xml, profile=profile)
    assert bt24 in str(excinfo.value)
    assert profile.specification_identifier in str(excinfo.value)


def test_signed_pdf_is_rejected() -> None:
    writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(pdf())))
    writer.root_object[NameObject("/AcroForm")] = DictionaryObject({NameObject("/SigFlags"): NumberObject(3)})
    signed = io.BytesIO()
    writer.write(signed)

    with pytest.raises(PdfError, match="the PDF is signed; embed before signing"):
        facturx.embed(signed.getvalue(), _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931)


def test_pdf_with_permissions_dictionary_is_rejected() -> None:
    writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(pdf())))
    writer.root_object[NameObject("/Perms")] = DictionaryObject()
    signed = io.BytesIO()
    writer.write(signed)

    with pytest.raises(PdfError, match="signed"):
        facturx.embed(signed.getvalue(), _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931)


def test_unsigned_acroform_is_accepted() -> None:
    writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(pdf())))
    writer.root_object[NameObject("/AcroForm")] = DictionaryObject({NameObject("/Fields"): ArrayObject()})
    form = io.BytesIO()
    writer.write(form)

    out = facturx.embed(form.getvalue(), _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931)

    assert "factur-x.xml" in pypdf.PdfReader(io.BytesIO(out)).attachments


def test_malformed_xml_is_rejected() -> None:
    with pytest.raises(ParseError):
        facturx.embed(pdf(), b"<rsm:CrossIndustryInvoice", profile=profiles.FACTURX_EN16931)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (lambda: b"not a pdf", "cannot read the PDF"),
        (lambda: pdf(metadata=None), "no XMP metadata"),
        (lambda: pdf(xmp(PDFA_ID.format(part=2), PRODUCER)), r"pdfaid:part \['2'\]"),
        (lambda: pdf(xmp(PRODUCER)), r"pdfaid:part \[\]"),
        (lambda: pdf(xmp(PDFA_ID.format(part=3), PDFA_ID.format(part=2))), r"pdfaid:part \['3', '2'\]"),
        # veraPDF rejects whitespace around the part (6.6.4-2, 6.6.2.3.1-2), so it is not stripped.
        (lambda: pdf(xmp(PDFA_ID.format(part=" 3 "), PRODUCER)), r"pdfaid:part \[' 3 '\]"),
        (lambda: pdf(encrypt=True), "encrypted"),
    ],
    ids=["not-pdf", "no-xmp", "pdfa-2", "no-pdfaid", "two-parts", "padded-part", "encrypted"],
)
def test_non_pdfa3_input_raises_pdf_error(source: Callable[[], bytes], message: str) -> None:
    with pytest.raises(PdfError, match=message):
        facturx.embed(source(), _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931)


def test_malformed_xmp_raises_pdf_error() -> None:
    with pytest.raises(PdfError, match="XMP metadata is not well-formed") as excinfo:
        facturx.embed(pdf(b"<x:xmpmeta"), _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931)
    assert isinstance(excinfo.value.__cause__, ParseError)


def test_doctype_in_xmp_is_rejected() -> None:
    bomb = b'<!DOCTYPE x [<!ENTITY a "a">]><x:xmpmeta xmlns:x="adobe:ns:meta/">&a;</x:xmpmeta>'

    with pytest.raises(PdfError, match="XMP"):
        facturx.embed(pdf(bomb), _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931)


def test_xmp_without_rdf_is_rejected() -> None:
    packet = b'<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/" pdfaid:part="3"/>'

    with pytest.raises(PdfError, match="rdf:RDF"):
        facturx.embed(pdf(packet), _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931)


def test_already_factur_x_pdf_is_rejected() -> None:
    once = facturx.embed(pdf(), _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931)

    with pytest.raises(PdfError, match="already carries Factur-X XMP"):
        facturx.embed(once, _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931)


def test_existing_attachment_with_the_file_name_is_rejected() -> None:
    with pytest.raises(PdfError, match=r"already has an attachment named 'factur-x\.xml'"):
        facturx.embed(
            pdf(attachment="factur-x.xml"), _xml_for(profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931
        )


def test_missing_pypdf_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pypdf", None)
    monkeypatch.delitem(sys.modules, "euinvoice.facturx")
    monkeypatch.delitem(sys.modules, "euinvoice.facturx._embed")

    with pytest.raises(ImportError, match=r"euinvoice\[pdf\]"):
        importlib.import_module("euinvoice.facturx")
