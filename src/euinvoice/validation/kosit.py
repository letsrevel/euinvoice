r"""The KoSIT XRechnung verdict: scenario match and ``customLevel`` overrides (issue #49, option 3).

:func:`euinvoice.validate` reports the raw official flags (D8). For the XRechnung profiles it adds
:class:`~euinvoice.report.KositAssessment`, the verdict the KoSIT validator would give with the pinned
``xrechnung-validator-configuration`` (2026-08-31). Everything is read from that artifact at run time; no rule
id is copied into euinvoice.

**Scenario.** ``scenarios.xml`` lists ``<scenario>`` elements, each with a ``<match>`` XPath and its
``<namespace prefix="...">`` declarations. :func:`select` evaluates them in document order on Saxon (the
matches use XPath 2 functions such as ``exists``) and takes the first that is true. In the pinned file each
match compares BT-24 with a different value, or tests a different root, so at most one scenario matches a
schema-valid document and "first match" cannot differ from "the only match".

**Levels.** The overrides are the ``<customLevel level="...">`` children of the matched scenario's
``<createReport>``. Their text is a whitespace-separated list of codes: ``rep:custom-level`` in
``resources/default-report.xsl`` looks a message up with ``$custom-levels[tokenize(., '\s+') = $message/@code]``,
where ``@code`` is the Schematron assert ``@id`` (the templates for ``svrl:failed-assert/@id`` and
``svrl:successful-report/@id``), i.e. :attr:`~euinvoice.report.Finding.rule_id`.

**Verdict.** Template ``rep:report`` in mode ``assessment`` (``default-report.xsl`` lines 312-335) rejects the
document when any message has ``rep:custom-level(.) = 'error'`` and accepts it otherwise. Without an override a
message keeps the level the report gave it: an SVRL ``@flag`` of ``fatal`` or ``error`` becomes the VARL level
``error`` (template ``svrl:failed-assert | svrl:successful-report``, line 251:
``(@flag, @role) = ('fatal', 'error')``), ``warning`` stays ``warning`` and ``information`` stays
``information``. An XSD error is level ``error`` and a schema warning ``warning`` (template
``in:xmlSyntaxError``, ``SEVERITY_WARNING``). So a finding blocks KoSIT exactly when its effective severity
is ``fatal`` or ``error``, which is what :func:`assess` computes. Every assert in the pinned rule sets carries
a ``flag`` (a conformance test checks it), so KoSIT's ``@role`` fallbacks never apply.

**When.** :func:`assessment` returns ``None`` unless the profile is XRECHNUNG, XRECHNUNG_EXTENSION or
XRECHNUNG_CVD, a scenario matches, and that scenario's ``validateWithSchematron`` steps are the rule sets
``validate()`` ran, compared by stylesheet file stem (``EN16931-UBL-validation``, ``XRechnung-CII-validation``,
...). The pinned configuration names the same CEN 1.3.16 and XRechnung Schematron 2.6.0 releases as the
``cen-*`` and ``xrechnung-schematron`` pins (its ``scenarios.xml`` description). With an explicit profile,
KoSIT's choice of scenario still follows the document: XRECHNUNG on an Extension document gets the Extension
scenario (same rule sets), while XRECHNUNG on a plain EN 16931 document matches a CEN-only scenario and gets
``None``, because that verdict would not be about the XRechnung rules that ran.
"""

import dataclasses
import functools
import typing as t
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

from lxml import etree

from euinvoice import _xml, profiles
from euinvoice.errors import ArtifactIntegrityError
from euinvoice.report import Finding, KositAssessment, Severity, SeverityOverride
from euinvoice.validation import artifacts, schematron

__all__ = ["SOURCE", "Scenario", "assess", "assessment", "load", "scenarios", "select"]

SOURCE: t.Final[artifacts.SourceName] = "xrechnung-validator-configuration"
"""The manifest source that ships ``scenarios.xml``."""

_FILE: t.Final = "scenarios.xml"
_S: t.Final = f"{{{_xml.KOSIT_SCENARIOS}}}"
_PROFILES: t.Final = (profiles.XRECHNUNG, profiles.XRECHNUNG_EXTENSION, profiles.XRECHNUNG_CVD)
# The VARL message levels a customLevel can set (default-report.xsl: error, warning, information).
_LEVELS: t.Final = {s.value: s for s in (Severity.ERROR, Severity.WARNING, Severity.INFORMATION)}
_BLOCKING: t.Final = (Severity.FATAL, Severity.ERROR)


@dataclasses.dataclass(frozen=True, slots=True)
class Scenario:
    """One ``<scenario>`` of the KoSIT ``scenarios.xml``.

    Attributes:
        name: The scenario's ``<name>``.
        match: Its ``<match>`` XPath.
        namespaces: Its ``<namespace>`` declarations as ``(prefix, uri)``, in document order.
        schematron: The file stems of its ``validateWithSchematron`` stylesheets, in order.
        levels: Each code of its ``<customLevel>`` elements, mapped to that element's level.
    """

    name: str
    match: str
    namespaces: tuple[tuple[str, str], ...]
    schematron: tuple[str, ...]
    levels: Mapping[str, Severity]


def scenarios(
    *, root: Path | None = None, sources: t.Mapping[str, artifacts.Source] | None = None
) -> tuple[Scenario, ...]:
    """The scenarios of the pinned KoSIT configuration, parsed once per cache entry.

    Args:
        root: Artifact cache root; defaults to :func:`~euinvoice.validation.artifacts.cache_dir`.
        sources: Manifest; defaults to the packaged one.

    Returns:
        Every scenario, in document order.

    Raises:
        ArtifactsNotAvailableError: The configuration is not in the cache (names the fetch command).
        ParseError: ``scenarios.xml`` is not well-formed or has a DOCTYPE (D10).
        ArtifactIntegrityError: ``scenarios.xml`` is not a KoSIT scenarios file this module can read.
    """
    directory = artifacts.source_dir(SOURCE, root=root, sources=sources)
    fingerprint = (directory / artifacts.MARKER).read_text(encoding="ascii").strip()
    return _cached(directory / _FILE, fingerprint)


