"""The one place where euinvoice parses XML, plus the namespace constants of UBL 2.1 and CII D16B.

Every XML parse in the library goes through :func:`parse` (IMPLEMENTATION_PLAN.md D10). How each
attack class is blocked:

* **XXE (external entities, ``file://`` / ``http://``)** and **external DTDs**: the parser never
  loads external resources (``load_dtd=False``, ``no_network=True``, ``resolve_entities=False``),
  and any document carrying a DOCTYPE is rejected outright.
* **Billion laughs / quadratic blowup / parameter entities**: entities can only be declared in a
  DOCTYPE, which is rejected; the parser never resolves external entities (``resolve_entities=False``)
  and libxml2's entity-amplification guard aborts expansion bombs while parsing.
* **Trusted schemas**: :func:`load_trusted_schema` is the one place that reads files. It is for the
  pinned, sha256-verified XSDs only, and a confining resolver keeps every load local and inside the
  schema package.
* **Saxon**: :func:`to_xdm` is the only way a document reaches saxonche, as text re-serialized from a
  tree this module parsed. Only pinned stylesheets are ever loaded by path, outside this module.
* **Oversized input**: ``huge_tree=False`` keeps libxml2's safety limits (nesting depth, text node
  and attribute size).

A test (``tests/test_xml_guard.py``) fails if any other module under ``src/`` parses XML itself.
"""

import pathlib
import typing as t
import urllib.parse
import urllib.request

from lxml import etree

from euinvoice.errors import ParseError

# Namespace URIs, verified against the ``<ns>`` declarations of the CEN validation artifacts
# release ``validation-1.3.16`` (EN16931-UBL-validation.sch, EN16931-CII-validation.sch) and the
# official examples shipped with it (ubl-tc434-example1.xml, ubl-tc434-creditnote1.xml, CII_example1.xml).

UBL_INVOICE: t.Final = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
"""UBL 2.1 ``Invoice`` document namespace."""
UBL_CREDIT_NOTE: t.Final = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
"""UBL 2.1 ``CreditNote`` document namespace."""
UBL_CAC: t.Final = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
"""UBL 2.1 common aggregate components (``cac``)."""
UBL_CBC: t.Final = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
"""UBL 2.1 common basic components (``cbc``)."""
UBL_EXT: t.Final = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
"""UBL 2.1 extension components (``ext``); ``ext:UBLExtensions`` should not be used (UBL-CR-001, flag warning)."""

CII_RSM: t.Final = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
"""CII D16B ``CrossIndustryInvoice`` root (``rsm``)."""
CII_RAM: t.Final = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
"""CII D16B reusable aggregate business information entities (``ram``)."""
CII_UDT: t.Final = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"
"""CII D16B unqualified data types (``udt``)."""
CII_QDT: t.Final = "urn:un:unece:uncefact:data:standard:QualifiedDataType:100"
"""CII D16B qualified data types (``qdt``)."""

