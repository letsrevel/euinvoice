"""``facturx.embed``: the CII XML of an invoice into a PDF/A-3 (plan §1 item 5, §5).

:func:`embed` takes a PDF that is already PDF/A-3 (euinvoice does not convert to PDF/A; render it, e.g., with
WeasyPrint ``pdf_variant="pdf/a-3b"``) and adds the invoice as an associated file plus the Factur-X XMP. It is
built on pypdf only (the ``[pdf]`` extra; D6: no ``factur-x`` package).

The Factur-X / ZUGFeRD specification package is not pinned (#42). Each value written is the one the Factur-X PDFs
of the pinned ZUGFeRD corpus carry (``ZUGFeRDv2/correct`` and ``XML-Rechnung/FX``, the 74 PDFs whose XMP declares
:data:`euinvoice._xml.FACTURX_XMP`; counts below are over their 87 file specifications, of which 74 are the
invoice XML). The XMP values are cited in :mod:`euinvoice.facturx.xmp`. Per invoice file specification:

* ``/F`` and ``/UF`` are the level's file name (``Profile.facturx_filename``, cited in
  :mod:`euinvoice.profiles.facturx`): 74 of 74. ``/Desc`` is present on 87 of 87; its text varies, and the file
  name is the variant of the ZUGFeRD examples (``ZUGFeRDv2/correct/symtrax/Beispiele``, 38 files).
* ``/AFRelationship``: ``/Data`` for 46 of the 74 invoice files, at every level but XRECHNUNG, ``/Alternative`` for
  24 EN 16931 ones (``XML-Rechnung/FX``, Mustang) and ``/Source`` for all 4 XRECHNUNG ones. :func:`embed` writes
  the attested per-level default (``Source`` for XRECHNUNG, ``Data`` otherwise) unless told otherwise; which
  values the spec allows per level is open (#42).
* The file specification is in the catalog ``/AF`` array: 87 of 87.
* The embedded file stream's ``/Subtype`` is ``/text/xml`` (74 of 74) and its ``/Params`` hold ``/ModDate``
  (87 of 87) and ``/Size`` (60 of 87).

``fx:Version`` is ``1.0`` in the 70 files at levels other than XRECHNUNG. The 4 XRECHNUNG files carry ``2.1``,
the version of the XRechnung they embed; :data:`~euinvoice.profiles.FACTURX_XRECHNUNG` writes XRechnung 3.0, so it
gets ``3.0``. The corpus has no XRECHNUNG-level PDF of XRechnung 3.0, so that value is an inference (#42).
"""

import datetime
import io
import typing as t

try:
    import pypdf
    from pypdf.errors import PyPdfError
    from pypdf.generic import ArrayObject, NameObject, NumberObject, TextStringObject
except ImportError as exc:
    raise ImportError("Factur-X embedding needs pypdf: install the extra with `pip install 'euinvoice[pdf]'`.") from exc
from lxml import etree

from euinvoice import _xml, detect, profiles
from euinvoice.errors import ParseError, PdfError, UnsupportedDocumentError
from euinvoice.facturx import xmp
from euinvoice.model import Invoice
from euinvoice.profiles import Profile
from euinvoice.syntax import Syntax, cii

__all__ = ["Relationship", "embed"]

type Relationship = t.Literal["Data", "Source", "Alternative"]
"""The ``/AFRelationship`` values the corpus attests for the invoice XML (see the module docstring; plan §5)."""
_RELATIONSHIPS: t.Final[tuple[str, ...]] = t.get_args(Relationship.__value__)

_XRECHNUNG: t.Final = "XRECHNUNG"
_GENERATED: t.Final = (profiles.FACTURX_EN16931, profiles.FACTURX_XRECHNUNG)
"""The levels an :class:`~euinvoice.model.Invoice` can be written for (plan §1: Generate ✅)."""


