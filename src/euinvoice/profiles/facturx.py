"""Factur-X 1.0 / ZUGFeRD 2.1+ levels: CII D16B invoices for embedding in a PDF/A-3 (plan §1, §5).

Every value below is taken from pinned evidence, because the Factur-X / ZUGFeRD specification package is not
pinned (issue #42): the ZUGFeRD corpus (manifest source ``zugferd-corpus``, paths relative to its root) and
plan §5. The evidence is the BT-24 (``ram:GuidelineSpecifiedDocumentContextParameter/ram:ID``) of the embedded
XML, the embedded file's name, and the XMP ``fx:ConformanceLevel`` / ``fx:DocumentFileName`` of each PDF in
the Factur-X XMP namespace ``urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#``, read with pypdf.

Two levels share their BT-24 with another profile: EN 16931 with the core and XRECHNUNG with XRechnung 3.0.
Only the PDF container tells them apart, by its XMP ``fx:ConformanceLevel`` (:func:`by_conformance_level`), so
the BT-24 registry (:func:`euinvoice.profiles.get`) does not hold them.

Rule sets: EN 16931 runs the CEN rules and XRECHNUNG the CEN and XRechnung rules, which are pinned. MINIMUM,
BASIC WL, BASIC and EXTENDED declare ``"facturx"``: their official per-profile Schematron ships only in the
Factur-X package (plan §3), so ``validate()`` raises ``ArtifactsNotAvailableError`` for them until #42 pins it.
"""

import dataclasses
import typing as t
from collections.abc import Mapping

from euinvoice.errors import UnsupportedDocumentError
from euinvoice.profiles._base import Profile
from euinvoice.profiles.xrechnung import XRECHNUNG
from euinvoice.syntax import Syntax

__all__ = [
    "FACTURX_BASIC",
    "FACTURX_BASIC_WL",
    "FACTURX_EN16931",
    "FACTURX_EXTENDED",
    "FACTURX_MINIMUM",
    "FACTURX_XRECHNUNG",
    "by_conformance_level",
]

_CII: t.Final = frozenset({Syntax.CII})
_FILENAME: t.Final = "factur-x.xml"
"""The embedded file name of every level but XRECHNUNG: XMP ``fx:DocumentFileName`` and attachment name of every
Factur-X-namespace PDF of the corpus except ``XML-Rechnung/FX/XRECHNUNG_*.pdf`` (and the deliberately wrong
``ZUGFeRDv2/fail/Mustangproject/wrongFilename.pdf``); plan §5."""
_FACTURX_RULES: t.Final = ("facturx",)

FACTURX_MINIMUM: t.Final = Profile(
    id="facturx-minimum",
    title="Factur-X / ZUGFeRD MINIMUM",
    # BT-24 and level "MINIMUM": ZUGFeRDv2/correct/FNFE-factur-x-examples/Facture_{DOM,FR,UE}_MINIMUM.pdf and
    # ZUGFeRDv2/correct/symtrax/Beispiele/MINIMUM/zugferd_2p1_MINIMUM_{Buchungshilfe,Rechnung}.pdf; plan §5.
    specification_identifier="urn:factur-x.eu:1p0:minimum",
    syntaxes=_CII,
    rule_sets=_FACTURX_RULES,
    facturx_filename=_FILENAME,
    facturx_conformance_level="MINIMUM",
)
"""Factur-X MINIMUM. Not an EN 16931 invoice (no lines, BG-25), so it cannot be read into the model (#69)."""

FACTURX_BASIC_WL: t.Final = Profile(
    id="facturx-basic-wl",
    title="Factur-X / ZUGFeRD BASIC WL",
    # BT-24 and level "BASIC WL" (with a space): ZUGFeRDv2/correct/FNFE-factur-x-examples/
    # Facture_{DOM,FR,UE}_BASICWL.pdf and ZUGFeRDv2/correct/symtrax/Beispiele/BASIC WL/
    # zugferd_2p1_BASIC-WL_{Buchungshilfe,Einfach}.pdf; plan §5.
    specification_identifier="urn:factur-x.eu:1p0:basicwl",
    syntaxes=_CII,
    rule_sets=_FACTURX_RULES,
    facturx_filename=_FILENAME,
    facturx_conformance_level="BASIC WL",
)
"""Factur-X BASIC WL. Not an EN 16931 invoice (no lines, BG-25), so it cannot be read into the model (#69)."""

