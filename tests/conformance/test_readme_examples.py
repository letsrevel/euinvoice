"""Every README usage example runs, validation against the official artifacts included (#27 AC)."""

import pytest

import _readme

pytestmark = pytest.mark.conformance


def test_every_readme_example_runs() -> None:
    assert _readme.run(with_artifacts=True) == 13
