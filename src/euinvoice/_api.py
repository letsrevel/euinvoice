"""The top-level API: :func:`to_xml`, :func:`parse` and :func:`parse_detailed` (plan §4 "Public API", "Data flow").

Writing: ``profile.prepare(invoice)`` → ``profile.preflight(prepared, syntax)`` and
``calc.check(prepared, syntax=syntax)`` → the syntax writer. Reading:
(a Factur-X / ZUGFeRD PDF goes through :func:`euinvoice.facturx.extract` first) → :func:`euinvoice._xml.parse`
(D10) → :func:`euinvoice.detection.detect_root` → the syntax reader. This module sits above every other package;
nothing below imports it.
"""

import typing as t

from lxml import etree

from euinvoice import _xml, calc, profiles
from euinvoice.detection import detect_root, is_pdf, refuse_signed
from euinvoice.errors import PreflightError, UnsupportedDocumentError
from euinvoice.model import Invoice
from euinvoice.profiles._base import FACTURX_RULE_SET
from euinvoice.report import ValidationReport
from euinvoice.syntax import Syntax, cii, fatturapa, ubl
from euinvoice.syntax.fatturapa._write import serialize
from euinvoice.syntax.result import ParseResult
from euinvoice.validation import sdi

__all__ = ["parse", "parse_all", "parse_detailed", "to_xml"]


def to_xml(
    invoice: Invoice,
    *,
    profile: profiles.Profile | None = None,
    syntax: Syntax | t.Literal["ubl", "cii", "fatturapa"] | None = None,
    fatturapa_transmission: fatturapa.Transmission | None = None,
) -> bytes:
    """Write an invoice as UBL 2.1 or CII D16B XML under a profile, after its pre-flight and calculation checks.

    ``syntax=Syntax.FATTURAPA`` writes an FPR12 FatturaPA 1.2.3 file instead (#119), with no profile (FatturaPA has
    no BT-24) and the transmission header from ``fatturapa_transmission``. Its checks are FatturaPA's (D8 as
    amended), not the CEN ones: :func:`euinvoice.syntax.fatturapa.preflight` runs first (what the invoice lacks, what
    FPR12 cannot carry, totals against the summaries), then the document is written and the offline SdI checks of
    Allegato A 1.9.1 (:mod:`euinvoice.validation.sdi`, the ones :func:`euinvoice.validate` runs after the XSD) run on
    it. An ``error`` from either refuses the write with :class:`PreflightError`; every set business term is either
    written or reported. The XSD step needs the fetched artifacts and does not run here; run
    :func:`euinvoice.validate` on the result for it.

    The invoice is first set up for the profile with :meth:`~euinvoice.profiles.Profile.prepare` (BT-24 becomes
    the profile's, BT-23 gets its default; see there), so the written document reads back as
    ``profile.prepare(invoice)``, not as ``invoice``. Then two checks run on the prepared invoice:
    :attr:`~euinvoice.profiles.Profile.preflight` (the profile's rules) and :func:`euinvoice.calc.check` with the
    target syntax (the CEN calculation, VAT category and period rules, each ``fatal`` exactly when that syntax's
    official CEN binding rejects it; ``tests/conformance/test_calc_oracle.py``). Any ``fatal`` or ``error``
    finding refuses the write with :class:`PreflightError`, because the official rules would reject the document.
    Warnings do not block and are not returned; call ``profile.preflight(prepared, syntax)`` and
    ``calc.check(prepared, syntax=syntax)`` to see them. Both checks are early, model-level messages; the official
    Schematron stays the oracle (D8), so run :func:`euinvoice.validate` on the result for the verdict.

    Args:
        invoice: The invoice, e.g. from :func:`euinvoice.calc.complete`.
        profile: The profile to write under. ``None`` uses the profile registered for the invoice's own BT-24
            (:func:`euinvoice.profiles.get`); a Factur-X level shares its BT-24 with another profile, so pass it
            explicitly (and see :func:`euinvoice.facturx.embed` for the PDF).
        syntax: ``Syntax.UBL`` / ``"ubl"``, ``Syntax.CII`` / ``"cii"`` or ``Syntax.FATTURAPA`` / ``"fatturapa"``.
            ``None`` is allowed only when the profile supports a single syntax, which is then used (e.g.
            ``FACTURX_EN16931`` / ``FACTURX_XRECHNUNG``: CII).
        fatturapa_transmission: The FatturaPA transmission header (:class:`euinvoice.syntax.fatturapa.Transmission`),
            required with ``Syntax.FATTURAPA`` and refused with any other syntax.

    Returns:
        The serialized XML document.

    Raises:
        PreflightError: The pre-flight or calculation checks report a ``fatal`` or ``error`` finding; ``findings``
            holds every finding of both. For FatturaPA, the FatturaPA pre-flight reports an ``error`` or an SdI check
            fails on the written document (``findings`` then holds the pre-flight's and the SdI checks' findings;
            ``profile_id`` and ``syntax`` are ``"fatturapa"``).
        UnsupportedDocumentError: ``profile`` is ``None`` and no profile is registered for the invoice's BT-24;
            a profile is given with ``Syntax.FATTURAPA``;
            the profile does not support ``syntax``; or it is a Factur-X level that is not generated (MINIMUM,
            BASIC WL, BASIC, EXTENDED, plan §1), whose official Schematron is not pinned (issue #42), so nothing
            could tell whether its rules accept the document.
        ValueError: ``syntax`` is not a syntax, or is ``None`` for a profile that supports more than one;
            ``fatturapa_transmission`` is missing with ``Syntax.FATTURAPA`` or given with another syntax.
        ModelError: The invoice holds something the target syntax cannot express, e.g. a set national extension
            (``Invoice.it``, D3 as amended) in UBL or CII; see :func:`euinvoice.syntax.ubl.write`,
            :func:`euinvoice.syntax.cii.write` and :func:`euinvoice.syntax.fatturapa.write`.
    """
    if syntax is not None and Syntax(syntax) is Syntax.FATTURAPA:
        return _to_fatturapa(invoice, profile, fatturapa_transmission)
    if fatturapa_transmission is not None:
        raise ValueError("fatturapa_transmission applies only to syntax=Syntax.FATTURAPA")
    if profile is None:
        profile = profiles.get(invoice.process_control.specification_identifier)
    if FACTURX_RULE_SET in profile.rule_sets:
        raise UnsupportedDocumentError(
            f"profile {profile.id!r} is not generated (plan §1): its Factur-X / ZUGFeRD Schematron is not pinned "
            "(https://github.com/letsrevel/euinvoice/issues/42)"
        )
    target = _target_syntax(profile, syntax)
    prepared = profile.prepare(invoice)
    findings = (*profile.preflight(prepared, target), *calc.check(prepared, syntax=target))
    if not ValidationReport(findings).ok:
        raise PreflightError(profile.id, target, findings)
    return ubl.write(prepared) if target is Syntax.UBL else cii.write(prepared)


