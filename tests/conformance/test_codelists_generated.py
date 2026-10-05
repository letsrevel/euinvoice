"""The committed code lists equal the generator output for the pinned CEN release (``make conformance``)."""

from pathlib import Path

import pytest

import gen_codelists

pytestmark = pytest.mark.conformance


def test_committed_generated_module_matches_the_pinned_cen_code_lists() -> None:
    committed = gen_codelists.DEFAULT_OUTPUT.read_text(encoding="utf-8")

    assert gen_codelists.generate() == committed, "stale code lists: run `make codelists`"


def test_regeneration_is_deterministic(tmp_path: Path) -> None:
    first, second = tmp_path / "first.py", tmp_path / "second.py"

    assert gen_codelists.main(["--output", str(first)]) == 0
    assert gen_codelists.main(["--output", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()
