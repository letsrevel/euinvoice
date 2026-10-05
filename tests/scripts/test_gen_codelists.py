"""Unit tests of ``scripts/gen_codelists.py`` on tiny synthetic Schematron snippets (no artifacts needed)."""

import ast
from pathlib import Path

import pytest

import gen_codelists as gen
from euinvoice.errors import ParseError

SCH_NS = 'xmlns="http://purl.oclc.org/dsdl/schematron"'


def _in(codes: str, compact: bool = False) -> str:
    """The CEN list-membership shape, e.g. ``contains(' A B ', concat(' ', normalize-space(.), ' '))``."""
    if compact:  # BR-CL-16..18 spell it without spaces after commas
        tail = "concat(' ',normalize-space(.),' ') ) ) )"
        return f"( ( not(contains(normalize-space(.),' ')) and contains( '{codes}',{tail}"
    return f"((not(contains(normalize-space(.), ' ')) and contains('{codes}', concat(' ', normalize-space(.), ' '))))"


# Shapes copied from the CEN code-list files (validation-1.3.16), with made-up short code lists:
# BR-CL-01 (UBL) holds two lists in one assert, BR-CL-24 uses an `or` of equality tests.
UBL_BR_CL_01 = (
    f"(self::cbc:InvoiceTypeCode and {_in(' 380 81 ')}) or (self::cbc:CreditNoteTypeCode and {_in(' 81 381 ')})"
)
SYNTHETIC_UBL = f"""<?xml version="1.0" encoding="UTF-8"?>
<pattern {SCH_NS} id="Codesmodel">
  <rule context="cbc:InvoiceTypeCode | cbc:CreditNoteTypeCode" flag="fatal">
    <assert test="{UBL_BR_CL_01}" id="BR-CL-01" flag="fatal">[BR-CL-01]-Document type.</assert>
  </rule>
  <rule context="cbc:DocumentCurrencyCode" flag="fatal">
    <assert test="{_in(" EUR  USD\n CHF ", compact=True)}" id="BR-CL-04" flag="fatal">[BR-CL-04]-Currency.</assert>
  </rule>
  <rule context="cbc:EmbeddedDocumentBinaryObject[@mimeCode]" flag="fatal">
    <assert test="((@mimeCode = 'application/pdf' or @mimeCode  = 'image/png'))" id="BR-CL-24">mime</assert>
  </rule>
</pattern>
"""

SYNTHETIC_CII = f"""<?xml version="1.0" encoding="ISO-8859-1"?>
<pattern {SCH_NS} id="EN16931-Codes">
  <rule context="rsm:ExchangedDocument/ram:TypeCode" flag="fatal">
    <assert test="{_in(" 81 380 381 ")}" flag="fatal" id="BR-CL-01">[BR-CL-01]-Document type.</assert>
  </rule>
  <rule context="ram:InvoiceCurrencyCode" flag="fatal">
    <assert test="{_in(" CHF EUR USD ")}" flag="fatal" id="BR-CL-04">[BR-CL-04]-Currency.</assert>
  </rule>
</pattern>
"""

TABLE = (
    gen.CodeList("DOC", "Document types.", (gen.Ref("cii", "BR-CL-01"),)),
    gen.CodeList("DOC_INVOICE_UBL", "UBL invoice types.", (gen.Ref("ubl", "BR-CL-01", 0),)),
    gen.CodeList("DOC_CREDIT_NOTE_UBL", "UBL credit note types.", (gen.Ref("ubl", "BR-CL-01", 1),)),
    gen.CodeList("CURRENCY", "Currencies.", (gen.Ref("ubl", "BR-CL-04"), gen.Ref("cii", "BR-CL-04"))),
    gen.CodeList("MIME", "MIME codes.", (gen.Ref("ubl", "BR-CL-24"),)),
)


def _extracted() -> dict[gen.Syntax, gen.RuleLists]:
    return {"ubl": gen.extract(SYNTHETIC_UBL.encode()), "cii": gen.extract(SYNTHETIC_CII.encode("iso-8859-1"))}


def test_extract_reads_every_list_of_every_assert_in_document_order() -> None:
    assert gen.extract(SYNTHETIC_UBL.encode()) == {
        "BR-CL-01": gen.Assert((("380", "81"), ("81", "381"))),
        "BR-CL-04": gen.Assert((("EUR", "USD", "CHF"),)),
        "BR-CL-24": gen.Assert((("application/pdf", "image/png"),)),
    }