SVRL: t.Final = "http://purl.oclc.org/dsdl/svrl"
"""Schematron Validation Report Language (ISO/IEC 19757-3 Annex D), the output of every compiled rule set.

Verified as the ``svrl`` namespace of the pinned CEN ``EN16931-UBL-validation.xslt`` /
``EN16931-CII-validation.xslt`` (1.3.16), the SchXslt-compiled Peppol 3.0.21 stylesheets and the
XRechnung 2.6.0 ``XRechnung-*-validation.xsl``.
"""
SCHEMATRON: t.Final = "http://purl.oclc.org/dsdl/schematron"
"""ISO Schematron (ISO/IEC 19757-3), the default namespace of the pinned Peppol 3.0.21 ``rules/sch/*.sch``."""
XSLT: t.Final = "http://www.w3.org/1999/XSL/Transform"
"""XSLT, the namespace of every compiled rule set."""
FACTURX_XMP: t.Final = "urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#"
"""The Factur-X 1.0 / ZUGFeRD 2.1+ XMP extension schema (prefix ``fx``; plan §5), as declared in the XMP of the
Factur-X PDFs of the pinned ZUGFeRD corpus (e.g. ``ZUGFeRDv2/correct/symtrax/Beispiele``, ``XML-Rechnung/FX``)."""
ZUGFERD_2_XMP: t.Final = "urn:zugferd:pdfa:CrossIndustryDocument:invoice:2p0#"
"""The ZUGFeRD 2.0 XMP extension schema, read by ``facturx.extract`` only (plan §8 7.2): the XMP of all 30 ZUGFeRD 2.0
PDFs of ``ZUGFeRDv2/correct`` in the pinned ZUGFeRD corpus (e.g. ``intarsys/EN16931``)."""
ZUGFERD_1_XMP: t.Final = "urn:ferd:pdfa:CrossIndustryDocument:invoice:1p0#"
"""The ZUGFeRD 1.0 XMP extension schema, read by ``facturx.extract`` only: 18 of the 21 PDFs of ``ZUGFeRDv1/correct``
in the pinned ZUGFeRD corpus (e.g. ``Intarsys``)."""
ZUGFERD_1_RC_XMP: t.Final = "urn:ferd:pdfa:invoice:rc#"
"""The XMP schema of the ZUGFeRD 1.0 release candidate (``fx``-like properties, ``Version`` ``RC``), read by
``facturx.extract`` only: the other 3 of ``ZUGFeRDv1/correct`` (``Mustangproject/MustangGnuaccountingBeispielRE-
2014*.pdf``)."""
# XMP / PDF/A namespaces, as declared in the XMP of all 74 Factur-X PDFs of the pinned ZUGFeRD corpus
# (``ZUGFeRDv2/correct``, ``XML-Rechnung/FX``; e.g. ``FNFE-factur-x-examples/Facture_FR_BASICWL.pdf``).
RDF: t.Final = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
"""RDF, the syntax of an XMP packet (``rdf:RDF`` / ``rdf:Description``)."""
PDFAID: t.Final = "http://www.aiim.org/pdfa/ns/id/"
"""PDF/A identification schema (prefix ``pdfaid``): ``pdfaid:part`` and ``pdfaid:conformance``."""
PDFA_EXTENSION: t.Final = "http://www.aiim.org/pdfa/ns/extension/"
"""PDF/A extension schema container (prefix ``pdfaExtension``): ``pdfaExtension:schemas``."""
PDFA_SCHEMA: t.Final = "http://www.aiim.org/pdfa/ns/schema#"
"""PDF/A schema value type (prefix ``pdfaSchema``): one declared extension schema."""
PDFA_PROPERTY: t.Final = "http://www.aiim.org/pdfa/ns/property#"
"""PDF/A property value type (prefix ``pdfaProperty``): one property of an extension schema."""
VEFA: t.Final = "http://difi.no/xsd/vefa/validator/1.0"
"""vefa-validator test sets: the format of the Peppol rules' unit tests (``rules/unit-*/*.xml``, ``testSet``)."""

# Plain dicts because lxml's ``xpath(namespaces=…)`` rejects read-only mappings. Do not mutate.
UBL_NSMAP: t.Final[dict[str, str]] = {"cac": UBL_CAC, "cbc": UBL_CBC, "ext": UBL_EXT}
"""Prefix map for UBL components (the document namespace is the default one, set per root)."""
CII_NSMAP: t.Final[dict[str, str]] = {"rsm": CII_RSM, "ram": CII_RAM, "udt": CII_UDT, "qdt": CII_QDT}
"""Prefix map for CII documents."""


def _new_parser() -> etree.XMLParser:
    """Create the hardened parser of D10.

    A new parser per call, because lxml parser objects must not be shared across threads.

    Returns:
        A parser that never resolves entities, loads DTDs or touches the network.
    """
    # ponytail: huge_tree=False is libxml2's ceiling: depth 256, 10 MB per text node or attribute.
    # A BT-125 attachment above roughly 7.5 MB (base64 grows by 4/3) therefore cannot be parsed. Raising
    # it means a reviewed opt-in (huge_tree=True plus our own size and depth caps), not a silent flip.
    # There is no total-size cap: the caller already holds the bytes and the tree is linear in them.
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        remove_blank_text=False,
    )


