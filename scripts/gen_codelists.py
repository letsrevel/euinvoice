"""Generate ``src/euinvoice/model/codes/_generated.py`` from the pinned CEN code-list and model Schematron.

Run with ``make codelists`` (needs ``make artifacts``). The inputs of the pinned CEN release are:

* the BR-CL-* asserts of ``schematron/codelist/EN16931-UBL-codes.sch`` (source ``cen-ubl``) and
  ``schematron/codelist/EN16931-CII-codes.sch`` (source ``cen-cii``), read by :func:`extract`;
* the BR-CL-* params of the syntax binding files ``schematron/UBL/EN16931-UBL-model.sch`` and
  ``schematron/CII/EN16931-CII-model.sch``, read by :func:`extract_model`. Some code lists are bound
  there instead: in CEN 1.3.16, UBL BR-CL-08 (note subject codes; asserted by
  ``schematron/abstract/EN16931-model.sch``). The CII model file has no BR-CL param, and the
  ``*-syntax.sch`` files hold no code list.

Both encode each code list in one of two shapes:

* ``contains(' A B C ', concat(' ', normalize-space(.), ' '))``: a space-separated list literal. One
  assert may hold several (UBL BR-CL-01 has one list per root element, UBL BR-CL-10 adds ``SEPA``);
* ``@mimeCode = 'a' or @mimeCode = 'b'``: equality tests (BR-CL-24).

Lists in model params that are not BR-CL rules (e.g. the BR-CO-09 VAT identifier prefixes) are not
code lists and are skipped.

``contains`` lists are matched against ``normalize-space(...)`` of the value (BR-CL-24 compares the
attribute as is). BR-CL-22 also upper-cases it
(``normalize-space(upper-case(.))``); :func:`extract` records any ``upper-case(`` / ``lower-case(`` and
:func:`build` fails unless the table entry acknowledges it (``case_insensitive=True``).

:data:`TABLE` names every list. :func:`build` fails unless every list of every rule is claimed by
exactly one entry and every list an entry claims is identical, so a new or changed upstream list stops
the generator instead of slipping through. Where the UBL and CII files differ, the entry is split by
syntax and the title says how they differ.
"""

import argparse
import hashlib
import re
import sys
import textwrap
import typing as t
from dataclasses import dataclass
from pathlib import Path

from euinvoice import _xml  # ruff: ignore[import-private-name] - the one hardened parser (D10), also for dev scripts
from euinvoice.validation import artifacts

Syntax = t.Literal["ubl", "cii"]


class Assert(t.NamedTuple):
    """The code lists of one BR-CL assert.

    Attributes:
        lists: Its code lists, in document order, codes in upstream order.
        case_insensitive: The test case-folds the value (``upper-case(`` or ``lower-case(``).
    """

    lists: tuple[tuple[str, ...], ...]
    case_insensitive: bool = False


RuleLists = dict[str, Assert]

SCH = "{http://purl.oclc.org/dsdl/schematron}"
LINE_LIMIT = 100
# scripts/check-file-length.sh limit. ponytail: the generated module is ~550 lines with CEN 1.3.16. If a
# pin bump crosses this, render() fails; then emit UNECE_REC20_REC21_UNIT (the biggest list, ~150
# lines) into its own generated module (e.g. codes/_generated_units.py) and re-export it.
MAX_LINES = 600
REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO / "src" / "euinvoice" / "model" / "codes" / "_generated.py"

# A list literal inside contains(...), and the right-hand side of `@attr = '...'` (BR-CL-24).
_CONTAINS = re.compile(r"contains\(\s*'([^']*)'")
_EQUALS = re.compile(r"@[\w:-]+\s*=\s*'([^']*)'")
_CASE_FOLD = re.compile(r"\b(?:upper|lower)-case\(")
# Model params that hold a multi-code list but are not code lists. BR-CO-09: the VAT identifier prefixes
# (BT-31, BT-48, BT-63) of a business rule, not a BR-CL rule (abstract/EN16931-model.sch, CEN 1.3.16).
_NOT_CODE_LISTS: t.Final[frozenset[str]] = frozenset({"BR-CO-09"})


