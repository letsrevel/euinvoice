"""Code lists derived from the generated ones, for the syntax-neutral model (D1)."""

import typing as t

from euinvoice.model.codes._generated import ISO_3166_1_COUNTRY_CII, ISO_3166_1_COUNTRY_UBL

__all__ = ["ISO_3166_1_COUNTRY"]

ISO_3166_1_COUNTRY: t.Final[frozenset[str]] = ISO_3166_1_COUNTRY_UBL | ISO_3166_1_COUNTRY_CII
"""ISO 3166-1 alpha-2 country codes the model accepts: the union of the UBL and CII lists.

The CEN 1.3.16 code-list files disagreed on BR-CL-14/15 (UBL had ``SS`` and lacked ``AN``, CII the
reverse); CEN 1.3.17 harmonised them (eInvoicing-EN16931#509), so the two lists are equal today. The
model is syntax-neutral (D1) and does not know the target syntax, so it keeps accepting the union,
which stays correct if the files diverge again. The official per-syntax Schematron stays the oracle
(D8).
"""