def parse(data: bytes) -> etree._Element:
    """Parse untrusted XML bytes safely.

    Args:
        data: The serialized XML document.

    Returns:
        The root element.

    Raises:
        TypeError: If ``data`` is not ``bytes``.
        ParseError: If the XML is malformed, exceeds the parser limits or contains a DOCTYPE.
    """
    if not isinstance(data, bytes):
        raise TypeError(f"XML input must be bytes, got {type(data).__name__}")
    try:
        root = etree.fromstring(data, _new_parser())  # hardened parser, see _new_parser()
    except etree.XMLSyntaxError as exc:
        raise _malformed(exc) from exc
    _reject_doctype(root.getroottree())
    return root


def getpath(element: etree._Element) -> str:
    """The XPath of ``element`` as lxml's ``ElementTree.getpath`` writes it, for any element name (#90).

    ``getpath`` is libxml2's ``xmlGetNodePath`` (2.14.6 ``tree.c``), which cuts bytes in two places: a
    ``prefix:name`` step is written with ``snprintf(nametemp, sizeof(nametemp) - 1, "%s:%s", ...)`` into
    ``char nametemp[100]``, keeping 98 bytes, and each partial path with ``snprintf((char *) buf, buf_len, ...)``,
    dropping the tail of a path longer than its buffer. A cut can fall inside a UTF-8 character, and lxml decodes
    the result strictly (``funicode`` in ``apihelpers.pxi``: ``s.decode('UTF-8')``), raising
    ``UnicodeDecodeError``. Such a path is decoded with :func:`path_text` instead, so a hostile element name
    cannot turn a located :class:`ParseError` or a finding into a crash.

    Args:
        element: An element of a parsed tree.

    Returns:
        ``getpath``'s result whenever lxml can decode it; otherwise libxml2's bytes with each cut character
        replaced by U+FFFD.
    """
    try:
        return element.getroottree().getpath(element)
    except UnicodeDecodeError as exc:
        return path_text(exc.object)


def path_text(raw: bytes) -> str:
    """Decode a node path libxml2 wrote: UTF-8, a character it cut becoming one U+FFFD (see :func:`getpath`).

    Args:
        raw: The UTF-8 bytes of the path.

    Returns:
        The same string as ``raw.decode()`` whenever that succeeds.
    """
    return raw.decode("utf-8", "replace")


def load_trusted_schema(path: pathlib.Path, *, root: pathlib.Path | None = None) -> etree.XMLSchema:
    """Load an XML Schema from the local artifact cache.

    For **trusted local artifacts only** (the pinned, sha256-verified XSDs fetched by
    ``euinvoice artifacts fetch``), never for user input. The root schema goes through the hardened
    parser and must not have a DOCTYPE. Documents it imports or includes are parsed by libxml2 with
    libxml2's own options, not ours. The protection for them is the sha256 pin plus a confining
    resolver: every document or entity libxml2 tries to load (imports, includes, DTDs, external
    entities) must be a local file inside ``root``. Anything else (``http://``, other schemes, paths
    outside ``root``) is refused and turns the whole load into a ``ParseError``. This holds whether or
    not the bundled libxml2 was built with HTTP support.

    Args:
        path: The root ``.xsd`` file.
        root: The directory every loaded file must be inside. Defaults to ``path``'s directory. Pass
            the schema package's top directory when the schema imports siblings such as
            ``../common/*.xsd`` (UBL 2.1 ``maindoc`` does).

    Returns:
        The compiled schema.

    Raises:
        ValueError: If ``path`` is not inside ``root``.
        OSError: If ``path`` cannot be read.
        ParseError: If the root schema is malformed or has a DOCTYPE, if any load was refused by the
            confining resolver, or if the schema does not compile. On its own, libxml2 silently skips
            an ``xs:import`` it cannot load and fails only on a failed ``xs:include`` or a reference
            into the missing import. The resolver makes every refused load an error instead.
    """
    confine = (root or path.parent).resolve()
    if not path.resolve().is_relative_to(confine):
        raise ValueError(f"schema {path} is not inside {confine}")
    resolver = _ConfiningResolver(confine)
    parser = _new_parser()
    parser.resolvers.add(resolver)
    try:
        tree = etree.parse(str(path), parser)  # hardened parser, see _new_parser()
    except etree.XMLSyntaxError as exc:
        raise _malformed(exc) from exc
    _reject_doctype(tree)
    error: etree.XMLSchemaParseError | None = None
    try:
        schema = etree.XMLSchema(tree)
    except etree.XMLSchemaParseError as exc:
        error = exc
    # libxml2 swallows exceptions raised in a resolver, so refusals are collected and reported here.
    if resolver.refused:
        raise ParseError(f"schema {path.name} tried to load {resolver.refused[0]!r}, outside {confine}") from error
    if error is not None:
        raise ParseError(f"invalid XML Schema {path.name}: {error}") from error
    return schema


