"""Unit tests for the XRechnung profiles and their pre-flight checks (offline)."""

from decimal import Decimal

import pytest

from _xrechnung_cases import (
    CVD_VIOLATIONS,
    EDGES,
    VIOLATIONS,
    cvd_invoice,
    seller,
    xrechnung_invoice,
    xrechnung_o_invoice,
)
from euinvoice import profiles
from euinvoice.model import (
    Invoice,
    ProcessControl,
    SellerTaxRepresentative,
    TaxRepresentativePostalAddress,
)
from euinvoice.profiles import xrechnung
from euinvoice.report import Severity
from euinvoice.syntax import Syntax

CIUS = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
XRECHNUNG_PROFILES = (profiles.XRECHNUNG, profiles.XRECHNUNG_EXTENSION, profiles.XRECHNUNG_CVD)


def rule_ids(profile: profiles.Profile, invoice: Invoice) -> set[str]:
    """Rule ids of the pre-flight findings, for cases where both syntaxes agree."""
    ubl, cii = (profile.preflight(invoice, syntax) for syntax in (Syntax.UBL, Syntax.CII))
    assert ubl == cii
    return {f.rule_id for f in ubl}


class TestDeclarations:
    # XR-CIUS-ID, XR-EXTENSION-ID, XR-CVD-ID: xrechnung-schematron 2.6.0 schematron/common.sch lines 5-9.
    @pytest.mark.parametrize(
        ("profile", "bt24"),
        [
            (profiles.XRECHNUNG, CIUS),
            (profiles.XRECHNUNG_EXTENSION, f"{CIUS}#conformant#urn:xeinkauf.de:kosit:extension:xrechnung_3.0"),
            (profiles.XRECHNUNG_CVD, f"{CIUS}#compliant#urn:xeinkauf.de:kosit:xrechnung:cvd_0.9"),
        ],
        ids=lambda v: v.id if isinstance(v, profiles.Profile) else "",
    )
    def test_each_bt24_is_its_own_registered_profile(self, profile: profiles.Profile, bt24: str) -> None:
        assert profile.specification_identifier == bt24
        assert profiles.get(bt24) is profile

    @pytest.mark.parametrize("profile", XRECHNUNG_PROFILES, ids=lambda p: p.id)
    def test_both_syntaxes_cen_then_xrechnung_never_peppol(self, profile: profiles.Profile) -> None:
        assert profile.syntaxes == {Syntax.UBL, Syntax.CII}
        assert profile.rule_sets == ("cen", "xrechnung")

    @pytest.mark.parametrize("profile", XRECHNUNG_PROFILES, ids=lambda p: p.id)
    def test_no_bt23_default(self, profile: profiles.Profile) -> None:
        assert profile.business_process_type is None

    @pytest.mark.parametrize("profile", XRECHNUNG_PROFILES, ids=lambda p: p.id)
    def test_prepare_keeps_each_claim(self, profile: profiles.Profile) -> None:
        # prepare() under one XRechnung profile writes its own BT-24, so an Extension or CVD claim survives a
        # round trip through its profile (issue #21).
        prepared = profile.prepare(xrechnung_invoice())
        assert prepared.process_control.specification_identifier == profile.specification_identifier
        assert profiles.get(prepared.process_control.specification_identifier) is profile


class TestNotSubjectToVat:
    """BR-DE-14 requires BT-119 on every VAT breakdown, an O one included (issue #75)."""

    @pytest.mark.parametrize("profile", [*XRECHNUNG_PROFILES, profiles.FACTURX_XRECHNUNG], ids=lambda p: p.id)
    def test_prepare_writes_bt119_zero_on_the_o_breakdown(self, profile: profiles.Profile) -> None:
        invoice = xrechnung_o_invoice()
        assert invoice.vat_breakdown[0].rate is None  # as calc.complete builds it

        prepared = profile.prepare(invoice)

        assert [g.rate for g in prepared.vat_breakdown] == [Decimal("0")]

    @pytest.mark.parametrize("profile", [profiles.XRECHNUNG, profiles.XRECHNUNG_EXTENSION], ids=lambda p: p.id)
    def test_prepared_o_invoice_has_no_findings(self, profile: profiles.Profile) -> None:
        assert rule_ids(profile, profile.prepare(xrechnung_o_invoice())) == set()

    def test_unprepared_o_invoice_fails_br_de_14(self) -> None:
        assert rule_ids(profiles.XRECHNUNG, xrechnung_o_invoice()) == {"BR-DE-14"}

    def test_a_missing_s_rate_is_still_reported(self) -> None:
        invoice = profiles.XRECHNUNG.prepare(VIOLATIONS["BR-DE-14"]())
        assert invoice.vat_breakdown[0].rate is None
        assert rule_ids(profiles.XRECHNUNG, invoice) == {"BR-DE-14"}


