"""``facturx.extract`` on every PDF of the pinned ZUGFeRD corpus (``make conformance``, #24).

AC of plan §8 7.2: the corpus PDFs extract. Every PDF of a ``correct`` directory (``ZUGFeRDv1/correct``,
``ZUGFeRDv2/correct``, ``XML-Rechnung``) extracts, with the counts per XMP schema, level and resolved profile pinned
below so a new upstream file is noticed; its XML is the attachment the XMP names, parses with
:func:`euinvoice._xml.parse` and has the expected syntax. The ``fail`` PDFs behave as documented in
``src/euinvoice/facturx/_extract.py``: all extract but ``wrongFilename.pdf``.
"""

import collections
import functools
import io
import pathlib
import typing as t

import pypdf
import pytest

from _pdfa import pdf
from euinvoice import _xml, facturx, parse, parse_detailed
from euinvoice.detect import detect_root
from euinvoice.errors import ParseError, PdfError, UnsupportedDocumentError
from euinvoice.syntax import Syntax
from euinvoice.validate import artifacts

pytestmark = pytest.mark.conformance

type _Key = tuple[str, str | None, str | None]

CORRECT: t.Final[dict[_Key, int]] = {
    # (container, XMP level, profile id); see facturx.Extracted.profile for how the profile is resolved.
    ("factur-x", "MINIMUM", "facturx-minimum"): 5,
    ("factur-x", "BASIC WL", "facturx-basic-wl"): 5,
    ("factur-x", "BASIC", "facturx-basic"): 3,
    # FNFE's colon-form BASIC id (needs-human #69).
    ("factur-x", "BASIC", None): 1,
    ("factur-x", "EN 16931", "facturx-en16931"): 48,
    # XRechnung 1.2 inside the EN 16931 level.
    ("factur-x", "EN 16931", None): 3,
    ("factur-x", "EXTENDED", "facturx-extended"): 5,
    # XRechnung 2.1 inside the XRECHNUNG level; FACTURX_XRECHNUNG is XRechnung 3.0.
    ("factur-x", "XRECHNUNG", None): 4,
    ("zugferd-2.0", "MINIMUM", None): 1,
    ("zugferd-2.0", "BASIC", None): 3,
    # The core BT-24 is the core profile; the ZUGFeRD 2.0 level selects no Factur-X profile.
    ("zugferd-2.0", "EN 16931", "en16931"): 21,
    ("zugferd-2.0", "EXTENDED", None): 5,
    ("zugferd-1.0", "BASIC", None): 6,
    ("zugferd-1.0", "COMFORT", None): 9,
    ("zugferd-1.0", "EXTENDED", None): 5,
    ("zugferd-1.0", None, None): 1,
}
"""The 125 PDFs of the ``correct`` directories."""

REFUSED: t.Final = {
    # XMP and attachment agree on a name no Factur-X level uses.
    "ZUGFeRDv2/fail/Mustangproject/wrongFilename.pdf": "'factur-x.xml', but the XMP names 'factur-y.xml'",
    # Not an e-invoice: no Factur-X / ZUGFeRD XMP.
    "unstructured/RE-E-974-Hetzner_2016-01-19_R0005532486.pdf": "no Factur-X / ZUGFeRD XMP",
}
"""The PDFs :func:`facturx.extract` refuses, with the message."""

FAIL_EXTRACTED: t.Final = 24
"""``fail`` PDFs that extract: they fail upstream for their content, not for how the invoice is attached."""


def _corpus() -> pathlib.Path:
    return artifacts.fetch(["zugferd-corpus"])["zugferd-corpus"]


@functools.cache
def _pdfs() -> dict[str, bytes]:
    root = _corpus()
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.suffix == ".pdf"}


def _kind(name: str) -> str:
    if "/correct/" in name or name.startswith("XML-Rechnung/"):
        return "correct"
    return "fail" if "/fail/" in name else "other"


def test_every_correct_pdf_extracts() -> None:
    found: collections.Counter[_Key] = collections.Counter()
    for name, data in _pdfs().items():
        if _kind(name) != "correct":
            continue
        extracted = facturx.extract(data)
        profile = None if extracted.profile is None else extracted.profile.id
        found[extracted.container, extracted.conformance_level, profile] += 1
        # The XML is the attachment the XMP names, byte for byte, and well-formed (D10 parser).
        assert pypdf.PdfReader(io.BytesIO(data)).attachments[extracted.filename] == [extracted.xml], name
        root = _xml.parse(extracted.xml)
        if extracted.container == "zugferd-1.0":
            # ZUGFeRD 1.0 embeds its own CrossIndustryDocument (or the RC's CBFBUY Invoice), not CII D16B.
            with pytest.raises(UnsupportedDocumentError):
                detect_root(root)
        else:
            assert detect_root(root).syntax is Syntax.CII, name
    assert dict(found) == CORRECT


def test_fail_and_other_pdfs_behave_as_documented() -> None:
    refused: dict[str, str] = {}
    extracted = 0
    for name, data in _pdfs().items():
        if _kind(name) == "correct":
            continue
        try:
            facturx.extract(data)
        except PdfError as exc:
            refused[name] = str(exc)
        else:
            extracted += 1
    assert set(refused) == set(REFUSED)
    for name, message in REFUSED.items():
        assert message in refused[name], name
    assert extracted == FAIL_EXTRACTED


def test_round_trip_of_every_factur_x_pdf_through_embed() -> None:
    # A corpus invoice embedded again comes back byte-identical (the Factur-X levels embed accepts).
    count = 0
    for name, data in _pdfs().items():
        if _kind(name) != "correct":
            continue
        extracted = facturx.extract(data)
        if extracted.container != "factur-x" or extracted.profile is None:
            continue
        again = facturx.extract(facturx.embed(pdf(), extracted.xml, profile=extracted.profile))
        assert (again.xml, again.profile) == (extracted.xml, extracted.profile), name
        count += 1
    assert count == sum(n for (container, _, profile), n in CORRECT.items() if container == "factur-x" and profile)


def test_parse_reads_every_correct_pdf_as_its_extracted_xml() -> None:
    # euinvoice.parse on a PDF is parse_detailed of the XML extract() selects. Factur-X MINIMUM and BASIC WL lack terms
    # EN 16931 requires (BG-25 lines, BR-16; MINIMUM also BG-23 and BT-106), so they raise ParseError (#69).
    # (XMP level, the error parse raised or None) -> PDFs.
    outcomes: collections.Counter[tuple[str | None, type[Exception] | None]] = collections.Counter()
    for name, data in _pdfs().items():
        if _kind(name) != "correct":
            continue
        extracted = facturx.extract(data)
        try:
            expected = parse_detailed(extracted.xml)
        except (ParseError, UnsupportedDocumentError) as exc:
            with pytest.raises(type(exc)):
                parse(data)
            outcomes[extracted.conformance_level, type(exc)] += 1
        else:
            assert parse_detailed(data) == expected, name
            assert parse(data) == expected.invoice, name
            outcomes[extracted.conformance_level, None] += 1
    for level, count in (("MINIMUM", 6), ("BASIC WL", 5)):
        assert {key: n for key, n in outcomes.items() if key[0] == level} == {(level, ParseError): count}
