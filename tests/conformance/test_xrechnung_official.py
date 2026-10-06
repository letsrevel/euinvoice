"""XRechnung profiles against the pinned XRechnung Schematron 2.6.0, through both writers (``make conformance``).

Every case (the valid invoice, one violation per pre-flight rule, and the binding edge cases) is prepared,
written in UBL and in CII, and validated with the auto-detected profile. The pre-flight findings must agree
exactly with the official ones: for every pre-flighted rule id, pre-flight reports it as ``fatal`` if and only
if the official XRechnung Schematron does on that writer's output (D8, decision recorded on issue #20).
"""

import typing as t
from collections.abc import Callable

import pytest

from _xrechnung_cases import CVD_VIOLATIONS, EDGES, VIOLATIONS, xrechnung_invoice, xrechnung_o_invoice
from euinvoice import profiles
from euinvoice.model import Invoice
from euinvoice.profiles import xrechnung
from euinvoice.report import Severity, ValidationReport
from euinvoice.syntax import Syntax, cii, ubl
from euinvoice.validate import EUINVOICE_SOURCE, validate

pytestmark = pytest.mark.conformance

WRITERS: t.Final[dict[Syntax, Callable[[Invoice], bytes]]] = {Syntax.UBL: ubl.write, Syntax.CII: cii.write}
XRECHNUNG_SOURCE = "xrechnung-schematron"
BLOCKING = (Severity.FATAL, Severity.ERROR)


def agreement(profile: profiles.Profile, invoice: Invoice, syntax: Syntax) -> tuple[set[str], ValidationReport]:
    """Assert pre-flight and the official rules agree exactly on ``invoice``; return the ids and the report.

    validate() auto-detects the profile from the written BT-24, so this also checks that the profile writes
    and is found by its own identifier.
    """
    prepared = profile.prepare(invoice)
    report = validate(WRITERS[syntax](prepared))
    assert all(f.source != EUINVOICE_SOURCE for f in report.findings), "fell back to EN 16931 core"
    preflight = profile.preflight(prepared, syntax)
    assert all(f.severity is Severity.FATAL for f in preflight)
    ids = {f.rule_id for f in preflight}
    official = {
        f.rule_id
        for f in report.findings
        if f.source == XRECHNUNG_SOURCE and f.severity is Severity.FATAL and f.rule_id in xrechnung._RULES
    }
    assert ids == official, report.findings
    return ids, report


def test_every_preflight_rule_has_a_violation_case() -> None:
    assert set(VIOLATIONS) | set(CVD_VIOLATIONS) == xrechnung._RULES


@pytest.mark.parametrize("syntax", list(WRITERS))
@pytest.mark.parametrize("profile", [profiles.XRECHNUNG, profiles.XRECHNUNG_EXTENSION], ids=lambda p: p.id)
def test_valid_invoice_passes_cen_and_xrechnung(profile: profiles.Profile, syntax: Syntax) -> None:
    ids, report = agreement(profile, xrechnung_invoice(), syntax)

    assert ids == set()
    assert report.ok, [f for f in report.findings if f.severity in BLOCKING]
    # BR-DE-21 (warning) accepts each of the three identifiers; BR-DE-TMP-32 (information) asks for a
    # delivery date or period, which the synthetic invoice omits.
    assert {f.rule_id for f in report.findings} <= {"BR-DE-TMP-32"}


@pytest.mark.parametrize(("syntax", "blocking"), [(Syntax.UBL, set()), (Syntax.CII, {"PEPPOL-EN16931-R008"})])
def test_empty_purchase_order_reference(syntax: Syntax, blocking: set[str]) -> None:
    # Issue #79: an empty BT-13 is written empty. No CEN rule tests BT-13's content. XRechnung 2.6.0 exempts
    # exactly this UBL element from PEPPOL-EN16931-R008 (ubl/XRechnung-UBL-validation.sch:190-191,
    # `self::cbc:ID[parent::cac:OrderReference]`); its CII R008 (cii/XRechnung-CII-validation.sch:297-298) has no
    # such exemption.
    invoice = xrechnung_invoice(purchase_order_reference="", sales_order_reference="SO-1")
    ids, report = agreement(profiles.XRECHNUNG, invoice, syntax)

    assert ids == set()
    assert {f.rule_id for f in report.findings if f.severity in BLOCKING} == blocking


@pytest.mark.parametrize("syntax", list(WRITERS))
@pytest.mark.parametrize("rule_id", list(VIOLATIONS))
def test_each_preflight_rule_fires_officially(rule_id: str, syntax: Syntax) -> None:
    ids, _ = agreement(profiles.XRECHNUNG, VIOLATIONS[rule_id](), syntax)

    assert ids == {rule_id}


@pytest.mark.parametrize("syntax", list(WRITERS))
@pytest.mark.parametrize("rule_id", list(CVD_VIOLATIONS))
def test_each_cvd_preflight_rule_fires_officially(rule_id: str, syntax: Syntax) -> None:
    ids, _ = agreement(profiles.XRECHNUNG_CVD, CVD_VIOLATIONS[rule_id](), syntax)

    # No model invoice satisfies BR-DE-CVD-03 (see cvd_invoice), so it accompanies the other CVD rules.
    assert ids == {rule_id, "BR-DE-CVD-03"}


@pytest.mark.parametrize(
    ("name", "syntax"), [(name, syntax) for name, (_, expected) in EDGES.items() for syntax in expected]
)
def test_binding_edges_agree_with_the_schematron(name: str, syntax: Syntax) -> None:
    make, expected = EDGES[name]

    ids, _ = agreement(profiles.XRECHNUNG, make(), syntax)

    assert ids == expected[syntax]


@pytest.mark.parametrize("syntax", list(WRITERS))
@pytest.mark.parametrize("profile", [profiles.XRECHNUNG, profiles.XRECHNUNG_EXTENSION], ids=lambda p: p.id)
def test_prepared_o_invoice_passes_cen_and_xrechnung(profile: profiles.Profile, syntax: Syntax) -> None:
    # Issue #75: complete() leaves BT-119 off the O breakdown (BR-48 allows it), BR-DE-14 requires it, and
    # prepare() writes 0 there, which CEN and XRechnung accept. XRECHNUNG_CVD shares that prepare() hook and is
    # covered by the unit test only: no model invoice can pass it here, since BR-DE-CVD-03 needs item
    # classification list id 'CVD', which the model rejects under CEN BR-CL-13 (#49).
    invoice = xrechnung_o_invoice()
    unprepared = validate(WRITERS[syntax](invoice))
    assert {f.rule_id for f in unprepared.findings if f.severity in BLOCKING} == {"BR-DE-14"}

    ids, report = agreement(profile, invoice, syntax)

    assert ids == set()
    assert report.ok, [f for f in report.findings if f.severity in BLOCKING]
    assert {f.rule_id for f in report.findings} <= {"BR-DE-TMP-32"}
