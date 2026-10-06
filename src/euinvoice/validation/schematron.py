"""Run the official Schematron rule sets on Saxon and turn their SVRL output into findings.

Every rule set runs as a compiled XSLT stylesheet from the artifact cache (D7, D8): CEN ships its
compiled XSLT, XRechnung ships compiled ``.xsl``, and the Peppol ``.sch`` files are compiled with SchXslt
at fetch time (:mod:`euinvoice.validation.artifacts`). The stylesheet writes an SVRL report (ISO/IEC
19757-3 Annex D, namespace :data:`euinvoice._xml.SVRL`), and every ``svrl:failed-assert`` and
``svrl:successful-report`` in it becomes a :class:`~euinvoice.report.Finding`. Nothing is
filtered or downgraded.

Input hardening (D10): the document reaches Saxon only through :func:`euinvoice._xml.to_xdm`, which
runs it through the hardened parser and hands Saxon the re-serialized text. The only file Saxon reads by
path is the pinned stylesheet itself, from a cache entry whose recipe fingerprint
:func:`~euinvoice.validation.artifacts.source_dir` has just checked (that catches a stale cache, not
tampering).

Run-time errors (D9): a well-formed document can still make an official stylesheet fail while it runs,
e.g. ``cbc:PayableAmount`` = ``abc`` raises ``FORG0001`` inside an ``xs:decimal`` cast of CEN's BR-CO
rules. That is a property of the document, so it becomes one blocking finding
(:data:`RUNTIME_ERROR_RULE_ID`, ``fatal``) rather than an exception. saxonche 12.x puts the error's
template trace, with the absolute path of the cached stylesheet, into the ``PySaxonApiError`` message
(13.0.0 printed it to standard error instead). The finding keeps only Saxon's first two lines: the
location in the stylesheet and the error code with its description, on one line.

Caching and threads: one :class:`saxonche.PySaxonProcessor` per process, created on first use, and one
compiled executable per ``(stylesheet path, cache-entry fingerprint)``, so a re-fetched or re-pinned
artifact is compiled again and an unchanged one is compiled once (about 0.14 s for the CEN UBL
stylesheet). saxonche (12.10 and 13.0.0) documents a compiled ``PyXsltExecutable`` as "immutable and
thread-safe" (``PyXslt30Processor.compile_stylesheet`` docstring) but says nothing about the shared processor's
``parse_xml`` or about the per-call state of ``transform_to_string``. So one module lock serializes
compiling, building the XDM node and transforming: :func:`run` is safe to call from any thread, and
transforms never run in parallel. SVRL parsing happens outside the lock.
"""

import dataclasses
import threading
import typing as t
from pathlib import Path

from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ArtifactIntegrityError, ArtifactsNotAvailableError, ParseError
from euinvoice.report import Finding, Severity
from euinvoice.validation import artifacts

__all__ = [
    "CEN_CII",
    "CEN_UBL",
    "PEPPOL_CII",
    "PEPPOL_UBL",
    "RULE_SETS",
    "RUNTIME_ERROR_RULE_ID",
    "XRECHNUNG_CII",
    "XRECHNUNG_UBL",
    "RuleSet",
    "run",
    "svrl_findings",
]


@dataclasses.dataclass(frozen=True, slots=True)
class RuleSet:
    """One compiled official rule set: a stylesheet inside a fetched manifest source.

    Attributes:
        source: Manifest source that ships (or precompiles) the stylesheet; also the ``source`` of every
            finding it produces.
        stylesheet: Path of the compiled XSLT, relative to the source's cache directory.
    """

    source: artifacts.SourceName
    stylesheet: str


