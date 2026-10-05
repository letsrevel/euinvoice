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
    assert set(codes.__all__) - set(lists) == {"ISO_3166_1_COUNTRY", "DocumentType", "VatCategory"}
    assert len(lists) == 22
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


def test_model_country_list_is_the_union_of_both_syntaxes() -> None:
    assert codes.ISO_3166_1_COUNTRY == codes.ISO_3166_1_COUNTRY_UBL | codes.ISO_3166_1_COUNTRY_CII
    assert {"SS", "AN", "DE"} <= codes.ISO_3166_1_COUNTRY


def test_vatex_codes_are_upper_case_so_callers_match_upper_cased_values() -> None:
    # BR-CL-22 tests normalize-space(upper-case(.)) against the list (CEN 1.3.16, UBL and CII).
    assert all(code == code.upper() for code in codes.VATEX_EXEMPTION_REASON)
    assert " vatex-eu-79-c ".strip().upper() in codes.VATEX_EXEMPTION_REASON


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


def test_note_subject_ubl_list_is_a_strict_subset_of_the_cii_list() -> None:
    # CEN 1.3.16: UBL BR-CL-08 (schematron/UBL/EN16931-UBL-model.sch) has 383 UNTDID 4451 codes, CII
    # BR-CL-08 (schematron/codelist/EN16931-CII-codes.sch) 401. The model accepts the CII superset (D8).
    ubl, cii = codes.UNTDID_4451_NOTE_SUBJECT_UBL, codes.UNTDID_4451_TEXT_SUBJECT

    assert (len(ubl), len(cii)) == (383, 401)
    assert ubl < cii
