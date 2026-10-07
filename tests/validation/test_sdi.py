"""Unit tests for the offline SdI checks of FatturaPA (Allegato A 1.9.1, Appendix 1; issue #121).

Each code has documents that pass it and one that fails it (tests/_fatturapa.py). That every one of these documents
is valid against the pinned XSD 1.2.3 is proved in tests/conformance/test_sdi_official.py.
"""

import re

import pytest

from _fatturapa import CASES, Body, Case, Doc, body, line, summary
from euinvoice import _xml
from euinvoice.report import Severity
from euinvoice.validation import sdi


def codes(doc: Doc) -> set[str]:
    return {finding.rule_id for finding in sdi.check(_xml.parse(doc.xml()))}


@pytest.mark.parametrize(("code", "case"), CASES.items(), ids=list(CASES))
def test_passing_documents_raise_nothing(code: str, case: Case) -> None:
    for doc in case.passing:
        assert sdi.check(_xml.parse(doc.xml())) == (), doc


@pytest.mark.parametrize(("code", "case"), CASES.items(), ids=list(CASES))
def test_failing_document_raises_exactly_its_codes(code: str, case: Case) -> None:
    assert code in case.codes
    assert codes(case.failing) == case.codes


def test_every_described_code_has_a_case_and_vice_versa() -> None:
    assert set(sdi.DESCRIPTIONS) == set(CASES)


def test_default_document_passes() -> None:
    assert sdi.check(_xml.parse(Doc().xml())) == ()


def test_a_finding_is_an_error_citing_the_allegato_a_text_at_the_offending_element() -> None:
    doc = Doc(bodies=body(summaries=summary(tax="22.02")))

    (finding,) = sdi.check(_xml.parse(doc.xml()))

    assert finding.rule_id == "00421"
    assert finding.severity is Severity.ERROR
    assert finding.source == "sdi"
    assert finding.location == "/p:FatturaElettronica/FatturaElettronicaBody/DatiBeniServizi/DatiRiepilogo"
    assert finding.message.startswith(
        "SdI 00421 (Allegato A 1.9.1, Appendix 1): 2.2.2.6 <Imposta> non calcolato secondo le regole definite "
        "nelle specifiche tecniche."
    )
    assert "Imposta 22.02, computed 22.00" in finding.message


def test_findings_name_the_body_of_a_lotto() -> None:
    doc = Doc(bodies=(Body(), Body(number="FT-2", summaries=summary(tax="23.00"))))

    (finding,) = sdi.check(_xml.parse(doc.xml()))

    assert finding.location == "/p:FatturaElettronica/FatturaElettronicaBody[2]/DatiBeniServizi/DatiRiepilogo"


def test_duplicate_in_lotto_is_reported_on_the_repeating_body_and_names_the_first() -> None:
    doc = Doc(bodies=(Body(), Body(number="FT-2"), Body(date="2026-12-31")))

    (finding,) = sdi.check(_xml.parse(doc.xml()))

    assert finding.rule_id == "00409"
    assert finding.location == "/p:FatturaElettronica/FatturaElettronicaBody[3]/DatiGenerali/DatiGeneraliDocumento"
    assert finding.message.endswith("repeats /p:FatturaElettronica/FatturaElettronicaBody[1].")


@pytest.mark.parametrize(
    ("first", "second", "duplicate"),
    [
        (Body(art73=True), Body(art73=True), True),  # Art73 SI: same full date
        (Body(art73=True), Body(date="2026-02-15"), False),  # Art73 SI on either: the full date decides
        (Body(tipo="TD04"), Body(tipo="TD04"), False),  # both credit notes: not settled by Allegato A (#130)
        (Body(), Body(number="FT-2"), False),
    ],
)
def test_duplicate_in_lotto_rules(first: Body, second: Body, duplicate: bool) -> None:
    assert ("00409" in codes(Doc(bodies=(first, second)))) is duplicate


def test_withholding_is_reported_once_per_body() -> None:
    lines = line(withholding=True) + line(2, withholding=True)
    doc = Doc(bodies=body(lines=lines, summaries=summary("22.00", "200.00", "44.00")))

    assert [f.rule_id for f in sdi.check(_xml.parse(doc.xml()))] == ["00411"]


def test_generic_natura_is_reported_per_element() -> None:
    doc = Doc(
        bodies=body(lines=line(rate="0.00", natura="N3"), summaries=summary("0.00", "100.00", "0.00", natura="N3"))
    )

    findings = sdi.check(_xml.parse(doc.xml()))

    assert [(f.rule_id, f.location.rsplit("/", 2)[-2]) for f in findings if f.location] == [
        ("00445", "DettaglioLinee"),
        ("00445", "DatiRiepilogo"),
    ]


def test_decimals_are_compared_by_value_and_whitespace_is_collapsed() -> None:
    doc = Doc(bodies=body(lines=line(rate=" 22.00 "), summaries=summary(rate="22.00")))

    assert sdi.check(_xml.parse(doc.xml())) == ()


def test_every_description_is_quoted_with_its_element_ids() -> None:
    # Spot-check the quoting against Allegato A 1.9.1, Appendix 1 (fatture ordinarie wording).
    assert sdi.DESCRIPTIONS["00425"] == "2.1.1.4 <Numero> non contenente caratteri numerici"
    assert sdi.DESCRIPTIONS["00409"] == "Fattura duplicata nel lotto"
    assert all(re.fullmatch(r"00[34][0-9]{2}", code) for code in sdi.DESCRIPTIONS)


@pytest.mark.parametrize(("linked", "reported"), [("10000-01-01", True), ("2025-12-31+01:00", False)])
def test_linked_dates_compare_for_any_xsd_year_and_ignore_the_timezone(linked: str, reported: bool) -> None:
    fragment = f"<DatiFattureCollegate><IdDocumento>FT-0</IdDocumento><Data>{linked}</Data></DatiFattureCollegate>"

    assert ("00418" in codes(Doc(bodies=body(linked=fragment)))) is reported


def test_a_document_that_skipped_the_xsd_is_refused_not_misjudged() -> None:
    root = _xml.parse(f'<p:FatturaElettronica xmlns:p="{_xml.FATTURAPA}" versione="FPR12"/>'.encode())

    with pytest.raises(ValueError, match=r"has no FatturaElettronicaHeader/DatiTrasmissione; sdi\.check needs"):
        sdi.check(root)
