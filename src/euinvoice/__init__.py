"""EN 16931 e-invoicing: build, serialize (UBL/CII), validate, parse and embed (Factur-X) European e-invoices.

The public API (plan §4): :func:`to_xml`, :func:`parse`, :func:`parse_detailed`, :func:`validate` and
:func:`detect`, the :class:`Invoice` / :class:`InvoiceDraft` models and the ``calc``, ``profiles`` and
``facturx`` subpackages. ``facturx`` needs the ``[pdf]`` extra and is imported on first access
(``euinvoice.facturx`` or ``from euinvoice import facturx``); it is not in ``__all__``, so ``from euinvoice import *``
works without pypdf. ``import euinvoice`` loads neither pypdf nor saxonche (the ``[validate]`` extra, loaded when
validating).

``euinvoice.validate`` and ``euinvoice.detect`` name the functions here, not their modules; import from the
modules with ``from euinvoice.validate import artifacts`` or ``from euinvoice.detect import Detection``.
"""

import importlib
import typing as t
from importlib.metadata import version

from euinvoice import calc, profiles
from euinvoice._api import parse, parse_detailed, to_xml
from euinvoice.detect import detect
from euinvoice.model import Invoice, InvoiceDraft
from euinvoice.report import ValidationReport
from euinvoice.syntax import Syntax
from euinvoice.syntax.result import ParseResult
from euinvoice.validate import validate

if t.TYPE_CHECKING:
    # The redundant alias marks an explicit re-export, so ruff does not add ``facturx`` to ``__all__`` (which would
    # make ``from euinvoice import *`` need pypdf).
    from euinvoice import facturx as facturx

__version__ = version("euinvoice")

__all__ = [
    "Invoice",
    "InvoiceDraft",
    "ParseResult",
    "Syntax",
    "ValidationReport",
    "__version__",
    "calc",
    "detect",
    "parse",
    "parse_detailed",
    "profiles",
    "to_xml",
    "validate",
]


# Hidden from type checkers so that a typo such as ``euinvoice.facturxx`` is a mypy error, not ``Any``; the
# ``TYPE_CHECKING`` import above gives them ``facturx``.
if not t.TYPE_CHECKING:

    def __getattr__(name: str) -> t.Any:
        """Import ``euinvoice.facturx`` on first access (it needs the ``[pdf]`` extra).

        Raises:
            AttributeError: ``name`` is not a lazily imported subpackage.
            ImportError: ``name`` is ``"facturx"`` and pypdf is not installed; the message names the extra.
        """
        if name == "facturx":
            return importlib.import_module("euinvoice.facturx")
        raise AttributeError(f"module 'euinvoice' has no attribute {name!r}")