class TestPreflight:
    @pytest.mark.parametrize("profile", [profiles.XRECHNUNG, profiles.XRECHNUNG_EXTENSION], ids=lambda p: p.id)
    def test_valid_invoice_has_no_findings(self, profile: profiles.Profile) -> None:
        assert rule_ids(profile, profile.prepare(xrechnung_invoice())) == set()

    @pytest.mark.parametrize("profile", XRECHNUNG_PROFILES, ids=lambda p: p.id)
    @pytest.mark.parametrize("rule_id", list(VIOLATIONS))
    def test_each_violation_fires_exactly_its_rule(self, profile: profiles.Profile, rule_id: str) -> None:
        findings = profile.preflight(profile.prepare(VIOLATIONS[rule_id]()), Syntax.CII)

        ids = {f.rule_id for f in findings} - set(CVD_VIOLATIONS)
        assert ids == {rule_id}
        finding = next(f for f in findings if f.rule_id == rule_id)
        assert (finding.severity, finding.source) == (Severity.FATAL, xrechnung.PREFLIGHT_SOURCE)
        assert finding.message.startswith(f"[{rule_id}] ")
        assert finding.location

    @pytest.mark.parametrize("rule_id", list(CVD_VIOLATIONS))
    def test_cvd_rules_fire_only_under_the_cvd_profile(self, rule_id: str) -> None:
        invoice = CVD_VIOLATIONS[rule_id]()

        assert rule_id in rule_ids(profiles.XRECHNUNG_CVD, invoice)
        assert rule_ids(profiles.XRECHNUNG, invoice) == set()

    def test_cvd_invoice_with_its_references_only_lacks_the_cvd_line(self) -> None:
        assert rule_ids(profiles.XRECHNUNG_CVD, cvd_invoice()) == {"BR-DE-CVD-03"}

    def test_profiles_without_preflight_return_nothing(self) -> None:
        assert profiles.EN16931.preflight is profiles.no_preflight
        assert profiles.EN16931.preflight(VIOLATIONS["BR-DE-1"](), Syntax.UBL) == ()

    @pytest.mark.parametrize("profile", XRECHNUNG_PROFILES, ids=lambda p: p.id)
    def test_unknown_syntax_is_misuse(self, profile: profiles.Profile) -> None:
        with pytest.raises(ValueError, match="unknown syntax"):
            profile.preflight(xrechnung_invoice(), "pdf")  # type: ignore[arg-type]  # the runtime check is the point

    def test_rule_set_lists_every_rule_with_a_case(self) -> None:
        assert set(VIOLATIONS) | set(CVD_VIOLATIONS) == xrechnung._RULES

    def test_one_finding_per_vat_breakdown_without_rate(self) -> None:
        findings = profiles.XRECHNUNG.preflight(VIOLATIONS["BR-DE-14"](), Syntax.UBL)
        assert [f.location for f in findings] == ["vat_breakdown[0].rate"]


class TestPreflightEdges:
    """Cases where the UBL and CII bindings differ, or where an exception of the rule applies."""

    @pytest.mark.parametrize("name", list(EDGES))
    def test_per_syntax_expectations(self, name: str) -> None:
        make, expected = EDGES[name]
        invoice = make()
        for syntax, ids in expected.items():
            assert {f.rule_id for f in profiles.XRECHNUNG.preflight(invoice, syntax)} == ids, syntax

    def test_blank_vat_id_counts_as_missing(self) -> None:
        assert rule_ids(profiles.XRECHNUNG, xrechnung_invoice(seller=seller(vat_identifier=" "))) == {"BR-DE-16"}

    def test_br_de_16_tax_representative_suffices(self) -> None:
        representative = SellerTaxRepresentative(
            name="Rep", vat_identifier="DE111111111", postal_address=TaxRepresentativePostalAddress(country_code="DE")
        )
        invoice = xrechnung_invoice(seller=seller(vat_identifier=None), seller_tax_representative=representative)
        assert rule_ids(profiles.XRECHNUNG, invoice) == set()

    def test_bt23_is_left_to_the_caller(self) -> None:
        invoice = xrechnung_invoice(process_control=ProcessControl(specification_identifier=CIUS))
        assert profiles.XRECHNUNG.prepare(invoice).process_control.business_process_type is None
