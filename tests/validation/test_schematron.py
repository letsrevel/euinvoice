"""Unit tests for the Schematron runner, offline: synthetic SVRL and a tiny synthetic stylesheet in a fake cache."""

import concurrent.futures
import sys
import typing as t
from pathlib import Path

import pytest
from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ArtifactIntegrityError, ArtifactsNotAvailableError, ParseError
from euinvoice.report import Finding, Severity
from euinvoice.validation import artifacts, schematron
from euinvoice.validation.artifacts import Source

SVRL_NS = _xml.SVRL


def svrl(*results: str) -> bytes:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><svrl:schematron-output xmlns:svrl="{SVRL_NS}">'
        '<svrl:active-pattern id="p"/><svrl:fired-rule context="/"/>' + "".join(results) + "</svrl:schematron-output>"
    ).encode()


# --- SVRL → Finding --------------------------------------------------------------------------------


def test_failed_assert_becomes_a_finding() -> None:
    result = schematron.svrl_findings(
        svrl(
            '<svrl:failed-assert test="x" id="BR-02" flag="fatal" location="/*:Invoice[1]">'
            "<svrl:text>[BR-02]-An Invoice shall have an Invoice number (BT-1).</svrl:text>"
            "</svrl:failed-assert>"
        ),
        source="cen-ubl",
    )

    assert result == (
        Finding(
            rule_id="BR-02",
            severity=Severity.FATAL,
            location="/*:Invoice[1]",
            message="[BR-02]-An Invoice shall have an Invoice number (BT-1).",
            source="cen-ubl",
        ),
    )


def test_successful_reports_count_too_and_document_order_is_kept() -> None:
    result = schematron.svrl_findings(
        svrl(
            '<svrl:failed-assert id="A" flag="warning" location="/a"><svrl:text>a</svrl:text></svrl:failed-assert>',
            '<svrl:successful-report id="B" flag="information" location="/b"><svrl:text>b</svrl:text>'
            "</svrl:successful-report>",
            '<svrl:failed-assert id="C" flag="error" location="/c"><svrl:text>c</svrl:text></svrl:failed-assert>',
        ),
        source="peppol-bis",
    )

    assert [(f.rule_id, f.severity) for f in result] == [
        ("A", Severity.WARNING),
        ("B", Severity.INFORMATION),
        ("C", Severity.ERROR),
    ]
    assert {f.source for f in result} == {"peppol-bis"}


def test_passing_document_has_no_findings() -> None:
    assert schematron.svrl_findings(svrl(), source="cen-ubl") == ()


@pytest.mark.parametrize("flag", [None, "", "FATAL", "info", "critical"])
def test_missing_or_unknown_flag_is_an_error_never_dropped(flag: str | None) -> None:
    attr = "" if flag is None else f' flag="{flag}"'
    result = schematron.svrl_findings(
        svrl(f'<svrl:failed-assert id="X-1"{attr} location="/x"><svrl:text>t</svrl:text></svrl:failed-assert>'),
        source="cen-ubl",
    )
    assert [(f.rule_id, f.severity) for f in result] == [("X-1", Severity.ERROR)]


def test_missing_id_location_and_text_are_kept_as_empty_or_none() -> None:
    (result,) = schematron.svrl_findings(svrl('<svrl:failed-assert flag="fatal"/>'), source="cen-ubl")
    assert result == Finding(rule_id="", severity=Severity.FATAL, location=None, message="", source="cen-ubl")


def test_message_whitespace_is_normalized_and_nested_markup_kept_as_text() -> None:
    (result,) = schematron.svrl_findings(
        svrl(
            '<svrl:failed-assert id="R" flag="fatal" location="/r"><svrl:text>\n   Value \n  '
            "<svrl:emph>ä€</svrl:emph>  is   wrong </svrl:text></svrl:failed-assert>"
        ),
        source="cen-ubl",
    )
    assert result.message == "Value ä€ is wrong"


def test_svrl_output_that_is_not_svrl_is_an_integrity_error() -> None:
    with pytest.raises(ArtifactIntegrityError, match="not SVRL"):
        schematron.svrl_findings(b"<html/>", source="cen-ubl")


def test_malformed_svrl_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        schematron.svrl_findings(b"<svrl:oops", source="cen-ubl")


# --- run() against a fake cache --------------------------------------------------------------------

