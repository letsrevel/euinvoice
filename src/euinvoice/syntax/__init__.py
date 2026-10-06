"""Syntax bindings of the EN 16931 semantic model.

Each syntax module maps :class:`euinvoice.model.Invoice` to and from one XML syntax: ``ubl`` (UBL 2.1,
CEN/TS 16931-3-2) and ``cii`` (UN/CEFACT CII D16B, CEN/TS 16931-3-3).
"""

from euinvoice._syntax import Syntax

__all__ = ["Syntax"]
