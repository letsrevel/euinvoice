"""The UBL reader against every UBL instance of the pinned corpora (``make conformance``, plan §4 round-trip invariant).

For each UBL file X (classified with ``detect``) of the CEN examples, the Peppol BIS examples and the KoSIT
XRechnung testsuite: X reads, ``read(write(read(X))) == read(X)`` with nothing unmapped the second time, and
``validate(write(read(X)))`` has no fatal or error finding. The unmapped XPaths of each file are printed
(``pytest -m conformance -rP``). Files that cannot be read are listed in :data:`EXCLUDED` with the reason; each
must still fail with a :class:`ParseError` naming that rule. Files that read but break a CEN rule themselves are
listed in :data:`UPSTREAM_INVALID`; their round trip must give exactly the upstream file's blocking findings, plus
any rule listed in :data:`LOST_WITH_UNMAPPED` (one that needs content the reader reported as unmapped).
"""

import pathlib
import typing as t

import pytest

from euinvoice import _xml, detect
from euinvoice.errors import ParseError, UnsupportedDocumentError
from euinvoice.syntax import ubl
from euinvoice.validate import artifacts, validate

pytestmark = pytest.mark.conformance


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
    "cen-ubl": {
        # Peppol BT-24: its placeholder Swedish organisation numbers (schemeID 0007, e.g. "1234567890") fail the
        # check digit of PEPPOL-COMMON-R049 (fatal), which validate() runs under the Peppol profile (#64).
        "issue116.xml": {"PEPPOL-COMMON-R049"},
    },
    "xrechnung-testsuite": {
        # XRechnung extension with cac:PrepaidPayment (UBL-CR-470): BT-115 = BT-112 - BT-113 does not hold within
        # EN 16931 core, so the upstream file itself fails BR-CO-16 (fatal) under validate().
        "instances/extension/05.01a-INVOICE_ubl.xml": {"BR-CO-16"},
    },
}

LOST_WITH_UNMAPPED: t.Final[dict[str, dict[str, set[str]]]] = {
    "xrechnung-testsuite": {
        # BR-DEX-09 (XRechnung extension, fatal) adds the third party payments BT-DEX-002 to BT-115. They are
        # cac:PrepaidPayment, outside EN 16931, so the reader reports them unmapped and write(read(X)) lacks them.
        "instances/extension/05.01a-INVOICE_ubl.xml": {"BR-DEX-09"},
    },
}
"""Rules the round trip fails only because content outside the model (reported in ``unmapped``) is not written."""


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
            # D8: the model refuses only what the official CEN rules refuse, so the rule is fatal upstream too.
            fatal = {f.rule_id for f in validate(data).findings if f.severity == "fatal"}
            assert excluded[name] in fatal, (name, sorted(fatal))
            with pytest.raises(ParseError, match=excluded[name]):
                ubl.read(_xml.parse(data))
            continue
        first = ubl.read(_xml.parse(data))
        # The per-file report of out-of-model content asked for by plan §4 (shown with -rP or -s).
        print(f"{source}:{name}: {len(first.unmapped)} unmapped", *first.unmapped, sep="\n  ")  # ruff: ignore[print] - the per-file report plan §4 asks for
        written = ubl.write(first.invoice)
        second = ubl.read(_xml.parse(written))
        if second.invoice != first.invoice:
            failures.append(f"{name}: read(write(read(X))) != read(X)")
        if second.unmapped:
            failures.append(f"{name}: the writer's output has unmapped content {second.unmapped}")
        expected = upstream_invalid.get(name, set())
        if expected:
            assert _fatal_or_error(validate(data).findings) == expected, name  # the exclusion is still true
        expected = expected | LOST_WITH_UNMAPPED.get(source, {}).get(name, set())
        # validate() runs the CEN rules plus those of the BT-24 profile (Peppol #64, XRechnung #21).
        found = _fatal_or_error(validate(written).findings)
        if found != expected:
            failures.append(f"{name}: {sorted(found)}")
    assert failures == []
