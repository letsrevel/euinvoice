"""The validate() orchestration: XSD, then the Schematron rule sets of the profile (plan D7, D8, D9, §4).

:func:`validate` runs, in order (rule sets per profile verified on issue #17 against the pinned KoSIT
``scenarios.xml`` and Peppol BIS 3.0.21):

1. the XML Schema of the root namespace (:func:`euinvoice.validate.xsd.validate`);
2. if the XSD step reported nothing ``fatal`` / ``error``, each Schematron rule set the profile names in
   :attr:`~euinvoice.profiles.Profile.rule_sets`, in that order (EN 16931: CEN; Peppol BIS: CEN, Peppol;
   XRechnung: CEN, XRechnung).

A profile whose rule sets include ``"facturx"`` (Factur-X MINIMUM, BASIC WL, BASIC, EXTENDED) raises
``ArtifactsNotAvailableError`` before any step: its official Schematron ships only in the Factur-X package, which
is not pinned (issue #42), and a report without it would claim a verdict no official rule gave.

XSD short-circuit: a blocking XSD finding stops validation, as KoSIT skips its Schematron steps after an
XSD failure. An XSD ``warning`` does not stop it. KoSIT's ``default-report.xsl`` marks the ``val-xsd``
step invalid on warnings (template ``in:validationResultsXmlSchema``), but its assessment (template
``rep:report`` in mode ``assessment``, lines 312-330) accepts a document whose messages are all below
``error``, so KoSIT also accepts a warning-only XSD result. Here a warning-only report is ``ok``, so
stopping on a warning would report ``ok`` with no Schematron having run. libxml2 practically never emits
schema warnings.

Severities are the raw official flags. KoSIT's ``customLevel`` overrides in ``scenarios.xml``
(xrechnung-validator-configuration 2026-08-31) are not applied (open question, issue #49), and they move
the verdict in both directions:

* Downgrades of CEN ``fatal`` rules, so the raw flags reject what KoSIT accepts. To ``information``:
  BR-CL-13 (CVD scenarios); BR-CL-10, BR-CL-11, BR-CL-21, BR-CL-24, BR-CL-25, BR-CL-26 (Extension
  scenarios); BR-CO-16 (Extension UBL). To ``warning``: BR-CL-23 (every XRechnung scenario) and BR-CL-21
  (every non-Extension XRechnung scenario).
* Downgrades of CEN ``warning`` rules to ``information`` (no verdict change): UBL-CR-470, UBL-CR-646
  (Extension UBL); CII-SR-475, CII-SR-476 (XRechnung, Extension and CVD CII).
* Upgrades (``level="error"``) of CEN ``warning`` rules, so the raw flags accept what KoSIT rejects:
  UBL-CR-646 (XRechnung UBL Invoice, CVD UBL Invoice and CreditNote); CII-SR-452, CII-SR-453,
  CII-SR-454, CII-SR-465, CII-SR-466 (XRechnung, Extension and CVD CII).

The hook for applying them is :func:`_rule_findings`, the single place every Schematron finding passes
through.
"""

import typing as t

from lxml import etree

from euinvoice import _xml, profiles
from euinvoice.detect import Detection, detect_root
from euinvoice.errors import ArtifactsNotAvailableError, UnsupportedDocumentError
from euinvoice.profiles._base import FACTURX_RULE_SET
from euinvoice.report import Finding, Severity, ValidationReport
from euinvoice.validate import schematron, xsd

__all__ = ["EUINVOICE_SOURCE", "PROFILE_FALLBACK_RULE_ID", "validate"]

PROFILE_FALLBACK_RULE_ID: t.Final = "EUINVOICE-PROFILE-FALLBACK"
"""Rule id of the ``information`` finding added when an auto-detected profile falls back to EN 16931 core."""
EUINVOICE_SOURCE: t.Final = "euinvoice"
"""``source`` of findings euinvoice itself adds (not produced by an official rule set)."""