def test_extract_honours_the_declared_encoding() -> None:
    assert gen.extract(SYNTHETIC_CII.encode("iso-8859-1"))["BR-CL-04"] == gen.Assert((("CHF", "EUR", "USD"),))


def test_extract_records_case_folding() -> None:
    # Shape of BR-CL-22 (VATEX) in both CEN 1.3.16 files.
    value = "concat(' ', normalize-space(upper-case(.)), ' ')"
    test = f"((not(contains(normalize-space(.), ' ')) and contains(' VATEX-EU-G ', {value})))"
    sch = f"<pattern {SCH_NS}><rule context='x'><assert id='BR-CL-22' test=\"{test}\"/></rule></pattern>"

    assert gen.extract(sch.encode()) == {"BR-CL-22": gen.Assert((("VATEX-EU-G",),), case_insensitive=True)}


def _vatex(*, folded: bool, acknowledged: bool) -> tuple[dict[gen.Syntax, gen.RuleLists], tuple[gen.CodeList, ...]]:
    extracted: dict[gen.Syntax, gen.RuleLists] = {"ubl": {"BR-CL-22": gen.Assert((("VATEX-EU-G",),), folded)}}
    entry = gen.CodeList("VATEX", "VATEX.", (gen.Ref("ubl", "BR-CL-22"),), case_insensitive=acknowledged)
    return extracted, (entry,)


@pytest.mark.parametrize(
    ("folded", "message"),
    [(True, "case-folds the value but the table says case_insensitive=False"), (False, "is case-sensitive but")],
)
def test_build_rejects_case_folding_the_table_does_not_match(folded: bool, message: str) -> None:
    extracted, table = _vatex(folded=folded, acknowledged=not folded)

    with pytest.raises(gen.GenerationError, match=f"VATEX: ubl BR-CL-22 {message}"):
        gen.build(extracted, table)


def test_render_tells_callers_to_upper_case_for_case_insensitive_lists() -> None:
    extracted, table = _vatex(folded=True, acknowledged=True)

    source = gen.render(gen.build(extracted, table), table, ())

    assert "match `code.strip().upper()`" in source


def test_extract_rejects_an_assert_without_a_recognised_code_list() -> None:
    sch = f"<pattern {SCH_NS}><rule context='x'><assert id='BR-CL-99' test=\"string-length(.) = 3\"/></rule></pattern>"
    with pytest.raises(gen.GenerationError, match="BR-CL-99"):
        gen.extract(sch.encode())


def test_extract_rejects_an_assert_without_id() -> None:
    sch = f"<pattern {SCH_NS}><rule context='x'><assert test=\"contains(' A ', .)\"/></rule></pattern>"
    with pytest.raises(gen.GenerationError, match="without id"):
        gen.extract(sch.encode())


def test_extract_rejects_duplicate_rule_ids() -> None:
    assert_ = "<assert id='BR-CL-01' test=\"contains(' A ', .)\"/>"
    sch = f"<pattern {SCH_NS}><rule context='x'>{assert_}{assert_}</rule></pattern>"
    with pytest.raises(gen.GenerationError, match="BR-CL-01 twice"):
        gen.extract(sch.encode())


def test_extract_rejects_doctype_and_does_not_expand_entities() -> None:
    sch = f'<!DOCTYPE pattern [<!ENTITY x "A B">]><pattern {SCH_NS}/>'
    with pytest.raises(ParseError, match="DOCTYPE"):
        gen.extract(sch.encode())


def test_build_maps_every_list_and_sorts_codes() -> None:
    lists = gen.build(_extracted(), TABLE)

    assert lists == {
        "DOC": ("81", "380", "381"),
        "DOC_INVOICE_UBL": ("81", "380"),
        "DOC_CREDIT_NOTE_UBL": ("81", "381"),
        "CURRENCY": ("CHF", "EUR", "USD"),
        "MIME": ("application/pdf", "image/png"),
    }


def test_build_rejects_lists_that_differ_between_references() -> None:
    extracted = _extracted()
    extracted["cii"] = {**extracted["cii"], "BR-CL-04": gen.Assert((("EUR", "USD"),))}

    with pytest.raises(gen.GenerationError, match="CURRENCY: cii BR-CL-04 differs from ubl BR-CL-04"):
        gen.build(extracted, TABLE)