def parse(data: bytes) -> Invoice:
    """Read a UBL, CII or FatturaPA invoice, or the invoice of a Factur-X / ZUGFeRD PDF, into the semantic model.

    This is :func:`parse_detailed` without its ``unmapped`` list: input that has no business term in the model
    is **discarded** here. Use :func:`parse_detailed` to see it.

    Args:
        data: UBL 2.1 ``Invoice`` / ``CreditNote``, CII D16B ``CrossIndustryInvoice`` or FatturaPA 1.2
            ``FatturaElettronica`` XML, or a PDF with an embedded Factur-X / ZUGFeRD invoice.

    Returns:
        The invoice.

    Raises:
        TypeError: ``data`` is not ``bytes``.
        ParseError: See :func:`parse_detailed`.
        UnsupportedDocumentError: See :func:`parse_detailed`.
        PdfError: See :func:`parse_detailed`.
        ImportError: ``data`` is a PDF and the ``[pdf]`` extra (pypdf) is not installed.
    """
    return parse_detailed(data).invoice


def parse_detailed(data: bytes) -> ParseResult:
    """Read a UBL, CII or FatturaPA invoice, or the invoice of a Factur-X / ZUGFeRD PDF, and list what was not mapped.

    The syntax comes from the root element (:func:`euinvoice.detection.detect_root`); the BT-24 profile plays no part
    in reading. A PDF (``%PDF-`` header, see :func:`euinvoice.detection.is_pdf`) is read with
    :func:`euinvoice.facturx.extract`, which needs the ``[pdf]`` extra, and its embedded XML is parsed like any
    other. A FatturaPA document is read per App. 4.1 of the SdI "Regole tecniche fatture europee" v2.6, with the data
    that has no business term in ``Invoice.it`` (see :mod:`euinvoice.syntax.fatturapa`); it must hold a single
    invoice: read a lotto with :func:`parse_all`.

    Args:
        data: UBL 2.1 ``Invoice`` / ``CreditNote``, CII D16B ``CrossIndustryInvoice`` or FatturaPA 1.2
            ``FatturaElettronica`` XML, or a PDF with an embedded Factur-X / ZUGFeRD invoice.

    Returns:
        The invoice plus the XPath of every element or attribute that has no business term in the model
        (:attr:`~euinvoice.syntax.result.ParseResult.unmapped`).

    Raises:
        TypeError: ``data`` is not ``bytes``.
        ParseError: The XML is malformed, has a DOCTYPE or exceeds the parser limits (D10), or its content does not
            form a valid invoice (the message names the BT/BG id). Factur-X MINIMUM and BASIC WL documents raise it,
            as they lack terms EN 16931 requires (issue #69).
        UnsupportedDocumentError: The root element is not a UBL 2.1 Invoice / CreditNote, a CII D16B
            CrossIndustryInvoice or a FatturaPA 1.2 FatturaElettronica; a FatturaPA document holds several invoices
            (a lotto, read it with :func:`parse_all`); or ``data`` is a signed FatturaPA (``.p7m``, CAdES), which is
            not read: extract its XML first.
        PdfError: ``data`` is a PDF that does not name exactly one embedded invoice (see
            :func:`euinvoice.facturx.extract`).
        ImportError: ``data`` is a PDF and the ``[pdf]`` extra (pypdf) is not installed.
    """
    root = _root(data)
    syntax = detect_root(root).syntax
    if syntax is Syntax.FATTURAPA:
        return fatturapa.read(root)
    return ubl.read(root) if syntax is Syntax.UBL else cii.read(root)


