"""The committed code lists equal the generator output for the pinned CEN release (``make conformance``)."""

import os
import subprocess  # ruff: ignore[suspicious-subprocess-import] - runs our own generator script with a fixed argv
import sys
from pathlib import Path

import pytest

import gen_codelists

pytestmark = pytest.mark.conformance


def test_committed_generated_module_matches_the_pinned_cen_code_lists() -> None:
    committed = gen_codelists.DEFAULT_OUTPUT.read_text(encoding="utf-8")

    assert gen_codelists.generate() == committed, "stale code lists: run `make codelists`"


@pytest.mark.parametrize("hash_seed", ["1", "2"])
def test_regeneration_is_deterministic_across_hash_seeds(tmp_path: Path, hash_seed: str) -> None:
    # Set iteration order depends on PYTHONHASHSEED; the generated module must not.
    out = tmp_path / "generated.py"
    script = Path(gen_codelists.__file__)
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}

    subprocess.run([sys.executable, str(script), "--output", str(out)], check=True, env=env)  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv

    assert out.read_text(encoding="utf-8") == gen_codelists.DEFAULT_OUTPUT.read_text(encoding="utf-8")
