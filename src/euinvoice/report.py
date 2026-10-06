"""Validation results as data (IMPLEMENTATION_PLAN.md D9).

``validate()`` never raises on rule failures. Every XSD error and every failed Schematron assert or
successful report becomes a :class:`Finding` in a :class:`ValidationReport`; ``calc.check()``
reports its arithmetic findings, and profile pre-flight checks (e.g. ``euinvoice.profiles.PEPPOL``)
theirs, with the same type. For the XRechnung profiles a report also carries the KoSIT validator's
verdict (:class:`KositAssessment`, issue #49) next to the raw official flags. This module is pure data and
imports nothing from the package, so ``model`` ← ``calc`` ← … ← ``profiles`` ← ``validate`` can all use it.
"""

import dataclasses
import enum


class Severity(enum.StrEnum):
    """Severity of a finding.

    The values are the ``flag`` values used by the official Schematron rule sets.
    """

    FATAL = "fatal"
    ERROR = "error"
    WARNING = "warning"
    INFORMATION = "information"


_BLOCKING = frozenset({Severity.FATAL, Severity.ERROR})


@dataclasses.dataclass(frozen=True, slots=True)
class Finding:
    """One problem reported by a validation step.

    Attributes:
        rule_id: The official rule id (e.g. ``BR-02``, ``PEPPOL-EN16931-R001``, ``BR-DE-15``), or
            ``XSD`` for a schema-validity error.
        severity: How serious the finding is; ``fatal`` and ``error`` make the report not ok.
        location: Where the problem is (an XPath for Schematron, the line number and element path for XSD,
            a model path such as ``vat_breakdown[0].tax_amount`` for ``calc`` or
            ``buyer.electronic_address`` for a pre-flight check), if known.
        message: The rule's human-readable text.
        source: The rule set that produced it, as the manifest source name plus what ran
            (e.g. ``cen-ubl``, ``peppol-bis``, ``xsd:ubl-2_1``), ``calc``, or a pre-flight source such as
            ``peppol-preflight``.
    """

    rule_id: str
    severity: Severity
    location: str | None
    message: str
    source: str


@dataclasses.dataclass(frozen=True, slots=True)
class SeverityOverride:
    """A finding whose severity a validator configuration replaces.

    Attributes:
        finding: The finding, unchanged: its ``severity`` is the official flag.
        severity: The severity the configuration gives it instead (for KoSIT, the ``customLevel``).
    """

    finding: Finding
    severity: Severity


@dataclasses.dataclass(frozen=True, slots=True)
class KositAssessment:
    """The verdict the KoSIT XRechnung validator would give, next to the raw official flags (issue #49).

    The KoSIT validator configuration replaces the severity of some official rules per scenario
    (``customLevel`` in its ``scenarios.xml``) and rejects a document when any message is still at level
    ``error`` (``resources/default-report.xsl``, template ``rep:report`` in mode ``assessment``).
    :func:`euinvoice.validate` builds this; :attr:`ValidationReport.findings` and :attr:`ValidationReport.ok`
    are never changed by it.

    Attributes:
        scenario: The ``<name>`` of the KoSIT scenario that matched the document.
        overrides: Every finding a ``customLevel`` of that scenario applies to, with the effective level.
        blocking: Every finding that is ``fatal`` or ``error`` after the overrides, with its official severity.
            A blocking XSD finding is among them, as KoSIT rejects a schema-invalid document.
    """

    scenario: str
    overrides: tuple[SeverityOverride, ...] = ()
    blocking: tuple[Finding, ...] = ()

    @property
    def accepted(self) -> bool:
        """Whether KoSIT would accept the document: no finding is blocking after the overrides."""
        return not self.blocking


@dataclasses.dataclass(frozen=True, slots=True)
class ValidationReport:
    """The result of validating one document.

    Attributes:
        findings: Every finding, in the order the validation steps produced them.
        kosit: The KoSIT verdict, for the XRechnung profiles when a KoSIT scenario matches the document;
            ``None`` otherwise.
    """

    findings: tuple[Finding, ...] = ()
    kosit: KositAssessment | None = None

    @property
    def ok(self) -> bool:
        """Whether no finding is ``fatal`` or ``error`` (warnings and information do not count)."""
        return not any(f.severity in _BLOCKING for f in self.findings)
