"""``facturx.extract`` on malformed PDFs (#24): only an ``Extracted`` or ``PdfError`` comes out, never a raw pypdf
exception."""

import functools

import pypdf
import pytest
from hypothesis import HealthCheck, given, settings

from _invoices import minimal_invoice
from _mutations import CUTS, EDITS, Edit, mutate
from _pdfa import pdf
from euinvoice import facturx, profiles
from euinvoice.errors import PdfError
from euinvoice.syntax import cii


@functools.cache
def _source() -> bytes:
    profile = profiles.FACTURX_EN16931
    return facturx.embed(pdf(), cii.write(profile.prepare(minimal_invoice())), profile=profile)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(edits=EDITS, cut=CUTS)
def test_mutated_pdf_gives_extracted_or_pdf_error(edits: list[Edit], cut: int | None) -> None:
    try:
        found = facturx.extract(mutate(_source(), edits, cut))
    except PdfError:
        return
    assert isinstance(found, facturx.Extracted)


def test_pypdf_failure_is_chained() -> None:
    with pytest.raises(PdfError, match="cannot read the PDF") as excinfo:
        facturx.extract(b"%PDF-1.7\n")
    assert isinstance(excinfo.value.__cause__, pypdf.errors.PyPdfError)


def test_our_own_bug_is_not_reported_as_a_broken_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise AttributeError("bug in our XMP code")

    monkeypatch.setattr("euinvoice.facturx._extract.xmp._values", broken)

    with pytest.raises(AttributeError, match="bug in our XMP code"):
        facturx.extract(_source())
