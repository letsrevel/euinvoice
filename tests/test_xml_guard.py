"""AC of #6: no module under ``src/`` except ``euinvoice._xml`` parses XML (IMPLEMENTATION_PLAN.md D10).

The check walks the AST, so aliases (``from lxml import etree as ET``), from-imports and docstrings are
handled correctly, unlike a text grep. It targets accidental misuse; adversarial rebinding (e.g.
``_xml = etree``) is out of scope for a static check.
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
        "XMLTreeBuilder",
        "Schematron",
        "parse_xml",
        "parseString",
        # saxonche loaders that take a file name positionally.
        "set_catalog",
        "set_catalog_files",
        "set_query_file",
    }
)
# Private parser factory of euinvoice._xml: it skips the DOCTYPE check, so it is flagged even on a safe root.
PRIVATE_XML_NAMES = frozenset({"_new_parser"})
# Whole modules that are parsers in their own right.
FORBIDDEN_MODULES = ("xml", "lxml.objectify", "lxml.html")
# Module names that must never count as a safe root, even when imported from euinvoice.
PARSER_MODULE_NAMES = frozenset({"etree", "objectify", "html", "ElementTree", "minidom", "sax", "expat"})
# The public helpers of euinvoice._xml.
XML_HELPERS = frozenset({"parse", "load_trusted_schema"})
# Names imported from these modules are safe roots: a forbidden attribute directly on them is fine
# (``_xml.parse``, ``urllib.parse``), but not deeper (``_xml.etree.parse``).
SAFE_MODULES = ("euinvoice", "urllib")
# saxonche keyword arguments that make Saxon read a file or URI (from the saxonche 13.0.0 docstrings).
# D10: documents reach Saxon only through ``_xml.to_xdm``, as text from a tree ``_xml.parse`` accepted.
SAXON_FILE_KEYWORDS = frozenset(
    {
        "source_file",
        "xml_file_name",
        "xml_uri",
        "stylesheet_file",
        "associated_file",
        "file_name",
        "input_file_name",
        "query_file",
        "xsd_file",
        "json_file_name",
        "package_file_name",
    }
)
# saxonche methods that accept one of the keywords above; a ``**`` splat in a call to them could hide one.
SAXON_METHODS = frozenset(
    {
        "parse_xml",
        "parse_json",
        "compile_stylesheet",
        "import_package",
        "transform_to_string",
        "transform_to_value",
        "transform_to_file",
        "apply_templates_returning_string",
        "apply_templates_returning_value",
        "apply_templates_returning_file",
        "call_template_returning_string",
        "call_template_returning_value",
        "call_template_returning_file",
        "call_function_returning_string",
        "call_function_returning_value",
        "call_function_returning_file",
        "set_initial_match_selection",
        "set_global_context_item",
        "set_context",
        "run_query_to_string",
        "run_query_to_value",
        "run_query_to_file",
        "register_schema",
        "validate",
        "validate_to_node",
        "compile",
    }
)
# Explicit per-file exceptions, as {path relative to src/euinvoice: {name: exact number of uses}}. Keep
# this tiny and give a reason per entry; a test fails if the number of uses changes either way.
PER_FILE_ALLOWED: dict[str, dict[str, int]] = {
    # Compiles the pinned rule set by path from a recipe-fingerprint-checked cache entry (xsl:include
    # and xsl:import need a base URI).
    "validate/schematron.py": {"stylesheet_file": 1},
    # Compiles the pinned SchXslt pipeline by path (it xsl:includes its sibling stylesheets).
    "validate/artifacts.py": {"stylesheet_file": 1},
}


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
            forbidden = FORBIDDEN_NAMES | PARSER_MODULE_NAMES | PRIVATE_XML_NAMES
            bad = [n for n in names if n in forbidden - XML_HELPERS - allowed]
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


def _check_attribute(node: ast.Attribute, allowed: frozenset[str], safe_roots: set[str]) -> str | None:
    """Flag a forbidden attribute unless it hangs directly off a safe name (private names never are)."""
    on_safe_root = isinstance(node.value, ast.Name) and node.value.id in safe_roots
    if node.attr in PRIVATE_XML_NAMES or (node.attr in FORBIDDEN_NAMES - allowed and not on_safe_root):
        return f"line {node.lineno}: .{node.attr}"
    return None


def _check_call(node: ast.Call, allowed: frozenset[str]) -> str | None:
    """Flag ``ElementTree(file=...)``, saxonche file keywords, ``getattr(x, "<forbidden>")`` and dynamic imports."""
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    first = node.args[1 if name == "getattr" else 0] if len(node.args) > (name == "getattr") else None
    constant = first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None
    if name == "ElementTree" and (len(node.args) > 1 or any(k.arg == "file" for k in node.keywords)):
        return f"line {node.lineno}: ElementTree(file=...)"
    keyword = next((k.arg for k in node.keywords if k.arg in SAXON_FILE_KEYWORDS - allowed), None)
    if keyword:
        return f"line {node.lineno}: {keyword}=..."
    if isinstance(func, ast.Attribute) and name in SAXON_METHODS and any(k.arg is None for k in node.keywords):
        return f"line {node.lineno}: {name}(**...)"
    if name == "getattr" and constant in (FORBIDDEN_NAMES | PRIVATE_XML_NAMES) - allowed:
        return f"line {node.lineno}: getattr(..., {constant!r})"
    if name in {"import_module", "__import__"} and constant and _in(constant, FORBIDDEN_MODULES):
        return f"line {node.lineno}: {name}({constant!r})"
    return None


def _check_node(node: ast.AST, allowed: frozenset[str], safe_roots: set[str]) -> str | None:
    """Return a description if ``node`` is a forbidden attribute use or call."""
    if isinstance(node, ast.Attribute):
        return _check_attribute(node, allowed, safe_roots)
    if isinstance(node, ast.Call):
        return _check_call(node, allowed)
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
        "doc_builder.parse_xml(xml_uri=u)",
        "executable.transform_to_string(source_file=p)",
        "executable.transform_to_value(source_file=p)",
        "xslt.compile_stylesheet(stylesheet_file=p)",
        "xslt.compile_stylesheet(associated_file=p)",
        "executable.set_initial_match_selection(file_name=p)",
        "xquery.set_context(xml_file_name=p)",
        "xquery.run_query_to_string(input_file_name=p)",
        "xquery.run_query_to_value(query_file=p)",
        "validator.register_schema(xsd_file=p)",
        "compiler.compile(xsd_file=p)",
        "proc.parse_json(json_file_name=p)",
        "xslt.import_package(package_file_name=p)",
        "proc.parse_xml(**kw)",
        "executable.transform_to_string(xdm_node=n, **kw)",
        "xslt.compile_stylesheet(**{'stylesheet_file': p})",
        "proc.set_catalog(p)",
        "xquery.set_query_file(p)",
        "self.parser.parse(b)",
        "from euinvoice._xml import etree\netree.fromstring(b)",
        "from ._xml import etree as ET\nET.XML(b)",
        "from .._xml import XMLParser",
        "from euinvoice._xml import *",
        "import euinvoice._xml as x\nx.etree.parse(b)",
        "from euinvoice import _xml\n_xml.etree.fromstring(b)",
        "from euinvoice.syntax import etree\netree.fromstring(b)",
        "from ._xml import _new_parser",
        "from euinvoice._xml import _new_parser as p",
        "from euinvoice import _xml\np = _xml._new_parser()\np.feed(b)",
        "from lxml import etree\netree.XMLTreeBuilder()",
        "from lxml.etree import XMLTreeBuilder",
        "from lxml import isoschematron\nisoschematron.Schematron(doc)",
        "from lxml.isoschematron import Schematron",
        "from lxml import etree\ngetattr(etree, 'fromstring')(b)",
        "from euinvoice import _xml\ngetattr(_xml, '_new_parser')()",
        "import importlib\nimportlib.import_module('xml.dom.minidom')",
        "from importlib import import_module\nimport_module('lxml.objectify')",
        "__import__('lxml.html')",
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
        "from lxml import etree\ngetattr(etree, 'tostring')(e)",
        "import importlib\nimportlib.import_module('json')",
        "getattr(obj, name)",
        "import euinvoice._xml as x\nx.parse(b)",
        "import urllib.parse\nurllib.parse.quote(s)",
        "from urllib import parse",
        "from lxml import etree\netree.tostring(e)",
        "from lxml import etree\netree.ElementTree(root)",
        "from euinvoice.model import *",
        "executable.transform_to_string(xdm_node=node)",
        "xslt.compile_stylesheet(stylesheet_text=s)",
        "build(**options)",
        "obj.render(**options)",
    ],
)
def test_guard_allows(snippet: str) -> None:
    assert forbidden_parser_uses(snippet) == []


def test_per_file_allowlist() -> None:
    assert forbidden_parser_uses("proc.parse_xml(xml_text=s)", frozenset({"parse_xml"})) == []
    assert forbidden_parser_uses("xslt.compile_stylesheet(stylesheet_file=p)", frozenset({"stylesheet_file"})) == []
    assert forbidden_parser_uses("e.transform_to_string(source_file=p)", frozenset({"stylesheet_file"})) != []


def allowed_use_counts(source: str, allowed: dict[str, int]) -> dict[str, int]:
    """How many uses of each allowlisted name ``source`` has (uses that disappear when it is allowed)."""
    names = frozenset(allowed)
    baseline = len(forbidden_parser_uses(source, names))
    return {name: len(forbidden_parser_uses(source, names - {name})) - baseline for name in names}


def test_allowed_use_counts_are_exact() -> None:
    source = "a.compile_stylesheet(stylesheet_file=p)\nb.compile_stylesheet(stylesheet_file=q)"
    assert allowed_use_counts(source, {"stylesheet_file": 1}) == {"stylesheet_file": 2}


def test_xml_is_parsed_only_in_xml_module() -> None:
    offenders: dict[str, list[str]] = {}
    counts: dict[str, dict[str, int]] = {}
    for path in SRC.rglob("*.py"):
        relative = path.relative_to(SRC).as_posix()
        if relative == "_xml.py":
            continue
        source = path.read_text(encoding="utf-8")
        allowed = PER_FILE_ALLOWED.get(relative, {})
        found = forbidden_parser_uses(source, frozenset(allowed))
        if found:
            offenders[relative] = found
        if allowed:
            counts[relative] = allowed_use_counts(source, allowed)
    assert offenders == {}, "XML must be parsed only via euinvoice._xml (D10)"
    assert counts == PER_FILE_ALLOWED, "allowlisted uses changed: review them and update PER_FILE_ALLOWED"


def test_getpath_is_called_only_through_xml_getpath() -> None:
    # lxml's getpath raises UnicodeDecodeError when libxml2 cuts a path inside a character (#90).
    offenders: dict[str, list[int]] = {}
    for path in SRC.rglob("*.py"):
        relative = path.relative_to(SRC).as_posix()
        if relative == "_xml.py":
            continue
        lines = [
            node.lineno
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Attribute)
            and node.attr == "getpath"
            and not (isinstance(node.value, ast.Name) and node.value.id == "_xml")
        ]
        if lines:
            offenders[relative] = lines
    assert offenders == {}, "compute node paths with euinvoice._xml.getpath"
