"""The :class:`Syntax` enum, a leaf module so ``calc`` can name a syntax without importing ``syntax``.

The dependency direction is ``model`` ← ``calc`` ← ``syntax`` (CLAUDE.md); the public path is
:class:`euinvoice.syntax.Syntax`.
"""

import enum

__all__ = ["Syntax"]


class Syntax(enum.StrEnum):
    """An XML syntax for EN 16931 invoices."""

    UBL = "ubl"
    CII = "cii"