def embed(
    pdf: bytes,
    invoice: Invoice | bytes,
    *,
    profile: Profile,
    relationship: Relationship | None = None,
) -> bytes:
    """Embed an invoice's CII XML into a PDF/A-3 as a Factur-X / ZUGFeRD document.

    The XML becomes an associated file named after the level (``factur-x.xml``, ``xrechnung.xml``) and the XMP
    gets the ``fx`` properties and their PDF/A extension schema. The rest of the PDF is kept as it is,
    including the document information dictionary and the first file identifier; the second identifier is
    regenerated, because the content changed (ISO 32000-1 §14.4). The XML is embedded byte for byte.

    Args:
        pdf: A PDF/A-3 document (XMP ``pdfaid:part`` 3).
        invoice: The CII XML as bytes, embedded unchanged, or an :class:`~euinvoice.model.Invoice`, written
            with :func:`euinvoice.syntax.cii.write` after ``profile.prepare`` (EN 16931 and XRECHNUNG levels
            only, plan §1). Pre-flight checks are not run; that is ``to_xml``'s job (#27).
        profile: The Factur-X level, e.g. :data:`euinvoice.profiles.FACTURX_EN16931`.
        relationship: The file specification's ``/AFRelationship``; by default ``Source`` for XRECHNUNG and
            ``Data`` otherwise (the corpus-attested choice, see the module docstring).

    Returns:
        The Factur-X PDF.

    Raises:
        UnsupportedDocumentError: ``profile`` is not a Factur-X level, ``invoice`` is an ``Invoice`` for a level
            that is not generated, or the XML is not CII.
        ParseError: The XML is malformed or has a DOCTYPE (D10).
        PdfError: ``pdf`` cannot be read, is encrypted, is not PDF/A-3, has malformed XMP, already carries
            Factur-X XMP, or already has an attachment with the level's file name.
        ValueError: ``relationship`` is not one of :data:`Relationship`.
    """
    level, filename = _level(profile)
    if relationship is None:
        relationship = "Source" if level == _XRECHNUNG else "Data"
    elif relationship not in _RELATIONSHIPS:
        raise ValueError(f"unknown AFRelationship {relationship!r}; known: {', '.join(map(repr, _RELATIONSHIPS))}")
    xml = _cii(invoice, profile)
    reader = _reader(pdf)
    packet = _packet(reader)
    if filename in reader.attachments:
        raise PdfError(f"the PDF already has an attachment named {filename!r}")
    rdf = next(packet.iter(f"{{{_xml.RDF}}}RDF"), None)
    if rdf is None:
        raise PdfError("the XMP metadata has no rdf:RDF element")
    # fx:Version: "1.0", or the embedded XRechnung's version for XRECHNUNG (inferred "3.0", see the docstring; #42).
    xmp.add_facturx(rdf, filename=filename, version="3.0" if level == _XRECHNUNG else "1.0", level=level)

    writer = pypdf.PdfWriter(clone_from=reader)
    _attach(writer, filename, xml, relationship)
    # The packet's processing instructions (<?xpacket?>) are siblings of the root, so serialize the tree.
    writer.xmp_metadata = etree.tostring(packet.getroottree(), encoding="UTF-8")
    writer.generate_file_identifiers()
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _level(profile: Profile) -> tuple[str, str]:
    """``(fx:ConformanceLevel, file name)`` of a Factur-X level."""
    if profile.facturx_conformance_level is None or profile.facturx_filename is None:
        raise UnsupportedDocumentError(f"profile {profile.id!r} is not a Factur-X / ZUGFeRD level")
    return profile.facturx_conformance_level, profile.facturx_filename


def _cii(invoice: Invoice | bytes, profile: Profile) -> bytes:
    if isinstance(invoice, Invoice):
        if profile not in _GENERATED:
            generated = ", ".join(p.id for p in _GENERATED)
            raise UnsupportedDocumentError(
                f"profile {profile.id!r} is not generated from an Invoice (plan §1); pass its CII XML as bytes, "
                f"or use {generated}"
            )
        return cii.write(profile.prepare(invoice))
    found = detect.detect(invoice)
    if found.syntax is not Syntax.CII:
        raise UnsupportedDocumentError(f"Factur-X embeds UN/CEFACT CII, got {found.syntax} ({found.root})")
    return invoice


def _reader(pdf: bytes) -> pypdf.PdfReader:
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf))
        encrypted = reader.is_encrypted
    except PyPdfError as exc:
        raise PdfError(f"cannot read the PDF: {exc}") from exc
    if encrypted:
        raise PdfError("the PDF is encrypted, which PDF/A forbids")
    return reader


def _packet(reader: pypdf.PdfReader) -> etree._Element:
    """The parsed XMP packet of a PDF/A-3 document; raises :class:`PdfError` for anything else."""
    metadata = reader.root_object.get("/Metadata")
    if metadata is None:
        raise PdfError("the PDF has no XMP metadata, so it is not PDF/A-3 (plan §5)")
    try:
        packet = _xml.parse(t.cast(pypdf.generic.StreamObject, metadata.get_object()).get_data())
    except ParseError as exc:
        raise PdfError(f"the XMP metadata is not well-formed XML: {exc}") from exc
    if (parts := xmp.pdfa_parts(packet)) != ["3"]:
        raise PdfError(f"the PDF is not PDF/A-3: XMP pdfaid:part {parts}, expected ['3'] (plan §5)")
    if xmp.has_facturx(packet):
        raise PdfError("the PDF already carries Factur-X XMP properties")
    return packet


def _attach(writer: pypdf.PdfWriter, filename: str, xml: bytes, relationship: Relationship) -> None:
    """Add the file specification (see the module docstring for each entry) and list it in the catalog ``/AF``."""
    embedded = writer.add_attachment(filename, xml)
    name = TextStringObject(filename)
    embedded.alternative_name = name  # /F and /UF
    embedded.description = name
    embedded.associated_file_relationship = NameObject(f"/{relationship}")
    embedded.subtype = NameObject("/text/xml")
    embedded.size = NumberObject(len(xml))
    embedded.modification_date = datetime.datetime.now(datetime.UTC)
    reference = embedded.pdf_object.indirect_reference
    catalog = writer.root_object
    af = catalog.get("/AF")
    if af is None:
        catalog[NameObject("/AF")] = ArrayObject([reference])
    else:
        t.cast(ArrayObject, af.get_object()).append(reference)