class GenerationError(Exception):
    """The Schematron does not have the shape the generator expects, or :data:`TABLE` is out of date."""


@dataclass(frozen=True)
class Ref:
    """One code list inside a BR-CL assert.

    Attributes:
        syntax: Which code-list file (``ubl`` or ``cii``).
        rule: Assert id, e.g. ``BR-CL-04``.
        index: Position of the list among the assert's lists; ``None`` if the assert has exactly one.
    """

    syntax: Syntax
    rule: str
    index: int | None = None

    def __str__(self) -> str:
        """Return e.g. ``ubl BR-CL-01[1]`` (the index only when the assert holds several lists)."""
        return f"{self.syntax} {self.rule}" + ("" if self.index is None else f"[{self.index}]")


@dataclass(frozen=True)
class CodeList:
    """A generated constant: a name, what it is, and every assert list it must equal.

    Attributes:
        name: Python constant name.
        title: What the code list is (rendered as a comment above the constant).
        refs: The asserts' lists it is extracted from; all must hold the same set of codes.
        case_insensitive: The asserts case-fold the value before matching; must agree with
            :attr:`Assert.case_insensitive` of every ref.
    """

    name: str
    title: str
    refs: tuple[Ref, ...]
    case_insensitive: bool = False


@dataclass(frozen=True)
class Provenance:
    """Where an input file came from, cited in the generated header."""

    source: str
    version: str
    member: str
    sha256: str


class Input(t.NamedTuple):
    """One Schematron file in the artifact cache and the function that reads its code lists."""

    syntax: Syntax
    source: artifacts.SourceName
    version: str
    root: Path
    member: str
    reader: t.Callable[[bytes], RuleLists]


def _both(*rules: str) -> tuple[Ref, ...]:
    syntaxes: tuple[Syntax, ...] = ("ubl", "cii")
    return tuple(Ref(syntax, rule) for syntax in syntaxes for rule in rules)


