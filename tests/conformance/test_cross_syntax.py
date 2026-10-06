"""Cross-syntax round trip over every upstream invoice of the pinned corpora (``make conformance``, issue #30).

For each sample X that reads (:func:`_corpus.samples`; the harness ``test_corpus_harness.py`` covers the rest), in
syntax S with the other syntax T:

- ``read_T(write_T(read_S(X)))`` has nothing unmapped and equals ``read_S(X)`` up to the writer normalizations of T
  that ``docs/reference/bt-mapping.md`` documents (:func:`_as_written`), and no other difference;
- ``validate(write_T(read_S(X)))`` has no fatal or error finding.

UBL → CII is the direction issue #30 names; CII → UBL runs under the same rules. The round trip is our own, not the
upstream UBL/CII twins: the twins differ in content upstream (issue #30, comment of the PR #65 spec audit).

The exceptions are the ``[[cross_syntax]]`` section of ``expected_invalid.toml``, each asserted exactly: a writer
refusal (``refuses``, a documented gap of T: the ``ModelError`` names exactly the listed ids) or the exact blocking
rule ids of the T output and, for a tracked gap, the exact BT ids that differ (``reads``).

Validation profile of the T output: the profile of X (as in the harness) when it supports T and has pinned rules,
else EN 16931 core. Peppol BIS pins both ``PEPPOL-EN16931-UBL.sch`` and ``PEPPOL-EN16931-CII.sch`` (peppol-bis
3.0.21), so the CII output of a Peppol sample runs the CEN and Peppol CII rules. The Factur-X levels are CII only (and
their Schematron is not pinned, #42), so their UBL output runs the CEN UBL rules.
"""

import collections
import re
import typing as t

import pytest
from _corpus import Sample, cross_syntax, expected_invalid, samples
from test_corpus_harness import TOO_LARGE, _assert_blocking, _differs, _profile, _read, _write
from test_detect_corpora import EXCLUDED as NOT_INVOICES

from _strategies import cii_normalized
from euinvoice import _xml, profiles
from euinvoice.detect import detect_root
from euinvoice.errors import ModelError
from euinvoice.model import Invoice, InvoiceLine, PriceDetails
from euinvoice.profiles._base import FACTURX_RULE_SET
from euinvoice.syntax import Syntax
from euinvoice.validate import artifacts, validate

pytestmark = pytest.mark.conformance

SAMPLES: t.Final = samples()

COUNTS: t.Final[dict[tuple[Syntax, str], int]] = {
    (Syntax.UBL, "lossless"): 92,
    (Syntax.UBL, "normalized"): 5,
    (Syntax.UBL, "refuses"): 2,
    (Syntax.CII, "lossless"): 74,
    (Syntax.CII, "normalized"): 71,
    (Syntax.CII, "refuses"): 6,
}
"""Outcomes per source syntax: ``lossless`` (equal without normalization), ``normalized`` (equal after
:func:`_as_written`), ``differs`` (a ``differs`` entry of ``expected_invalid.toml``), ``refuses`` (a documented
writer gap). Pinned so that the parametrized test is not vacuous and a change of the corpora or the mappers is
noticed."""

_NAMED_ID: t.Final = re.compile(r"\b(?:BR|BT|BG)-[A-Z0-9-]*[0-9]\b")
"""A BT, BG or rule id as a ``ModelError`` message names it (CLAUDE.md: error messages cite BT/BG/rule ids)."""


def _other(syntax: Syntax) -> Syntax:
    return Syntax.CII if syntax == Syntax.UBL else Syntax.UBL


