"""Factur-X / ZUGFeRD PDF/A-3 documents (plan §1 item 5, §5): :func:`embed` and :func:`extract`.

Needs the ``[pdf]`` extra (pypdf). The evidence behind every value written or required is in
:mod:`euinvoice.facturx._embed`, :mod:`euinvoice.facturx._extract` and :mod:`euinvoice.facturx.xmp`.
"""

from euinvoice.facturx._embed import Relationship, embed
from euinvoice.facturx._extract import Container, Extracted, extract

__all__ = ["Container", "Extracted", "Relationship", "embed", "extract"]
