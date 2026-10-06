"""The validate() orchestration: XSD, then the Schematron rule sets of the profile (plan D7, D8, D9, §4).

:func:`validate` runs, in order (rule sets per profile verified on issue #17 against the pinned KoSIT
``scenarios.xml`` and Peppol BIS 3.0.21):

1. the XML Schema of the root namespace (:func:`euinvoice.validate.xsd.validate`);
2. if the XSD step reported nothing ``fatal`` / ``error``, each Schematron rule set the profile names in
   :attr:`~euinvoice.profiles.Profile.rule_sets`, in that order (EN 16931: CEN; Peppol BIS: CEN, Peppol;
   XRechnung: CEN, XRechnung).

XSD short-circuit: a blocking XSD finding stops validation, as KoSIT skips its Schematron steps after an
XSD failure. An XSD ``warning`` does not stop it. KoSIT's ``default-report.xsl`` (template
``in:validationResultsXmlSchema``) marks the ``val-xsd`` step invalid on warnings too, but here a
warning-only report is ``ok``, so stopping on a warning would report ``ok`` with no Schematron having
run, claiming more conformance than was checked. Running the rules after a warning only checks more.
libxml2 practically never emits schema warnings.

Severities are the raw official flags. KoSIT's ``customLevel`` overrides in ``scenarios.xml`` are not
applied (open question, issue #49): the hook for them is :func:`_rule_findings`, the single place every
Schematron finding passes through.
"""

import typing as t

from lxml import etree

from euinvoice import _xml, profiles
from euinvoice.errors import UnsupportedDocumentError
from euinvoice.validate import schematron, xsd
from euinvoice.validate.report import Finding, Severity, ValidationReport

__all__ = ["PROFILE_FALLBACK_RULE_ID", "SOURCE", "validate"]

PROFILE_FALLBACK_RULE_ID: t.Final = "EUINVOICE-PROFILE-FALLBACK"
"""Rule id of the ``information`` finding added when the profile is auto-detected but BT-24 matches none."""
SOURCE: t.Final = "euinvoice"
"""``source`` of findings euinvoice itself adds (not produced by an official rule set)."""

# Root namespace → syntax. The XSD step checks the root's local name (a wrong one is an XSD finding).
_SYNTAXES: t.Final[t.Mapping[str, str]] = {
    _xml.UBL_INVOICE: "ubl",
    _xml.UBL_CREDIT_NOTE: "ubl",
    _xml.CII_RSM: "cii",
}

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

# BT-24 locations, relative to the root: the BR-01 params of the CEN 1.3.16 EN16931-UBL-model.sch
# (``cbc:CustomizationID``) and EN16931-CII-model.sch.
_BT24: t.Final[t.Mapping[str, str]] = {
    "ubl": f"{{{_xml.UBL_CBC}}}CustomizationID",
    "cii": (
        f"{{{_xml.CII_RSM}}}ExchangedDocumentContext/{{{_xml.CII_RAM}}}GuidelineSpecifiedDocumentContextParameter"
        f"/{{{_xml.CII_RAM}}}ID"
    ),
}


def validate(data: bytes, profile: profiles.Profile | None = None) -> ValidationReport:
    """Validate an e-invoice against the official XSD and the Schematron rule sets of its profile.

    Rule failures are findings, never exceptions (D9). Nothing is downloaded (D7): the artifacts must have
    been fetched with ``python -m euinvoice artifacts fetch``.

    Profile resolution when ``profile`` is ``None``: the document's BT-24 is looked up exactly with
    :func:`euinvoice.profiles.get`. If there is no single non-empty BT-24, or no registered profile
    declares it (e.g. a CIUS whose profile is not implemented yet), the document is validated against
    :data:`euinvoice.profiles.EN16931` (XSD and CEN rules) and the report starts with an ``information``
    finding :data:`PROFILE_FALLBACK_RULE_ID` saying that only the core rules ran. A missing or repeated
    BT-24 is itself reported by the official rules (BR-01, CII-SR-009/010).

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
        UnsupportedDocumentError: The root element is not in the UBL 2.1 Invoice / CreditNote or CII D16B
            namespace, or ``profile`` does not support the document's syntax.
        ArtifactsNotAvailableError: An artifact the run needs is not in the cache (names the fetch
            command), or ``saxonche`` is not installed.
    """
    root = _xml.parse(data)
    syntax = _syntax(root)
    findings: list[Finding] = []
    if profile is None:
        profile, note = _resolve(root, syntax)
        findings.extend(note)
    elif syntax not in profile.syntaxes:
        raise UnsupportedDocumentError(
            f"profile {profile.id!r} does not support {syntax.upper()} documents; it supports "
            f"{', '.join(sorted(profile.syntaxes))}"
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


def _syntax(root: etree._Element) -> str:
    """The syntax of a document by its root namespace.

    Raises:
        UnsupportedDocumentError: The root namespace is neither UBL 2.1 Invoice / CreditNote nor CII D16B.
    """
    syntax = _SYNTAXES.get(etree.QName(root).namespace or "")
    if syntax is None:
        raise UnsupportedDocumentError(
            f"unsupported root element {root.tag!r}; expected a UBL 2.1 Invoice or CreditNote, or a CII D16B "
            "CrossIndustryInvoice"
        )
    return syntax


# ponytail: minimal BT-24 sniffing duplicated from the in-flight ``euinvoice.detect`` (#26). Once it lands,
# use it here, keeping this fallback: ``detect`` raises for a missing or repeated BT-24, which validate()
# must report as findings (BR-01, CII-SR-009/010) rather than raise.
def _resolve(root: etree._Element, syntax: str) -> tuple[profiles.Profile, tuple[Finding, ...]]:
    """The profile named by the document's BT-24, or EN 16931 core plus an ``information`` note."""
    values = root.findall(_BT24[syntax])
    bt24 = " ".join(str(values[0].xpath("string()")).split()) if len(values) == 1 else ""
    if bt24:
        try:
            return profiles.get(bt24), ()
        except UnsupportedDocumentError:
            reason = f"specification identifier (BT-24) {bt24!r} is not a registered profile"
    else:
        reason = f"{len(values)} specification identifiers (BT-24) found (exactly one non-empty is required)"
    note = Finding(
        rule_id=PROFILE_FALLBACK_RULE_ID,
        severity=Severity.INFORMATION,
        location=None,
        message=(
            f"{reason}; validated against EN 16931 core only (XSD and CEN rules). Rules of any CIUS or "
            "extension the document claims were not checked; pass its profile to validate() to run them."
        ),
        source=SOURCE,
    )
    return profiles.EN16931, (note,)