def parse_all(data: bytes) -> tuple[ParseResult, ...]:
    """Read every invoice of a document into ``ParseResult`` s, the detailed form of :func:`parse_detailed`.

    Only a FatturaPA batch file (a lotto, #120) holds several invoices: one per ``FatturaElettronicaBody``, sharing
    the header. Each result's ``unmapped`` lists the unmapped header content and that of its own body. UBL, CII and
    Factur-X documents hold one invoice, so the result has one entry, equal to :func:`parse_detailed`'s.

    Args:
        data: As for :func:`parse_detailed`.

    Returns:
        One result per invoice, in document order.

    Raises:
        TypeError: ``data`` is not ``bytes``.
        ParseError: See :func:`parse_detailed`.
        UnsupportedDocumentError: See :func:`parse_detailed`; a lotto is read, not refused.
        PdfError: See :func:`parse_detailed`.
        ImportError: See :func:`parse_detailed`.
    """
    root = _root(data)
    syntax = detect_root(root).syntax
    if syntax is Syntax.FATTURAPA:
        return fatturapa.read_all(root)
    return (ubl.read(root) if syntax is Syntax.UBL else cii.read(root),)


def _root(data: bytes) -> etree._Element:
    """The parsed root of ``data``: the XML itself, or the XML embedded in a Factur-X / ZUGFeRD PDF."""
    if is_pdf(data):
        # Imported here so that ``import euinvoice`` and XML parsing never need pypdf (the ``[pdf]`` extra);
        # without it, importing ``euinvoice.facturx`` raises an ImportError naming the extra.
        from euinvoice import facturx

        data = facturx.extract(data).xml
    else:
        refuse_signed(data)
    return _xml.parse(data)


def _to_fatturapa(invoice: Invoice, profile: profiles.Profile | None, options: fatturapa.Transmission | None) -> bytes:
    """The FatturaPA branch of :func:`to_xml`."""
    if profile is not None:
        raise UnsupportedDocumentError(
            f"FatturaPA is written without a profile (it has no BT-24, D8 as amended); got profile {profile.id!r}"
        )
    if options is None:
        raise ValueError("writing FatturaPA needs fatturapa_transmission=euinvoice.syntax.fatturapa.Transmission(...)")
    findings = fatturapa.preflight(invoice)
    if not ValidationReport(findings).ok:
        raise PreflightError(Syntax.FATTURAPA, Syntax.FATTURAPA, findings)
    data = serialize(invoice, options)
    # The SdI checks are FatturaPA's oracle (D8 as amended), so they block the write as calc.check and the profile
    # pre-flight do for UBL/CII: e.g. 00421 (Imposta) and 00423 (PrezzoTotale) on amounts the writer copies.
    # sdi.check assumes XSD-valid input, which the writer produces by construction: a ValueError here is a writer bug,
    # not caller misuse.
    rejected = sdi.check(_xml.parse(data))
    if rejected:
        raise PreflightError(Syntax.FATTURAPA, Syntax.FATTURAPA, (*findings, *rejected))
    return data


def _target_syntax(profile: profiles.Profile, syntax: Syntax | str | None) -> Syntax:
    """The syntax to write: ``syntax`` if the profile supports it, else the profile's only one."""
    if syntax is None:
        if len(profile.syntaxes) != 1:
            raise ValueError(
                f"profile {profile.id!r} supports {', '.join(sorted(profile.syntaxes))}; pass syntax= to choose one"
            )
        (only,) = profile.syntaxes
        return only
    target = Syntax(syntax)
    if target not in profile.syntaxes:
        raise UnsupportedDocumentError(
            f"profile {profile.id!r} does not support {target.upper()}; it supports "
            f"{', '.join(sorted(profile.syntaxes))}"
        )
    return target
