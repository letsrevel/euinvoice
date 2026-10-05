"""The one place where euinvoice parses XML, plus the namespace constants of UBL 2.1 and CII D16B.

Every XML parse in the library goes through :func:`parse` (IMPLEMENTATION_PLAN.md D10). How each
attack class is blocked:

* **XXE (external entities, ``file://`` / ``http://``)** and **external DTDs**: the parser never
  loads external resources (``load_dtd=False``, ``no_network=True``, ``resolve_entities=False``),
  and any document carrying a DOCTYPE is rejected outright.
* **Billion laughs / quadratic blowup / parameter entities**: entities can only be declared in a
  DOCTYPE, which is rejected; the parser never resolves external entities (``resolve_entities=False``)
  and libxml2's entity-amplification guard aborts expansion bombs while parsing.
* **Trusted schemas**: :func:`load_trusted_schema` is the one place that reads files (local XSD
  imports of the pinned artifacts); it keeps ``no_network=True`` and the DOCTYPE rejection.
* **Oversized input**: ``huge_tree=False`` keeps libxml2's safety limits (nesting depth, text node
  and attribute size).

A test (``tests/test_xml.py``) fails if any other module under ``src/`` parses XML itself.
"""

import pathlib
import typing as t

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

# Plain dicts because lxml's ``xpath(namespaces=…)`` rejects read-only mappings. Do not mutate.
UBL_NSMAP: t.Final[dict[str, str]] = {"cac": UBL_CAC, "cbc": UBL_CBC, "ext": UBL_EXT}
"""Prefix map for UBL components (the document namespace is the default one, set per root)."""
CII_NSMAP: t.Final[dict[str, str]] = {"rsm": CII_RSM, "ram": CII_RAM, "udt": CII_UDT, "qdt": CII_QDT}
"""Prefix map for CII documents."""


def new_parser() -> etree.XMLParser:
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
        root = etree.fromstring(data, new_parser())  # hardened parser, see new_parser()
    except etree.XMLSyntaxError as exc:
        raise _malformed(exc) from exc
    _reject_doctype(root.getroottree())
    return root


def load_trusted_schema(path: pathlib.Path) -> etree.XMLSchema:
    """Load an XML Schema from the local artifact cache.

    For **trusted local artifacts only** (the pinned official XSDs fetched by
    ``euinvoice artifacts fetch``), never for user input. Unlike :func:`parse` it reads files: libxml2
    follows the schema's ``xs:import`` / ``xs:include`` locations relative to ``path``. It still never
    touches the network (``no_network=True``), never resolves entities, and rejects a DOCTYPE in the
    root schema document.

    Args:
        path: The root ``.xsd`` file.

    Returns:
        The compiled schema.

    Raises:
        OSError: If ``path`` cannot be read.
        ParseError: If a schema document is malformed, has a DOCTYPE, or is not a valid XML Schema
            (including an import that cannot be loaded locally).
    """
    try:
        tree = etree.parse(str(path), new_parser())  # hardened parser, see new_parser()
    except etree.XMLSyntaxError as exc:
        raise _malformed(exc) from exc
    _reject_doctype(tree)
    try:
        return etree.XMLSchema(tree)
    except etree.XMLSchemaParseError as exc:
        raise ParseError(f"invalid XML Schema {path.name}: {exc}") from exc


def _malformed(exc: etree.XMLSyntaxError) -> ParseError:
    line, column = exc.position
    message = exc.msg.removesuffix(f", line {line}, column {column}")
    return ParseError(f"malformed XML: {message}", location=f"{line}:{column}")


def _reject_doctype(tree: etree._ElementTree) -> None:
    # libxml2 records every DOCTYPE (with or without an internal subset) as the document's intSubset.
    if tree.docinfo.internalDTD is not None:
        raise ParseError("DOCTYPE declarations are not allowed (entity and DTD attacks, D10)")
