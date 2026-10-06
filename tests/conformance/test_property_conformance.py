"""Property: invoices built through ``calc.complete`` pass the official rules of their profile (issue #31, plan §7).

Each invoice drawn by :func:`_property_drafts.invoices` for a profile is prepared with
:meth:`~euinvoice.profiles.Profile.prepare` (BT-24, BT-23, BT-119 = 0 on O breakdowns where required), written
in UBL and in CII and validated with :func:`euinvoice.validate.validate` against the pinned XSD and the
profile's Schematron rule sets (EN 16931: CEN; Peppol BIS: CEN, Peppol; XRechnung: CEN, XRechnung): no
``fatal`` or ``error`` finding is allowed (``ValidationReport.ok``), and neither from the profile's pre-flight
checks. The round trip half of the
property runs without artifacts in ``tests/syntax/test_round_trip_properties.py``.

Hypothesis settings: :data:`MAX_EXAMPLES` examples per (profile, syntax), no deadline (the profiles in
``tests/conftest.py``), and ``derandomize=True`` so a CI failure reproduces locally with the same examples. A
validation takes about 5-80 ms on an idle laptop: 300 examples per test took about 45 s for all 6 tests run
serially (stylesheet compilation included). 200 leaves headroom for slower CI runners; ``pytest -n auto``
spreads the 6 tests.
"""

import typing as t

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from _invoices import minimal_invoice, rebuild
from _property_drafts import TARGETS, Target, invoices
from euinvoice import profiles
from euinvoice.model import Invoice
from euinvoice.report import Severity
from euinvoice.syntax import Syntax, cii, ubl
from euinvoice.validate import validate

pytestmark = pytest.mark.conformance

MAX_EXAMPLES: t.Final = 200
"""Examples per (profile, syntax); see the module docstring for the time budget."""

WRITERS: t.Final = {Syntax.UBL: ubl.write, Syntax.CII: cii.write}
BLOCKING: t.Final = (Severity.FATAL, Severity.ERROR)


@pytest.mark.parametrize("syntax", list(WRITERS))
@pytest.mark.parametrize("target", TARGETS, ids=lambda target: target.profile.id)
@settings(max_examples=MAX_EXAMPLES, derandomize=True)
@given(data=st.data())
def test_invoices_validate(target: Target, syntax: Syntax, data: st.DataObject) -> None:
    invoice: Invoice = target.profile.prepare(data.draw(invoices(target)))
    report = validate(WRITERS[syntax](invoice), target.profile)
    assert [f for f in report.findings if f.severity in BLOCKING] == []
    assert report.ok
    # D8: the profile's pre-flight never reports a blocking finding the official rules do not.
    assert [f for f in target.profile.preflight(invoice, syntax) if f.severity in BLOCKING] == []


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="issue #74: SaxonC-HE 13.0.0 regression (12.9 passes): normalize-space() throws "
    "ArrayIndexOutOfBoundsException on whitespace + a character above U+00FF + one above U+FFFF, so the CEN "
    "stylesheet fails at run time",
)
@pytest.mark.parametrize("syntax", list(WRITERS))
def test_saxon_normalize_space_regression(syntax: Syntax) -> None:
    """Found by the property above: a valid buyer name makes validate() report SCHEMATRON-RUNTIME (fatal)."""
    invoice = minimal_invoice()
    invoice = rebuild(invoice, buyer=invoice.buyer.model_copy(update={"name": " \u0100\U000100000000"}))
    report = validate(WRITERS[syntax](invoice), profiles.EN16931)
    assert [f.rule_id for f in report.findings if f.severity in BLOCKING] == []
