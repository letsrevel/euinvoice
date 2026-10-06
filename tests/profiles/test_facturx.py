"""Tests for the Factur-X / ZUGFeRD level profiles, their registration and the conformance-level lookup (#22)."""

import typing as t

import pytest

from euinvoice import _xml, profiles
from euinvoice.detect import detect
from euinvoice.errors import UnsupportedDocumentError
from euinvoice.model import Invoice
from euinvoice.profiles import facturx
from euinvoice.profiles._base import FACTURX_RULE_SET
from euinvoice.syntax import Syntax, cii

CORE = "urn:cen.eu:en16931:2017"
XRECHNUNG = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"

# (profile, BT-24, XMP fx:ConformanceLevel, embedded file name, rule sets): the evidence is cited per value in
# src/euinvoice/profiles/facturx.py; tests/conformance/test_facturx_corpus.py checks it against the corpus PDFs.
DECLARED = [
    (profiles.FACTURX_MINIMUM, "urn:factur-x.eu:1p0:minimum", "MINIMUM", "factur-x.xml", (FACTURX_RULE_SET,)),
    (profiles.FACTURX_BASIC_WL, "urn:factur-x.eu:1p0:basicwl", "BASIC WL", "factur-x.xml", (FACTURX_RULE_SET,)),
    (
        profiles.FACTURX_BASIC,
        "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic",
        "BASIC",
        "factur-x.xml",
        (FACTURX_RULE_SET,),
    ),
    (profiles.FACTURX_EN16931, CORE, "EN 16931", "factur-x.xml", ("cen",)),
    (
        profiles.FACTURX_EXTENDED,
        "urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended",
        "EXTENDED",
        "factur-x.xml",
        (FACTURX_RULE_SET,),
    ),
    (profiles.FACTURX_XRECHNUNG, XRECHNUNG, "XRECHNUNG", "xrechnung.xml", ("cen", "xrechnung")),
]
_IDS = [row[0].id for row in DECLARED]
SHARED_BT24 = (profiles.FACTURX_EN16931, profiles.FACTURX_XRECHNUNG)
OWN_BT24 = [row[0] for row in DECLARED if row[0] not in SHARED_BT24]


def _cii(bt24: str) -> bytes:
    return (
        f'<rsm:CrossIndustryInvoice xmlns:rsm="{_xml.CII_RSM}" xmlns:ram="{_xml.CII_RAM}">'
        "<rsm:ExchangedDocumentContext>"
        f"<ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>{bt24}</ram:ID>"
        "</ram:GuidelineSpecifiedDocumentContextParameter></rsm:ExchangedDocumentContext></rsm:CrossIndustryInvoice>"
    ).encode()


@pytest.mark.parametrize(("profile", "bt24", "level", "filename", "rule_sets"), DECLARED, ids=_IDS)
def test_declares_its_identifiers(
    profile: profiles.Profile, bt24: str, level: str, filename: str, rule_sets: tuple[str, ...]
) -> None:
    assert profile.specification_identifier == bt24
    assert profile.facturx_conformance_level == level
    assert profile.facturx_filename == filename
    assert profile.rule_sets == rule_sets
    assert profile.syntaxes == frozenset({Syntax.CII})  # Factur-X embeds CII only (plan §1)
    assert profile.business_process_type is None


def test_levels_lists_every_level_once() -> None:
    assert tuple(row[0] for row in DECLARED) == facturx._LEVELS
    assert len({p.id for p in facturx._LEVELS}) == len(facturx._LEVELS)


class TestByConformanceLevel:
    @pytest.mark.parametrize(("profile", "level"), [(row[0], row[2]) for row in DECLARED], ids=_IDS)
    def test_finds_every_level(self, profile: profiles.Profile, level: str) -> None:
        assert profiles.by_conformance_level(level) is profile

    @pytest.mark.parametrize("level", ["EN16931", "en 16931", "BASICWL", " BASIC", "COMFORT", ""])
    def test_is_exact_and_lists_the_known_levels(self, level: str) -> None:
        with pytest.raises(UnsupportedDocumentError, match="known: 'MINIMUM', 'BASIC WL'"):
            profiles.by_conformance_level(level)


