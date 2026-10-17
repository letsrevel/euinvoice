"""Unit tests for the offline SdI checks of FatturaPA (Allegato A 1.9.1, Appendix 1; issue #121).

Each code has documents that pass it and one that fails it (tests/_fatturapa.py). That every one of these documents
is valid against the pinned XSD 1.2.3 is proved in tests/conformance/test_sdi_official.py.
"""

import re
import typing as t

import pytest

from _fatturapa import CASES, EXTRA_FAILING, Body, Case, Doc, adjustment, body, cassa, line, summary
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
        (Body(art73=True), Body(art73=True), True),  # both Art73 SI: same full date
        (Body(art73=True), Body(art73=True, date="2026-02-15"), False),  # both Art73 SI: the full date decides
        # Elenco p. 15: Art73 is read on F only, so the pair is also compared with F = the non-SI body, by year.
        (Body(art73=True), Body(date="2026-02-15"), True),
        (Body(date="2026-02-15"), Body(art73=True), True),
        (Body(art73=True), Body(date="2027-02-15"), False),
        (Body(tipo="TD04"), Body(tipo="TD04"), True),  # Elenco p. 15: same TipoDocumento, Numero and year
        (Body(tipo="TD04"), Body(tipo="TD04", date="2027-01-15"), False),
        (Body(tipo="TD04"), Body(), False),  # one TD04 and another type: never
        (Body(tipo="TD04", art73=True), Body(tipo="TD04", art73=True, date="2026-02-15"), False),  # full date, p. 16
        (Body(tipo="TD04", art73=True), Body(tipo="TD04", art73=True), True),
        (Body(), Body(number="FT-2"), False),
    ],
)
def test_duplicate_in_lotto_rules(first: Body, second: Body, duplicate: bool) -> None:
    assert ("00409" in codes(Doc(bodies=(first, second)))) is duplicate


def _priced(total: str, *adjustments: str, quantity: str | None = "100.00") -> Doc:
    return Doc(
        bodies=body(
            lines=line(quantity=quantity, unit="500.00", total=total, adjustments="".join(adjustments)),
            summaries=summary("22.00", total, "0.00"),
        )
    )


def _sc(*, percent: str | None = None, amount: str | None = None) -> str:
    return adjustment("SC", percent=percent, amount=amount)


_CASO_1: t.Final = [_sc(amount="10.05"), _sc(amount="5.25"), _sc(amount="4.70")]
_CASO_2: t.Final = [_sc(percent="8.50"), _sc(percent="5.15"), _sc(percent="3.00")]
_CASO_3: t.Final = [_sc(percent="8.50"), _sc(percent="5.15", amount="23.56"), _sc(amount="15.00"), _sc(percent="2.00")]


@pytest.mark.parametrize(
    ("total", "adjustments", "quantity", "ok"),
    [
        # Elenco pp. 28-30, Caso 1: amounts are per unit and add up: [500.00 - 20.00] * 100.00
        ("48000.00", _CASO_1, "100.00", True),
        ("48100.00", _CASO_1, "100.00", False),
        # Caso 2: percentages cascade on the running price: 420.9205875 * 100
        ("42092.05875", _CASO_2, "100.00", True),
        ("42092.05", _CASO_2, "100.00", True),
        ("42092.06", _CASO_2, "100.00", True),
        ("42092.07", _CASO_2, "100.00", False),
        ("42092.04", _CASO_2, "100.00", False),
        # Caso 3: mixed, in document order; an entry with both uses Importo (23.56, not 5.15 %)
        ("41056.12", _CASO_3, "100.00", True),
        ("41055.9975", _CASO_3, "100.00", False),
        # The order matters: a percentage applies to the running price.
        ("40000.00", [_sc(percent="10.00"), _sc(amount="50.00")], "100.00", True),
        ("40500.00", [_sc(amount="50.00"), _sc(percent="10.00")], "100.00", True),
        ("43700.00", [_sc(percent="10.00"), _sc(amount="50.00")], "100.00", False),
        # A surcharge adds; an absent Quantita counts as 1.
        ("510.00", [adjustment("MG", amount="10.00")], None, True),
        ("550.00", [adjustment("MG", percent="10.00")], None, True),
        ("500.00", [], None, True),
        ("1000.00", [], None, False),
    ],
)
def test_line_total_follows_the_elenco_algorithm(
    total: str, adjustments: list[str], quantity: str | None, ok: bool
) -> None:
    assert ("00423" not in codes(_priced(total, *adjustments, quantity=quantity))) is ok


@pytest.mark.parametrize(
    ("rate", "reported"),
    [("0.00", False), ("0.01", True), ("0.10", True), ("0.99", True), ("1.00", False), ("10.00", False)],
)
def test_a_rate_between_0_and_1_is_not_a_percentage(rate: str, reported: bool) -> None:
    natura = "N2.1" if rate == "0.00" else None
    doc = Doc(
        bodies=body(lines=line(rate=rate, natura=natura), summaries=summary(rate, "100.00", "0.00", natura=natura))
    )

    found = [f for f in sdi.check(_xml.parse(doc.xml())) if f.rule_id == "00424"]

    assert [(f.location or "").rsplit("/", 1)[-1] for f in found] == (
        ["DettaglioLinee", "DatiRiepilogo"] if reported else []
    )


def test_missing_rates_are_counted_not_matched() -> None:
    """Elenco p. 22: 00419 compares the number of DatiRiepilogo with the number of distinct rates."""
    lines = line() + line(2, rate="10.00")
    count_only = Doc(bodies=body(lines=lines, summaries=summary() + summary("22.00", "0.00", "0.00")))
    one_summary = Doc(bodies=body(lines=lines))

    assert "00419" not in codes(count_only)  # two blocks for two rates: SdI reports 00443 only
    assert "00443" in codes(count_only)
    found = [f for f in sdi.check(_xml.parse(one_summary.xml())) if f.rule_id == "00419"]
    assert [f.location for f in found] == ["/p:FatturaElettronica/FatturaElettronicaBody/DatiBeniServizi"]


def test_a_rate_shared_by_cassa_and_lines_is_counted_once() -> None:
    doc = Doc(bodies=body(cassa=cassa("22.00"), summaries=summary("22.00", "104.00", "22.88")))

    assert "00419" not in codes(doc)


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


@pytest.mark.parametrize("name", list(EXTRA_FAILING))
def test_other_branches_of_a_check_fail_too(name: str) -> None:
    assert codes(EXTRA_FAILING[name]) == {name.split()[0]}
