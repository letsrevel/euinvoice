"""The round-trip invariant over every upstream invoice of the pinned corpora (``make conformance``, plan §4, §8 9.1).

For each sample X (:func:`_corpus.samples`: CEN UBL/CII, Peppol BIS, the KoSIT XRechnung testsuite, the ZUGFeRD
corpus XML and the XML embedded in its Factur-X PDFs):

- ``validate(X)`` has no fatal or error finding: the upstream file is valid;
- X reads, ``read(write(read(X))) == read(X)``, and the second read has nothing unmapped;
- ``validate(write(read(X)))`` has no fatal or error finding.

The samples that do not hold are listed in ``expected_invalid.toml``, the single source of truth, each with the
exact rule ids it must fail with (never skipped). The unmapped XPaths of each sample are printed (``-rP``).

Validation profile: the one ``detect`` finds from BT-24 (EN 16931 core when none), and for a PDF the one its XMP
``fx:ConformanceLevel`` selects. Factur-X levels without pinned rules refuse validation (#42); for those the
harness asserts the refusal and runs the EN 16931 core rules explicitly.
"""

import collections
import re
import typing as t

import pydantic
import pytest
from _corpus import Sample, expected_invalid, facturx_pdfs, samples
from test_detect_corpora import EXCLUDED as NOT_INVOICES

from euinvoice import _xml, detect, profiles
from euinvoice.errors import ArtifactsNotAvailableError, ParseError, UnsupportedDocumentError
from euinvoice.model import Invoice, bt_id
from euinvoice.profiles._base import FACTURX_RULE_SET
from euinvoice.report import Finding
from euinvoice.syntax import cii, ubl
from euinvoice.syntax.result import ParseResult
from euinvoice.validate import artifacts, validate

pytestmark = pytest.mark.conformance

SAMPLES: t.Final = samples()

COUNTS: t.Final[dict[tuple[str, str], int]] = {
    ("cen-ubl", "ubl"): 19,
    ("cen-cii", "cii"): 15,
    ("peppol-bis", "ubl"): 10,
    ("xrechnung-testsuite", "ubl"): 45,
    ("xrechnung-testsuite", "cii"): 41,
    ("zugferd-corpus", "ubl"): 31,
    ("zugferd-corpus", "cii"): 42,
    ("zugferd-corpus", "not an invoice"): 15,
    ("zugferd-corpus", "pdf"): 74,
}
"""Samples per corpus and kind (the buckets of ``test_detect_corpora.py``), so a new upstream file is noticed."""

_NAMED_ID: t.Final = re.compile(r"\b(?:BR|BT|BG|PEPPOL|UBL|CII)-[A-Z0-9-]*[0-9]\b")
"""A rule, BT or BG id as a ``ParseError`` message names it (CLAUDE.md: error messages cite BT/BG/rule ids)."""

TWO_CREDIT_TRANSFERS: t.Final[dict[str, tuple[str, ...]]] = {
    # A second payment means without ram:Information is the same BG-16 (CII-SR-467/468 count only present
    # elements), so its account is a second BG-17; the UBL twin of 03.07a carries both accounts too.
    "xrechnung-testsuite:instances/standard/03.07a-INVOICE_uncefact.xml": (
        "DE79000000001234567890",
        "DE16000000002345678901",
    ),
    "cen-cii:examples/CII_example5.xml": ("DK1212341234123412", "A"),
}
"""Upstream files whose payment means carry two credit transfers (BG-17), with their BT-84 values."""

TOO_LARGE: t.Final[frozenset[str]] = frozenset(
    f"zugferd-corpus:PEPPOL/Valid/Qvalia/Large_Invoice_sample{n}.xml" for n in (1, 2)
)
"""Peppol stress samples (25 MB and 61 MB) beyond the time budget of the suite: ``validate`` of sample1 alone takes
about 300 s and its read did not finish in 30 min (measured 2026-10-06). ponytail: they are only classified here
(Peppol UBL); the ceiling is the reader's and Saxon's cost on very large inputs, the upgrade path issue #80."""


def _kind(sample: Sample) -> str:
    if sample.level is not None:
        return "pdf"
    try:
        return detect.detect(sample.data()).syntax
    except (ParseError, UnsupportedDocumentError):
        return "not an invoice"


def _read(data: bytes) -> ParseResult:
    root = _xml.parse(data)
    return ubl.read(root) if detect.detect_root(root).syntax == "ubl" else cii.read(root)


def _write(syntax: str, invoice: Invoice) -> bytes:
    return ubl.write(invoice) if syntax == "ubl" else cii.write(invoice)


def _profile(sample: Sample, data: bytes) -> profiles.Profile:
    if sample.level is not None:
        return profiles.by_conformance_level(sample.level)
    return detect.detect(data).profile or profiles.EN16931


