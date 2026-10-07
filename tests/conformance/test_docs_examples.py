"""Every documentation example runs, validation against the official artifacts included (issue #33)."""

import pytest

import _docs
import _markdown_doctest

pytestmark = pytest.mark.conformance


def test_every_docs_example_runs_with_the_official_artifacts() -> None:
    with_artifacts = _docs.run(with_artifacts=True)
    without = _docs.run(with_artifacts=False)
    gated = {
        page
        for page in _docs.PAGES
        if any(
            block.kind == "needs-artifacts"
            for block in _markdown_doctest.blocks(_docs.DOCS / page, prefix=_docs.PREFIX)
        )
    }
    assert gated == {
        "quickstart.md",
        "validation.md",
        "facturx.md",
        "fatturapa.md",
        "mapping/freelancer.md",
        "mapping/ticketing.md",
    }
    assert all(with_artifacts[page] > without[page] for page in gated), (with_artifacts, without)
