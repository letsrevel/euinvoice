"""Factur-X levels against the Factur-X PDFs of the pinned ZUGFeRD corpus (``make conformance``, #22).

The corpus PDFs are the only pinned evidence of the Factur-X identifiers (the spec package is not pinned, #42). In
scope: every PDF under ``ZUGFeRDv2/correct`` and ``XML-Rechnung/FX`` whose XMP declares the Factur-X 1.0 / ZUGFeRD
2.1+ schema (:data:`euinvoice._xml.FACTURX_XMP`). Out of scope: ZUGFeRD 1.x and 2.0 PDFs (their own XMP schemas and
BT-24 ids; extract-only, plan §8 7.2) and ``fail`` directories (upstream marks them invalid).

1. Registry consistency: each PDF's XMP ``fx:ConformanceLevel`` selects a profile whose file name is the XMP
   ``fx:DocumentFileName`` and an attachment of the PDF, and whose BT-24 is the embedded XML's, except the files
   in :data:`OTHER_BT24`.
2. Round trip (plan §4 invariant) for the levels that read into the model (BASIC, EN 16931, EXTENDED,
   XRECHNUNG): ``read(write(read(X))) == read(X)`` and the written XML adds no fatal or error finding. MINIMUM and
   BASIC WL fail with the ``ParseError`` of the missing lines (BR-16), see needs-human #69.

The test reads the PDFs with pypdf (the ``[pdf]`` extra) only to get at the XMP and the attachments; every XML
goes through :func:`euinvoice._xml.parse`.
"""

import collections
import dataclasses
import functools
import pathlib
import typing as t

import pypdf
import pytest
from lxml import etree

from euinvoice import _xml, detect, profiles
from euinvoice.errors import ArtifactsNotAvailableError, ParseError
from euinvoice.report import Finding
from euinvoice.syntax import cii
from euinvoice.validate import artifacts, validate

pytestmark = pytest.mark.conformance

_SCOPE: t.Final = ("ZUGFeRDv2/correct", "XML-Rechnung/FX")

COUNTS: t.Final = {"MINIMUM": 5, "BASIC WL": 5, "BASIC": 4, "EN 16931": 51, "EXTENDED": 5, "XRECHNUNG": 4}
"""In-scope PDFs per XMP conformance level, so a new upstream file is noticed."""

_XR_1_2 = "urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_1.2"
_XR_2_1 = "urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_2.1"
_SYMTRAX_EN16931 = "ZUGFeRDv2/correct/symtrax/Beispiele/EN16931/zugferd_2p1_EN16931_{}.pdf"
OTHER_BT24: t.Final[dict[str, str]] = {
    # FNFE writes BASIC's BT-24 with colons instead of '#compliant#urn:' (needs-human #69; its fail/ twins
    # do too). No profile declares it, so detect() gives profile None.
    "ZUGFeRDv2/correct/FNFE-factur-x-examples/Avoir_FR_type381_BASIC.pdf": (
        "urn:cen.eu:en16931:2017:compliant:factur-x.eu:1p0:basic"
    ),
    # Level EN 16931 carrying an XRechnung 1.2 CIUS id: a CIUS of EN 16931 inside the EN 16931 level.
    **{
        _SYMTRAX_EN16931.format(name): _XR_1_2
        for name in (
            "Betriebskostenabrechnung_XRechnung_embedded",
            "Elektron_XRechnung",
            "Reisekostenabrechnung_XRechnung_embedded",
        )
    },
    # Level XRECHNUNG of XRechnung 2.1; FACTURX_XRECHNUNG writes the XRechnung 3.0 id (the pinned XRechnung version).
    **{
        f"XML-Rechnung/FX/XRECHNUNG_{name}.pdf": _XR_2_1
        for name in ("Betriebskostenabrechnung", "Einfach", "Elektron", "Reisekostenabrechnung")
    },
}
"""In-scope PDFs whose BT-24 is not their level's, with the BT-24 they carry."""

