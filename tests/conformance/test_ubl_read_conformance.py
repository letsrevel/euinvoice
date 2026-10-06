"""The UBL reader against every UBL instance of the pinned corpora (``make conformance``, plan §4 round-trip invariant).

For each UBL file X (classified with ``detect``) of the CEN examples, the Peppol BIS examples and the KoSIT
XRechnung testsuite: X reads, ``read(write(read(X))) == read(X)`` with nothing unmapped the second time, and
``validate(write(read(X)))`` has no fatal or error finding. The unmapped XPaths of each file are printed
(``pytest -m conformance -rP``). Files that cannot be read are listed in :data:`EXCLUDED` with the reason; each
must still fail with a :class:`ParseError` naming that rule. Files that read but break a CEN rule themselves are
listed in :data:`UPSTREAM_INVALID`; their round trip must give exactly the upstream file's blocking findings.
"""

import pathlib
import typing as t

import pytest

from euinvoice import _xml, detect
from euinvoice.errors import ParseError, UnsupportedDocumentError
from euinvoice.syntax import ubl
from euinvoice.validate import artifacts, schematron, validate

pytestmark = pytest.mark.conformance

PEPPOL: t.Final = "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
XRECHNUNG: t.Final = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"

_DIRECTORIES: t.Final[dict[artifacts.SourceName, str]] = {
    "cen-ubl": "examples",
    "peppol-bis": "rules/examples",
    "xrechnung-testsuite": ".",
}

COUNTS: t.Final[dict[str, int]] = {"cen-ubl": 19, "peppol-bis": 10, "xrechnung-testsuite": 45}
"""UBL files per corpus (the UBL buckets of ``test_detect_corpora.py``), so a new upstream file is noticed."""

EXCLUDED: t.Final[dict[str, dict[str, str]]] = {
    # The file breaks a fatal CEN rule (run on the upstream file itself), which the model enforces too (D8 permits
    # refusing what the official CEN Schematron refuses). The value is the rule the ParseError must name.
    "xrechnung-testsuite": {
        # CVD extension: ItemClassificationCode listID="CVD" (BR-CL-13 fatal).
        "instances/technical-cases/cvd/02.01a-cvd_INVOICE_ubl.xml": "BR-CL-13",
    },
}

UPSTREAM_INVALID: t.Final[dict[str, dict[str, set[str]]]] = {
    "xrechnung-testsuite": {
        # XRechnung extension with cac:PrepaidPayment (UBL-CR-470): BT-115 = BT-112 - BT-113 does not hold within
        # EN 16931 core, so the upstream file itself fails BR-CO-16 (fatal) under validate().
        "instances/extension/05.01a-INVOICE_ubl.xml": {"BR-CO-16"},
    },
}

_EXTRA_RULES: t.Final = {PEPPOL: schematron.PEPPOL_UBL, XRECHNUNG: schematron.XRECHNUNG_UBL}
"""The CIUS rule sets that validate() does not run yet (no registered profile, #20 / #21)."""


def _ubl_files(source: artifacts.SourceName) -> list[tuple[str, bytes]]:
    directory: pathlib.Path = artifacts.fetch([source])[source] / _DIRECTORIES[source]
    found = []
    for path in sorted(p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() == ".xml"):
        data = path.read_bytes()
        if _syntax(data) == "ubl":
            found.append((path.relative_to(directory).as_posix(), data))
    return found


def _syntax(data: bytes) -> str | None:
    """The detected syntax; ``None`` for the corpora's non-invoices (``test_detect_corpora.py`` covers them)."""
    try:
        return detect.detect(data).syntax
    except (ParseError, UnsupportedDocumentError):
        return None


def _fatal_or_error(findings: t.Iterable[t.Any]) -> set[str]:
    return {f.rule_id for f in findings if f.severity in ("fatal", "error")}


@pytest.mark.parametrize("source", list(_DIRECTORIES))
def test_every_ubl_file_reads_and_round_trips(source: artifacts.SourceName) -> None:
    files = _ubl_files(source)
    assert len(files) == COUNTS[source]
    excluded = EXCLUDED.get(source, {})
    upstream_invalid = UPSTREAM_INVALID.get(source, {})
    failures: list[str] = []
    for name, data in files:
        if name in excluded:
            with pytest.raises(ParseError, match=excluded[name]):
                ubl.read(_xml.parse(data))
            continue
        first = ubl.read(_xml.parse(data))
        # The per-file report of out-of-model content asked for by plan §4 (shown with -rP or -s).
        print(f"{source}:{name}: {len(first.unmapped)} unmapped", *first.unmapped, sep="\n  ")  # ruff: ignore[print]
        written = ubl.write(first.invoice)
        second = ubl.read(_xml.parse(written))
        if second.invoice != first.invoice:
            failures.append(f"{name}: read(write(read(X))) != read(X)")
        if second.unmapped:
            failures.append(f"{name}: the writer's output has unmapped content {second.unmapped}")
        expected = upstream_invalid.get(name, set())
        if expected:
            assert _fatal_or_error(validate(data).findings) == expected, name  # the exclusion is still true
        found = _fatal_or_error(validate(written).findings)
        if found != expected:
            failures.append(f"{name}: {sorted(found)}")
        extra = _EXTRA_RULES.get(detect.detect(data).specification_identifier or "")
        if extra is not None:
            # ponytail: validate() runs only the CEN rules for Peppol and XRechnung until #20 / #21 register their
            # profiles; until then their UBL rules run here, and the round trip must not add a fatal or error.
            added = _fatal_or_error(schematron.run(extra, written)) - _fatal_or_error(schematron.run(extra, data))
            if added:
                failures.append(f"{name}: {extra.source} {sorted(added)}")
    assert failures == []
