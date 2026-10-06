"""Tests for the profile type, the BT-24 registry and the EN 16931 core profile."""

import dataclasses
from collections.abc import Callable
from decimal import Decimal

import pydantic
import pytest

from _calc_drafts import not_subject_to_vat
from euinvoice import profiles
from euinvoice.errors import UnsupportedDocumentError
from euinvoice.model import Invoice, ProcessControl, VatBreakdown
from euinvoice.profiles import EN16931, Profile, registry
from euinvoice.syntax import Syntax

MakeInvoice = Callable[..., Invoice]

PEPPOL_BT24 = "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"


def _profile(**changes: object) -> Profile:
    fields: dict[str, object] = {
        "id": "test",
        "title": "Test profile",
        "specification_identifier": "urn:example:test",
        "syntaxes": frozenset({"ubl"}),
        "rule_sets": ("cen",),
    }
    fields.update(changes)
    return Profile(**fields)  # type: ignore[arg-type]  # object values exercise the runtime checks


class TestRegistry:
    def test_get_returns_the_profile_registered_for_a_bt24(self) -> None:
        assert profiles.get("urn:cen.eu:en16931:2017") is EN16931

    def test_unknown_bt24_raises_listing_the_known_ones(self) -> None:
        with pytest.raises(UnsupportedDocumentError) as excinfo:
            profiles.get("urn:example:unknown")
        message = str(excinfo.value)
        assert "urn:example:unknown" in message
        assert "BT-24" in message
        assert "urn:cen.eu:en16931:2017" in message

    def test_lookup_is_exact(self) -> None:
        # A CIUS identifier only *starts* with the core one (and an extension with the CIUS one); neither
        # resolves to the profile whose BT-24 it extends.
        with pytest.raises(UnsupportedDocumentError):
            profiles.get("urn:cen.eu:en16931:2017#compliant#urn:example.com:cius")
        with pytest.raises(UnsupportedDocumentError):
            profiles.get(PEPPOL_BT24 + "#conformant#urn:example.com:extension")

    def test_index_rejects_two_profiles_with_the_same_bt24(self) -> None:
        with pytest.raises(ValueError, match="urn:example:test"):
            registry._index((_profile(id="a"), _profile(id="b")))

    def test_index_keys_profiles_by_bt24(self) -> None:
        one, two = _profile(id="a"), _profile(id="b", specification_identifier="urn:example:other")
        assert registry._index((one, two)) == {"urn:example:test": one, "urn:example:other": two}


