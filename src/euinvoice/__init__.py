"""EN 16931 e-invoicing: build, serialize (UBL/CII), validate, parse and embed (Factur-X) European e-invoices.

The public API (plan §4): :func:`to_xml`, :func:`parse`, :func:`parse_detailed`, :func:`validate` and
:func:`detect`, the :class:`Invoice` / :class:`InvoiceDraft` models and the ``calc``, ``profiles`` and
``facturx`` subpackages. ``facturx`` needs the ``[pdf]`` extra and is imported on first access, so
``import euinvoice`` loads neither pypdf nor saxonche (the ``[validate]`` extra, loaded when validating).

``euinvoice.validate`` and ``euinvoice.detect`` name the functions here, not their modules; import from the
modules with ``from euinvoice.validate import artifacts`` or ``from euinvoice.detect import Detection``.
"""

import importlib
import typing as t
from importlib.metadata import version

# Set before the imports below: euinvoice.validate.artifacts reads it (User-Agent of the artifact fetcher).
__version__ = version("euinvoice")

from euinvoice import calc, profiles
from euinvoice._api import parse, parse_detailed, to_xml
from euinvoice.detect import detect
from euinvoice.model import Invoice, InvoiceDraft
from euinvoice.report import ValidationReport
from euinvoice.syntax import Syntax
from euinvoice.syntax.result import ParseResult
from euinvoice.validate import validate

if t.TYPE_CHECKING:
    from euinvoice import facturx

__all__ = [
    "Invoice",
    "InvoiceDraft",
    "ParseResult",
    "Syntax",
    "ValidationReport",
    "__version__",
    "calc",
    "detect",
    "facturx",
    "parse",
    "parse_detailed",
    "profiles",
    "to_xml",
    "validate",
]


def __getattr__(name: str) -> t.Any:
    """Import ``euinvoice.facturx`` on first access (it needs the ``[pdf]`` extra).

    Raises:
        AttributeError: ``name`` is not a lazily imported subpackage.
        ImportError: ``name`` is ``"facturx"`` and pypdf is not installed; the message names the extra.
    """
    if name == "facturx":
        return importlib.import_module("euinvoice.facturx")
    raise AttributeError(f"module 'euinvoice' has no attribute {name!r}")
