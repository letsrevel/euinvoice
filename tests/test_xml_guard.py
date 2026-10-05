"""AC of #6: no module under ``src/`` except ``euinvoice._xml`` parses XML (IMPLEMENTATION_PLAN.md D10).

The check walks the AST, so aliases (``from lxml import etree as ET``), from-imports and docstrings are
handled correctly, unlike a text grep.
"""

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "euinvoice"

# Parser and loader entry points of lxml, the stdlib and saxonche, flagged as attribute or imported
# name whatever object they hang off (unless directly on a safe name, see below).
FORBIDDEN_NAMES = frozenset(
    {
        "fromstring",
        "fromstringlist",
        "parse",
        "XML",
        "XMLID",
        "XMLDTDID",
        "HTML",
        "iterparse",
        "XMLParser",
        "XMLPullParser",
        "HTMLParser",
        "ETCompatXMLParser",
        "XMLSchema",
        "DTD",
        "RelaxNG",
        "XSLT",
        "XInclude",
        "xinclude",
        "parse_xml",
        "parseString",
    }
)
# Whole modules that are parsers in their own right.
FORBIDDEN_MODULES = ("xml", "lxml.objectify", "lxml.html")
# Module names that must never count as a safe root, even when imported from euinvoice.
PARSER_MODULE_NAMES = frozenset({"etree", "objectify", "html", "ElementTree", "minidom", "sax", "expat"})
# The public helpers of euinvoice._xml.
XML_HELPERS = frozenset({"parse", "new_parser", "load_trusted_schema"})
# Names imported from these modules are safe roots: a forbidden attribute directly on them is fine
# (``_xml.parse``, ``urllib.parse``), but not deeper (``_xml.etree.parse``).
SAFE_MODULES = ("euinvoice", "urllib")
# Explicit per-file exceptions, as {path relative to src/euinvoice: names}. Keep this tiny and give
# a reason per entry (e.g. ``parse_xml`` will be allowed only in ``validate/schematron.py``, which
# hands Saxon bytes that already passed ``_xml.parse``).
PER_FILE_ALLOWED: dict[str, frozenset[str]] = {}


def _in(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == p or module.startswith(p + ".") for p in prefixes)


def _check_import(node: ast.Import | ast.ImportFrom, allowed: frozenset[str], safe_roots: set[str]) -> list[str]:
    """Return forbidden imports in ``node``; record names bound from safe modules in ``safe_roots``."""
    if isinstance(node, ast.Import):
        found = []
        for alias in node.names:
            if _in(alias.name, FORBIDDEN_MODULES):
                found.append(f"import {alias.name}")
            elif _in(alias.name, SAFE_MODULES):
                safe_roots.add(alias.asname or alias.name.split(".")[0])
        return found
    module = node.module or ""
    names = [a.name for a in node.names]
    if node.level or _in(module, SAFE_MODULES):
        if "*" in names and (module.endswith("_xml") or not (node.level or _in(module, ("euinvoice",)))):
            return [f"from {module} import *"]
        if module.endswith("_xml") or names == ["_xml"]:
            bad = [n for n in names if n in (FORBIDDEN_NAMES | PARSER_MODULE_NAMES) - XML_HELPERS - allowed]
        else:
            bad = [n for n in names if n in PARSER_MODULE_NAMES]
        safe_roots.update(a.asname or a.name for a in node.names if a.name not in PARSER_MODULE_NAMES)
        return [f"from {module} import {n}" for n in bad]
    if "*" in names or _in(module, FORBIDDEN_MODULES):
        return [f"from {module} import {', '.join(names)}"]
    return [
        f"from {module} import {n}"
        for n in names
        if n in FORBIDDEN_NAMES - allowed or f"{module}.{n}" in FORBIDDEN_MODULES
    ]


def _check_node(node: ast.AST, allowed: frozenset[str], safe_roots: set[str]) -> str | None:
    """Return a description if ``node`` is a forbidden attribute use or ``ElementTree(file=...)`` call."""
    if (
        isinstance(node, ast.Attribute)
        and node.attr in FORBIDDEN_NAMES - allowed
        and not (isinstance(node.value, ast.Name) and node.value.id in safe_roots)
    ):
        return f"line {node.lineno}: .{node.attr}"
    if isinstance(node, ast.Call):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name == "ElementTree" and (len(node.args) > 1 or any(k.arg == "file" for k in node.keywords)):
            return f"line {node.lineno}: ElementTree(file=...)"
    return None