def test_build_rejects_an_unclaimed_list() -> None:
    with pytest.raises(gen.GenerationError, match=r"unmapped code lists: cii BR-CL-01$"):
        gen.build(_extracted(), TABLE[1:])


def test_build_rejects_a_reference_to_a_missing_list() -> None:
    table = (*TABLE, gen.CodeList("GONE", "Missing.", (gen.Ref("cii", "BR-CL-24"),)))
    with pytest.raises(gen.GenerationError, match="GONE: cii BR-CL-24 not found"):
        gen.build(_extracted(), table)


def test_build_rejects_a_list_claimed_twice() -> None:
    table = (*TABLE, gen.CodeList("AGAIN", "Twice.", (gen.Ref("ubl", "BR-CL-24"),)))
    with pytest.raises(gen.GenerationError, match="ubl BR-CL-24 claimed by MIME and AGAIN"):
        gen.build(_extracted(), table)


def _render() -> str:
    provenance = (
        gen.Provenance("cen-ubl", "1.3.16", "schematron/codelist/EN16931-UBL-codes.sch", "ab" * 32),
        gen.Provenance("cen-cii", "1.3.16", "schematron/codelist/EN16931-CII-codes.sch", "cd" * 32),
    )
    return gen.render(gen.build(_extracted(), TABLE), TABLE, provenance)


def test_render_is_deterministic_valid_python_with_typed_frozensets() -> None:
    source = _render()

    assert source == _render()
    module = ast.parse(source)
    assigned = {
        node.target.id: node
        for node in module.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert list(assigned) == ["DOC", "DOC_INVOICE_UBL", "DOC_CREDIT_NOTE_UBL", "CURRENCY", "MIME"]
    mime = assigned["MIME"]
    assert mime.value is not None
    assert ast.unparse(mime.annotation) == "t.Final[frozenset[str]]"
    assert ast.unparse(mime.value) == "frozenset({'application/pdf', 'image/png'})"


def test_render_cites_sources_rules_and_regeneration_command() -> None:
    source = _render()

    assert "#   cen-ubl 1.3.16 schematron/codelist/EN16931-UBL-codes.sch\n#     sha256 " + "ab" * 32 in source
    assert "make codelists" in source
    assert "# Currencies. BR-CL-04 (ubl, cii)." in source
    assert "# UBL credit note types. BR-CL-01 list 2 (ubl)." in source


def test_render_wraps_long_lists_within_the_line_limit() -> None:
    codes = tuple(f"C{i:04d}" for i in range(500))
    table = (gen.CodeList("BIG", "Big.", (gen.Ref("ubl", "BR-CL-23"),)),)

    source = gen.render({"BIG": codes}, table, ())

    assert max(len(line) for line in source.splitlines()) <= gen.LINE_LIMIT
    code_lines = [line for line in source.splitlines() if line.startswith('    "C')]
    assert len(code_lines) <= len(codes) // 10  # compact: at least 10 codes per line


def test_render_refuses_to_exceed_the_file_length_limit() -> None:
    table = (gen.CodeList("BIG", "Big.", (gen.Ref("ubl", "BR-CL-23"),)),)
    codes = tuple(f"C{i:04d}" for i in range(500))

    assert gen.render({"BIG": codes}, table, ()).count("\n") <= gen.MAX_LINES
    with pytest.raises(gen.GenerationError, match="over the 30-line limit: split the biggest list"):
        gen.render({"BIG": codes}, table, (), max_lines=30)


def test_main_writes_the_rendered_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ubl, cii = tmp_path / "ubl.sch", tmp_path / "cii.sch"
    ubl.write_text(SYNTHETIC_UBL, encoding="utf-8")
    cii.write_text(SYNTHETIC_CII, encoding="iso-8859-1")
    out = tmp_path / "out.py"
    monkeypatch.setattr(gen, "TABLE", TABLE)
    inputs = {
        "ubl": gen.Input("cen-ubl", "9.9", tmp_path, "ubl.sch"),
        "cii": gen.Input("cen-cii", "9.9", tmp_path, "cii.sch"),
    }
    monkeypatch.setattr(gen, "inputs", lambda: inputs)

    assert gen.main(["--output", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == gen.generate()
    assert "#   cen-cii 9.9 cii.sch\n" in out.read_text(encoding="utf-8")
