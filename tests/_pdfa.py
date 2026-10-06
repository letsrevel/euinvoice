"""Synthetic PDF/A-3B input for the Factur-X tests, generated with pypdf instead of a committed binary.

:func:`pdf` writes one blank A4 page. It draws nothing, so it needs no fonts and no output intent, and with
:data:`PDFA_3B` as XMP it passes veraPDF's PDF/A-3B profile (``tests/conformance/test_facturx_verapdf.py``): the
trailer ``/ID`` (rule 6.1.3-1) and the metadata stream's ``/Type /Metadata /Subtype /XML`` (6.6.2.1-1) are set,
and ``pdf:Producer`` repeats the ``/Producer`` pypdf writes into the document information dictionary.
"""

import io
import typing as t

import pypdf
from pypdf.generic import NameObject

_PACKET: t.Final = """<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
{}
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""

PDFA_ID: t.Final = """    <rdf:Description rdf:about="" xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/">
      <pdfaid:part>{part}</pdfaid:part>
      <pdfaid:conformance>B</pdfaid:conformance>
    </rdf:Description>"""
PRODUCER: t.Final = """    <rdf:Description rdf:about="" xmlns:pdf="http://ns.adobe.com/pdf/1.3/">
      <pdf:Producer>pypdf</pdf:Producer>
    </rdf:Description>"""


def xmp(*descriptions: str) -> bytes:
    """An XMP packet whose ``rdf:RDF`` holds ``descriptions`` (serialized ``rdf:Description`` elements)."""
    return _PACKET.format("\n".join(descriptions)).encode()


PDFA_3B: t.Final = xmp(PDFA_ID.format(part=3), PRODUCER)
"""XMP of a PDF/A-3B document: ``pdfaid:part`` 3, ``pdfaid:conformance`` B."""


def pdf(metadata: bytes | None = PDFA_3B, *, attachment: str | None = None, encrypt: bool = False) -> bytes:
    """A one-page blank PDF with ``metadata`` as its XMP stream (none when ``None``).

    Args:
        metadata: The XMP packet; :data:`PDFA_3B` by default.
        attachment: Name of an unrelated text file to embed and reference from the catalog ``/AF`` array.
        encrypt: Encrypt the document (PDF/A forbids it).
    """
    writer = pypdf.PdfWriter()
    writer.add_blank_page(595, 842)
    if metadata is not None:
        writer.xmp_metadata = metadata
        stream = t.cast(pypdf.generic.StreamObject, writer.root_object["/Metadata"].get_object())
        stream[NameObject("/Type")] = NameObject("/Metadata")
        stream[NameObject("/Subtype")] = NameObject("/XML")
    if attachment is not None:
        embedded = writer.add_attachment(attachment, b"notes\n")
        embedded.alternative_name = pypdf.generic.TextStringObject(attachment)  # /UF next to /F (veraPDF 6.8-2)
        embedded.subtype = NameObject("/text/plain")
        embedded.associated_file_relationship = NameObject("/Supplement")
        reference = t.cast(pypdf.generic.IndirectObject, embedded.pdf_object.indirect_reference)
        writer.root_object[NameObject("/AF")] = pypdf.generic.ArrayObject([reference])
    if encrypt:
        writer.encrypt("secret", algorithm="RC4-128")
    writer.generate_file_identifiers()
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