# Every list of both CEN code-list files (validation-1.3.16). Differences between UBL and CII are
# asserted by build() (each entry's refs must be identical) and spelled out in the titles.
TABLE: tuple[CodeList, ...] = (
    CodeList(
        "UNTDID_1001_DOCUMENT_TYPE",
        "UNTDID 1001 document type codes for invoices and credit notes. It equals the union of the two UBL "
        "lists below.",
        (Ref("cii", "BR-CL-01"),),
    ),
    CodeList(
        "UNTDID_1001_INVOICE_TYPE_UBL",
        "UNTDID 1001 codes UBL accepts in cbc:InvoiceTypeCode (root Invoice).",
        (Ref("ubl", "BR-CL-01", 0),),
    ),
    CodeList(
        "UNTDID_1001_CREDIT_NOTE_TYPE_UBL",
        "UNTDID 1001 codes UBL accepts in cbc:CreditNoteTypeCode (root CreditNote). 81 is in both UBL lists.",
        (Ref("ubl", "BR-CL-01", 1),),
    ),
    CodeList("ISO_4217_CURRENCY", "ISO 4217 alpha-3 currency codes.", _both("BR-CL-03", "BR-CL-04", "BR-CL-05")),
    CodeList(
        "UNTDID_2005_VAT_POINT_DATE_UBL",
        "Value added tax point date codes, UBL: a restriction of UNTDID 2005 (cac:InvoicePeriod/"
        "cbc:DescriptionCode). CII uses UNTDID 2475 codes instead.",
        (Ref("ubl", "BR-CL-06"),),
    ),
    CodeList(
        "UNTDID_2475_VAT_POINT_DATE_CII",
        "Value added tax point date codes, CII: a restriction of UNTDID 2475 (ram:DueDateTypeCode). UBL "
        "uses UNTDID 2005 codes instead.",
        (Ref("cii", "BR-CL-06"),),
    ),
    CodeList(
        "UNTDID_1153_REFERENCE_QUALIFIER",
        "Object identifier scheme codes: a restriction of UNTDID 1153.",
        _both("BR-CL-07"),
    ),
    CodeList(
        "UNTDID_4451_TEXT_SUBJECT",
        "Note subject codes, CII (ram:SubjectCode): a restriction of UNTDID 4451. A strict superset of "
        "UNTDID_4451_NOTE_SUBJECT_UBL. The syntax-neutral model accepts this superset; the per-syntax "
        "Schematron decides (D8).",
        (Ref("cii", "BR-CL-08"),),
    ),
    CodeList(
        "UNTDID_4451_NOTE_SUBJECT_UBL",
        "Note subject codes, UBL: a restriction of UNTDID 4451, bound in the UBL model file, not the "
        "codes file. It checks the code between the first two '#' of cbc:Note ('#AAI#text'), not "
        "normalize-spaced, as a substring of the list. A note without '#', or whose '#...#' segment is "
        "not exactly 3 characters long, is not checked at all. A strict subset of "
        "UNTDID_4451_TEXT_SUBJECT (CII).",
        (Ref("ubl", "BR-CL-08"),),
    ),
    CodeList(
        "ISO_6523_ICD",
        "ISO 6523 ICD identifier scheme codes (party, legal registration, item standard and delivery "
        "location identifiers).",
        (Ref("ubl", "BR-CL-10", 0), *_both("BR-CL-11", "BR-CL-21", "BR-CL-26"), Ref("cii", "BR-CL-10")),
    ),
    CodeList(
        "PARTY_IDENTIFIER_EXTRA_SCHEME_UBL",
        "Scheme codes UBL BR-CL-10 accepts besides ISO 6523 ICD, only in cac:PartyIdentification under "
        "cac:AccountingSupplierParty or cac:PayeeParty. CII has no such extra list.",
        (Ref("ubl", "BR-CL-10", 1),),
    ),
    CodeList("UNTDID_7143_ITEM_CLASSIFICATION", "UNTDID 7143 item classification scheme codes.", _both("BR-CL-13")),
    CodeList(
        "ISO_3166_1_COUNTRY_UBL",
        "ISO 3166-1 alpha-2 country codes, UBL file. It has SS and lacks AN, unlike the CII file. The "
        "syntax-neutral model accepts the union, ISO_3166_1_COUNTRY in euinvoice.model.codes.derived.",
        (Ref("ubl", "BR-CL-14"), Ref("ubl", "BR-CL-15")),
    ),
    CodeList(
        "ISO_3166_1_COUNTRY_CII",
        "ISO 3166-1 alpha-2 country codes, CII file. It has AN and lacks SS, unlike the UBL file. The "
        "syntax-neutral model accepts the union, ISO_3166_1_COUNTRY in euinvoice.model.codes.derived.",
        (Ref("cii", "BR-CL-14"), Ref("cii", "BR-CL-15")),
    ),
    CodeList("UNTDID_4461_PAYMENT_MEANS", "UNTDID 4461 payment means codes.", _both("BR-CL-16")),
    CodeList("UNTDID_5305_VAT_CATEGORY", "UNTDID 5305 VAT category codes.", _both("BR-CL-17", "BR-CL-18")),
    CodeList("UNTDID_5189_ALLOWANCE_REASON", "UNTDID 5189 allowance reason codes.", _both("BR-CL-19")),
    CodeList("UNTDID_7161_CHARGE_REASON", "UNTDID 7161 charge reason codes.", _both("BR-CL-20")),
    CodeList(
        "VATEX_EXEMPTION_REASON",
        "CEF VATEX VAT exemption reason codes.",
        _both("BR-CL-22"),
        case_insensitive=True,
    ),
    CodeList("UNECE_REC20_REC21_UNIT", "UN/ECE Recommendation 20 unit codes with Rec 21 extension.", _both("BR-CL-23")),
    CodeList("MIME_CODE", "MIME codes of attached binary objects.", _both("BR-CL-24")),
    CodeList("CEF_EAS", "CEF EAS electronic address scheme codes.", _both("BR-CL-25")),
)


