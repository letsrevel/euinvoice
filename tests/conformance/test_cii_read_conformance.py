"""The CII reader against every CII instance of the pinned corpora (``make conformance``, plan §4 round-trip invariant).

For each CII file X (classified with ``detect``) of the CEN examples, the KoSIT XRechnung testsuite and the ZUGFeRD
corpus: X reads, ``read(write(read(X))) == read(X)``, and ``validate(write(read(X)))`` has no fatal or error
finding. The unmapped XPaths of each file are printed (``pytest -m conformance -rP``). Files that cannot be read are
listed in :data:`EXCLUDED` with the reason; each must still fail with a :class:`ParseError` naming that reason.
"""

import pathlib
import typing as t

import pytest

from euinvoice import _xml, detect
from euinvoice.errors import ParseError, UnsupportedDocumentError
from euinvoice.syntax import cii
from euinvoice.validate import artifacts, schematron, validate

pytestmark = pytest.mark.conformance

XRECHNUNG: t.Final = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"

_DIRECTORIES: t.Final[dict[artifacts.SourceName, str]] = {
    "cen-cii": "examples",
    "xrechnung-testsuite": ".",
    "zugferd-corpus": ".",
}

COUNTS: t.Final[dict[str, int]] = {"cen-cii": 15, "xrechnung-testsuite": 41, "zugferd-corpus": 42}
"""CII files per corpus (the CII buckets of ``test_detect_corpora.py``), so a new upstream file is noticed."""

EXCLUDED: t.Final[dict[str, dict[str, str]]] = {
    # Each file breaks a fatal CEN rule (run on the upstream file itself), which the model enforces too (D8 permits
    # refusing what the official CEN Schematron refuses). The value is the rule the ParseError must name.
    "xrechnung-testsuite": {
        # XRechnung extension: GlobalID schemeID="XR03" (BR-CL-10, BR-CL-21 fatal).
        "instances/extension/04.05a-INVOICE_uncefact.xml": "BR-CL-10",
        # CVD extension: ClassCode listID="CVD" (BR-CL-13 fatal).
        "instances/technical-cases/cvd/02.01a-cvd_INVOICE_uncefact.xml": "BR-CL-13",
    },
    "zugferd-corpus": {
        # URIID schemeID="9958" is not in the pinned CEF EAS list (BR-CL-25 fatal).
        "XML-Rechnung/CII/EN16931_ElektronischeAdresse.cii.xml": "BR-CL-25",
        "XML-Rechnung/CII/EN16931_RechnungsUebertragung.cii.xml": "BR-CL-25",
        # Malware-test sample with empty country codes (BR-09, BR-11, BR-CL-14 fatal).
        "other/eicar.cii.xml": "BR-CL-14",
    },
}


TWO_CREDIT_TRANSFERS: t.Final[dict[str, tuple[str, ...]]] = {
    # A second payment means without ram:Information is the same BG-16 (CII-SR-467/468 count only present
    # elements), so its account is a second BG-17; the UBL twin of 03.07a carries both accounts too.
    "xrechnung-testsuite:instances/standard/03.07a-INVOICE_uncefact.xml": (
        "DE79000000001234567890",
        "DE16000000002345678901",
    ),
    "cen-cii:CII_example5.xml": ("DK1212341234123412", "A"),
}
"""Upstream files whose payment means carry two credit transfers (BG-17), with their BT-84 values."""


def _cii_files(source: artifacts.SourceName) -> list[tuple[str, bytes]]:
    directory: pathlib.Path = artifacts.fetch([source])[source] / _DIRECTORIES[source]
    found = []
    for path in sorted(p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() == ".xml"):
        data = path.read_bytes()
        if _syntax(data) == "cii":
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
def test_every_cii_file_reads_and_round_trips(source: artifacts.SourceName) -> None:
    files = _cii_files(source)
    assert len(files) == COUNTS[source]
    excluded = EXCLUDED.get(source, {})
    failures: list[str] = []
    for name, data in files:
        if name in excluded:
            # D8: the model refuses only what the official CEN rules refuse, so the rule is fatal upstream too.
            fatal = {f.rule_id for f in validate(data).findings if f.severity == "fatal"}
            assert excluded[name] in fatal, (name, sorted(fatal))
            with pytest.raises(ParseError, match=excluded[name]):
                cii.read(_xml.parse(data))
            continue
        first = cii.read(_xml.parse(data))
        transfers = TWO_CREDIT_TRANSFERS.get(f"{source}:{name}")
        if transfers is not None:
            instructions = first.invoice.payment_instructions
            found = () if instructions is None else instructions.credit_transfers
            assert tuple(c.payment_account_identifier for c in found) == transfers, name
        # The per-file report of out-of-model content asked for by plan §4 (shown with -rP or -s).
        print(f"{source}:{name}: {len(first.unmapped)} unmapped", *first.unmapped, sep="\n  ")  # ruff: ignore[print]
        written = cii.write(first.invoice)
        if cii.read(_xml.parse(written)).invoice != first.invoice:
            failures.append(f"{name}: read(write(read(X))) != read(X)")
        report = validate(written)
        if not report.ok:
            failures.append(f"{name}: {sorted(_fatal_or_error(report.findings))}")
        if detect.detect(data).specification_identifier == XRECHNUNG:
            # ponytail: validate() runs only the CEN rules for XRechnung until #21 registers its profile; until
            # then the XRechnung CII rules run here, and the round trip must not add a fatal or error finding.
            added = _fatal_or_error(schematron.run(schematron.XRECHNUNG_CII, written)) - _fatal_or_error(
                schematron.run(schematron.XRECHNUNG_CII, data)
            )
            if added:
                failures.append(f"{name}: XRechnung {sorted(added)}")
    assert failures == []