class TestProfile:
    def test_is_immutable(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            EN16931.id = "changed"  # type: ignore[misc]  # assigning a frozen field is the point

    def test_rejects_an_unknown_syntax(self) -> None:
        with pytest.raises(ValueError, match="'xml'"):
            _profile(syntaxes=frozenset({"ubl", "xml"}))

    def test_rejects_no_syntax(self) -> None:
        with pytest.raises(ValueError, match="at least one syntax"):
            _profile(syntaxes=frozenset())

    def test_rejects_no_rule_set(self) -> None:
        with pytest.raises(ValueError, match="at least one rule set"):
            _profile(rule_sets=())

    def test_rejects_an_unknown_rule_set(self) -> None:
        with pytest.raises(ValueError, match="'kosit'"):
            _profile(rule_sets=("cen", "kosit"))

    def test_rejects_a_repeated_rule_set(self) -> None:
        with pytest.raises(ValueError, match="repeats a rule set"):
            _profile(rule_sets=("cen", "cen"))

    def test_rejects_peppol_with_xrechnung(self) -> None:
        # The XRechnung XSLT re-asserts PEPPOL-EN16931-R* rules: running both double-counts them.
        with pytest.raises(ValueError, match="counted twice"):
            _profile(rule_sets=("cen", "peppol", "xrechnung"))

    @pytest.mark.parametrize("rule_sets", [("cen", "peppol"), ("cen", "xrechnung"), ("peppol",)])
    def test_accepts_known_rule_set_combinations(self, rule_sets: tuple[str, ...]) -> None:
        # "cen" is not required: Factur-X MINIMUM and BASIC WL are not EN 16931 documents.
        assert _profile(rule_sets=rule_sets).rule_sets == rule_sets


class TestEn16931:
    def test_declares_the_core_identifiers(self) -> None:
        assert EN16931.id == "en16931"
        assert EN16931.specification_identifier == "urn:cen.eu:en16931:2017"
        assert EN16931.business_process_type is None
        assert EN16931.syntaxes == frozenset(Syntax)

    def test_runs_the_cen_rules_only(self) -> None:
        assert EN16931.rule_sets == ("cen",)

    def test_is_not_a_facturx_profile(self) -> None:
        assert EN16931.facturx_filename is None
        assert EN16931.facturx_conformance_level is None

    def test_never_requires_bt119(self) -> None:
        assert EN16931.requires_vat_breakdown_rate is None


class TestPrepare:
    def test_sets_the_profile_bt24(self, make_invoice: MakeInvoice) -> None:
        invoice = make_invoice(process_control=ProcessControl(specification_identifier=PEPPOL_BT24))
        prepared = EN16931.prepare(invoice)
        assert prepared.process_control.specification_identifier == "urn:cen.eu:en16931:2017"
        assert prepared.model_dump(exclude={"process_control"}) == invoice.model_dump(exclude={"process_control"})

    def test_keeps_a_bt23_the_caller_set(self, make_invoice: MakeInvoice) -> None:
        pc = ProcessControl(business_process_type="urn:example:process", specification_identifier=PEPPOL_BT24)
        prepared = _profile(business_process_type="urn:example:default").prepare(make_invoice(process_control=pc))
        assert prepared.process_control.business_process_type == "urn:example:process"

    def test_keeps_the_bt23_while_replacing_the_bt24(self, make_invoice: MakeInvoice) -> None:
        pc = ProcessControl(
            business_process_type="urn:fdc:peppol.eu:2017:poacc:billing:01:1.0", specification_identifier=PEPPOL_BT24
        )
        prepared = EN16931.prepare(make_invoice(process_control=pc))
        assert prepared.process_control == ProcessControl(
            business_process_type="urn:fdc:peppol.eu:2017:poacc:billing:01:1.0",
            specification_identifier="urn:cen.eu:en16931:2017",
        )

    def test_fills_a_missing_bt23_with_the_profile_default(self, make_invoice: MakeInvoice) -> None:
        prepared = _profile(business_process_type="urn:example:default").prepare(make_invoice())
        assert prepared.process_control == ProcessControl(
            business_process_type="urn:example:default", specification_identifier="urn:example:test"
        )

    def test_leaves_bt23_empty_without_a_default(self, make_invoice: MakeInvoice) -> None:
        assert EN16931.prepare(make_invoice()).process_control.business_process_type is None

    def test_returns_an_equal_invoice_when_nothing_changes(self, make_full_invoice: Callable[[], Invoice]) -> None:
        invoice = make_full_invoice()
        assert invoice.process_control.specification_identifier == "urn:cen.eu:en16931:2017"
        assert EN16931.prepare(invoice) == invoice

    def test_core_leaves_an_o_breakdown_without_bt119(self) -> None:
        # BR-48 exempts category O from BT-119, so neither complete() nor the core profile writes one (#75).
        invoice = not_subject_to_vat()
        assert invoice.vat_breakdown[0].rate is None
        assert EN16931.prepare(invoice).vat_breakdown == invoice.vat_breakdown

    def test_writes_bt119_zero_on_an_o_breakdown_when_the_profile_requires_bt119(self) -> None:
        invoice = not_subject_to_vat()
        prepared = _profile(requires_vat_breakdown_rate=lambda _: True).prepare(invoice)
        (breakdown,) = prepared.vat_breakdown
        assert breakdown.rate == Decimal("0")
        assert breakdown.model_dump(exclude={"rate"}) == invoice.vat_breakdown[0].model_dump(exclude={"rate"})
        assert prepared.model_dump(exclude={"process_control", "vat_breakdown"}) == invoice.model_dump(
            exclude={"process_control", "vat_breakdown"}
        )

    def test_asks_the_profile_with_the_invoice(self) -> None:
        invoice = not_subject_to_vat()
        seen: list[Invoice] = []

        def not_required(asked: Invoice) -> bool:
            seen.append(asked)
            return False

        prepared = _profile(requires_vat_breakdown_rate=not_required).prepare(invoice)
        assert seen == [invoice]
        assert prepared.vat_breakdown[0].rate is None

    def test_writes_no_rate_for_another_category(self, make_invoice: MakeInvoice) -> None:
        # Only O has a rate that follows from the category; a missing S rate is the caller's error (BR-S-09).
        (s_group,) = make_invoice().vat_breakdown
        groups = (VatBreakdown.model_validate({**dict(s_group), "rate": None}),)
        prepared = _profile(requires_vat_breakdown_rate=lambda _: True).prepare(make_invoice(vat_breakdown=groups))
        assert prepared.vat_breakdown == groups

    def test_keeps_a_bt119_the_caller_set_on_an_o_breakdown(self) -> None:
        invoice = not_subject_to_vat()
        groups = (VatBreakdown.model_validate({**dict(invoice.vat_breakdown[0]), "rate": Decimal("0.00")}),)
        prepared = _profile(requires_vat_breakdown_rate=lambda _: True).prepare(
            Invoice.model_validate({**dict(invoice), "vat_breakdown": groups})
        )
        assert format(prepared.vat_breakdown[0].rate, "f") == "0.00"

    def test_validates_the_values_it_sets(self, make_invoice: MakeInvoice) -> None:
        # BT-24 is NonBlankText: a blank identifier must fail model validation, not slip through.
        with pytest.raises(pydantic.ValidationError, match="specification_identifier"):
            _profile(specification_identifier=" ").prepare(make_invoice())
