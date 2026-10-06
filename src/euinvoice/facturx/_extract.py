"""``facturx.extract``: the invoice XML out of a Factur-X / ZUGFeRD PDF (plan §1 item 5, §8 7.2).

The Factur-X / ZUGFeRD specification package is not pinned (#42), so the selection rule is the one every PDF of the
pinned ZUGFeRD corpus (manifest source ``zugferd-corpus``) satisfies. Of its 151 PDFs, 150 declare one of four XMP
invoice schemas, :data:`_CONTAINERS`; the other one (``unstructured/``) is not an e-invoice. In each of the 125 PDFs
of the ``correct`` directories (74 Factur-X 1.0 / ZUGFeRD 2.1+, 30 ZUGFeRD 2.0, 21 ZUGFeRD 1.0):

* the XMP declares exactly one of the four schemas, with exactly one ``DocumentFileName``;
* that name is an attachment of the ``/EmbeddedFiles`` name tree, which holds it once, and the invoice. An entry
  matches by its name-tree key or by its file specification's ``/UF`` (else ``/F``) name, as pypdf lists
  attachments; in the corpus all three are equal;
* the name is the one the schema uses: ``factur-x.xml`` (70) or ``xrechnung.xml`` (the 4
  ``XRECHNUNG``-level PDFs) for Factur-X, always the level's ``Profile.facturx_filename``;
  ``zugferd-invoice.xml`` (30) for ZUGFeRD 2.0; ``ZUGFeRD-invoice.xml`` (21) for ZUGFeRD 1.0;
* Factur-X has exactly one ``ConformanceLevel``, a registered level; ZUGFeRD 1.0 omits it once
  (``ZUGFeRDv1/correct/Mustangproject/MustangGnuaccountingBeispielRE-20170509_505.pdf``).

Several PDFs have more attachments: other XML files (``ZUGFeRDv1/correct/4s4u/additional-data-sample-1.pdf``, whose
second XMP schema names the second XML), images and PDFs. So the XMP name selects the invoice, never "the only XML
file". :func:`extract` refuses everything outside the rule above with :class:`PdfError`; this is the strict choice
where the corpus is silent (several invoice schemas, an unknown Factur-X level, a duplicate name), pending the
spec text (#42). Of the 25 ``fail`` PDFs, only ``ZUGFeRDv2/fail/Mustangproject/wrongFilename.pdf`` (XMP and
attachment both ``factur-y.xml``) is refused; the others fail upstream for their content, which is the job of
``parse()`` and ``validate()``.

Not checked, because a receiver gets what it gets: PDF/A conformance, the catalog ``/AF`` array, the
``/AFRelationship`` (``Data``, ``Alternative``, ``Source`` and ``Unspecified`` all occur) and the MIME type.

Hostile input: memory is bounded by pypdf's limits (``pypdf.Configuration``, 75 MB each by default in pypdf 6):
``maximum_declared_stream_length`` caps a stream's declared ``/Length``, and ``zlib_maximum_output_length``,
``lzw_maximum_output_length`` and ``run_length_maximum_output_length`` cap each decoded ``FlateDecode``, ``LZWDecode``
and ``RunLengthDecode`` stream. Exceeding one raises pypdf's ``LimitReachedError``, a ``PdfError`` here. Only two
streams are decoded: the XMP and the one selected attachment (entries with its name are counted before any is
decoded). The XMP goes through :func:`euinvoice._xml.parse` (D10), with libxml2's limits.
"""
# ponytail: each decoded stream may reach pypdf's 75 MB default; an invoice XML is far smaller. The upgrade path is an
# invoice-specific cap (e.g. checking the file spec's /Params /Size, or decoding with a smaller pypdf.Configuration).

import dataclasses
import io
import typing as t

import pypdf
from lxml import etree

from euinvoice import _xml, profiles
from euinvoice.detection import detect
from euinvoice.errors import ParseError, PdfError, UnsupportedDocumentError
from euinvoice.facturx import xmp
from euinvoice.facturx._pypdf import PYPDF_FAILURES, metadata_bytes
from euinvoice.profiles import Profile
from euinvoice.syntax import Syntax

__all__ = ["Container", "Extracted", "extract"]

type Container = t.Literal["factur-x", "zugferd-2.0", "zugferd-1.0"]
"""The XMP invoice schema of a PDF: Factur-X 1.0 / ZUGFeRD 2.1+, ZUGFeRD 2.0 or ZUGFeRD 1.0 (and its release
candidate)."""

_CONTAINERS: t.Final[t.Mapping[str, Container]] = {
    _xml.FACTURX_XMP: "factur-x",
    _xml.ZUGFERD_2_XMP: "zugferd-2.0",
    _xml.ZUGFERD_1_XMP: "zugferd-1.0",
    _xml.ZUGFERD_1_RC_XMP: "zugferd-1.0",
}
_ZUGFERD_FILE_NAMES: t.Final[t.Mapping[Container, str]] = {
    "zugferd-2.0": "zugferd-invoice.xml",
    "zugferd-1.0": "ZUGFeRD-invoice.xml",
}
"""The invoice file name of the ZUGFeRD schemas; a Factur-X level has its own (``Profile.facturx_filename``)."""


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Extracted:
    """The invoice found in a Factur-X / ZUGFeRD PDF.

    Attributes:
        xml: The embedded file, byte for byte. Not parsed beyond detection: ``parse()`` / ``validate()`` read it.
        filename: Its name, the XMP ``DocumentFileName``.
        container: The XMP invoice schema.
        conformance_level: The XMP ``ConformanceLevel`` as written (``"EN 16931"``, ``"COMFORT"``…), or ``None``.
        profile: For Factur-X, the level's profile when the XML is CII with that level's BT-24 (the pairing
            ``embed`` enforces); otherwise the profile :func:`euinvoice.detection.detect` finds from the XML alone
            (a ZUGFeRD 2.0 ``EN 16931`` invoice is the core profile), or ``None`` (no registered BT-24, not a
            supported invoice, not well-formed).
    """

    xml: bytes
    filename: str
    container: Container
    conformance_level: str | None
    profile: Profile | None


