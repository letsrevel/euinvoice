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
from collections.abc import Callable

import pytest
from _corpus import Sample, cross_syntax, expected_invalid, samples
from lxml import etree
from pydantic import BaseModel
from test_corpus_harness import TOO_LARGE, _assert_blocking, _profile
from test_detect_corpora import EXCLUDED as NOT_INVOICES

from euinvoice import _xml, detect, profiles
from euinvoice.errors import ModelError
from euinvoice.model import Invoice, InvoiceLine, PriceDetails, bt_id
from euinvoice.profiles._base import FACTURX_RULE_SET
from euinvoice.syntax import Syntax, cii, ubl
from euinvoice.syntax.result import ParseResult
from euinvoice.validate import artifacts, validate

pytestmark = pytest.mark.conformance

SAMPLES: t.Final = samples()

COUNTS: t.Final[dict[tuple[Syntax, str], int]] = {
    (Syntax.UBL, "lossless"): 92,
    (Syntax.UBL, "normalized"): 5,
    (Syntax.UBL, "refuses"): 2,
    (Syntax.CII, "lossless"): 74,
    (Syntax.CII, "normalized"): 70,
    (Syntax.CII, "differs"): 1,
    (Syntax.CII, "refuses"): 6,
}
"""Outcomes per source syntax: ``lossless`` (equal without normalization), ``normalized`` (equal after
:func:`_as_written`), ``differs`` (a ``differs`` entry of ``expected_invalid.toml``), ``refuses`` (a documented
writer gap). Pinned so that the parametrized test is not vacuous and
a change of the corpora or the mappers is noticed."""

_NAMED_ID: t.Final = re.compile(r"\b(?:BR|BT|BG)-[A-Z0-9-]*[0-9]\b")
"""A BT, BG or rule id as a ``ModelError`` message names it (CLAUDE.md: error messages cite BT/BG/rule ids)."""

type Codec = tuple[Syntax, Callable[[Invoice], bytes], Callable[[etree._Element], ParseResult]]

CODECS: t.Final[dict[Syntax, Codec]] = {
    Syntax.UBL: (Syntax.UBL, ubl.write, ubl.read),
    Syntax.CII: (Syntax.CII, cii.write, cii.read),
}


def _other(syntax: Syntax) -> Syntax:
    return Syntax.CII if syntax == Syntax.UBL else Syntax.UBL


def _as_written(invoice: Invoice, syntax: Syntax) -> Invoice:
    """What ``read(write(invoice))`` in ``syntax`` returns: ``invoice`` with that writer's documented normalizations.

    ``docs/reference/bt-mapping.md`` "Normalizations" (the only ones the corpora reach; any other difference fails):

    * CII: a BT-147 without BT-148 gains BT-148 = BT-146 + BT-147 (the D16B ``TradePriceType`` requires
      ``ram:ChargeAmount`` on the gross price that carries the discount; PEPPOL-EN16931-R046);
    * UBL: a BT-148 without BT-147 gains BT-147 = BT-148 - BT-146 (``cbc:Amount`` is mandatory in the UBL 2.1
      ``AllowanceChargeType``; PEPPOL-EN16931-R046).
    """

    def price(details: PriceDetails) -> PriceDetails:
        net, discount, gross = details.item_net_price, details.item_price_discount, details.item_gross_price
        if syntax == Syntax.CII and discount is not None and gross is None:
            gross = net + discount
        if syntax == Syntax.UBL and gross is not None and discount is None:
            discount = gross - net
        return PriceDetails.model_validate(
            {**dict(details), "item_price_discount": discount, "item_gross_price": gross}
        )

    lines = tuple(
        InvoiceLine.model_validate({**dict(line), "price_details": price(line.price_details)}) for line in invoice.lines
    )
    return Invoice.model_validate({**dict(invoice), "lines": lines})


def _differs(first: BaseModel, second: BaseModel) -> frozenset[str]:
    """The BT/BG ids (else the field names) of the innermost fields where ``first`` and ``second`` differ."""
    found: set[str] = set()
    for name in type(first).model_fields:
        a, b = getattr(first, name), getattr(second, name)
        if a == b:
            continue
        if isinstance(a, BaseModel) and isinstance(b, BaseModel):
            found |= _differs(a, b)
        elif isinstance(a, tuple) and isinstance(b, tuple) and len(a) == len(b) and a and isinstance(a[0], BaseModel):
            found |= {term for x, y in zip(a, b, strict=True) for term in _differs(x, y)}
        else:
            found.add(bt_id(type(first), name) or name)
    return frozenset(found)


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


def _read_source(data: bytes) -> tuple[Invoice, Codec]:
    """``read_S(data)`` and the writer and reader of the other syntax T."""
    root = _xml.parse(data)
    if detect.detect_root(root).syntax == Syntax.UBL:
        return ubl.read(root).invoice, CODECS[Syntax.CII]
    return cii.read(root).invoice, CODECS[Syntax.UBL]


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda sample: sample.id)
def test_cross_syntax_round_trip(sample: Sample) -> None:
    expected = cross_syntax().get(sample.id)
    if _skipped_by_harness(sample):
        assert expected is None
        return
    data = sample.data()
    first, (target, write, read) = _read_source(data)
    if expected is not None and expected.outcome == "refuses":
        with pytest.raises(ModelError) as error:
            write(first)
        assert frozenset(_NAMED_ID.findall(str(error.value))) == expected.rules, str(error.value)
        return
    written = write(first)
    second = read(_xml.parse(written))
    assert second.unmapped == ()
    normalized = _as_written(first, target)
    differs = frozenset() if expected is None else expected.differs
    assert _differs(normalized, second.invoice) == differs
    assert (second.invoice == normalized) == (not differs)
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
        first, (target, write, read) = _read_source(sample.data())
        source = _other(target)
        try:
            second = read(_xml.parse(write(first))).invoice
        except ModelError:
            found[source, "refuses"] += 1
            continue
        if second == first:
            found[source, "lossless"] += 1
        else:
            found[source, "normalized" if second == _as_written(first, target) else "differs"] += 1
    assert dict(found) == COUNTS