# Paths verified against the pinned cache entries (manifest.toml): CEN validation-1.3.16 release zips,
# Peppol BIS 3.0.21 (``precompile`` entries, compiled by SchXslt 1.10.1), XRechnung Schematron 2.6.0.
CEN_UBL: t.Final = RuleSet("cen-ubl", "xslt/EN16931-UBL-validation.xslt")
"""EN 16931 core rules (BR-*, BR-CO-*, UBL-*) for UBL 2.1 Invoice and CreditNote."""
CEN_CII: t.Final = RuleSet("cen-cii", "xslt/EN16931-CII-validation.xslt")
"""EN 16931 core rules (BR-*, BR-CO-*, CII-*) for CII D16B."""
PEPPOL_UBL: t.Final = RuleSet("peppol-bis", "rules/sch/PEPPOL-EN16931-UBL.xslt")
"""Peppol BIS Billing 3.0 rules (PEPPOL-EN16931-*, national rules) for UBL."""
PEPPOL_CII: t.Final = RuleSet("peppol-bis", "rules/sch/PEPPOL-EN16931-CII.xslt")
"""Peppol BIS Billing 3.0 rules for CII (used by the Peppol vefa unit tests ``rules/unit-CII-*``)."""
XRECHNUNG_UBL: t.Final = RuleSet("xrechnung-schematron", "schematron/ubl/XRechnung-UBL-validation.xsl")
"""XRechnung 3.0.2 rules for UBL: BR-DE-*, BR-DE-CVD-*, BR-DEX-*, BR-TMP-*, BR-DE-TMP-32, BR-TMP-CVD-01.

The stylesheet also re-asserts a subset of 21 PEPPOL-EN16931-R* rules, so do not run
:data:`PEPPOL_UBL` alongside it, or those findings are counted twice.
"""
XRECHNUNG_CII: t.Final = RuleSet("xrechnung-schematron", "schematron/cii/XRechnung-CII-validation.xsl")
"""XRechnung 3.0.2 rules for CII: BR-DE-*, BR-DE-CVD-*, BR-DEX-*, BR-TMP-*, BR-DE-TMP-32, BR-TMP-CVD-01.

The stylesheet also re-asserts a subset of 22 PEPPOL-EN16931-R* rules, so do not run
:data:`PEPPOL_CII` alongside it, or those findings are counted twice.
"""
RULE_SETS: t.Final = (CEN_UBL, CEN_CII, PEPPOL_UBL, PEPPOL_CII, XRECHNUNG_UBL, XRECHNUNG_CII)
"""Every rule set above; which ones apply to a document is the orchestrator's decision."""
RUNTIME_ERROR_RULE_ID: t.Final = "SCHEMATRON-RUNTIME"
"""Rule id of the fatal finding reported when a stylesheet cannot evaluate a document (see module docs)."""

_SVRL_ROOT: t.Final = f"{{{_xml.SVRL}}}schematron-output"
_SVRL_RESULTS: t.Final = (f"{{{_xml.SVRL}}}failed-assert", f"{{{_xml.SVRL}}}successful-report")
_SVRL_TEXT: t.Final = f"{{{_xml.SVRL}}}text"
_SEVERITIES: t.Final = {s.value: s for s in Severity}

# ponytail: one lock serializes every Saxon call (see the module docstring), capping throughput at one
# transform at a time per process (a few ms for an ordinary invoice). If that ever matters, measure
# per-thread processors / executable clones against saxonche's threading guarantees before lifting it.
_lock = threading.Lock()
_processor: t.Any = None  # saxonche.PySaxonProcessor; saxonche ships no type information
_executables: dict[tuple[Path, str], t.Any] = {}  # (stylesheet, fingerprint) -> saxonche.PyXsltExecutable


def run(
    rule_set: RuleSet,
    document: bytes | etree._Element,
    *,
    root: Path | None = None,
    sources: t.Mapping[str, artifacts.Source] | None = None,
) -> tuple[Finding, ...]:
    """Run one official rule set over a document.

    Args:
        rule_set: The compiled rule set to run, e.g. :data:`CEN_UBL`.
        document: The XML as bytes or an element; either way it goes through :func:`euinvoice._xml.to_xdm`.
        root: Artifact cache root; defaults to :func:`~euinvoice.validation.artifacts.cache_dir`.
        sources: Manifest; defaults to the packaged one.

    Returns:
        One finding per failed assert or successful report, in SVRL document order, each with
        ``source`` set to ``rule_set.source``. Empty when the document passes the rule set. If the
        stylesheet fails while evaluating the document, a single fatal
        :data:`RUNTIME_ERROR_RULE_ID` finding with Saxon's message.

    Raises:
        TypeError: ``document`` is neither bytes nor an element.
        ParseError: The document is malformed or has a DOCTYPE (D10), or Saxon rejects the text the
            hardened parser accepted.
        ArtifactsNotAvailableError: The source is not in the cache (names the fetch command), or
            ``saxonche`` is missing (names the ``euinvoice[validate]`` extra).
        ArtifactIntegrityError: The stylesheet does not compile, or produces empty or non-SVRL output.
    """
    saxonche = _saxonche()
    directory = artifacts.source_dir(rule_set.source, root=root, sources=sources)
    stylesheet = (directory / rule_set.stylesheet).resolve()
    fingerprint = (directory / artifacts.MARKER).read_text(encoding="ascii").strip()
    with _lock:
        executable = _executable(saxonche, stylesheet, fingerprint, rule_set)
        try:
            node = _xml.to_xdm(_processor, document)
        except saxonche.PySaxonApiError as exc:
            raise ParseError(f"Saxon rejected XML the hardened parser accepted: {exc}") from exc
        try:
            output = executable.transform_to_string(xdm_node=node)
        except saxonche.PySaxonApiError as exc:
            # Saxon's first two lines are the location ("Error ... of <file>:") and "<code>  <description>".
            # saxonche 12.x appends the template trace, with absolute cache paths, which is dropped.
            lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
            message = f"{rule_set.stylesheet} could not evaluate the document: {' '.join(lines[:2])}"
            return (Finding(RUNTIME_ERROR_RULE_ID, Severity.FATAL, None, message, rule_set.source),)
    try:
        # The pinned stylesheets' xsl:output leaves the encoding at its UTF-8 default, so the declaration
        # in ``output`` says UTF-8.
        return svrl_findings((output or "").encode("utf-8"), source=rule_set.source)
    except ParseError as exc:
        raise ArtifactIntegrityError(f"{rule_set.source}: {rule_set.stylesheet} produced no SVRL: {exc}") from exc


