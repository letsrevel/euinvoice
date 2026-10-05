"""Classify e-invoice XML: syntax and root element from the root's qualified name, profile from BT-24.

Contract (the first step of parsing and of profile auto-detection, plan §4):

* Not well-formed XML, a DOCTYPE, or input over the parser limits: ``ParseError`` from
  :func:`euinvoice._xml.parse` (D10). A PDF gets an ``UnsupportedDocumentError`` pointing to
  ``euinvoice.facturx.extract``, which takes the embedded XML out of a Factur-X / ZUGFeRD PDF.
* A root other than UBL 2.1 ``Invoice`` / ``CreditNote`` or CII D16B ``CrossIndustryInvoice``, or a
  document without exactly one BT-24: ``UnsupportedDocumentError``. Without BT-24 there is nothing to
  pick a profile by, and the official rules reject such a document anyway (BR-01, CII-SR-009/010).
* A supported root with a BT-24 that no registered profile declares (a CIUS or extension whose profile is
  not implemented yet, or a legacy id such as ``urn:ferd:CrossIndustryDocument:invoice:1p0:comfort``):
  a :class:`Detection` with ``profile=None``. The document is still a classified EN 16931 syntax
  instance; what to do without a profile is the caller's decision (``validate()`` / ``parse()``).

The profile match is exact (:func:`euinvoice.profiles.get`): a CIUS id never resolves to the core
profile. A bare core BT-24 is the core profile even when the XML came out of a Factur-X PDF, where only the
PDF container's XMP selects a Factur-X profile.
"""

import dataclasses
import typing as t

from euinvoice import _xml, profiles
from euinvoice.errors import UnsupportedDocumentError

__all__ = ["Detection", "Root", "detect"]

# ponytail: plain strings until ``euinvoice.syntax.Syntax`` (a StrEnum with these values) lands; switch the
# annotation to the enum then. StrEnum members compare equal to these strings, so callers keep working.
type Syntax = t.Literal["ubl", "cii"]

type Root = t.Literal["Invoice", "CreditNote", "CrossIndustryInvoice"]
"""The supported root elements. UBL has one per document kind; CII has one for both (BT-3 tells them apart)."""

# Root qualified name → (syntax, root). Root names per the UBL 2.1 maindoc XSDs (UBL-Invoice-2.1.xsd,
# UBL-CreditNote-2.1.xsd) and the CII D16B CrossIndustryInvoice_100pD16B.xsd.
_ROOTS: t.Final[t.Mapping[str, tuple[Syntax, Root]]] = {
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


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Detection:
    """What :func:`detect` found out about a document.

    Attributes:
        syntax: ``"ubl"`` (UBL 2.1) or ``"cii"`` (UN/CEFACT CII D16B).
        root: The root element's local name; for UBL it is the document kind (``Invoice`` or
            ``CreditNote``), CII uses ``CrossIndustryInvoice`` for both.
        specification_identifier: BT-24 as found, whitespace-normalized (``normalize-space()``, as BR-01
            and PEPPOL-EN16931-R004 read it).
        profile: The registered profile whose BT-24 matches exactly, or ``None`` when none does.
    """

    syntax: Syntax
    root: Root
    specification_identifier: str
    profile: profiles.Profile | None


def detect(data: bytes) -> Detection:
    """Classify an e-invoice XML document by its root element and specification identifier (BT-24).

    Args:
        data: The serialized XML document.

    Returns:
        The syntax, root element, BT-24 and matching profile (``None`` for an unregistered BT-24).

    Raises:
        TypeError: ``data`` is not ``bytes``.
        ParseError: The XML is malformed, has a DOCTYPE or exceeds the parser limits.
        UnsupportedDocumentError: ``data`` is a PDF, the root element is not a UBL 2.1 Invoice /
            CreditNote or a CII D16B CrossIndustryInvoice, or the document does not carry exactly one
            non-empty BT-24.

    Example:
        >>> from euinvoice import _xml
        >>> xml = (
        ...     f'<Invoice xmlns="{_xml.UBL_INVOICE}" xmlns:cbc="{_xml.UBL_CBC}">'
        ...     "<cbc:CustomizationID>urn:cen.eu:en16931:2017</cbc:CustomizationID></Invoice>"
        ... )
        >>> detect(xml.encode()).profile.id
        'en16931'
    """
    if isinstance(data, bytes) and data.startswith(_PDF_MAGIC):
        raise UnsupportedDocumentError(
            "input is a PDF; extract the embedded Factur-X / ZUGFeRD XML with euinvoice.facturx.extract first"
        )
    root = _xml.parse(data)
    try:
        syntax, root_name = _ROOTS[root.tag]
    except KeyError:
        raise UnsupportedDocumentError(
            f"unsupported root element {root.tag!r}; expected a UBL 2.1 Invoice or CreditNote, or a CII D16B "
            "CrossIndustryInvoice"
        ) from None
    values = root.findall(_UBL_BT24 if syntax == "ubl" else _CII_BT24)
    if len(values) > 1:
        # Only CII can repeat it (D16B: GuidelineSpecifiedDocumentContextParameter maxOccurs="unbounded");
        # CII-SR-009/010 (fatal, CEN 1.3.16 EN16931-CII-syntax.sch) allow exactly one parameter and ID.
        # UBL's cbc:CustomizationID has maxOccurs="1" in the maindoc XSDs, so a repeat is not UBL 2.1.
        rules = "CII-SR-009, CII-SR-010" if syntax == "cii" else "UBL 2.1 XSD"
        raise UnsupportedDocumentError(
            f"{len(values)} specification identifiers (BT-24) found, exactly one is allowed ({rules})"
        )
    # XPath normalize-space() strips only #x20, #x9, #xD, #xA; str.split() would also strip e.g. U+00A0.
    bt24 = str(values[0].xpath("normalize-space(.)")) if values else ""
    if not bt24:
        raise UnsupportedDocumentError(f"{root_name} has no specification identifier (BT-24, required by BR-01)")
    try:
        profile: profiles.Profile | None = profiles.get(bt24)
    except UnsupportedDocumentError:
        profile = None
    return Detection(syntax=syntax, root=root_name, specification_identifier=bt24, profile=profile)
