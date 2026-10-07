"""The validate() orchestration: XSD, then the Schematron rule sets of the profile (plan D7, D8, D9, §4).

:func:`validate` runs, in order (rule sets per profile verified on issue #17 against the pinned KoSIT
``scenarios.xml`` and Peppol BIS 3.0.21):

1. the XML Schema of the root namespace (:func:`euinvoice.validation.xsd.validate`);
2. if the XSD step reported nothing ``fatal`` / ``error``, each Schematron rule set the profile names in
   :attr:`~euinvoice.profiles.Profile.rule_sets`, in that order (EN 16931: CEN; Peppol BIS: CEN, Peppol;
   XRechnung: CEN, XRechnung).

A profile whose rule sets include ``"facturx"`` (Factur-X MINIMUM, BASIC WL, BASIC, EXTENDED) raises
``ArtifactsNotAvailableError`` before any step: its official Schematron ships only in the Factur-X package, which
is not pinned (issue #42), and a report without it would claim a verdict no official rule gave. So does an
auto-detected CII document whose BT-24 names such a level without being a profile's (the ZUGFeRD 2.0 ids and the
colon spellings of BASIC / EXTENDED, ``euinvoice.profiles.facturx._UNREGISTERED_LEVEL_IDENTIFIERS``, #98).

XSD short-circuit: a blocking XSD finding stops validation, as KoSIT skips its Schematron steps after an
XSD failure. An XSD ``warning`` does not stop it. KoSIT's ``default-report.xsl`` marks the ``val-xsd``
step invalid on warnings (template ``in:validationResultsXmlSchema``), but its assessment (template
``rep:report`` in mode ``assessment``, lines 312-330) accepts a document whose messages are all below
``error``, so KoSIT also accepts a warning-only XSD result. Here a warning-only report is ``ok``, so
stopping on a warning would report ``ok`` with no Schematron having run. libxml2 practically never emits
schema warnings.

FatturaPA (``Syntax.FATTURAPA``, #121) has no BT-24 and no Schematron, so it is validated by syntax, not by profile:
the FatturaPA 1.2.3 XSD, then (with the same short-circuit) the offline SdI checks of Allegato A 1.9.1, Appendix 1
(:mod:`euinvoice.validation.sdi`, D8 as amended by ADR 0001). No profile supports FatturaPA, so passing one raises
``UnsupportedDocumentError``, as for any profile that does not support the document's syntax. FPA12 (to a public
administration) gets the same checks as FPR12, because Allegato A's Appendix 1 covers both, plus a leading
``information`` finding :data:`FPA12_NOTE_RULE_ID` saying that the checks SdI adds for public-administration
recipients were not run.

Severities are the raw official flags: :attr:`~euinvoice.report.ValidationReport.findings` and ``ok`` never
change. For the XRechnung profiles (CIUS, Extension, CVD) the report also carries ``kosit``, the verdict of the KoSIT
validator: the scenario of the pinned ``scenarios.xml`` that matches the document, the ``customLevel`` overrides it
applies to the findings, and whether KoSIT would accept the document (issue #49; :mod:`euinvoice.validation.kosit`).
"""

import typing as t

from lxml import etree

from euinvoice import _xml, profiles
from euinvoice.detection import Detection, detect_root
from euinvoice.errors import ArtifactsNotAvailableError, UnsupportedDocumentError
from euinvoice.profiles._base import FACTURX_RULE_SET
from euinvoice.profiles.facturx import _UNREGISTERED_LEVEL_IDENTIFIERS
from euinvoice.report import Finding, Severity, ValidationReport
from euinvoice.syntax import Syntax
from euinvoice.validation import kosit, schematron, sdi, xsd

__all__ = ["EUINVOICE_SOURCE", "FPA12_NOTE_RULE_ID", "PROFILE_FALLBACK_RULE_ID", "validate"]

PROFILE_FALLBACK_RULE_ID: t.Final = "EUINVOICE-PROFILE-FALLBACK"
"""Rule id of the ``information`` finding added when an auto-detected profile falls back to EN 16931 core."""
FPA12_NOTE_RULE_ID: t.Final = "EUINVOICE-FATTURAPA-FPA12"
"""Rule id of the ``information`` finding that opens the report of a FatturaPA FPA12 document."""
EUINVOICE_SOURCE: t.Final = "euinvoice"
"""``source`` of findings euinvoice itself adds (not produced by an official rule set)."""

# (Profile.rule_sets name, syntax) → compiled rule set. Lives here, not in profiles: profiles must not
# import euinvoice.validation (dependency direction, plan §4).
_RULE_SETS: t.Final[t.Mapping[tuple[str, str], schematron.RuleSet]] = {
    ("cen", "ubl"): schematron.CEN_UBL,
    ("cen", "cii"): schematron.CEN_CII,
    ("peppol", "ubl"): schematron.PEPPOL_UBL,
    ("peppol", "cii"): schematron.PEPPOL_CII,
    ("xrechnung", "ubl"): schematron.XRECHNUNG_UBL,
    ("xrechnung", "cii"): schematron.XRECHNUNG_CII,
}


