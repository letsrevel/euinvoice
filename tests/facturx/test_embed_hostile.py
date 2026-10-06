"""``facturx.embed`` on malformed PDFs (#23): only bytes or ``PdfError`` come out, never a raw pypdf exception."""

import functools
import io
import re
import typing as t

import pypdf
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pypdf.generic import NameObject

from _invoices import minimal_invoice
from _pdfa import pdf
from euinvoice import _xml, facturx, profiles
from euinvoice.errors import PdfError
from euinvoice.syntax import cii

_PROFILE: t.Final = profiles.FACTURX_EN16931


@functools.cache
def _source() -> bytes:
    return pdf()


@functools.cache
def _xml_bytes() -> bytes:
    return cii.write(_PROFILE.prepare(minimal_invoice()))


def _rewrite(change: t.Callable[[pypdf.PdfWriter], None]) -> bytes:
    writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(_source())))
    change(writer)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _metadata(data: bytes) -> pypdf.generic.StreamObject:
    catalog = t.cast(pypdf.generic.DictionaryObject, pypdf.PdfReader(io.BytesIO(data)).trailer["/Root"])
    return t.cast(pypdf.generic.StreamObject, catalog["/Metadata"].get_object())


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    mutations=st.lists(st.tuples(st.integers(min_value=0), st.integers(min_value=0, max_value=255)), max_size=8),
    cut=st.one_of(st.none(), st.integers(min_value=0)),
)
def test_mutated_pdf_gives_bytes_or_pdf_error(mutations: list[tuple[int, int]], cut: int | None) -> None:
    data = bytearray(_source())
    for position, value in mutations:
        data[position % len(data)] = value
    if cut is not None:
        del data[cut % len(data) :]

    try:
        out = facturx.embed(bytes(data), _xml_bytes(), profile=_PROFILE)
    except PdfError:
        return
    assert out.startswith(b"%PDF-")


def test_non_stream_metadata_is_rejected() -> None:
    def change(writer: pypdf.PdfWriter) -> None:
        writer.root_object[NameObject("/Metadata")] = NameObject("/NotAStream")

    with pytest.raises(PdfError, match="the catalog /Metadata is not a stream"):
        facturx.embed(_rewrite(change), _xml_bytes(), profile=_PROFILE)


def test_ascii_hex_encoded_xmp_is_read_and_rewritten_unfiltered() -> None:
    def change(writer: pypdf.PdfWriter) -> None:
        stream = t.cast(pypdf.generic.StreamObject, writer.root_object["/Metadata"].get_object())
        stream.set_data(stream.get_data().hex().encode() + b">")
        stream[NameObject("/Filter")] = NameObject("/ASCIIHexDecode")

    source = _rewrite(change)
    assert str(_metadata(source)["/Filter"]) == "/ASCIIHexDecode"

    out = facturx.embed(source, _xml_bytes(), profile=_PROFILE)

    stream = _metadata(out)
    assert "/Filter" not in stream
    assert str(stream["/Type"]) == "/Metadata"
    assert str(stream["/Subtype"]) == "/XML"
    conformance = [e.text for e in _xml.parse(stream.get_data()).iter(f"{{{_xml.FACTURX_XMP}}}ConformanceLevel")]
    assert conformance == ["EN 16931"]


def test_one_element_file_identifier_is_rejected() -> None:
    source = re.sub(rb"/ID \[ (<[0-9a-f]+>) <[0-9a-f]+> \]", rb"/ID [ \1 ]", _source())
    assert source != _source()

    with pytest.raises(PdfError, match="two file identifiers"):
        facturx.embed(source, _xml_bytes(), profile=_PROFILE)


def test_trailer_without_size_is_a_pdf_error() -> None:
    # /Size is required in the trailer (ISO 32000-1 §7.5.5); pypdf's KeyError is mapped, with the cause chained.
    source = re.sub(rb"/Size \d+\s*", b"", _source())
    assert source != _source()

    with pytest.raises(PdfError, match="cannot read the PDF: KeyError") as excinfo:
        facturx.embed(source, _xml_bytes(), profile=_PROFILE)
    assert isinstance(excinfo.value.__cause__, KeyError)


def test_pypdf_failure_is_chained() -> None:
    with pytest.raises(PdfError, match="cannot read the PDF") as excinfo:
        facturx.embed(b"%PDF-1.7\n", _xml_bytes(), profile=_PROFILE)
    assert isinstance(excinfo.value.__cause__, pypdf.errors.PyPdfError)
