"""Validation against the official XSD and Schematron artifacts (IMPLEMENTATION_PLAN.md D7, D8, D9).

:func:`validate` is the entry point; see :mod:`euinvoice.validate.orchestration` for the steps it runs.
"""

from euinvoice.validate.orchestration import EUINVOICE_SOURCE, PROFILE_FALLBACK_RULE_ID, validate

__all__ = ["EUINVOICE_SOURCE", "PROFILE_FALLBACK_RULE_ID", "validate"]