# Synthetic stand-in for a compiled rule set: one fatal assert "the root has an ID child".
STYLESHEET = f"""<xsl:stylesheet version="3.0" xmlns:xsl="{_xml.XSLT}"
    xmlns:svrl="{SVRL_NS}">
  <xsl:template match="/">
    <svrl:schematron-output>
      <xsl:if test="not(/*/*:ID)">
        <svrl:failed-assert id="T-01" flag="fatal" location="/*[1]">
          <svrl:text>[T-01] The root needs an ID (<xsl:value-of select="local-name(/*)"/>).</svrl:text>
        </svrl:failed-assert>
      </xsl:if>
    </svrl:schematron-output>
  </xsl:template>
</xsl:stylesheet>"""
NAME: artifacts.SourceName = "cen-ubl"
RULES = schematron.RuleSet(NAME, "xslt/rules.xslt")
VALID = b'<?xml version="1.0" encoding="ISO-8859-1"?><Invoice><ID>F\xfc-1</ID></Invoice>'
INVALID = b"<Invoice><Note>no id</Note></Invoice>"


def install(root: Path, stylesheet: str = STYLESHEET, *, sha: str = "0" * 64) -> dict[str, Source]:
    """Lay out a complete fake cache entry for ``NAME`` and return the manifest describing it."""
    source = Source(
        name=NAME, version="1.0", url="https://example.com/x.zip", sha256=sha, license="MIT", members=("*",)
    )
    sources: dict[str, Source] = {NAME: source}
    target = root / NAME / "1.0"
    (target / "xslt").mkdir(parents=True, exist_ok=True)
    (target / "xslt" / "rules.xslt").write_text(stylesheet, encoding="utf-8")
    (target / artifacts.MARKER).write_text(artifacts._fingerprint(source, sources) + "\n", encoding="ascii")
    return sources


@pytest.fixture
def cache(tmp_path: Path) -> dict[str, Source]:
    return install(tmp_path)


def run(document: bytes | etree._Element, root: Path, sources: t.Mapping[str, Source]) -> tuple[Finding, ...]:
    return schematron.run(RULES, document, root=root, sources=sources)


def test_run_reports_failed_asserts_with_the_rule_set_source(tmp_path: Path, cache: dict[str, Source]) -> None:
    assert run(VALID, tmp_path, cache) == ()
    assert run(INVALID, tmp_path, cache) == (
        Finding("T-01", Severity.FATAL, "/*[1]", "[T-01] The root needs an ID (Invoice).", NAME),
    )


def test_run_accepts_an_element(tmp_path: Path, cache: dict[str, Source]) -> None:
    wrapper = _xml.parse(b"<wrapper><Invoice><Note/></Invoice></wrapper>")
    assert [f.rule_id for f in run(wrapper[0], tmp_path, cache)] == ["T-01"]


def test_element_tail_text_is_not_part_of_the_document(tmp_path: Path, cache: dict[str, Source]) -> None:
    # Regression: serializing with the tail made the hardened parser reject a valid invoice.
    wrapper = _xml.parse(b"<wrapper><Invoice><ID>1</ID></Invoice>trailing</wrapper>")
    assert run(wrapper[0], tmp_path, cache) == ()


def test_run_rejects_unsafe_or_wrong_input_before_saxon(tmp_path: Path, cache: dict[str, Source]) -> None:
    with pytest.raises(ParseError, match="DOCTYPE"):
        run(b'<!DOCTYPE x [<!ENTITY e "boom">]><Invoice>&e;</Invoice>', tmp_path, cache)
    with pytest.raises(TypeError, match="bytes"):
        run(t.cast(t.Any, "<Invoice/>"), tmp_path, cache)


def test_run_on_a_cold_cache_names_the_fetch_command(tmp_path: Path) -> None:
    with pytest.raises(ArtifactsNotAvailableError, match=r"artifacts fetch"):
        run(VALID, tmp_path, {NAME: install(tmp_path / "elsewhere")[NAME]})


def test_compiled_stylesheet_is_cached_per_path_and_fingerprint(tmp_path: Path, cache: dict[str, Source]) -> None:
    assert run(INVALID, tmp_path, cache) != ()
    # Same path and fingerprint: the cached executable is reused, the edited file is not re-read.
    install(tmp_path, STYLESHEET.replace('test="not(/*/*:ID)"', 'test="false()"'))
    assert run(INVALID, tmp_path, cache) != ()
    # A new artifact recipe (new fingerprint) compiles the stylesheet again.
    other = install(tmp_path, STYLESHEET.replace('test="not(/*/*:ID)"', 'test="false()"'), sha="1" * 64)
    assert run(INVALID, tmp_path, other) == ()