# (Profile.rule_sets name, syntax) → compiled rule set. Lives here, not in profiles: profiles must not
# import euinvoice.validate (dependency direction, plan §4).
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

    Profile resolution when ``profile`` is ``None``: :func:`euinvoice.detect.detect_root` reads BT-24
    (XPath ``normalize-space``) and looks it up exactly with :func:`euinvoice.profiles.get`. If there is
    no single non-empty BT-24, or no registered profile declares it (e.g. a CIUS whose profile is not
    implemented yet), the document is validated against :data:`euinvoice.profiles.EN16931` (XSD and CEN
    rules) and the report starts with an ``information`` finding :data:`PROFILE_FALLBACK_RULE_ID` saying
    that only the core rules ran. The same fallback applies when the BT-24's profile does not support the
    document's syntax. The official steps report the BT-24
    problem itself: a missing or blank BT-24 fails BR-01 (and, in CII without the context parameter,
    CII-SR-009 and CII-SR-010); a repeated UBL ``cbc:CustomizationID`` or CII ``ram:ID`` fails the XSD
    (each allows at most one); a repeated CII ``ram:GuidelineSpecifiedDocumentContextParameter`` makes the
    CEN stylesheet fail at run time (``SCHEMATRON-RUNTIME``, fatal) before CII-SR-009 is evaluated.

    An explicit ``profile`` is used as given, even if the document's BT-24 names another one; the
    profile's own rules check BT-24 where they require a value (e.g. XRechnung BR-DE-21).

    Args:
        data: The serialized XML document.
        profile: The profile to validate under; ``None`` auto-detects it from BT-24.

    Returns:
        The XSD findings, then the findings of each rule set in profile order (none if the XSD step had
        a ``fatal`` or ``error`` finding), each tagged with its ``source``.

    Raises:
        TypeError: ``data`` is not ``bytes``.
        ParseError: The XML is malformed, has a DOCTYPE or exceeds the parser limits (D10).
        UnsupportedDocumentError: The root element is not a UBL 2.1 Invoice / CreditNote or a CII D16B
            CrossIndustryInvoice, or ``profile`` does not support the document's syntax.
        ArtifactsNotAvailableError: An artifact the run needs is not in the cache (names the fetch
            command), ``saxonche`` is not installed, or the profile needs the Factur-X Schematron, which is not
            pinned yet (issue #42).
    """
    root = _xml.parse(data)
    detection = detect_root(root)
    syntax = detection.syntax
    findings: list[Finding] = []
    if profile is None:
        profile, note = _resolve(detection)
        findings.extend(note)
    elif syntax not in profile.syntaxes:
        raise UnsupportedDocumentError(
            f"profile {profile.id!r} does not support {syntax.upper()} documents; it supports "
            f"{', '.join(sorted(profile.syntaxes))}"
        )
    if FACTURX_RULE_SET in profile.rule_sets:
        raise ArtifactsNotAvailableError(
            f"profile {profile.id!r} is validated by the Factur-X / ZUGFeRD Schematron, which is not pinned yet "
            "(https://github.com/letsrevel/euinvoice/issues/42); no fetch command can provide it. To run only the "
            "EN 16931 core rules, pass profile=euinvoice.profiles.EN16931"
        )
    schema_findings = xsd.validate(root)
    findings.extend(schema_findings)
    if not ValidationReport(schema_findings).ok:
        return ValidationReport(tuple(findings))
    for name in profile.rule_sets:
        findings.extend(_rule_findings(_RULE_SETS[name, syntax], root))
    return ValidationReport(tuple(findings))


def _rule_findings(rule_set: schematron.RuleSet, root: etree._Element) -> tuple[Finding, ...]:
    """Run one rule set; findings keep their official flags.

    ponytail: this is the hook for KoSIT ``customLevel`` severity overrides (issue #49, needs-human). If
    the maintainer decides to apply them, they belong here, keyed by profile, never as a silent filter.
    """
    return schematron.run(rule_set, root)


def _resolve(detection: Detection) -> tuple[profiles.Profile, tuple[Finding, ...]]:
    """The detected profile, or EN 16931 core plus an ``information`` note."""
    bt24, profile, syntax = detection.specification_identifier, detection.profile, detection.syntax
    if bt24 is None:
        reason = "the document has no single non-empty specification identifier (BT-24)"
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
