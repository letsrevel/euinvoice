"""The Factur-X XMP: the ``fx`` properties and the PDF/A extension schema that declares them (plan §5).

The Factur-X / ZUGFeRD specification package is not pinned (#42), so every value here is the one the 74 Factur-X
PDFs of the pinned ZUGFeRD corpus carry (manifest source ``zugferd-corpus``, every PDF under ``ZUGFeRDv2/correct``
and ``XML-Rechnung/FX`` whose XMP declares :data:`euinvoice._xml.FACTURX_XMP`), read with pypdf and parsed with
:func:`euinvoice._xml.parse`:

* ``pdfaid:part`` is ``3`` in all 74 (plan §5: the input must already be PDF/A-3).
* The ``fx`` properties are exactly ``DocumentType``, ``DocumentFileName``, ``Version`` and ``ConformanceLevel``
  in all 74, ``fx:DocumentType`` is ``INVOICE`` in all 74.
* The extension schema (``pdfaExtension:schemas``): ``pdfaSchema:namespaceURI`` :data:`~euinvoice._xml.FACTURX_XMP`
  and ``pdfaSchema:prefix`` ``fx`` in all 74; ``pdfaSchema:schema`` ``Factur-X PDFA Extension Schema`` in 73 (one
  Mustang file says ``ZUGFeRD PDFA Extension Schema``); the four properties in the order of :data:`_PROPERTIES`,
  each ``pdfaProperty:valueType`` ``Text`` and ``pdfaProperty:category`` ``external``, in all 74. The
  ``pdfaProperty:description`` texts vary (3 variants); :data:`_PROPERTIES` uses the 46-file variant, which is
  the one of the FNFE samples (``ZUGFeRDv2/correct/FNFE-factur-x-examples``). Whether the spec mandates a text
  is open (#42).

Every element this module adds is an ``rdf:Description`` about the input's resource (its ``rdf:about``), so the
packet keeps describing one document.
"""

import typing as t

from lxml import etree

from euinvoice import _xml

__all__ = ["DOCUMENT_TYPE", "add_facturx", "has_facturx", "pdfa_parts", "values"]

DOCUMENT_TYPE: t.Final = "INVOICE"
"""``fx:DocumentType`` of all 74 Factur-X PDFs of the pinned corpus (plan §5)."""

_SCHEMA_NAME: t.Final = "Factur-X PDFA Extension Schema"
# (pdfaProperty:name, pdfaProperty:description), in the corpus order; see the module docstring.
_PROPERTIES: t.Final = (
    ("DocumentFileName", "name of the embedded XML invoice file"),
    ("DocumentType", DOCUMENT_TYPE),
    ("Version", "The actual version of the Factur-X XML schema"),
    ("ConformanceLevel", "The conformance level of the embedded Factur-X data"),
)


