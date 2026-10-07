"""Classify e-invoice XML: syntax and root element from the root's qualified name, profile from BT-24.

Contract (the first step of parsing and of profile auto-detection, plan §4):

* Not well-formed XML, a DOCTYPE, or input over the parser limits: ``ParseError`` from
  :func:`euinvoice._xml.parse` (D10). A PDF gets an ``UnsupportedDocumentError`` pointing to
  ``euinvoice.facturx.extract``, which takes the embedded XML out of a Factur-X / ZUGFeRD PDF.
* A root other than UBL 2.1 ``Invoice`` / ``CreditNote``, CII D16B ``CrossIndustryInvoice`` or FatturaPA 1.2
  ``FatturaElettronica``: ``UnsupportedDocumentError``. These are the only two errors :func:`detect` raises for its
  own reasons.
* FatturaPA (``Syntax.FATTURAPA``, #121) has no BT-24: ``specification_identifier`` and ``profile`` are always
  ``None``, and ``fatturapa_version`` holds the root's ``versione`` attribute (``FPA12`` or ``FPR12`` in a valid
  document). Any other value, or none, is still detected as FatturaPA: the XSD reports it, so ``validate()``
  must get to run (D9).
* A supported root without exactly one non-empty BT-24: a :class:`Detection` with
  ``specification_identifier=None`` and ``profile=None``. Such a document is an invalid invoice, not
  garbage; the official rules report it (BR-01, CII-SR-009/010), so ``validate()`` must get to run them
  (D9).
* A supported root with a BT-24 that no registered profile declares (a CIUS or extension whose profile is
  not implemented yet, or a legacy id such as ``urn:ferd:CrossIndustryDocument:invoice:1p0:comfort``):
  a :class:`Detection` with ``profile=None``. What to do without a profile is the caller's decision
  (``validate()`` / ``parse()``).

The profile match is exact (:func:`euinvoice.profiles.get`): a CIUS id never resolves to the core
profile. A bare core BT-24 is the core profile even when the XML came out of a Factur-X PDF, where only the
PDF container's XMP selects a Factur-X profile.
"""

import dataclasses
import typing as t

from lxml import etree

from euinvoice import _xml, profiles
from euinvoice.errors import UnsupportedDocumentError
from euinvoice.syntax import Syntax

__all__ = ["Detection", "Root", "detect", "detect_root", "is_pdf"]

type Root = t.Literal["Invoice", "CreditNote", "CrossIndustryInvoice", "FatturaElettronica"]
"""The supported root elements. UBL has one per document kind; CII has one for both (BT-3 tells them apart), and so
has FatturaPA (``TipoDocumento`` per body)."""

# Root qualified name → (syntax, root). Root names per the UBL 2.1 maindoc XSDs (UBL-Invoice-2.1.xsd,
# UBL-CreditNote-2.1.xsd), the CII D16B CrossIndustryInvoice_100pD16B.xsd and the FatturaPA Schema_VFPR12_v1.2.3.xsd
# (global element FatturaElettronica, the one root of FPA12 and FPR12).
_ROOTS: t.Final[t.Mapping[str, tuple[Syntax, Root]]] = {
    f"{{{_xml.UBL_INVOICE}}}Invoice": (Syntax.UBL, "Invoice"),
    f"{{{_xml.UBL_CREDIT_NOTE}}}CreditNote": (Syntax.UBL, "CreditNote"),
    f"{{{_xml.CII_RSM}}}CrossIndustryInvoice": (Syntax.CII, "CrossIndustryInvoice"),
    f"{{{_xml.FATTURAPA}}}FatturaElettronica": (Syntax.FATTURAPA, "FatturaElettronica"),
}

# BT-24 locations, relative to the root: the BR-01 params of the CEN 1.3.16 EN16931-UBL-model.sch
# (``cbc:CustomizationID``, at most once per the UBL 2.1 maindoc XSDs) and EN16931-CII-model.sch.
_UBL_BT24: t.Final = f"{{{_xml.UBL_CBC}}}CustomizationID"
_CII_BT24: t.Final = (
    f"{{{_xml.CII_RSM}}}ExchangedDocumentContext/{{{_xml.CII_RAM}}}GuidelineSpecifiedDocumentContextParameter"
    f"/{{{_xml.CII_RAM}}}ID"
)

