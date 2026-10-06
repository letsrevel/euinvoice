"""Factur-X levels against the Factur-X PDFs of the pinned ZUGFeRD corpus (``make conformance``, #22).

The corpus PDFs are the only pinned evidence of the Factur-X identifiers (the spec package is not pinned, #42). In
scope: every PDF under ``ZUGFeRDv2/correct`` and ``XML-Rechnung/FX`` whose XMP declares the Factur-X 1.0 / ZUGFeRD
2.1+ schema (:data:`euinvoice._xml.FACTURX_XMP`). Out of scope: ZUGFeRD 1.x and 2.0 PDFs (their own XMP schemas and
BT-24 ids; extract-only, plan §8 7.2) and ``fail`` directories (upstream marks them invalid).

Registry consistency: each PDF's XMP ``fx:ConformanceLevel`` selects a profile whose file name is the XMP
``fx:DocumentFileName`` and an attachment of the PDF, and whose BT-24 is the embedded XML's, except the files in
:data:`OTHER_BT24`. The round trip of every PDF's XML (plan §4 invariant) is in ``test_corpus_harness.py``, with its
documented exceptions (MINIMUM and BASIC WL, needs-human #69) in ``expected_invalid.toml``.
"""

import collections
import typing as t

import pytest
from _corpus import facturx_pdfs

from euinvoice import _xml, profiles
from euinvoice.detect import detect
from euinvoice.report import Finding
from euinvoice.syntax import cii
from euinvoice.validate import artifacts, validate

pytestmark = pytest.mark.conformance

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


def _bt24(data: bytes) -> str | None:
    return detect(data).specification_identifier


def _blocking(findings: t.Iterable[Finding]) -> set[str]:
    return {f.rule_id for f in findings if f.severity in ("fatal", "error")}


def test_counts_per_level() -> None:
    assert collections.Counter(pdf.level for pdf in facturx_pdfs()) == COUNTS


def test_the_xmp_level_selects_the_profile_of_the_embedded_xml() -> None:
    mismatches: dict[str, str] = {}
    for pdf in facturx_pdfs():
        profile = profiles.by_conformance_level(pdf.level)
        # pdf.xmp_filename == profile.facturx_filename is enforced by facturx.extract (test_facturx_extract_corpus.py);
        # the attachment names here are an independent pypdf listing.
        assert profile.facturx_filename in pdf.attachments, pdf.name
        bt24 = _bt24(pdf.xml)
        if bt24 != profile.specification_identifier:
            mismatches[pdf.name] = str(bt24)
        elif profile not in (profiles.FACTURX_EN16931, profiles.FACTURX_XRECHNUNG):
            # A level with a BT-24 of its own is found from the bare XML too.
            assert detect(pdf.xml).profile is profile, pdf.name
    assert mismatches == OTHER_BT24


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