class TestRegistry:
    @pytest.mark.parametrize("profile", OWN_BT24, ids=lambda p: p.id)
    def test_levels_with_their_own_bt24_are_registered(self, profile: profiles.Profile) -> None:
        assert profiles.get(profile.specification_identifier) is profile
        assert detect(_cii(profile.specification_identifier)).profile is profile

    def test_the_core_bt24_stays_the_core_profile(self) -> None:
        # A bare core BT-24 is EN 16931 core; only the PDF's XMP selects FACTURX_EN16931 (#26).
        assert profiles.get(CORE) is profiles.EN16931
        assert detect(_cii(CORE)).profile is profiles.EN16931

    def test_the_xrechnung_bt24_stays_the_xrechnung_profile(self) -> None:
        assert profiles.get(XRECHNUNG) is profiles.XRECHNUNG
        assert detect(_cii(XRECHNUNG)).profile is profiles.XRECHNUNG


class TestGeneration:
    """EN 16931 and XRECHNUNG levels are written by the CII writer after ``prepare`` (plan §1)."""

    @pytest.mark.parametrize("profile", SHARED_BT24, ids=lambda p: p.id)
    def test_prepare_and_write_claim_the_level_bt24(self, profile: profiles.Profile, invoice: Invoice) -> None:
        written = cii.write(profile.prepare(invoice))
        assert detect(written).specification_identifier == profile.specification_identifier
        assert cii.read(_xml.parse(written)).invoice == profile.prepare(invoice)


def test_the_xrechnung_level_is_xrechnung_in_a_factur_x_container() -> None:
    # Same BT-24, rule sets, BT-23 default and BR-DE pre-flight as XRECHNUNG; only the container fields differ.
    level, xrechnung = profiles.FACTURX_XRECHNUNG, profiles.XRECHNUNG
    assert level.preflight is xrechnung.preflight
    assert level.specification_identifier == xrechnung.specification_identifier
    assert level.rule_sets == xrechnung.rule_sets
    assert level.business_process_type == xrechnung.business_process_type
    assert profiles.get(XRECHNUNG) is xrechnung


class TestUnregisteredLevelIdentifiers:
    """BT-24 values the corpus pairs with a level but no profile declares (#98); validate() refuses them."""

    EXPECTED: t.ClassVar = {
        "urn:zugferd.de:2p0:minimum": "MINIMUM",
        "urn:cen.eu:en16931:2017#compliant#urn:zugferd.de:2p0:basic": "BASIC",
        "urn:cen.eu:en16931:2017#conformant#urn:zugferd.de:2p0:extended": "EXTENDED",
        "urn:cen.eu:en16931:2017:compliant:factur-x.eu:1p0:basic": "BASIC",
        "urn:cen.eu:en16931:2017:compliant:factur-x.eu:1p0:extended": "EXTENDED",
    }

    def test_lists_the_corpus_pairs(self) -> None:
        # tests/conformance/test_facturx_extract_corpus.py checks each pair against the corpus PDFs.
        assert dict(facturx.UNREGISTERED_LEVEL_IDENTIFIERS) == self.EXPECTED

    @pytest.mark.parametrize("bt24", sorted(EXPECTED))
    def test_none_is_registered_or_written(self, bt24: str) -> None:
        # Not a profile's BT-24, so prepare() / to_xml never write one, and detect() gives no profile.
        with pytest.raises(UnsupportedDocumentError):
            profiles.get(bt24)
        assert detect(_cii(bt24)).profile is None
        assert all(row[0].specification_identifier != bt24 for row in DECLARED)

    @pytest.mark.parametrize("level", sorted(set(EXPECTED.values())))
    def test_each_names_a_level_without_pinned_rules(self, level: str) -> None:
        assert FACTURX_RULE_SET in profiles.by_conformance_level(level).rule_sets