def test_run_is_safe_from_many_threads(tmp_path: Path, cache: dict[str, Source]) -> None:
    documents = [VALID, INVALID] * 20
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda d: run(d, tmp_path, cache), documents))
    assert results == [run(d, tmp_path, cache) for d in documents]


def test_stylesheet_that_does_not_compile_is_an_integrity_error(tmp_path: Path) -> None:
    sources = install(tmp_path, "<not-a-stylesheet/>", sha="2" * 64)
    with pytest.raises(ArtifactIntegrityError, match=r"cannot compile .*xslt/rules\.xslt"):
        run(VALID, tmp_path, sources)


def test_document_the_stylesheet_cannot_evaluate_is_a_fatal_finding(tmp_path: Path) -> None:
    # D9: like CEN's BR-CO rules on a non-numeric amount, abs() casts the ID to a number: FORG0001 on "abc".
    casting = STYLESHEET.replace('test="not(/*/*:ID)"', 'test="abs(/*/*:ID) lt 0"')
    sources = install(tmp_path, casting, sha="3" * 64)

    (finding,) = run(b"<Invoice><ID>abc</ID></Invoice>", tmp_path, sources)

    assert (finding.rule_id, finding.severity, finding.location, finding.source) == (
        schematron.RUNTIME_ERROR_RULE_ID,
        Severity.FATAL,
        None,
        NAME,
    )
    assert finding.message.startswith("xslt/rules.xslt could not evaluate the document: ")
    assert '"abc"' in finding.message
    assert run(b"<Invoice><ID>1.5</ID></Invoice>", tmp_path, sources) == ()


def test_stylesheet_without_output_is_an_integrity_error(tmp_path: Path) -> None:
    empty = f'<xsl:stylesheet version="3.0" xmlns:xsl="{_xml.XSLT}"/>'
    sources = install(tmp_path, empty.replace("/>", '><xsl:template match="/"/></xsl:stylesheet>'), sha="4" * 64)
    with pytest.raises(ArtifactIntegrityError, match="produced no SVRL"):
        run(VALID, tmp_path, sources)


def test_saxon_rejecting_what_lxml_accepted_is_a_parse_error(
    tmp_path: Path, cache: dict[str, Source], monkeypatch: pytest.MonkeyPatch
) -> None:
    import saxonche

    run(VALID, tmp_path, cache)  # compiles the stylesheet and creates the shared processor

    class Rejecting:
        def parse_xml(self, xml_text: str, encoding: str) -> object:
            raise saxonche.PySaxonApiError("SXXP0003 rejected")

    monkeypatch.setattr(schematron, "_processor", Rejecting())
    with pytest.raises(ParseError, match="Saxon rejected XML the hardened parser accepted: SXXP0003"):
        run(VALID, tmp_path, cache)


def test_missing_saxonche_names_the_validate_extra(
    tmp_path: Path, cache: dict[str, Source], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "saxonche", None)  # makes `import saxonche` raise ImportError
    with pytest.raises(ArtifactsNotAvailableError, match=r"euinvoice\[validate\]"):
        run(VALID, tmp_path, cache)


def test_public_surface() -> None:
    assert set(schematron.__all__) == {
        "CEN_CII",
        "CEN_UBL",
        "PEPPOL_CII",
        "PEPPOL_UBL",
        "RULE_SETS",
        "RUNTIME_ERROR_RULE_ID",
        "XRECHNUNG_CII",
        "XRECHNUNG_UBL",
        "RuleSet",
        "run",
        "svrl_findings",
    }


# --- rule-set catalogue ----------------------------------------------------------------------------


def test_rule_set_catalogue_points_into_known_sources() -> None:
    known = set(artifacts.load_manifest())
    assert set(schematron.RULE_SETS) == {
        schematron.CEN_UBL,
        schematron.CEN_CII,
        schematron.PEPPOL_UBL,
        schematron.PEPPOL_CII,
        schematron.XRECHNUNG_UBL,
        schematron.XRECHNUNG_CII,
    }
    for rule_set in schematron.RULE_SETS:
        assert rule_set.source in known
        assert not Path(rule_set.stylesheet).is_absolute()
        assert ".." not in Path(rule_set.stylesheet).parts