@functools.cache
def _cached(path: Path, fingerprint: str) -> tuple[Scenario, ...]:
    """Parse ``path``; the cache key includes the entry's fingerprint, so a re-pinned file is read again."""
    return load(path.read_bytes())


def load(data: bytes) -> tuple[Scenario, ...]:
    """Parse a KoSIT ``scenarios.xml`` through the hardened parser (D10).

    Args:
        data: The file's bytes.

    Returns:
        Every scenario, in document order.

    Raises:
        ParseError: ``data`` is not well-formed or has a DOCTYPE.
        ArtifactIntegrityError: The root is not ``scenarios``, a scenario lacks its name or match, a
            ``customLevel`` has a level other than ``error``, ``warning`` or ``information``, or a code appears
            in two ``customLevel`` elements of one scenario (KoSIT's lookup expects at most one).
    """
    root = _xml.parse(data)
    if root.tag != f"{_S}scenarios":
        raise ArtifactIntegrityError(f"{_FILE}: root element is {root.tag!r}, not KoSIT scenarios")
    return tuple(_scenario(element) for element in root.iterfind(f"{_S}scenario"))


def _scenario(element: etree._Element) -> Scenario:
    name = element.findtext(f"{_S}name")
    match = element.findtext(f"{_S}match")
    if name is None or match is None:
        raise ArtifactIntegrityError(f"{_FILE}: a scenario has no name or no match")
    levels: dict[str, Severity] = {}
    for custom in element.iterfind(f"{_S}createReport/{_S}customLevel"):
        level = _LEVELS.get(custom.get("level", ""))
        if level is None:
            raise ArtifactIntegrityError(f"{_FILE}: scenario {name!r} has customLevel level={custom.get('level')!r}")
        for code in (custom.text or "").split():
            if code in levels:
                raise ArtifactIntegrityError(f"{_FILE}: scenario {name!r} sets a customLevel for {code} twice")
            levels[code] = level
    return Scenario(
        name=name,
        match=match,
        namespaces=tuple((ns.get("prefix", ""), ns.text or "") for ns in element.iterfind(f"{_S}namespace")),
        schematron=tuple(
            PurePosixPath(location.text or "").stem
            for location in element.iterfind(f"{_S}validateWithSchematron/{_S}resource/{_S}location")
        ),
        levels=levels,
    )


def select(candidates: Sequence[Scenario], document: etree._Element) -> Scenario | None:
    """The first scenario whose ``match`` is true for the document, evaluated on Saxon.

    Args:
        candidates: The scenarios, in order.
        document: The root element, already parsed by :func:`euinvoice._xml.parse`.

    Returns:
        The first matching scenario, or ``None``.

    Raises:
        ArtifactsNotAvailableError: ``saxonche`` is missing.
        ArtifactIntegrityError: Saxon cannot evaluate a scenario's match.
    """
    if not candidates:
        return None
    with schematron.saxon() as (saxonche, processor):
        node = _xml.to_xdm(processor, document)
        for scenario in candidates:
            xpath = processor.new_xpath_processor()
            for prefix, uri in scenario.namespaces:
                xpath.declare_namespace(prefix, uri)
            xpath.set_context(xdm_item=node)
            try:
                if xpath.effective_boolean_value(scenario.match):
                    return scenario
            except saxonche.PySaxonApiError as exc:
                raise ArtifactIntegrityError(
                    f"{_FILE}: cannot evaluate the match of scenario {scenario.name!r}: {exc}"
                ) from exc
    return None


def assess(scenario: Scenario, findings: Sequence[Finding]) -> KositAssessment:
    """Apply the scenario's levels to the findings and give KoSIT's verdict (see the module docs).

    Args:
        scenario: The matched scenario.
        findings: Every finding of the report (XSD and Schematron).

    Returns:
        The assessment: the findings a ``customLevel`` applies to, and those still blocking.
    """
    levels = scenario.levels
    return KositAssessment(
        scenario=scenario.name,
        overrides=tuple(SeverityOverride(f, levels[f.rule_id]) for f in findings if f.rule_id in levels),
        blocking=tuple(f for f in findings if levels.get(f.rule_id, f.severity) in _BLOCKING),
    )


def assessment(
    document: etree._Element,
    profile: profiles.Profile,
    rule_sets: Sequence[schematron.RuleSet],
    findings: Sequence[Finding],
) -> KositAssessment | None:
    """The KoSIT verdict for a validated document, or ``None`` when it does not apply (see the module docs).

    Args:
        document: The root element, already parsed by :func:`euinvoice._xml.parse`.
        profile: The profile the document was validated under.
        rule_sets: The Schematron rule sets of that profile for the document's syntax, in order (also when
            the XSD step stopped validation before they ran).
        findings: Every finding of the report.

    Returns:
        The assessment, or ``None`` for a non-XRechnung profile, no matching scenario, or a scenario
        whose Schematron steps are not ``rule_sets``.

    Raises:
        ArtifactsNotAvailableError: The KoSIT configuration is not in the cache, or ``saxonche`` is missing.
        ArtifactIntegrityError: The configuration cannot be read or evaluated.
    """
    if profile not in _PROFILES:
        return None
    scenario = select(scenarios(), document)
    ran = tuple(PurePosixPath(r.stylesheet).stem for r in rule_sets)
    if scenario is None or scenario.schematron != ran:
        return None
    return assess(scenario, findings)
