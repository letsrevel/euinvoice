"""Tests of the generated EN 16931 code lists and the hand-written enums built on them."""

import typing as t

import pytest

from euinvoice.model import codes
from euinvoice.model.codes import _generated


def _generated_lists() -> dict[str, frozenset[str]]:
    return {name: value for name, value in vars(_generated).items() if name.isupper()}


def test_every_generated_list_is_exported_and_a_non_empty_frozenset_of_clean_codes() -> None:
    lists = _generated_lists()

    assert set(lists) <= set(codes.__all__)
    assert len(lists) == 21
    for name, value in lists.items():
        assert isinstance(value, frozenset), name
        assert value, name
        assert all(code and code == code.strip() and " " not in code for code in value), name
        assert getattr(codes, name) is value


def test_vat_category_equals_uncl5305_as_restricted_by_br_cl_17() -> None:
    assert {member.value for member in codes.VatCategory} == codes.UNTDID_5305_VAT_CATEGORY


def test_document_type_is_a_subset_of_untdid_1001() -> None:
    assert {member.value for member in codes.DocumentType} <= codes.UNTDID_1001_DOCUMENT_TYPE


@pytest.mark.parametrize("member", list(codes.DocumentType))
def test_document_type_ubl_root_follows_br_cl_01(member: codes.DocumentType) -> None:
    on_credit_note_root = member in codes.UNTDID_1001_CREDIT_NOTE_TYPE_UBL
    assert on_credit_note_root == (member is codes.DocumentType.CREDIT_NOTE)
    assert on_credit_note_root != (member in codes.UNTDID_1001_INVOICE_TYPE_UBL)


def test_ubl_document_type_lists_split_the_cii_list_and_share_only_81() -> None:
    invoice, credit_note = codes.UNTDID_1001_INVOICE_TYPE_UBL, codes.UNTDID_1001_CREDIT_NOTE_TYPE_UBL

    assert invoice | credit_note == codes.UNTDID_1001_DOCUMENT_TYPE
    assert invoice & credit_note == {"81"}


def test_country_lists_differ_between_syntaxes_exactly_as_documented() -> None:
    ubl, cii = codes.ISO_3166_1_COUNTRY_UBL, codes.ISO_3166_1_COUNTRY_CII

    assert ubl - cii == {"SS"}
    assert cii - ubl == {"AN"}


def test_vat_point_date_codes_are_different_code_lists_per_syntax() -> None:
    assert {"3", "35", "432"} == codes.UNTDID_2005_VAT_POINT_DATE_UBL
    assert {"5", "29", "72"} == codes.UNTDID_2475_VAT_POINT_DATE_CII


@pytest.mark.parametrize(
    ("name", "samples"),
    [
        ("ISO_4217_CURRENCY", {"EUR", "USD", "CHF"}),
        ("UNECE_REC20_REC21_UNIT", {"C62", "HUR", "KGM"}),
        ("ISO_6523_ICD", {"0088", "0208"}),
        ("CEF_EAS", {"9930", "EM"}),
        ("VATEX_EXEMPTION_REASON", {"VATEX-EU-79-C"}),
        ("MIME_CODE", {"application/pdf", "text/csv"}),
        ("PARTY_IDENTIFIER_EXTRA_SCHEME_UBL", {"SEPA"}),
    ],
)
def test_lists_contain_well_known_codes(name: str, samples: set[str]) -> None:
    assert samples <= t.cast(frozenset[str], getattr(codes, name))