def extract(pdf: bytes) -> Extracted:
    """Take the invoice XML out of a Factur-X or ZUGFeRD (1.0, 2.0, 2.1+) PDF.

    The XMP names the invoice attachment; the selection rule and its corpus evidence are in the module
    docstring. The PDF need not be PDF/A, and a signed PDF is read like any other.

    Args:
        pdf: The PDF.

    Returns:
        The XML and what the PDF and the XML say about it.

    Raises:
        PdfError: pypdf cannot read ``pdf`` (any pypdf failure on the untrusted input, with the cause chained); it
            is encrypted; its XMP is missing, not a stream or not well-formed; or the XMP does not name exactly one
            invoice attachment by an attested name (see the module docstring).

    Example:
        >>> from euinvoice import facturx
        >>> found = facturx.extract(pdf_bytes)  # doctest: +SKIP
        >>> found.filename, found.conformance_level  # doctest: +SKIP
        ('factur-x.xml', 'EN 16931')
    """
    # pypdf work on the untrusted PDF runs in _read and _attachment; what pypdf raises there becomes a PdfError. Our
    # own XMP code runs between them, unwrapped, so a bug of ours is not reported as a broken PDF.
    try:
        reader, metadata = _read(pdf)
    except PYPDF_FAILURES as exc:
        raise PdfError(f"cannot read the PDF: {type(exc).__name__}: {exc}") from exc
    try:
        packet = _xml.parse(metadata)
    except ParseError as exc:
        raise PdfError(f"the XMP metadata is not well-formed XML: {exc}") from exc
    namespace, container = _container(packet)
    filename = _one(packet, namespace, "DocumentFileName")
    levels = xmp._values(packet, namespace, "ConformanceLevel")
    if len(levels) > 1 or (container == "factur-x" and not levels):
        raise PdfError(f"the {container} XMP must have exactly one ConformanceLevel, found {levels}")
    level = levels[0] if levels else None
    level_profile = _level_profile(level) if container == "factur-x" and level is not None else None
    expected = _ZUGFERD_FILE_NAMES.get(container) if level_profile is None else level_profile.facturx_filename
    if filename != expected:
        raise PdfError(f"the {container} invoice of level {level!r} is {expected!r}, but the XMP names {filename!r}")
    try:
        xml = _attachment(reader, filename)
    except PYPDF_FAILURES as exc:
        raise PdfError(f"cannot read the PDF: {type(exc).__name__}: {exc}") from exc
    return Extracted(
        xml=xml,
        filename=filename,
        container=container,
        conformance_level=level,
        profile=_profile(xml, level_profile),
    )


def _read(pdf: bytes) -> tuple[pypdf.PdfReader, bytes]:
    """Pypdf phase 1: open the PDF and return the reader and the raw XMP packet."""
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    if reader.is_encrypted:
        raise PdfError("the PDF is encrypted")
    return reader, metadata_bytes(
        reader, missing="the PDF has no XMP metadata, so it does not name an invoice attachment"
    )


def _attachment(reader: pypdf.PdfReader, filename: str) -> bytes:
    """Pypdf phase 2: the content of the one attachment called ``filename``.

    Entries match by name-tree key or ``/UF`` / ``/F`` name (pypdf's ``attachments`` keys). They are counted before
    any is decoded, so duplicates cannot multiply the decoded size.
    """
    entries = [entry for entry in reader.attachment_list if filename in (entry.name, entry.alternative_name)]
    if not entries:
        raise PdfError(f"the XMP names {filename!r}, but the PDF has no attachment named {filename!r}")
    if len(entries) != 1:
        raise PdfError(f"the PDF has {len(entries)} attachments named {filename!r}")
    return entries[0].content


def _container(packet: etree._Element) -> tuple[str, Container]:
    """The one invoice schema the XMP uses (any of its properties present)."""
    found = [
        namespace
        for namespace in _CONTAINERS
        if any(xmp._values(packet, namespace, name) for name in ("DocumentFileName", "ConformanceLevel"))
    ]
    if not found:
        raise PdfError("the PDF has no Factur-X / ZUGFeRD XMP, so it does not name an invoice attachment")
    if len(found) > 1:
        raise PdfError(f"the XMP declares more than one invoice schema: {found}")
    return found[0], _CONTAINERS[found[0]]


def _one(packet: etree._Element, namespace: str, name: str) -> str:
    found = xmp._values(packet, namespace, name)
    if len(found) != 1:
        raise PdfError(f"the XMP must have exactly one {name} in {namespace}, found {found}")
    return found[0]


def _level_profile(level: str) -> Profile:
    try:
        return profiles.by_conformance_level(level)
    except UnsupportedDocumentError as exc:
        raise PdfError(str(exc)) from exc


def _profile(xml: bytes, level_profile: Profile | None) -> Profile | None:
    """See :attr:`Extracted.profile`."""
    try:
        found = detect(xml)
    except (ParseError, UnsupportedDocumentError):
        return None
    if (
        level_profile is not None
        and found.syntax is Syntax.CII
        and found.specification_identifier == level_profile.specification_identifier
    ):
        return level_profile
    return found.profile
