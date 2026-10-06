"""Runs the Python examples of the documentation site (``docs/``, issue #33) through ``tests/_markdown_doctest.py``.

Each page runs in its own namespace, in file order. ``validation.md`` and ``facturx.md`` continue from the
quickstart (they use its ``invoice``, ``ubl`` and ``cii``), so they start from a copy of the quickstart's namespace;
``facturx.md`` also gets ``rendered_pdf``, a synthetic blank PDF/A-3B (``tests/_pdfa.py``) standing in for the
output of the reader's PDF renderer. Blocks marked ``<!-- doctest: needs-artifacts -->`` run only in the
conformance suite (``tests/conformance/test_docs_examples.py``).
"""

import pathlib
import typing as t

import _markdown_doctest
from _pdfa import pdf

DOCS: t.Final = pathlib.Path(__file__).resolve().parents[1] / "docs"
PREFIX: t.Final = "doctest"
QUICKSTART: t.Final = "quickstart.md"
CONTINUES_QUICKSTART: t.Final = ("validation.md", "facturx.md")
PAGES: t.Final = (
    QUICKSTART,
    "concepts.md",
    *CONTINUES_QUICKSTART,
    "mapping/freelancer.md",
    "mapping/ticketing.md",
)
"""Every page with a ``python`` block, in run order (``tests/test_docs.py`` checks that none is left out)."""


def pages_with_code() -> set[str]:
    """The pages under ``docs/`` that have at least one ``python`` block."""
    return {
        path.relative_to(DOCS).as_posix()
        for path in DOCS.rglob("*.md")
        if _markdown_doctest.blocks(path, prefix=PREFIX)
    }


def run(*, with_artifacts: bool) -> dict[str, int]:
    """Run every page's examples; skip the blocks that need artifacts unless ``with_artifacts``.

    Returns:
        The number of examples that ran, per page.

    Raises:
        AssertionError: A doctest example or an ``assert`` in a script block failed.
    """
    ran: dict[str, int] = {}
    quickstart: dict[str, t.Any] = {}
    for page in PAGES:
        globs: dict[str, t.Any] = {}
        if page in CONTINUES_QUICKSTART:
            globs = {**quickstart, "rendered_pdf": pdf()}
        ran[page] = _markdown_doctest.run(DOCS / page, globs, prefix=PREFIX, with_artifacts=with_artifacts)
        if page == QUICKSTART:
            quickstart = globs
    return ran