def extract(data: bytes) -> RuleLists:
    """Extract the code lists of every assert of a code-list Schematron file.

    Args:
        data: The ``.sch`` file bytes (its XML declaration names the encoding).

    Returns:
        Assert id → its code lists (document order, codes in upstream order) and whether it case-folds.

    Raises:
        euinvoice.errors.ParseError: Malformed XML or a DOCTYPE (hardened parser, D10).
        GenerationError: An assert without id, a duplicate id, or an assert whose test holds no list
            the generator recognises.
    """
    lists: RuleLists = {}
    for node in _xml.parse(data).iter(f"{SCH}assert"):
        rule, test = node.get("id"), node.get("test", "")
        if rule is None:
            raise GenerationError(f"assert without id: {test[:80]!r}")
        _add(lists, rule, test)
    return lists


def extract_model(data: bytes) -> RuleLists:
    """Extract the code lists of the BR-CL-* params of a CEN model binding file.

    The ``schematron/{UBL,CII}/EN16931-*-model.sch`` files bind the abstract rules to a syntax with
    ``<param name="BR-CL-08" value="..."/>``. Params of other rules are ignored, but one that holds a
    multi-code list literal fails unless it is in :data:`_NOT_CODE_LISTS` (fail closed).

    Args:
        data: The ``.sch`` file bytes.

    Returns:
        Rule id → its code lists, as :func:`extract`.

    Raises:
        euinvoice.errors.ParseError: Malformed XML or a DOCTYPE (hardened parser, D10).
        GenerationError: A duplicate BR-CL param, one whose value holds no recognised list, or a
            multi-code list in a non-BR-CL param missing from :data:`_NOT_CODE_LISTS`.
    """
    lists: RuleLists = {}
    for node in _xml.parse(data).iter(f"{SCH}param"):
        name, value = node.get("name", ""), node.get("value", "")
        if name.startswith("BR-CL-"):
            _add(lists, name, value)
        elif name not in _NOT_CODE_LISTS and any(len(lit.split()) > 1 for lit in _CONTAINS.findall(value)):
            raise GenerationError(f"{name}: a code list outside a BR-CL param; claim it or add it to _NOT_CODE_LISTS")
    return lists


def _add(lists: RuleLists, rule: str, test: str) -> None:
    """Add the code lists of one rule's XPath test to ``lists``."""
    if rule in lists:
        raise GenerationError(f"{rule} twice in the same file")
    found = [tuple(lit.split()) for lit in _CONTAINS.findall(test) if lit.strip()]
    if equals := _EQUALS.findall(test):
        found.append(tuple(equals))
    if not found:
        raise GenerationError(f"{rule}: no code list recognised in {test[:80]!r}")
    lists[rule] = Assert(tuple(found), bool(_CASE_FOLD.search(test)))


def _code_order(code: str) -> tuple[int, int, str]:
    """Sort key: numeric codes by value first (``2`` before ``10``), then the others as text."""
    return (0, int(code), code) if code.isdigit() else (1, 0, code)


def _lookup(extracted: t.Mapping[Syntax, RuleLists], ref: Ref) -> tuple[tuple[str, ...], bool] | None:
    found = extracted[ref.syntax].get(ref.rule)
    if found is None:
        return None
    if ref.index is None:
        return (found.lists[0], found.case_insensitive) if len(found.lists) == 1 else None
    return (found.lists[ref.index], found.case_insensitive) if ref.index < len(found.lists) else None