_SYMTRAX_EXTENDED = "ZUGFeRDv2/correct/symtrax/Beispiele/EXTENDED/zugferd_2p1_EXTENDED_"
_ELEKTRONISCHE_ADRESSE = ("EN16931_ElektronischeAdresse", "EN16931_RechnungsUebertragung")
EXCLUDED: t.Final[dict[str, str]] = {
    # BT-49 URIID schemeID="9958" is not in the pinned CEF EAS list (BR-CL-25 fatal); as in test_cii_read_conformance.
    **{f"XML-Rechnung/FX/{name}.pdf": "BR-CL-25" for name in _ELEKTRONISCHE_ADRESSE},
    **{
        f"ZUGFeRDv2/correct/symtrax/Beispiele/EN16931/zugferd_2p1_{name}.pdf": "BR-CL-25"
        for name in _ELEKTRONISCHE_ADRESSE
    },
    # EXTENDED with codes outside the CEN code lists the model enforces: allowance reason 'ABK' (BR-CL-19) and EAS
    # '9958' (BR-CL-25). Whether the Factur-X EXTENDED rules allow them cannot be checked until #42 (needs-human #69).
    f"{_SYMTRAX_EXTENDED}Fremdwaehrung.pdf": "BR-CL-19",
    f"{_SYMTRAX_EXTENDED}InnergemeinschLieferungMehrereBestellungen.pdf": "BR-CL-25",
}
"""In-scope PDFs of a readable level the model refuses, with the fatal CEN rule the ParseError and the CEN
Schematron (run on the upstream XML) both name (D8)."""

NOT_IN_MODEL: t.Final = {"MINIMUM": r"BR-16.*issues/69", "BASIC WL": r"BR-16.*issues/69"}
"""Levels without lines (BG-25, BR-16; MINIMUM also lacks BT-106 and BG-23): no EN 16931 invoice, so no model
instance (needs-human #69)."""


@dataclasses.dataclass(frozen=True)
class FacturXPdf:
    name: str
    level: str
    xmp_filename: str
    attachments: dict[str, bytes]

    @property
    def xml(self) -> bytes:
        return self.attachments[self.xmp_filename]


def _fx(xmp: etree._Element, name: str) -> list[str]:
    """``fx:<name>`` of the Factur-X XMP schema, as element text or ``rdf:Description`` attribute."""
    qname = f"{{{_xml.FACTURX_XMP}}}{name}"
    return [element.text or "" for element in xmp.iter(qname)] + [
        str(element.get(qname)) for element in xmp.iter() if element.get(qname) is not None
    ]


def _read_pdf(path: pathlib.Path, name: str) -> FacturXPdf | None:
    reader = pypdf.PdfReader(path)
    root = t.cast(pypdf.generic.DictionaryObject, reader.trailer["/Root"])
    metadata = root.get("/Metadata")
    if metadata is None:
        return None
    xmp = _xml.parse(t.cast(pypdf.generic.StreamObject, metadata.get_object()).get_data())
    levels, filenames = _fx(xmp, "ConformanceLevel"), _fx(xmp, "DocumentFileName")
    if not levels:
        return None
    assert len(levels) == 1, name
    assert len(filenames) == 1, name
    attachments = {key: value[0] for key, value in reader.attachments.items()}
    return FacturXPdf(name, levels[0], filenames[0], attachments)


@functools.cache
def _pdfs() -> tuple[FacturXPdf, ...]:
    corpus = artifacts.fetch(["zugferd-corpus"])["zugferd-corpus"]
    found = []
    for scope in _SCOPE:
        for path in sorted((corpus / scope).rglob("*.pdf")):
            pdf = _read_pdf(path, path.relative_to(corpus).as_posix())
            if pdf is not None:
                found.append(pdf)
    return tuple(found)


def _bt24(data: bytes) -> str | None:
    return detect.detect(data).specification_identifier


def _blocking(findings: t.Iterable[Finding]) -> set[str]:
    return {f.rule_id for f in findings if f.severity in ("fatal", "error")}


def test_counts_per_level() -> None:
    assert collections.Counter(pdf.level for pdf in _pdfs()) == COUNTS