def _as_written(invoice: Invoice, syntax: Syntax) -> Invoice:
    """What ``read(write(invoice))`` in ``syntax`` returns: ``invoice`` with that writer's documented normalizations.

    ``docs/reference/bt-mapping.md`` "Normalizations"; any other difference fails:

    * CII: :func:`_strategies.cii_normalized` (empty BG-1, BG-13, BG-19 dropped, BT-29 without a scheme first, and a
      BT-147 without BT-148 gains BT-148 = BT-146 + BT-147: the D16B ``TradePriceType`` requires
      ``ram:ChargeAmount``; PEPPOL-EN16931-R046);
    * UBL: a BT-148 without BT-147 gains BT-147 = BT-148 - BT-146 (``cbc:Amount`` is mandatory in the UBL 2.1
      ``AllowanceChargeType``; PEPPOL-EN16931-R046).
    """
    if syntax == Syntax.CII:
        return cii_normalized(invoice)

    def price(details: PriceDetails) -> PriceDetails:
        gross, discount = details.item_gross_price, details.item_price_discount
        if gross is not None and discount is None:
            discount = gross - details.item_net_price
        return PriceDetails.model_validate({**dict(details), "item_price_discount": discount})

    lines = tuple(
        InvoiceLine.model_validate({**dict(line), "price_details": price(line.price_details)}) for line in invoice.lines
    )
    return Invoice.model_validate({**dict(invoice), "lines": lines})


def _target_profile(sample: Sample, data: bytes, target: Syntax) -> profiles.Profile:
    """The source sample's profile if it supports ``target`` with pinned rules, else EN 16931 core."""
    profile = _profile(sample, data)
    if target in profile.syntaxes and FACTURX_RULE_SET not in profile.rule_sets:
        return profile
    return profiles.EN16931


def _skipped_by_harness(sample: Sample) -> bool:
    """Samples that never read (not invoices, too large, or a documented ``parse-error``): the harness asserts them."""
    expected = expected_invalid().get(sample.id)
    return (
        sample.file in NOT_INVOICES.get(sample.source, {})
        or sample.id in TOO_LARGE
        or (expected is not None and expected.outcome == "parse-error")
    )


def _target(data: bytes) -> Syntax:
    """The syntax other than the one of ``data``."""
    return _other(detect_root(_xml.parse(data)).syntax)


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda sample: sample.id)
def test_cross_syntax_round_trip(sample: Sample) -> None:
    expected = cross_syntax().get(sample.id)
    if _skipped_by_harness(sample):
        assert expected is None
        return
    data = sample.data()
    target = _target(data)
    first = _read(data).invoice
    if expected is not None and expected.outcome == "refuses":
        with pytest.raises(ModelError) as error:
            _write(target, first)
        assert frozenset(_NAMED_ID.findall(str(error.value))) == expected.rules, str(error.value)
        return
    written = _write(target, first)
    second = _read(written)
    assert second.unmapped == ()
    assert _differs(_as_written(first, target), second.invoice) == (
        frozenset() if expected is None else expected.differs
    )
    blocking = [
        finding
        for finding in validate(written, _target_profile(sample, data, target)).findings
        if finding.severity in ("fatal", "error")
    ]
    _assert_blocking(blocking, frozenset() if expected is None else expected.rules)


def test_every_cross_syntax_entry_names_a_sample_that_reads() -> None:
    readable = {sample.id for sample in samples() if not _skipped_by_harness(sample)}
    assert set(cross_syntax()) <= readable


def test_outcome_counts() -> None:
    """All samples in one process give :data:`COUNTS`, so the parametrized test is not vacuous."""
    artifacts.fetch(["cen-ubl", "cen-cii", "peppol-bis", "xrechnung-testsuite", "zugferd-corpus"])
    found: collections.Counter[tuple[Syntax, str]] = collections.Counter()
    for sample in samples():
        if _skipped_by_harness(sample):
            continue
        data = sample.data()
        target = _target(data)
        source = _other(target)
        first = _read(data).invoice
        try:
            second = _read(_write(target, first)).invoice
        except ModelError:
            found[source, "refuses"] += 1
            continue
        if second == first:
            found[source, "lossless"] += 1
        else:
            found[source, "normalized" if second == _as_written(first, target) else "differs"] += 1
    assert dict(found) == COUNTS