def validate(data: bytes, profile: profiles.Profile | None = None) -> ValidationReport:
    """Validate an e-invoice against the official XSD and the Schematron rule sets of its profile.

    Rule failures are findings, never exceptions (D9). Nothing is downloaded (D7): the artifacts must have
    been fetched with ``python -m euinvoice artifacts fetch``.

    Profile resolution when ``profile`` is ``None``: :func:`euinvoice.detection.detect_root` reads BT-24
    (XPath ``normalize-space``) and looks it up exactly with :func:`euinvoice.profiles.get`. If there is
    no single non-empty BT-24, or no registered profile declares it (e.g. a CIUS whose profile is not
    implemented yet), the document is validated against :data:`euinvoice.profiles.EN16931` (XSD and CEN
    rules) and the report starts with an ``information`` finding :data:`PROFILE_FALLBACK_RULE_ID` saying
    that only the core rules ran. The same fallback applies when the BT-24's profile does not support the
    document's syntax. A CII document whose BT-24 is one of
    ``euinvoice.profiles.facturx._UNREGISTERED_LEVEL_IDENTIFIERS`` (a ZUGFeRD 2.0 MINIMUM, BASIC or EXTENDED id,
    or a colon spelling of Factur-X BASIC / EXTENDED) does not fall back: it raises ``ArtifactsNotAvailableError``
    like the Factur-X levels below. The official steps report the BT-24
    problem itself: a missing or blank BT-24 fails BR-01 (and, in CII without the context parameter,
    CII-SR-009 and CII-SR-010); a repeated UBL ``cbc:CustomizationID`` or CII ``ram:ID`` fails the XSD
    (each allows at most one); a repeated CII ``ram:GuidelineSpecifiedDocumentContextParameter`` makes the
    CEN stylesheet fail at run time (``SCHEMATRON-RUNTIME``, fatal) before CII-SR-009 is evaluated.

    An explicit ``profile`` is used as given, even if the document's BT-24 names another one; the
    profile's own rules check BT-24 where they require a value (e.g. XRechnung BR-DE-21).

    A FatturaPA document is validated by syntax (``profile`` must be ``None``): the FatturaPA 1.2.3 XSD, then, if
    it reported nothing ``fatal`` / ``error``, the offline SdI checks (:func:`euinvoice.validation.sdi.check`),
    each an ``error`` finding whose ``rule_id`` is the SdI error code. An FPA12 document's report starts with an
    ``information`` finding :data:`FPA12_NOTE_RULE_ID`.

    Args:
        data: The serialized XML document.
        profile: The profile to validate under; ``None`` auto-detects it from BT-24.

    For the XRECHNUNG, XRECHNUNG_EXTENSION and XRECHNUNG_CVD profiles, ``kosit`` holds the KoSIT validator's
    verdict when a scenario of the pinned KoSIT configuration matches the document and runs the same rule sets
    (:func:`euinvoice.validation.kosit.verdict`); otherwise it is ``None``. It never changes ``findings``
    or ``ok``.

    Returns:
        The XSD findings, then the findings of each rule set in profile order (none if the XSD step had
        a ``fatal`` or ``error`` finding), each tagged with its ``source``; and the KoSIT verdict.

    Raises:
        TypeError: ``data`` is not ``bytes``.
        ParseError: The XML is malformed, has a DOCTYPE or exceeds the parser limits (D10).
        UnsupportedDocumentError: The root element is not a UBL 2.1 Invoice / CreditNote, a CII D16B
            CrossIndustryInvoice or a FatturaPA 1.2 FatturaElettronica, or ``profile`` does not support the
            document's syntax (no profile supports FatturaPA).
        ArtifactsNotAvailableError: An artifact the run needs is not in the cache (names the fetch
            command; XRechnung profiles also read ``xrechnung-validator-configuration``), ``saxonche`` is not
            installed, or the profile (or, auto-detected, the BT-24's level) needs the
            Factur-X / ZUGFeRD Schematron, which is not pinned yet (issue #42).
    """
    root = _xml.parse(data)
    detection = detect_root(root)
    syntax = detection.syntax
    if syntax is Syntax.FATTURAPA and profile is None:
        return _fatturapa(root, detection)
    findings: list[Finding] = []
    if profile is None:
        profile, note = _resolve(detection)
        findings.extend(note)
    elif syntax not in profile.syntaxes:
        hint = (
            "; FatturaPA is validated by syntax, so omit the profile"
            if syntax is Syntax.FATTURAPA
            else f"; it supports {', '.join(sorted(profile.syntaxes))}"
        )
        raise UnsupportedDocumentError(f"profile {profile.id!r} does not support {syntax.upper()} documents{hint}")
    if FACTURX_RULE_SET in profile.rule_sets:
        raise _facturx_not_pinned(f"profile {profile.id!r} is a Factur-X / ZUGFeRD level")
    rule_sets = tuple(_RULE_SETS[name, syntax] for name in profile.rule_sets)
    schema_findings = xsd.validate(root)
    findings.extend(schema_findings)
    if ValidationReport(schema_findings).ok:
        for rule_set in rule_sets:
            findings.extend(schematron.run(rule_set, root))
    return ValidationReport(tuple(findings), kosit=kosit.verdict(root, profile, rule_sets, findings))