def svrl_findings(svrl: bytes, *, source: str) -> tuple[Finding, ...]:
    """Map an SVRL report to findings.

    Every ``svrl:failed-assert`` and ``svrl:successful-report`` becomes one finding: ``@id`` is the rule
    id (empty if absent), ``@location`` the XPath (``None`` if absent) and the whitespace-normalized
    text of ``svrl:text`` the message. ``@flag`` gives the severity. Every assert in the pinned CEN,
    Peppol and XRechnung stylesheets carries ``fatal``, ``warning`` or ``information`` (checked by a
    conformance test). A missing or unrecognised flag maps to ``error``: in ISO Schematron a failed
    assert means the document is invalid, so such a finding blocks rather than being dropped or
    downgraded (D8).

    Args:
        svrl: The SVRL document produced by a compiled rule set.
        source: The rule set name to record on each finding.

    Returns:
        The findings in document order.

    Raises:
        ParseError: ``svrl`` is not well-formed XML.
        ArtifactIntegrityError: The root element is not ``svrl:schematron-output``.
    """
    report = _xml.parse(svrl)
    if report.tag != _SVRL_ROOT:
        # A stylesheet that emits something else would otherwise look like a passing document.
        raise ArtifactIntegrityError(f"{source}: rule set output is not SVRL (root {report.tag!r})")
    return tuple(
        Finding(
            rule_id=result.get("id", ""),
            severity=_SEVERITIES.get(result.get("flag", ""), Severity.ERROR),
            location=result.get("location"),
            message=_message(result),
            source=source,
        )
        for result in report.iter(*_SVRL_RESULTS)
    )


def _message(result: etree._Element) -> str:
    """The whitespace-normalized string value of the result's ``svrl:text`` (empty if absent)."""
    text = result.find(_SVRL_TEXT)
    if text is None:
        return ""
    return " ".join(etree.tostring(text, method="text", encoding="unicode", with_tail=False).split())


def _saxonche() -> t.Any:  # saxonche ships no type information
    try:
        import saxonche
    except ImportError as exc:
        raise ArtifactsNotAvailableError(
            "Schematron validation needs saxonche: install the extra with `pip install 'euinvoice[validate]'`."
        ) from exc
    return saxonche


def _executable(saxonche: t.Any, stylesheet: Path, fingerprint: str, rule_set: RuleSet) -> t.Any:
    """Return the compiled stylesheet, compiling it on first use. Call with ``_lock`` held."""
    global _processor
    key = (stylesheet, fingerprint)
    if key not in _executables:
        if _processor is None:
            _processor = saxonche.PySaxonProcessor(license=False)
        try:
            # The one load by path: a pinned artifact from a recipe-fingerprint-checked cache entry (catches
            # a stale cache, not tampering); by path because xsl:include / xsl:import need a base URI.
            _executables[key] = _processor.new_xslt30_processor().compile_stylesheet(stylesheet_file=str(stylesheet))
        except saxonche.PySaxonApiError as exc:
            raise ArtifactIntegrityError(f"{rule_set.source}: cannot compile {rule_set.stylesheet}: {exc}") from exc
    return _executables[key]
