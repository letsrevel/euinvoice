"""Validation against the official XSD and Schematron artifacts (IMPLEMENTATION_PLAN.md D7, D8, D9).

:func:`validate` is the entry point; see :mod:`euinvoice.validate.orchestration` for the steps it runs.
The result types are re-exported for convenience.
"""

from euinvoice.validate.orchestration import PROFILE_FALLBACK_RULE_ID, SOURCE, validate
from euinvoice.validate.report import Finding, Severity, ValidationReport

__all__ = ["PROFILE_FALLBACK_RULE_ID", "SOURCE", "Finding", "Severity", "ValidationReport", "validate"]