def _fatturapa(root: etree._Element, detection: Detection) -> ValidationReport:
    """XSD 1.2.3, then the SdI checks unless the XSD step blocked; an FPA12 document opens with a note.

    FPA12 gets the same checks as FPR12: Allegato A 1.9.1, Appendix 1 lists the checks of the "fattura ordinaria",
    which both formats are (00427 names both), and v1 targets FPR12 (ADR 0001). The note covers what SdI checks
    only for public-administration recipients: the IPA registry checks of the SdI "Elenco dei controlli" v2.0, such as
    00398 (the IPA office code), which are registry checks and not part of Allegato A. (00399, the IPA check on an
    FPR12 sent to a public administration, is a registry check too; see :mod:`euinvoice.validation.sdi`.)
    """
    findings: list[Finding] = []
    if detection.fatturapa_version == "FPA12":
        findings.append(
            Finding(
                rule_id=FPA12_NOTE_RULE_ID,
                severity=Severity.INFORMATION,
                location=None,
                message=(
                    "FPA12 (public administration) document: validated against the FatturaPA 1.2.3 XSD and the "
                    "offline SdI checks of Allegato A 1.9.1, Appendix 1, which apply to FPA12 and FPR12 alike. Checks "
                    "SdI runs only for public-administration recipients (the IPA registry checks of "
                    "the SdI 'Elenco dei controlli', such as 00398 on the IPA office code) were not run."
                ),
                source=EUINVOICE_SOURCE,
            )
        )
    schema_findings = xsd.validate(root)
    findings.extend(schema_findings)
    if ValidationReport(schema_findings).ok:
        findings.extend(sdi.check(root))
    return ValidationReport(tuple(findings))


def _facturx_not_pinned(clause: str) -> ArtifactsNotAvailableError:
    """The refusal for a document only the unpinned Factur-X / ZUGFeRD Schematron can judge (#42).

    ``clause`` is a complete clause naming the profile or BT-24; the reason follows it, and the error carries the
    EN 16931 core profile as its fallback (its message ends with the hint).
    """
    return ArtifactsNotAvailableError(
        f"{clause}; it is validated by the Factur-X / ZUGFeRD Schematron, which is not pinned yet "
        "(https://github.com/letsrevel/euinvoice/issues/42); no fetch command can provide it",
        fallback_profile_id=profiles.EN16931.id,
    )


def _resolve(detection: Detection) -> tuple[profiles.Profile, tuple[Finding, ...]]:
    """The detected profile, or EN 16931 core plus an ``information`` note.

    Raises:
        ArtifactsNotAvailableError: A CII document's BT-24 is one of
            ``euinvoice.profiles.facturx._UNREGISTERED_LEVEL_IDENTIFIERS`` (#98).
    """
    bt24, profile, syntax = detection.specification_identifier, detection.profile, detection.syntax
    if bt24 is None:
        reason = "the document has no single non-empty specification identifier (BT-24)"
    elif profile is None and syntax is Syntax.CII and (level := _UNREGISTERED_LEVEL_IDENTIFIERS.get(bt24)):
        raise _facturx_not_pinned(
            f"specification identifier (BT-24) {bt24!r} names the Factur-X / ZUGFeRD level {level!r}"
        )
    elif profile is None:
        reason = f"specification identifier (BT-24) {bt24!r} is not a registered profile"
    elif syntax not in profile.syntaxes:
        reason = f"profile {profile.id!r} of BT-24 {bt24!r} does not support {syntax.upper()} documents"
    else:
        return profile, ()
    note = Finding(
        rule_id=PROFILE_FALLBACK_RULE_ID,
        severity=Severity.INFORMATION,
        location=None,
        message=(
            f"{reason}; validated against EN 16931 core only (XSD and CEN rules). Rules of any CIUS or "
            "extension the document claims were not checked; pass its profile to validate() to run them."
        ),
        source=EUINVOICE_SOURCE,
    )
    return profiles.EN16931, (note,)
