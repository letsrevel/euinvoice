"""What ``to_xml`` writes passes the official XSD and Schematron of its profile (#27)."""

import typing as t

import pytest

from _invoices import minimal_invoice, peppol_invoice
from _xrechnung_cases import xrechnung_invoice
from euinvoice import profiles, to_xml, validate
from euinvoice.model import Invoice
from euinvoice.syntax import Syntax

pytestmark = pytest.mark.conformance

CASES: t.Final[list[tuple[profiles.Profile, t.Callable[[], Invoice]]]] = [
    (profiles.EN16931, minimal_invoice),
    (profiles.PEPPOL, peppol_invoice),
    (profiles.XRECHNUNG, xrechnung_invoice),
]


@pytest.mark.parametrize("syntax", [Syntax.UBL, Syntax.CII])
@pytest.mark.parametrize(("profile", "build"), CASES, ids=[profile.id for profile, _ in CASES])
def test_to_xml_output_validates(profile: profiles.Profile, build: t.Callable[[], Invoice], syntax: Syntax) -> None:
    xml = to_xml(build(), profile=profile, syntax=syntax)
    report = validate(xml, profile)
    assert report.ok, report.findings
    assert validate(xml).ok  # the written BT-24 selects the same profile