def to_xdm(processor: t.Any, document: bytes | etree._Element) -> t.Any:
    """Hand a document to Saxon the D10 way: the one bridge from euinvoice to ``saxonche``.

    The document passes :func:`parse` first, also when it is an element (it is serialized without its
    tail and parsed again). Saxon then gets the lxml serialization of that tree as text, never a file
    name or URI, so it only ever sees XML the hardened parser accepted.

    Args:
        processor: A ``saxonche.PySaxonProcessor`` (``Any``: saxonche ships no type information).
        document: XML bytes, or an element.

    Returns:
        The ``saxonche.PyXdmNode`` of the document.

    Raises:
        TypeError: ``document`` is neither bytes nor an element.
        ParseError: The document is malformed or has a DOCTYPE.
    """
    data = etree.tostring(document, with_tail=False) if isinstance(document, etree._Element) else document
    text = etree.tostring(parse(data).getroottree(), encoding="unicode")
    return processor.parse_xml(xml_text=text, encoding="UTF-8")


class _ConfiningResolver(etree.Resolver):
    """Lets libxml2 load only local files inside ``root``; records and refuses everything else."""

    def __init__(self, root: pathlib.Path) -> None:
        super().__init__()
        self.root = root
        self.refused: list[str] = []

    def resolve(self, system_url: str, public_id: str, context: object) -> t.Any:  # type: ignore[override]
        # lxml-stubs omit the `context` argument and `resolve_filename`; both exist since lxml 2.x.
        local = _local_path(system_url)
        if local is None or not local.is_relative_to(self.root):
            self.refused.append(system_url)
            raise ParseError(f"refused to load {system_url!r}")
        return self.resolve_filename(str(local), context)  # type: ignore[attr-defined]  # see above


def _local_path(url: str) -> pathlib.Path | None:
    """The resolved local path of a ``file:`` URL or a plain path; ``None`` for any other scheme."""
    # libxml2 always passes absolute, base-joined URLs here; the caller confines the result to root anyway.
    if url.startswith("file:"):
        return pathlib.Path(urllib.request.url2pathname(urllib.parse.urlsplit(url).path)).resolve()
    if "://" in url:
        return None
    return pathlib.Path(url).resolve()


def _malformed(exc: etree.XMLSyntaxError) -> ParseError:
    line, column = exc.position
    message = exc.msg.removesuffix(f", line {line}, column {column}")
    return ParseError(f"malformed XML: {message}", location=f"{line}:{column}")


def _reject_doctype(tree: etree._ElementTree) -> None:
    # libxml2 records every DOCTYPE (with or without an internal subset) as the document's intSubset.
    if tree.docinfo.internalDTD is not None:
        raise ParseError("DOCTYPE declarations are not allowed (entity and DTD attacks, D10)")
