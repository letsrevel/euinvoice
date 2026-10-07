"""Rule ids and the finding builder of the FPR12 writer's pre-flight (#119)."""

import typing as t

from euinvoice.model.codes import VatCategory
from euinvoice.report import Finding, Severity

__all__ = [
    "ALLOWANCE_CHARGE",
    "CATEGORY",
    "DOCUMENT_TYPE",
    "EXTENSION",
    "ISSUER",
    "NATURA",
    "NOT_WRITTEN",
    "PAYMENT",
    "PREFLIGHT_SOURCE",
    "REQUIRED",
    "SUMMARY",
    "TOTALS",
    "UNSUPPORTED_CATEGORIES",
    "UNWRITTEN",
    "finding",
]

PREFLIGHT_SOURCE: t.Final = "fatturapa-preflight"
"""``source`` of every pre-flight finding."""
EXTENSION: t.Final = "EUINVOICE-FATTURAPA-EXTENSION"
"""``Invoice.it`` is missing: RegimeFiscale (1.2.1.8) and TipoDocumento (2.1.1.1) are required and have no BT."""
DOCUMENT_TYPE: t.Final = "EUINVOICE-FATTURAPA-DOCUMENT-TYPE"
"""TipoDocumento is not one the v1 writer emits (plan M11), or BT-3 is not its code in App. 5.4."""
ISSUER: t.Final = "EUINVOICE-FATTURAPA-ISSUER"
"""A TD17 without SoggettoEmittente (1.6)."""
REQUIRED: t.Final = "EUINVOICE-FATTURAPA-REQUIRED"
"""An element the XSD requires whose business term is missing."""
NATURA: t.Final = "EUINVOICE-FATTURAPA-NATURA"
"""A line's Natura (2.2.1.14) is missing at rate zero (SdI 00400) or does not match its VAT category (App. 5.1)."""
PAYMENT: t.Final = "EUINVOICE-FATTURAPA-PAYMENT"
"""DatiPagamento (2.4) cannot be filled: CondizioniPagamento or ModalitaPagamento has no source, or they conflict."""
UNWRITTEN: t.Final = "EUINVOICE-FATTURAPA-UNWRITTEN"
"""A business term FPR12 cannot carry (no App. 4.1 row the writer fills), or carries only partly."""
CATEGORY: t.Final = "EUINVOICE-FATTURAPA-CATEGORY"
"""VAT category O, L or M, which App. 5.1 gives no Natura (#133)."""
ALLOWANCE_CHARGE: t.Final = "EUINVOICE-FATTURAPA-ALLOWANCE-CHARGE"
"""A document level allowance or charge other than a zero stamp duty (App. 4.1 row 2.1.1.6; #133)."""
SUMMARY: t.Final = "EUINVOICE-FATTURAPA-SUMMARY"
"""The DatiRiepilogo (2.2.2) cannot be built from the lines, VAT BREAKDOWN, BT-8 and ``it.vat_summaries``."""
TOTALS: t.Final = "EUINVOICE-FATTURAPA-TOTALS"
"""A document total disagrees with the summaries written (App. 4.1 rows 2.1.1.9, 2.1.1.10, 2.4.2.6)."""
NOT_WRITTEN: t.Final = "EUINVOICE-FATTURAPA-NOT-WRITTEN"
"""A ``warning``: a business term App. 4.1 builds from FatturaPA elements the writer fills from ``.it``, so its own
text is not written (BT-20, BT-120, BT-121; #133)."""

UNSUPPORTED_CATEGORIES: t.Final = frozenset({VatCategory.NOT_SUBJECT_TO_VAT, VatCategory.IGIC, VatCategory.IPSI})
"""O, L and M: App. 5.1 gives them no Natura (#133)."""


def finding(rule_id: str, location: str, message: str, severity: Severity = Severity.ERROR) -> Finding:
    """A pre-flight finding located at a model path.

    Args:
        rule_id: One of the rule ids of this module.
        location: The model path, e.g. ``lines[0].it.nature``.
        message: What is wrong, citing its source.
        severity: ``error`` (blocks the write) or ``warning``.

    Returns:
        The finding, with source :data:`PREFLIGHT_SOURCE`.
    """
    return Finding(rule_id=rule_id, severity=severity, location=location, message=message, source=PREFLIGHT_SOURCE)
