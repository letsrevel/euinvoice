"""veraPDF PDF/A-3B on the Factur-X PDFs ``facturx.embed`` writes (``make conformance``, AC of #23; plan §5).

veraPDF is a Java CLI, so it is found through ``$EUINVOICE_VERAPDF`` (a command, e.g. ``scripts/verapdf-docker.sh``,
which runs the pinned ``verapdf/cli`` image) or ``verapdf`` on ``PATH``. Without either the module skips, except
under CI (``$CI`` set), where a missing validator fails instead of passing silently.

One veraPDF run checks every fixture: the synthetic PDF/A-3B input (``tests/_pdfa.py``), a Factur-X PDF per level,
one embedded next to an existing associated file, and a negative control that is not PDF/A, which must fail, so
a validator that passes everything is noticed.
"""

import os
import pathlib
import shlex
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] - runs the veraPDF CLI with a fixed argv
import typing as t
from collections.abc import Callable

import pytest

from _invoices import minimal_invoice
from _pdfa import pdf
from _xrechnung_cases import xrechnung_invoice
from euinvoice import facturx, profiles
from euinvoice.syntax import cii

pytestmark = pytest.mark.conformance

_FLAVOUR: t.Final = "3b"


def _level(profile: profiles.Profile) -> bytes:
    return facturx.embed(pdf(), cii.write(profile.prepare(minimal_invoice())), profile=profile)


FIXTURES: t.Final[dict[str, Callable[[], bytes]]] = {
    "input.pdf": pdf,
    "input-with-attachment.pdf": lambda: pdf(attachment="notes.txt"),
    "facturx-minimum.pdf": lambda: _level(profiles.FACTURX_MINIMUM),
    "facturx-basic-wl.pdf": lambda: _level(profiles.FACTURX_BASIC_WL),
    "facturx-basic.pdf": lambda: _level(profiles.FACTURX_BASIC),
    "facturx-en16931.pdf": lambda: facturx.embed(pdf(), minimal_invoice(), profile=profiles.FACTURX_EN16931),
    "facturx-extended.pdf": lambda: _level(profiles.FACTURX_EXTENDED),
    "facturx-xrechnung.pdf": lambda: facturx.embed(pdf(), xrechnung_invoice(), profile=profiles.FACTURX_XRECHNUNG),
    "facturx-with-attachment.pdf": lambda: facturx.embed(
        pdf(attachment="notes.txt"), minimal_invoice(), profile=profiles.FACTURX_EN16931
    ),
}
"""File name → generator of every PDF that must pass PDF/A-3B."""

_NOT_PDFA: t.Final = "not-pdfa.pdf"


def _verapdf() -> list[str]:
    command = os.environ.get("EUINVOICE_VERAPDF") or shutil.which("verapdf")
    if command:
        return shlex.split(command)
    message = "veraPDF not found: set EUINVOICE_VERAPDF (e.g. to scripts/verapdf-docker.sh) or put verapdf on PATH"
    if os.environ.get("CI"):
        pytest.fail(message)
    pytest.skip(message)


@pytest.fixture(scope="module")
def verdicts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """``{file name: "PASS" | "FAIL"}`` from one veraPDF run (``--format text``: ``PASS <path> 3b`` per file)."""
    command = _verapdf()
    directory = tmp_path_factory.mktemp("verapdf")
    files = {**{name: make() for name, make in FIXTURES.items()}, _NOT_PDFA: pdf(metadata=None)}
    for name, data in files.items():
        (directory / name).write_bytes(data)
    run = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, our own files
        [*command, "--flavour", _FLAVOUR, "--format", "text", "--verbose", *files],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    found = {
        pathlib.PurePosixPath(fields[1]).name: fields[0]
        for fields in (line.split() for line in run.stdout.splitlines())
        if len(fields) == 3 and fields[0] in {"PASS", "FAIL"} and fields[2] == _FLAVOUR
    }
    assert set(found) == set(files), f"veraPDF exit {run.returncode}\n{run.stdout}\n{run.stderr}"
    return {name: f"{verdict}\n{run.stdout}" for name, verdict in found.items()}


@pytest.mark.parametrize("name", list(FIXTURES))
def test_passes_pdfa_3b(verdicts: dict[str, str], name: str) -> None:
    assert verdicts[name].startswith("PASS\n"), verdicts[name]


def test_negative_control_fails(verdicts: dict[str, str]) -> None:
    assert verdicts[_NOT_PDFA].startswith("FAIL\n"), verdicts[_NOT_PDFA]
