"""Validation results as data (IMPLEMENTATION_PLAN.md D9).

``validate()`` never raises on rule failures. Every XSD error and every failed Schematron assert or
successful report becomes a :class:`Finding` in a :class:`ValidationReport`; ``calc.check()``
reports its arithmetic findings with the same type. This module is pure data and imports nothing
from the package, so ``model`` ← ``calc`` ← … ← ``validate`` can all use it.
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
            a model path such as ``vat_breakdown[0].tax_amount`` for ``calc``), if known.
        message: The rule's human-readable text.
        source: The rule set that produced it, as the manifest source name plus what ran
            (e.g. ``cen-ubl``, ``peppol-bis``, ``xsd:ubl-2_1``), or ``calc``.
    """

    rule_id: str
    severity: Severity
    location: str | None
    message: str
    source: str


@dataclasses.dataclass(frozen=True, slots=True)
class ValidationReport:
    """The result of validating one document.

    Attributes:
        findings: Every finding, in the order the validation steps produced them.
    """

    findings: tuple[Finding, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether no finding is ``fatal`` or ``error`` (warnings and information do not count)."""
        return not any(f.severity in _BLOCKING for f in self.findings)