def build(extracted: t.Mapping[Syntax, RuleLists], table: t.Sequence[CodeList]) -> dict[str, tuple[str, ...]]:
    """Map the extracted lists to the table's constants.

    Args:
        extracted: Per syntax, the output of :func:`extract`.
        table: The constants to build (normally :data:`TABLE`).

    Returns:
        Constant name → sorted, de-duplicated codes, in table order.

    Raises:
        GenerationError: A reference is missing, the references of one constant differ, a list is
            claimed twice, a list is claimed by no constant, or an entry's ``case_insensitive`` does
            not match whether its asserts case-fold the value.
    """
    claimed: dict[Ref, str] = {}
    result: dict[str, tuple[str, ...]] = {}
    for entry in table:
        codes: frozenset[str] | None = None
        for ref in entry.refs:
            hit = _lookup(extracted, ref)
            if hit is None:
                raise GenerationError(f"{entry.name}: {ref} not found")
            found, case_insensitive = hit
            if case_insensitive != entry.case_insensitive:
                raise GenerationError(
                    f"{entry.name}: {ref} "
                    + ("case-folds the value" if case_insensitive else "is case-sensitive")
                    + f" but the table says case_insensitive={entry.case_insensitive}"
                )
            if ref in claimed:
                raise GenerationError(f"{ref} claimed by {claimed[ref]} and {entry.name}")
            claimed[ref] = entry.name
            if codes is None:
                codes = frozenset(found)
            elif frozenset(found) != codes:
                raise GenerationError(f"{entry.name}: {ref} differs from {entry.refs[0]}")
        result[entry.name] = tuple(sorted(codes or (), key=_code_order))
    unclaimed = [
        str(Ref(syntax, rule, None if len(found.lists) == 1 else i))
        for syntax, rule_lists in extracted.items()
        for rule, found in rule_lists.items()
        for i in range(len(found.lists))
        if Ref(syntax, rule, None if len(found.lists) == 1 else i) not in claimed
    ]
    if unclaimed:
        raise GenerationError("unmapped code lists: " + ", ".join(unclaimed))
    return result


def _cite(refs: t.Sequence[Ref]) -> str:
    """Return e.g. ``BR-CL-03, BR-CL-04 (ubl, cii); BR-CL-01 list 2 (ubl)``."""
    by_rule: dict[str, list[str]] = {}
    for ref in refs:
        label = ref.rule if ref.index is None else f"{ref.rule} list {ref.index + 1}"
        by_rule.setdefault(label, []).append(ref.syntax)
    by_syntaxes: dict[str, list[str]] = {}
    for label, syntaxes in by_rule.items():
        by_syntaxes.setdefault(", ".join(syntaxes), []).append(label)
    return "; ".join(f"{', '.join(labels)} ({syntaxes})" for syntaxes, labels in by_syntaxes.items())


def _wrap(items: t.Iterable[str], indent: str) -> list[str]:
    lines: list[str] = []
    line = indent
    for item in items:
        if len(line) + len(item) + 1 > LINE_LIMIT and line != indent:
            lines.append(line.rstrip())
            line = indent
        line += item + " "
    lines.append(line.rstrip())
    return lines


