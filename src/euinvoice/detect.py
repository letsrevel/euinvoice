"""Classify e-invoice XML: syntax and root element from the root's qualified name, profile from BT-24.

Contract (the first step of parsing and of profile auto-detection, plan §4):

* Not well-formed XML, a DOCTYPE, or input over the parser limits: ``ParseError`` from
  :func:`euinvoice._xml.parse` (D10). A PDF gets an ``UnsupportedDocumentError`` pointing to
  ``euinvoice.facturx.extract``, which takes the embedded XML out of a Factur-X / ZUGFeRD PDF.
* A root other than UBL 2.1 ``Invoice`` / ``CreditNote`` or CII D16B ``CrossIndustryInvoice``:
  ``UnsupportedDocumentError``. These are the only two errors :func:`detect` raises for its own reasons.
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

__all__ = ["Detection", "Root", "detect", "detect_root"]

# ponytail: plain strings until ``euinvoice.syntax.Syntax`` (a StrEnum with these values) lands; switch the
# annotation to the enum then. StrEnum members compare equal to these strings, so callers keep working.
type _Syntax = t.Literal["ubl", "cii"]

type Root = t.Literal["Invoice", "CreditNote", "CrossIndustryInvoice"]
"""The supported root elements. UBL has one per document kind; CII has one for both (BT-3 tells them apart)."""

# Root qualified name → (syntax, root). Root names per the UBL 2.1 maindoc XSDs (UBL-Invoice-2.1.xsd,
# UBL-CreditNote-2.1.xsd) and the CII D16B CrossIndustryInvoice_100pD16B.xsd.
_ROOTS: t.Final[t.Mapping[str, tuple[_Syntax, Root]]] = {
    f"{{{_xml.UBL_INVOICE}}}Invoice": ("ubl", "Invoice"),
    f"{{{_xml.UBL_CREDIT_NOTE}}}CreditNote": ("ubl", "CreditNote"),
    f"{{{_xml.CII_RSM}}}CrossIndustryInvoice": ("cii", "CrossIndustryInvoice"),
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
        syntax: ``"ubl"`` (UBL 2.1) or ``"cii"`` (UN/CEFACT CII D16B).
        root: The root element's local name; for UBL it is the document kind (``Invoice`` or
            ``CreditNote``), CII uses ``CrossIndustryInvoice`` for both.
        specification_identifier: BT-24 as found, whitespace-normalized (``normalize-space()``, as BR-01
            and PEPPOL-EN16931-R004 read it); ``None`` when the document does not carry exactly one
            non-empty BT-24 element.
        profile: The registered profile whose BT-24 matches exactly, or ``None`` when none does (or there
            is no BT-24).
    """

    syntax: _Syntax
    root: Root
    specification_identifier: str | None
    profile: profiles.Profile | None


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
            CreditNote or a CII D16B CrossIndustryInvoice.

    Example:
        >>> from euinvoice import _xml
        >>> xml = (
        ...     f'<Invoice xmlns="{_xml.UBL_INVOICE}" xmlns:cbc="{_xml.UBL_CBC}">'
        ...     "<cbc:CustomizationID>urn:cen.eu:en16931:2017</cbc:CustomizationID></Invoice>"
        ... )
        >>> detect(xml.encode()).profile.id
        'en16931'
    """
    # A PDF header counts only before any markup: "%PDF-" in XML text (e.g. a BT-22 note) is not a PDF.
    header = data.find(_PDF_MAGIC, 0, _PDF_WINDOW) if isinstance(data, bytes) else -1
    if header != -1 and b"<" not in data[:header]:
        raise UnsupportedDocumentError(
            "input is a PDF; extract the embedded Factur-X / ZUGFeRD XML with euinvoice.facturx.extract first"
        )
    return detect_root(_xml.parse(data))


def detect_root(root: etree._Element) -> Detection:
    """Classify an already parsed document (the root element returned by ``euinvoice._xml.parse``).

    Args:
        root: The document's root element.

    Returns:
        The syntax, root element, BT-24 and matching profile. ``specification_identifier`` and ``profile``
        are ``None`` when there is not exactly one non-empty BT-24; ``profile`` alone is ``None`` for an
        unregistered BT-24.

    Raises:
        UnsupportedDocumentError: The root element is not a UBL 2.1 Invoice / CreditNote or a CII D16B
            CrossIndustryInvoice.
    """
    try:
        syntax, root_name = _ROOTS[root.tag]
    except KeyError:
        raise UnsupportedDocumentError(
            f"unsupported root element {root.tag!r}; expected a UBL 2.1 Invoice or CreditNote, or a CII D16B "
            "CrossIndustryInvoice"
        ) from None
    values = root.findall(_UBL_BT24 if syntax == "ubl" else _CII_BT24)
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
