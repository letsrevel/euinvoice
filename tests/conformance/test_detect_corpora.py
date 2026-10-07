"""``detect`` against every XML file of the pinned corpora (``make conformance``, plan §8 8.1).

Each corpus is classified file by file, and the result is asserted as counts per
(syntax, root, BT-24, profile id) bucket, so a new upstream file or a changed classification fails the
test. Files that are not invoices are listed explicitly below, with the outcome ``detect`` must give.
"""

import collections
import pathlib
import re
import typing as t

import pytest

from euinvoice import _xml
from euinvoice.detection import detect
from euinvoice.errors import ParseError, UnsupportedDocumentError
from euinvoice.validation import artifacts

pytestmark = pytest.mark.conformance

type Bucket = tuple[str, str, str | None, str | None]

CORE = "urn:cen.eu:en16931:2017"
PEPPOL = "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
XRECHNUNG = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
XRECHNUNG_EXTENSION = XRECHNUNG + "#conformant#urn:xeinkauf.de:kosit:extension:xrechnung_3.0"
XRECHNUNG_CVD = XRECHNUNG + "#compliant#urn:xeinkauf.de:kosit:xrechnung:cvd_0.9"
# Legacy ids still found in the corpora; no profile declares them (issue #26 spec-audit notes).
XRECHNUNG_1_2 = "urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_1.2"
ZUGFERD_1_COMFORT = "urn:ferd:CrossIndustryDocument:invoice:1p0:comfort"
FACTURX_EXTENDED = "urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended"

UBL_INVOICE = ("ubl", "Invoice")
UBL_CREDIT_NOTE = ("ubl", "CreditNote")
CII = ("cii", "CrossIndustryInvoice")
FATTURAPA = ("fatturapa", "FatturaElettronica")

# Profile ids are pinned to the registry of today (EN 16931 core, Peppol BIS, XRechnung and the Factur-X levels
# with a BT-24 of their own); a newly registered profile flips its buckets here.
EXPECTED: t.Final[dict[str, dict[Bucket, int]]] = {
    "cen-ubl": {
        (*UBL_INVOICE, CORE, "en16931"): 14,
        (*UBL_CREDIT_NOTE, CORE, "en16931"): 1,
        (*UBL_INVOICE, PEPPOL, "peppol"): 4,
    },
    "cen-cii": {
        (*CII, CORE, "en16931"): 12,
        (*CII, ZUGFERD_1_COMFORT, None): 3,
    },
    "peppol-bis": {
        (*UBL_INVOICE, PEPPOL, "peppol"): 9,
        (*UBL_CREDIT_NOTE, PEPPOL, "peppol"): 1,
    },
    "xrechnung-testsuite": {
        (*UBL_INVOICE, XRECHNUNG, "xrechnung"): 39,
        (*UBL_INVOICE, XRECHNUNG_EXTENSION, "xrechnung-extension"): 5,
        (*UBL_INVOICE, XRECHNUNG_CVD, "xrechnung-cvd"): 1,
        (*CII, XRECHNUNG, "xrechnung"): 39,
        (*CII, XRECHNUNG_EXTENSION, "xrechnung-extension"): 1,
        (*CII, XRECHNUNG_CVD, "xrechnung-cvd"): 1,
    },
    "zugferd-corpus": {
        (*UBL_INVOICE, PEPPOL, "peppol"): 25,
        (*UBL_INVOICE, XRECHNUNG, "xrechnung"): 5,
        (*UBL_CREDIT_NOTE, CORE, "en16931"): 1,
        (*CII, CORE, "en16931"): 32,
        (*CII, XRECHNUNG, "xrechnung"): 5,
        (*CII, XRECHNUNG_1_2, None): 2,
        (*CII, FACTURX_EXTENDED, "facturx-extended"): 3,
        # Italian FatturaPA 1.2 (#121): fatturaPA/eigor/valid (8, one more is truncated below) and
        # fatturaPA/official/valid (6). No BT-24, no profile.
        (*FATTURAPA, None, None): 14,
    },
}

# Corpus files that are not invoices detect() can classify, keyed by path relative to the scanned directory.
EXCLUDED: t.Final[dict[str, dict[str, type[Exception]]]] = {
    "zugferd-corpus": {
        # FatturaPA truncated upstream (ends inside the FatturaElettronica element): not well-formed XML.
        "fatturaPA/eigor/valid/con-ritenuta-acconto-e-cassa-previdenziale.xml": ParseError,
    },
}

# Where each corpus keeps its XML (relative to the source directory). The Peppol ``rules/unit-*``
# directories hold vefa ``testSet`` files (rule unit tests wrapping invoice fragments, not invoices);
# they are checked separately below.
_DIRECTORIES: t.Final[dict[artifacts.SourceName, str]] = {
    "cen-ubl": "examples",
    "cen-cii": "examples",
    "peppol-bis": "rules/examples",
    "xrechnung-testsuite": ".",
    "zugferd-corpus": ".",
}


def _xml_files(directory: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() == ".xml")


@pytest.mark.parametrize("source", list(_DIRECTORIES))
def test_every_corpus_file_is_classified(source: artifacts.SourceName) -> None:
    directory = artifacts.fetch([source])[source] / _DIRECTORIES[source]
    excluded = EXCLUDED.get(source, {})
    buckets: collections.Counter[Bucket] = collections.Counter()
    rejected: dict[str, type[Exception]] = {}
    for path in _xml_files(directory):
        name = path.relative_to(directory).as_posix()
        if name in excluded:
            with pytest.raises(excluded[name]):
                detect(path.read_bytes())
            rejected[name] = excluded[name]
            continue
        found = detect(path.read_bytes())
        buckets[
            found.syntax, found.root, found.specification_identifier, found.profile.id if found.profile else None
        ] += 1
    assert rejected == excluded
    assert dict(buckets) == EXPECTED[source]


def test_peppol_rule_unit_tests_are_rejected_as_non_invoices() -> None:
    rules = artifacts.fetch(["peppol-bis"])["peppol-bis"] / "rules"
    test_sets = [path for directory in sorted(rules.glob("unit-*")) for path in _xml_files(directory)]
    assert len(test_sets) == 240
    for path in test_sets:
        with pytest.raises(UnsupportedDocumentError, match=re.escape(f"root element '{{{_xml.VEFA}}}testSet'")):
            detect(path.read_bytes())