_PDF_MAGIC: t.Final = b"%PDF-"
# ponytail: PDF readers tolerate leading bytes (a BOM, a newline, junk) before the header and commonly look
# in the first 1024 bytes; a header further in is not sniffed and the input fails as malformed XML instead.
_PDF_WINDOW: t.Final = 1024


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Detection:
    """What :func:`detect` found out about a document.

    Attributes:
        syntax: :attr:`Syntax.UBL <euinvoice.syntax.Syntax.UBL>` (UBL 2.1), ``Syntax.CII`` (UN/CEFACT
            CII D16B) or ``Syntax.FATTURAPA`` (FatturaPA 1.2); a ``StrEnum``, so it also compares equal to
            ``"ubl"`` / ``"cii"`` / ``"fatturapa"``.
        root: The root element's local name; for UBL it is the document kind (``Invoice`` or
            ``CreditNote``), CII uses ``CrossIndustryInvoice`` for both, FatturaPA ``FatturaElettronica``.
        specification_identifier: BT-24 as found, whitespace-normalized (``normalize-space()``, as BR-01
            and PEPPOL-EN16931-R004 read it); ``None`` when the document does not carry exactly one
            non-empty BT-24 element.
        profile: The registered profile whose BT-24 matches exactly, or ``None`` when none does (or there
            is no BT-24).
        fatturapa_version: For FatturaPA, the root's ``versione`` attribute as written (``FPA12``: to a public
            administration, ``FPR12``: to private parties; ``FormatoTrasmissioneType`` of XSD 1.2.3), ``None`` when
            absent; always ``None`` for UBL and CII.
    """

    syntax: Syntax
    root: Root
    specification_identifier: str | None
    profile: profiles.Profile | None
    fatturapa_version: str | None = None


def detect(data: bytes) -> Detection:
    """Classify an e-invoice XML document by its root element and specification identifier (BT-24).

    Args:
        data: The serialized XML document.

    Returns:
        The syntax, root element, BT-24 and matching profile, see :func:`detect_root`.

    Raises:
        TypeError: ``data`` is not ``bytes``.
        ParseError: The XML is malformed, has a DOCTYPE or exceeds the parser limits.
        UnsupportedDocumentError: ``data`` is a PDF, or the root element is not a UBL 2.1 Invoice /
            CreditNote, a CII D16B CrossIndustryInvoice or a FatturaPA 1.2 FatturaElettronica.

    Example:
        >>> from euinvoice import _xml
        >>> xml = (
        ...     f'<Invoice xmlns="{_xml.UBL_INVOICE}" xmlns:cbc="{_xml.UBL_CBC}">'
        ...     "<cbc:CustomizationID>urn:cen.eu:en16931:2017</cbc:CustomizationID></Invoice>"
        ... )
        >>> detect(xml.encode()).profile.id
        'en16931'
    """
    if is_pdf(data):
        raise UnsupportedDocumentError(
            "input is a PDF; extract the embedded Factur-X / ZUGFeRD XML with euinvoice.facturx.extract first"
        )
    return detect_root(_xml.parse(data))


def is_pdf(data: bytes) -> bool:
    """Whether ``data`` starts like a PDF: a ``%PDF-`` header within its first 1024 bytes, before any ``<``.

    Args:
        data: The input; anything but ``bytes`` is not a PDF.

    Returns:
        ``True`` for a PDF header, ``False`` otherwise (e.g. XML whose text contains ``%PDF-``).
    """
    # A PDF header counts only before any markup: "%PDF-" in XML text (e.g. a BT-22 note) is not a PDF.
    header = data.find(_PDF_MAGIC, 0, _PDF_WINDOW) if isinstance(data, bytes) else -1
    return header != -1 and b"<" not in data[:header]


def detect_root(root: etree._Element) -> Detection:
    """Classify an already parsed document (the root element returned by ``euinvoice._xml.parse``).

    Args:
        root: The document's root element.

    Returns:
        The syntax, root element, BT-24 and matching profile. ``specification_identifier`` and ``profile``
        are ``None`` when there is not exactly one non-empty BT-24 (always, for FatturaPA); ``profile`` alone is
        ``None`` for an unregistered BT-24.

    Raises:
        UnsupportedDocumentError: The root element is not a UBL 2.1 Invoice / CreditNote, a CII D16B
            CrossIndustryInvoice or a FatturaPA 1.2 FatturaElettronica.
    """
    try:
        syntax, root_name = _ROOTS[root.tag]
    except KeyError:
        raise UnsupportedDocumentError(
            f"unsupported root element {root.tag!r}; expected a UBL 2.1 Invoice or CreditNote, a CII D16B "
            "CrossIndustryInvoice or a FatturaPA 1.2 FatturaElettronica"
        ) from None
    if syntax is Syntax.FATTURAPA:
        return Detection(
            syntax=syntax,
            root=root_name,
            specification_identifier=None,
            profile=None,
            fatturapa_version=root.get("versione"),
        )
    values = root.findall(_UBL_BT24 if syntax is Syntax.UBL else _CII_BT24)
    # Several BT-24 elements are ambiguous; the official rules report them, detection picks none.
    # XPath normalize-space() strips only #x20, #x9, #xD, #xA; str.split() would also strip e.g. U+00A0.
    bt24 = str(values[0].xpath("normalize-space(.)")) if len(values) == 1 else ""
    if not bt24:
        return Detection(syntax=syntax, root=root_name, specification_identifier=None, profile=None)
    try:
        profile: profiles.Profile | None = profiles.get(bt24)
    except UnsupportedDocumentError:
        profile = None
    return Detection(syntax=syntax, root=root_name, specification_identifier=bt24, profile=profile)