def forbidden_parser_uses(source: str, allowed: frozenset[str] = frozenset()) -> list[str]:
    """Return a description of every forbidden XML parser use in ``source``."""
    tree = ast.parse(source)
    safe_roots: set[str] = set()
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found += _check_import(node, allowed, safe_roots)
    for node in ast.walk(tree):
        problem = _check_node(node, allowed, safe_roots)
        if problem:
            found.append(problem)
    return found


@pytest.mark.parametrize(
    "snippet",
    [
        "from lxml import etree\netree.fromstring(b)",
        "from lxml import etree\netree.parse(f)",
        "from lxml import etree\netree.XML(b)",
        "import lxml.etree\nlxml.etree.XMLParser(load_dtd=True)",
        "from lxml import etree as ET\nET.parse(f)",
        "from lxml.etree import fromstring\nfromstring(b)",
        "from lxml.etree import parse",
        "from lxml.etree import XML as x",
        "from lxml.etree import XMLParser as P",
        "from lxml.etree import *\nfromstring(b)",
        "from lxml import etree\netree.XMLID(b)",
        "from lxml import etree\netree.XMLDTDID(b)",
        "from lxml import etree\netree.HTML(b)",
        "from lxml import etree\netree.iterparse(f)",
        "from lxml import etree\netree.fromstringlist([b])",
        "from lxml import etree\netree.XMLSchema(file='x.xsd')",
        "from lxml import etree\netree.DTD(p)",
        "from lxml import etree\netree.RelaxNG(file=p)",
        "from lxml import etree\netree.XInclude()",
        "tree.xinclude()",
        "from lxml import etree\netree.ElementTree(file=p)",
        "from lxml import etree\netree.ElementTree(None, p)",
        "from lxml.etree import ElementTree\nElementTree(file=p)",
        "from lxml import objectify\nobjectify.parse(f)",
        "from lxml import html",
        "import lxml.html",
        "import xml.etree.ElementTree",
        "import xml.parsers.expat",
        "from xml import sax",
        "from xml.dom import minidom\nminidom.parseString(b)",
        "proc.parse_xml(xml_text=s)",
        "self.parser.parse(b)",
        "from euinvoice._xml import etree\netree.fromstring(b)",
        "from ._xml import etree as ET\nET.XML(b)",
        "from .._xml import XMLParser",
        "from euinvoice._xml import *",
        "import euinvoice._xml as x\nx.etree.parse(b)",
        "from euinvoice import _xml\n_xml.etree.fromstring(b)",
        "from euinvoice.syntax import etree\netree.fromstring(b)",
    ],
)
def test_guard_detects(snippet: str) -> None:
    assert forbidden_parser_uses(snippet)


@pytest.mark.parametrize(
    "snippet",
    [
        '"""Never call etree.fromstring() here; use _xml.parse()."""',
        "from euinvoice import _xml\n_xml.parse(b)",
        "from . import _xml\n_xml.parse(b)\n_xml.load_trusted_schema(p)",
        "from euinvoice._xml import parse, load_trusted_schema, UBL_NSMAP\nparse(b)",
        "from ._xml import new_parser",
        "import euinvoice._xml as x\nx.parse(b)",
        "import urllib.parse\nurllib.parse.quote(s)",
        "from urllib import parse",
        "from lxml import etree\netree.tostring(e)",
        "from lxml import etree\netree.ElementTree(root)",
        "from euinvoice.model import *",
    ],
)
def test_guard_allows(snippet: str) -> None:
    assert forbidden_parser_uses(snippet) == []


def test_per_file_allowlist() -> None:
    assert forbidden_parser_uses("proc.parse_xml(xml_text=s)", frozenset({"parse_xml"})) == []


def test_xml_is_parsed_only_in_xml_module() -> None:
    offenders: dict[str, list[str]] = {}
    for path in SRC.rglob("*.py"):
        relative = path.relative_to(SRC).as_posix()
        if relative == "_xml.py":
            continue
        found = forbidden_parser_uses(path.read_text(encoding="utf-8"), PER_FILE_ALLOWED.get(relative, frozenset()))
        if found:
            offenders[relative] = found
    assert offenders == {}, "XML must be parsed only via euinvoice._xml (D10)"
