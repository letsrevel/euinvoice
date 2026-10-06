"""Factur-X / ZUGFeRD PDF/A-3 documents (plan §1 item 5, §5): :func:`embed` (this module) and, later, ``extract``.

Needs the ``[pdf]`` extra (pypdf). The evidence behind every value written is in :mod:`euinvoice.facturx._embed`
and :mod:`euinvoice.facturx.xmp`.
"""

from euinvoice.facturx._embed import Relationship, embed

__all__ = ["Relationship", "embed"]
