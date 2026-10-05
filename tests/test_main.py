"""Tests for the ``python -m euinvoice`` CLI stub."""

import runpy
import sys
import typing as t
from pathlib import Path

import pytest

from euinvoice import __main__ as cli
from euinvoice.errors import ArtifactIntegrityError
from euinvoice.validate import artifacts


def test_artifacts_fetch_passes_only_and_prints_paths(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[t.Any] = []

    def fake_fetch(names: t.Any) -> dict[str, Path]:
        calls.append(names)
        return {"cen-ubl": Path("/cache/cen-ubl/1.3.16")}

    monkeypatch.setattr(artifacts, "fetch", fake_fetch)
    assert cli.main(["artifacts", "fetch", "--only", "cen-ubl", "--only", "cen-cii"]) == 0
    assert calls == [["cen-ubl", "cen-cii"]]
    assert capsys.readouterr().out == "cen-ubl: /cache/cen-ubl/1.3.16\n"


def test_artifacts_fetch_without_only_fetches_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[t.Any] = []

    def fake_fetch(names: t.Any) -> dict[str, Path]:
        calls.append(names)
        return {}

    monkeypatch.setattr(artifacts, "fetch", fake_fetch)
    assert cli.main(["artifacts", "fetch"]) == 0
    assert calls == [None]


def test_fetch_error_exits_1_with_message(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def boom(names: t.Any) -> dict[str, Path]:
        raise ArtifactIntegrityError("sha256 mismatch")

    monkeypatch.setattr(artifacts, "fetch", boom)
    assert cli.main(["artifacts", "fetch"]) == 1
    assert capsys.readouterr().err == "error: sha256 mismatch\n"


@pytest.mark.parametrize("argv", [[], ["artifacts"], ["artifacts", "fetch", "--only", "nope"]])
def test_usage_errors_exit_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2


def test_module_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(artifacts, "fetch", lambda names: {})
    monkeypatch.setattr(sys, "argv", ["euinvoice", "artifacts", "fetch"])
    monkeypatch.delitem(sys.modules, "euinvoice.__main__")
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("euinvoice", run_name="__main__")
    assert exc.value.code == 0
