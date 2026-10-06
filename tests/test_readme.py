"""The README usage examples run (#27 AC); ``tests/conformance/test_readme_examples.py`` runs validation too."""

import _readme


def test_the_readme_has_its_three_example_blocks() -> None:
    assert [needs_artifacts for needs_artifacts, _ in _readme.blocks()] == [False, True, False]


def test_the_readme_examples_run_without_artifacts() -> None:
    assert _readme.run(with_artifacts=False) == 10