FACTURX_BASIC: t.Final = Profile(
    id="facturx-basic",
    title="Factur-X / ZUGFeRD BASIC",
    # BT-24 and level "BASIC": ZUGFeRDv2/correct/symtrax/Beispiele/BASIC/
    # zugferd_2p1_BASIC_{Einfach,Rechnungskorrektur,Taxifahrt}.pdf; plan §5. The FNFE samples write
    # "urn:cen.eu:en16931:2017:compliant:factur-x.eu:1p0:basic" instead (needs-human #69).
    specification_identifier="urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic",
    syntaxes=_CII,
    rule_sets=_FACTURX_RULES,
    facturx_filename=_FILENAME,
    facturx_conformance_level="BASIC",
)
"""Factur-X BASIC, an EN 16931 CIUS (``#compliant#``): reads into the full model."""

FACTURX_EN16931: t.Final = Profile(
    id="facturx-en16931",
    title="Factur-X / ZUGFeRD EN 16931 (COMFORT)",
    # Level "EN 16931" (with a space) with the core BT-24: the 23 PDFs of ZUGFeRDv2/correct/symtrax/Beispiele/
    # EN16931/ other than *_XRechnung*.pdf, the 22 XML-Rechnung/FX/EN16931_*.pdf,
    # ZUGFeRDv2/correct/Mustangproject/MustangGnuaccountingBeispielRE-20201121_508*.pdf; plan §5.
    specification_identifier="urn:cen.eu:en16931:2017",
    syntaxes=_CII,
    rule_sets=("cen",),
    facturx_filename=_FILENAME,
    facturx_conformance_level="EN 16931",
)
"""Factur-X EN 16931 (ZUGFeRD COMFORT). Shares BT-24 with the core; selected by the XMP conformance level."""

# Derived from XRECHNUNG, so BT-24, rule sets (CEN, XRechnung) and the BR-DE pre-flight are XRechnung's own; only
# the CII-only syntax and the Factur-X container fields differ. Level "XRECHNUNG" and file name "xrechnung.xml":
# XML-Rechnung/FX/XRECHNUNG_{Betriebskostenabrechnung,Einfach,Elektron,Reisekostenabrechnung}.pdf (whose XML is
# XRechnung 2.1); plan §5. Pairing the level with the XRechnung 3.0 CIUS id (XR-CIUS-ID, xrechnung-schematron
# 2.6.0 schematron/common.sch:7) is an inference: the corpus has no XRECHNUNG-level PDF of XRechnung 3.0 (#69).
FACTURX_XRECHNUNG: t.Final = dataclasses.replace(
    XRECHNUNG,
    id="facturx-xrechnung",
    title="Factur-X / ZUGFeRD XRECHNUNG",
    syntaxes=_CII,
    facturx_filename="xrechnung.xml",
    facturx_conformance_level="XRECHNUNG",
)
"""Factur-X XRECHNUNG: an XRechnung 3.0 CII invoice, selected by the XMP conformance level."""

FACTURX_EXTENDED: t.Final = Profile(
    id="facturx-extended",
    title="Factur-X / ZUGFeRD EXTENDED",
    # BT-24 and level "EXTENDED": ZUGFeRDv2/correct/symtrax/Beispiele/EXTENDED/zugferd_2p1_EXTENDED_*.pdf (5);
    # plan §5. Content beyond EN 16931 is reported in ParseResult.unmapped.
    specification_identifier="urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended",
    syntaxes=_CII,
    rule_sets=_FACTURX_RULES,
    facturx_filename=_FILENAME,
    facturx_conformance_level="EXTENDED",
)
"""Factur-X EXTENDED, an EN 16931 extension (``#conformant#``): reads into the model plus ``unmapped``."""

LEVELS: t.Final = (
    FACTURX_MINIMUM,
    FACTURX_BASIC_WL,
    FACTURX_BASIC,
    FACTURX_EN16931,
    FACTURX_EXTENDED,
    FACTURX_XRECHNUNG,
)
"""Every Factur-X level, from the smallest to the largest data set; XRECHNUNG last."""
_BY_LEVEL: t.Final[Mapping[str, Profile]] = {p.facturx_conformance_level or "": p for p in LEVELS}


def by_conformance_level(level: str) -> Profile:
    """Return the Factur-X profile whose XMP ``fx:ConformanceLevel`` is ``level``.

    The match is exact (``"EN 16931"`` and ``"BASIC WL"`` carry a space). This is how a Factur-X PDF selects
    :data:`FACTURX_EN16931` and :data:`FACTURX_XRECHNUNG`, whose BT-24 alone names the core / XRechnung.

    Args:
        level: The XMP conformance level, e.g. ``"EN 16931"``.

    Returns:
        The Factur-X profile.

    Raises:
        UnsupportedDocumentError: No Factur-X level is called ``level``; the message lists the known ones.

    Example:
        >>> by_conformance_level("EN 16931").id
        'facturx-en16931'
    """
    try:
        return _BY_LEVEL[level]
    except KeyError:
        known = ", ".join(repr(name) for name in _BY_LEVEL)
        raise UnsupportedDocumentError(f"unknown Factur-X conformance level {level!r}; known: {known}") from None