def render(
    lists: t.Mapping[str, t.Sequence[str]],
    table: t.Sequence[CodeList],
    provenance: t.Sequence[Provenance],
    *,
    max_lines: int = MAX_LINES,
) -> str:
    """Render the generated module.

    Args:
        lists: Output of :func:`build`.
        table: The table ``lists`` was built from (for titles and citations).
        provenance: The input files, cited in the header.
        max_lines: Most lines the module may have (``scripts/check-file-length.sh``).

    Returns:
        Python source: one ``t.Final[frozenset[str]]`` per table entry, codes sorted and wrapped at
        :data:`LINE_LIMIT`, under ``# fmt: off`` so that ``ruff format`` keeps the compact layout.

    Raises:
        GenerationError: The module would exceed ``max_lines`` (see the ponytail at :data:`MAX_LINES`).
    """
    out = [
        "# Generated by scripts/gen_codelists.py from the pinned CEN EN 16931 Schematron (code-list, model).",
        "# DO NOT EDIT. Regenerate with `make codelists` (after `make artifacts`).",
        "#",
        "# Sources (IMPLEMENTATION_PLAN.md D7, src/euinvoice/validation/manifest.toml):",
        *(line for p in provenance for line in (f"#   {p.source} {p.version} {p.member}", f"#     sha256 {p.sha256}")),
        '"""EN 16931 code lists (BR-CL-* rules), generated from the pinned CEN Schematron.',
        "",
        "Every constant holds the codes its BR-CL rules accept, sorted. All rules but BR-CL-24 (MIME) and",
        "UBL BR-CL-08 (note subject, see its comment) match the value after ``normalize-space``, so strip",
        "values before a lookup. Do not edit: change ``scripts/gen_codelists.py`` and run ``make codelists``.",
        '"""',
        "",
        "import typing as t",
        "",
        "# fmt: off",
    ]
    for entry in table:
        comment = f"{entry.title} {_cite(entry.refs)}."
        if entry.case_insensitive:
            comment += " The rule upper-cases the value first: match `code.strip().upper()`."
        out += [
            "",
            *textwrap.wrap(comment, LINE_LIMIT, initial_indent="# ", subsequent_indent="# ", break_on_hyphens=False),
        ]
        out.append(f"{entry.name}: t.Final[frozenset[str]] = frozenset({{")
        out += _wrap((f'"{code}",' for code in lists[entry.name]), "    ")
        out.append("})")
    if len(out) > max_lines:
        raise GenerationError(
            f"generated module has {len(out)} lines, over the {max_lines}-line limit: split the biggest "
            "list (UNECE_REC20_REC21_UNIT) into its own generated module (see MAX_LINES)"
        )
    return "\n".join(out) + "\n"


def inputs() -> tuple[Input, ...]:
    """Return the pinned code-list and model Schematron files in the artifact cache.

    Raises:
        euinvoice.errors.ArtifactsNotAvailableError: ``make artifacts`` has not been run.
    """
    manifest = artifacts.load_manifest()
    files: tuple[tuple[Syntax, artifacts.SourceName, str, t.Callable[[bytes], RuleLists]], ...] = (
        ("ubl", "cen-ubl", "schematron/codelist/EN16931-UBL-codes.sch", extract),
        ("ubl", "cen-ubl", "schematron/UBL/EN16931-UBL-model.sch", extract_model),
        ("cii", "cen-cii", "schematron/codelist/EN16931-CII-codes.sch", extract),
        ("cii", "cen-cii", "schematron/CII/EN16931-CII-model.sch", extract_model),
    )
    return tuple(
        Input(syntax, source, manifest[source].version, artifacts.source_dir(source), member, reader)
        for syntax, source, member, reader in files
    )


def generate() -> str:
    """Extract, check and render the code lists of the pinned artifacts.

    Returns:
        The content of ``_generated.py``.

    Raises:
        GenerationError: Two files of one syntax hold the same rule, or :func:`build` fails.
    """
    extracted: dict[Syntax, RuleLists] = {}
    origin: dict[tuple[Syntax, str], str] = {}
    provenance: list[Provenance] = []
    for syntax, source, version, root, member, reader in inputs():
        data = (root / member).read_bytes()
        for rule, found in reader(data).items():
            if (syntax, rule) in origin:
                raise GenerationError(f"{syntax} {rule} in both {origin[syntax, rule]} and {member}")
            origin[syntax, rule] = member
            extracted.setdefault(syntax, {})[rule] = found
        provenance.append(Provenance(source, version, member, hashlib.sha256(data).hexdigest()))
    return render(build(extracted, TABLE), TABLE, provenance)


def main(argv: t.Sequence[str] | None = None) -> int:
    """Write the generated module (default: ``src/euinvoice/model/codes/_generated.py``)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    args.output.write_text(generate(), encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
