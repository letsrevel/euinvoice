"""Validation against the official XSD and Schematron artifacts (IMPLEMENTATION_PLAN.md D7, D8, D9).

:func:`validate` is the entry point; see :mod:`euinvoice.validation.orchestration` for the steps it runs. FatturaPA
documents get the FatturaPA XSD and the offline SdI checks of :mod:`euinvoice.validation.sdi` instead.
"""

from euinvoice.validation.orchestration import (
    EUINVOICE_SOURCE,
    FPA12_NOTE_RULE_ID,
    PROFILE_FALLBACK_RULE_ID,
    validate,
)

__all__ = ["EUINVOICE_SOURCE", "FPA12_NOTE_RULE_ID", "PROFILE_FALLBACK_RULE_ID", "validate"]