def _q(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def values(root: etree._Element, namespace: str, name: str) -> list[str]:
    """Return every value of an XMP property, as element text or as ``rdf:Description`` attribute.

    Both RDF/XML forms occur in the corpus (plan §5).

    Args:
        root: The parsed XMP packet (or any element of it).
        namespace: The property's namespace URI.
        name: The property's local name.

    Returns:
        The raw values in document order, elements first.
    """
    qname = _q(namespace, name)
    return [element.text or "" for element in root.iter(qname)] + [
        str(element.get(qname)) for element in root.iter() if element.get(qname) is not None
    ]


def pdfa_parts(root: etree._Element) -> list[str]:
    """Return every ``pdfaid:part`` value of an XMP packet, element or attribute.

    Args:
        root: The parsed XMP packet.

    Returns:
        The raw values in document order (elements first). They are not stripped: veraPDF rejects
        ``<pdfaid:part> 3 </pdfaid:part>`` (rules 6.6.4-2 and 6.6.2.3.1-2), so only exactly ``3`` is PDF/A-3.
    """
    return values(root, _xml.PDFAID, "part")


def has_facturx(root: etree._Element) -> bool:
    """Tell whether an XMP packet already sets a Factur-X property (an element or attribute in ``fx``).

    Args:
        root: The parsed XMP packet.

    Returns:
        ``True`` when any ``fx:*`` property is present.
    """
    prefix = f"{{{_xml.FACTURX_XMP}}}"
    return any(
        (isinstance(element.tag, str) and element.tag.startswith(prefix))
        or any(str(name).startswith(prefix) for name in element.attrib)
        for element in root.iter()
    )


def add_facturx(rdf: etree._Element, *, filename: str, version: str, level: str) -> None:
    """Add the ``fx`` properties and, unless already declared, their PDF/A extension schema to ``rdf:RDF``.

    An existing ``pdfaExtension:schemas`` bag gets the Factur-X schema as one more ``rdf:li``, because the
    property may occur only once per resource; otherwise a new ``rdf:Description`` holds it.

    Args:
        rdf: The packet's ``rdf:RDF`` element, changed in place.
        filename: ``fx:DocumentFileName``, the embedded file's name.
        version: ``fx:Version``.
        level: ``fx:ConformanceLevel``.
    """
    about = _about(rdf)
    if _xml.FACTURX_XMP not in values(rdf, _xml.PDFA_SCHEMA, "namespaceURI"):
        _schema(_bag(rdf, about))
    description = _description(rdf, about, {"fx": _xml.FACTURX_XMP})
    for name, value in (
        ("DocumentType", DOCUMENT_TYPE),
        ("DocumentFileName", filename),
        ("Version", version),
        ("ConformanceLevel", level),
    ):
        etree.SubElement(description, _q(_xml.FACTURX_XMP, name)).text = value


def _about(rdf: etree._Element) -> str:
    """The ``rdf:about`` of the packet's first description: the resource every description must describe."""
    first = rdf.find(_q(_xml.RDF, "Description"))
    return "" if first is None else first.get(_q(_xml.RDF, "about"), "")


def _description(rdf: etree._Element, about: str, nsmap: dict[str, str]) -> etree._Element:
    return etree.SubElement(rdf, _q(_xml.RDF, "Description"), {_q(_xml.RDF, "about"): about}, nsmap=nsmap)


def _bag(rdf: etree._Element, about: str) -> etree._Element:
    """The ``rdf:Bag`` of ``pdfaExtension:schemas``, created in a new description when the packet has none."""
    bag = rdf.find(f"{_q(_xml.RDF, 'Description')}/{_q(_xml.PDFA_EXTENSION, 'schemas')}/{_q(_xml.RDF, 'Bag')}")
    if bag is not None:
        return bag
    nsmap = {"pdfaExtension": _xml.PDFA_EXTENSION, "pdfaSchema": _xml.PDFA_SCHEMA, "pdfaProperty": _xml.PDFA_PROPERTY}
    schemas = etree.SubElement(_description(rdf, about, nsmap), _q(_xml.PDFA_EXTENSION, "schemas"))
    return etree.SubElement(schemas, _q(_xml.RDF, "Bag"))


def _resource(parent: etree._Element) -> etree._Element:
    return etree.SubElement(parent, _q(_xml.RDF, "li"), {_q(_xml.RDF, "parseType"): "Resource"})


def _schema(bag: etree._Element) -> None:
    """One ``rdf:li`` declaring the Factur-X schema and its four ``Text`` / ``external`` properties."""
    schema = _resource(bag)
    for name, value in (("schema", _SCHEMA_NAME), ("namespaceURI", _xml.FACTURX_XMP), ("prefix", "fx")):
        etree.SubElement(schema, _q(_xml.PDFA_SCHEMA, name)).text = value
    properties = etree.SubElement(etree.SubElement(schema, _q(_xml.PDFA_SCHEMA, "property")), _q(_xml.RDF, "Seq"))
    for name, description in _PROPERTIES:
        item = _resource(properties)
        for key, value in (
            ("name", name),
            ("valueType", "Text"),
            ("category", "external"),
            ("description", description),
        ):
            etree.SubElement(item, _q(_xml.PDFA_PROPERTY, key)).text = value
