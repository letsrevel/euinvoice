"""The :class:`Syntax` enum, a leaf module so ``calc`` can name a syntax without importing ``syntax``.

The dependency direction is ``model`` ← ``calc`` ← ``syntax`` (CLAUDE.md); the public path is
:class:`euinvoice.syntax.Syntax`.
"""

import enum

__all__ = ["Syntax"]


class Syntax(enum.StrEnum):
    """An XML syntax of an e-invoice.

    ``UBL`` and ``CII`` are the EN 16931 syntaxes (CEN/TS 16931-3-2 and -3-3): every profile, writer and reader
    serves them. ``FATTURAPA`` (Italy's SdI format, XSD 1.2.3; ADR 0001) is not an EN 16931 syntax and so far is
    only detected and validated (#121); no profile supports it, and its reader (#120) and writer (#119) come later.
    """

    UBL = "ubl"
    CII = "cii"
    FATTURAPA = "fatturapa"