def _blocking(data: bytes, profile: profiles.Profile) -> list[Finding]:
    """Fatal and error findings of ``validate(data)``; Factur-X levels without pinned rules (#42) get core rules."""
    if FACTURX_RULE_SET in profile.rule_sets:
        with pytest.raises(ArtifactsNotAvailableError, match="issues/42"):
            validate(data, profile)
        profile = profiles.EN16931
    return [f for f in validate(data, profile).findings if f.severity in ("fatal", "error")]


def _assert_blocking(findings: list[Finding], expected: frozenset[str]) -> None:
    """The findings' rule ids are exactly ``expected``; on a mismatch, show ``(rule_id, message)`` for the reason."""
    found = frozenset(f.rule_id for f in findings)
    assert found == expected, sorted({(f.rule_id, f.message) for f in findings})


def test_every_corpus_is_complete() -> None:
    artifacts.fetch(["cen-ubl", "cen-cii", "peppol-bis", "xrechnung-testsuite", "zugferd-corpus"])
    found = collections.Counter((sample.source, _kind(sample)) for sample in samples())
    assert dict(found) == COUNTS
    assert len(SAMPLES) == sum(COUNTS.values())  # the parametrization below was not vacuous


def test_every_expected_invalid_entry_names_a_sample() -> None:
    entries = set(expected_invalid())
    assert entries <= {sample.id for sample in samples()}
    # Samples the harness only classifies never have an entry.
    not_invoices = {f"{source}:{file}" for source, files in NOT_INVOICES.items() for file in files}
    assert entries.isdisjoint(TOO_LARGE | not_invoices)


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda sample: sample.id)
def test_round_trip_invariant(sample: Sample) -> None:
    data = sample.data()
    not_invoice = NOT_INVOICES.get(sample.source, {}).get(sample.file)
    if not_invoice is not None:
        # Not an EN 16931 invoice (FatturaPA): detect refuses it, as test_detect_corpora.py documents.
        with pytest.raises(not_invoice):
            detect.detect(data)
        return
    if sample.id in TOO_LARGE:
        assert len(data) > 20_000_000
        assert detect.detect(data).profile is profiles.PEPPOL
        return
    profile = _profile(sample, data)
    expected = expected_invalid().get(sample.id)
    upstream = frozenset() if expected is None else expected.upstream
    _assert_blocking(_blocking(data, profile), upstream)
    if expected is not None and expected.outcome == "parse-error":
        with pytest.raises(ParseError) as error:
            _read(data)
        assert frozenset(_NAMED_ID.findall(str(error.value))) == expected.rules, str(error.value)
        return
    first = _read(data)
    # The per-file report of out-of-model content asked for by plan §4 (shown with -rP or -s).
    print(f"{sample.id}: {len(first.unmapped)} unmapped", *first.unmapped, sep="\n  ")  # ruff: ignore[print] - the per-file report plan §4 asks for
    written = _write(detect.detect(data).syntax, first.invoice)
    second = _read(written)
    assert _differs(first.invoice, second.invoice) == (frozenset() if expected is None else expected.differs)
    assert second.unmapped == ()
    _assert_blocking(_blocking(written, profile), frozenset() if expected is None else expected.rules)


def _differs(first: pydantic.BaseModel, second: pydantic.BaseModel) -> frozenset[str]:
    """The BT/BG ids (else the names) of the innermost fields that differ; empty iff equal.

    Groups and repeated groups of equal length are compared field by field, so a difference is named by its BT
    (e.g. BT-148 rather than BG-25); anything else (a term, a group present on one side only, a repeated group of
    another length) is named by its own id.
    """
    found: set[str] = set()
    for name in type(first).model_fields:
        a, b = getattr(first, name), getattr(second, name)
        if a == b:
            continue
        if isinstance(a, pydantic.BaseModel) and isinstance(b, pydantic.BaseModel):
            found |= _differs(a, b)
        elif (
            isinstance(a, tuple)
            and isinstance(b, tuple)
            and len(a) == len(b)
            and a
            and isinstance(a[0], pydantic.BaseModel)
        ):
            found |= {term for x, y in zip(a, b, strict=True) for term in _differs(x, y)}
        else:
            found.add(bt_id(type(first), name) or name)
    assert bool(found) == (first != second)
    return frozenset(found)


@pytest.mark.parametrize("sample", list(TWO_CREDIT_TRANSFERS))
def test_two_credit_transfers_are_two_bg17(sample: str) -> None:
    source, file = sample.split(":", 1)
    data = Sample(t.cast(artifacts.SourceName, source), file).data()
    instructions = _read(data).invoice.payment_instructions
    found = () if instructions is None else instructions.credit_transfers
    assert tuple(c.payment_account_identifier for c in found) == TWO_CREDIT_TRANSFERS[sample]


def test_extended_content_stays_visible() -> None:
    # EXTENDED content beyond EN 16931 is reported as unmapped, never dropped (plan §1).
    extended = [
        pdf
        for pdf in facturx_pdfs()
        if pdf.level == "EXTENDED" and f"zugferd-corpus:{pdf.name}" not in expected_invalid()
    ]
    assert extended
    assert all(_read(pdf.xml).unmapped for pdf in extended)