def test_the_xmp_level_selects_the_profile_of_the_embedded_xml() -> None:
    mismatches: dict[str, str] = {}
    for pdf in _pdfs():
        profile = profiles.by_conformance_level(pdf.level)
        assert pdf.xmp_filename == profile.facturx_filename, pdf.name
        assert profile.facturx_filename in pdf.attachments, pdf.name
        bt24 = _bt24(pdf.xml)
        if bt24 != profile.specification_identifier:
            mismatches[pdf.name] = str(bt24)
        elif profile not in (profiles.FACTURX_EN16931, profiles.FACTURX_XRECHNUNG):
            # A level with a BT-24 of its own is found from the bare XML too.
            assert detect.detect(pdf.xml).profile is profile, pdf.name
    assert mismatches == OTHER_BT24


@pytest.mark.parametrize("level", list(COUNTS))
def test_round_trip_per_level(level: str) -> None:
    profile = profiles.by_conformance_level(level)
    failures: list[str] = []
    for pdf in (pdf for pdf in _pdfs() if pdf.level == level):
        if level in NOT_IN_MODEL:
            with pytest.raises(ParseError, match=NOT_IN_MODEL[level]):
                cii.read(_xml.parse(pdf.xml))
            continue
        if pdf.name in EXCLUDED:
            fatal = {f.rule_id for f in validate(pdf.xml, profiles.EN16931).findings if f.severity == "fatal"}
            assert EXCLUDED[pdf.name] in fatal, (pdf.name, sorted(fatal))
            with pytest.raises(ParseError, match=EXCLUDED[pdf.name]):
                cii.read(_xml.parse(pdf.xml))
            continue
        first = cii.read(_xml.parse(pdf.xml))
        print(f"{pdf.name}: {len(first.unmapped)} unmapped", *first.unmapped, sep="\n  ")  # ruff: ignore[print]
        written = cii.write(first.invoice)
        if cii.read(_xml.parse(written)).invoice != first.invoice:
            failures.append(f"{pdf.name}: read(write(read(X))) != read(X)")
        failures.extend(f"{pdf.name}: {rule}" for rule in sorted(_added(profile, pdf.xml, written)))
    assert failures == []


def _added(profile: profiles.Profile, original: bytes, written: bytes) -> set[str]:
    """Fatal or error findings the round trip adds, under the level's runnable rules."""
    if profile is profiles.FACTURX_EN16931:
        return _blocking(validate(written, profile).findings)  # the corpus EN 16931 files are valid: none at all
    if "facturx" in profile.rule_sets:
        with pytest.raises(ArtifactsNotAvailableError, match="issues/42"):
            validate(written, profile)
        profile = profiles.EN16931  # the pinned rules that do run: the CEN core rules
    return _blocking(validate(written, profile).findings) - _blocking(validate(original, profile).findings)


def test_the_round_trip_keeps_extended_content_visible() -> None:
    # EXTENDED content beyond EN 16931 is reported as unmapped, never dropped (plan §1).
    extended = [pdf for pdf in _pdfs() if pdf.level == "EXTENDED" and pdf.name not in EXCLUDED]
    assert extended
    assert all(cii.read(_xml.parse(pdf.xml)).unmapped for pdf in extended)


def test_generation_of_the_xrechnung_level_validates() -> None:
    # Generate the XRECHNUNG level from the KoSIT CII standard instances: prepare + the CII writer (no new writer).
    suite = artifacts.fetch(["xrechnung-testsuite"])["xrechnung-testsuite"] / "instances" / "standard"
    instances = sorted(suite.glob("*_uncefact.xml"))
    assert instances
    failures = {}
    for path in instances:
        invoice = profiles.FACTURX_XRECHNUNG.prepare(cii.read(_xml.parse(path.read_bytes())).invoice)
        written = cii.write(invoice)
        assert _bt24(written) == profiles.FACTURX_XRECHNUNG.specification_identifier
        if blocking := _blocking(validate(written, profiles.FACTURX_XRECHNUNG).findings):
            failures[path.name] = sorted(blocking)
    assert failures == {}
