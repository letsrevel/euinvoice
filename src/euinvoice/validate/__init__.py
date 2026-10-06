"""Validation against the official XSD and Schematron artifacts (IMPLEMENTATION_PLAN.md D7, D8, D9).

:func:`validate` is the entry point; see :mod:`euinvoice.validate.orchestration` for the steps it runs.
"""

from euinvoice.validate.orchestration import PROFILE_FALLBACK_RULE_ID, SOURCE, validate

__all__ = ["PROFILE_FALLBACK_RULE_ID", "SOURCE", "validate"]
