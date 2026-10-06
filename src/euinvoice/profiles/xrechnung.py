"""XRechnung 3.0 (KoSIT): the German CIUS, its Extension and its CVD variant, in UBL and CII.

XRechnung accepts three specification identifiers (BT-24): the CIUS, the Extension and the CVD (Clean
Vehicles Directive) one. They are the variables ``XR-CIUS-ID``, ``XR-EXTENSION-ID`` and ``XR-CVD-ID`` of
the pinned ``xrechnung-schematron`` 2.6.0 (``schematron/common.sch`` lines 5-9), and BR-DE-21 (warning)
accepts exactly these three. Each is its own profile, because :meth:`~euinvoice.profiles.Profile.prepare`
writes the profile's BT-24: one shared profile would silently turn an Extension or CVD claim into the
CIUS one (issue #21).

Every XRechnung scenario of the pinned KoSIT validator configuration (``scenarios.xml``, 2026-08-31) runs
the XSD, then the CEN Schematron, then the XRechnung Schematron, and never the Peppol one (issue #17).
KoSIT's ``customLevel`` severity overrides are not applied (issue #49, needs-human).

No BT-23 default: the XRechnung rule set re-asserts PEPPOL-EN16931-R001 (fatal; ``XRechnung-UBL-validation.sch``
line 198, ``XRechnung-CII-validation.sch`` lines 173-175), so BT-23 must be present, but no pinned
artifact fixes its value. All 86 instances of the pinned testsuite (2026-08-31) carry
``urn:fdc:peppol.eu:2017:poacc:billing:01:1.0``; that is usage, not a rule, so the caller sets BT-23
(needs-human #67). The pre-flight reports a missing BT-23 under PEPPOL-EN16931-R001.

BT-119 on a "Not subject to VAT" (O) breakdown: BR-DE-14 requires BT-119 on every VAT breakdown, while EN 16931
lets an O breakdown leave it out (BR-48) and ``calc.complete`` does. So :meth:`~euinvoice.profiles.Profile.prepare`
writes BT-119 = 0 there, as the official instance ``standard/01.04a-INVOICE_ubl.xml`` does (issue #75).

Pre-flight checks (each profile's :attr:`~euinvoice.profiles.Profile.preflight`) mirror fatal BR-DE-* rules
(and the re-asserted PEPPOL-EN16931-R001) of the pinned XRechnung Schematron 2.6.0
(``schematron/ubl/XRechnung-UBL-validation.sch`` and ``schematron/cii/XRechnung-CII-validation.sch``,
line numbers below as UBL / CII). A pre-flight finding is
fatal under the official id exactly when the official rule fires on the output of the writer for the given
syntax (D8; decision recorded on issue #20), so where the UBL and CII bindings differ the check follows the
binding.
Where a rule tests content (``[boolean(normalize-space(.))]``), blank text counts as missing; where it tests
only that an element exists, any value counts as present.
"""

import dataclasses
import typing as t
from collections.abc import Iterator

from euinvoice.model import Invoice, PaymentInstructions
from euinvoice.model.datatypes import normalize_space
from euinvoice.profiles._base import Profile
from euinvoice.report import Finding, Severity
from euinvoice.syntax import Syntax

__all__ = ["PREFLIGHT_SOURCE", "XRECHNUNG", "XRECHNUNG_CVD", "XRECHNUNG_EXTENSION"]

PREFLIGHT_SOURCE: t.Final = "xrechnung-preflight"
"""``source`` of the findings of the XRechnung pre-flight checks."""

_CIUS_ID: t.Final = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
_SYNTAXES: t.Final = frozenset(Syntax)
_RULE_SETS: t.Final = ("cen", "xrechnung")

# BR-DE-16 (lines 332-333 / 339): the VAT category codes that require BT-31, BT-32 or BG-11.
_BR_DE_16_CODES: t.Final = frozenset({"S", "Z", "E", "AE", "K", "G", "L", "M"})
# Payment means type codes (BT-81) of BR-DE-23 (credit transfer), BR-DE-24 (card), BR-DE-25 (direct debit):
# UBL lines 431, 441, 447 / CII lines 423, 434, 442.
_CREDIT_TRANSFER_CODES: t.Final = frozenset({"30", "58"})
_CARD_CODES: t.Final = frozenset({"48", "54", "55"})
_DIRECT_DEBIT_CODES: t.Final = frozenset({"59"})


def _blank(value: str | None) -> bool:
    return value is None or not normalize_space(value)


def _fatal(rule_id: str, location: str, message: str) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=Severity.FATAL,
        location=location,
        message=f"[{rule_id}] {message}",
        source=PREFLIGHT_SOURCE,
    )


def _seller(invoice: Invoice) -> Iterator[Finding]:
    seller = invoice.seller
    address = seller.postal_address
    # BR-DE-3, BR-DE-4: UBL lines 390-396 / CII lines 365-371.
    if _blank(address.city):
        yield _fatal("BR-DE-3", "seller.postal_address.city", 'The "Seller city" (BT-37) must be provided.')
    if _blank(address.post_code):
        yield _fatal("BR-DE-4", "seller.postal_address.post_code", 'The "Seller post code" (BT-38) must be provided.')
    # BR-DE-2: UBL line 388 / CII line 363. Both writers emit the contact element whenever BG-6 is set.
    contact = seller.contact
    if contact is None:
        yield _fatal("BR-DE-2", "seller.contact", 'The group "SELLER CONTACT" (BG-6) must be provided.')
    else:
        # BR-DE-5, BR-DE-6, BR-DE-7: UBL lines 398-407 / CII lines 373-382 (CII binds BT-41 to PersonName
        # or DepartmentName; the CII writer uses PersonName).
        if _blank(contact.contact_point):
            yield _fatal(
                "BR-DE-5", "seller.contact.contact_point", 'The "Seller contact point" (BT-41) must be provided.'
            )
        if _blank(contact.telephone):
            yield _fatal(
                "BR-DE-6", "seller.contact.telephone", 'The "Seller contact telephone number" (BT-42) must be provided.'
            )
        if _blank(contact.email):
            yield _fatal(
                "BR-DE-7", "seller.contact.email", 'The "Seller contact email address" (BT-43) must be provided.'
            )


def _buyer_and_delivery(invoice: Invoice) -> Iterator[Finding]:
    buyer = invoice.buyer
    # BR-DE-8, BR-DE-9: UBL lines 415-421 / CII lines 390-396.
    if _blank(buyer.postal_address.city):
        yield _fatal("BR-DE-8", "buyer.postal_address.city", 'The "Buyer city" (BT-52) must be provided.')
    if _blank(buyer.postal_address.post_code):
        yield _fatal("BR-DE-9", "buyer.postal_address.post_code", 'The "Buyer post code" (BT-53) must be provided.')
    # BR-DE-10, BR-DE-11: UBL lines 423-429 / CII lines 415-421, when DELIVER TO ADDRESS (BG-15) is present.
    deliver_to = invoice.delivery.deliver_to_address if invoice.delivery else None
    if deliver_to is not None:
        if _blank(deliver_to.city):
            yield _fatal(
                "BR-DE-10",
                "delivery.deliver_to_address.city",
                'The "Deliver to city" (BT-77) must be provided when "DELIVER TO ADDRESS" (BG-15) is.',
            )
        if _blank(deliver_to.post_code):
            yield _fatal(
                "BR-DE-11",
                "delivery.deliver_to_address.post_code",
                'The "Deliver to post code" (BT-78) must be provided when "DELIVER TO ADDRESS" (BG-15) is.',
            )


def _seller_tax_ids(invoice: Invoice, syntax: Syntax) -> Iterator[Finding]:
    """BR-DE-16: UBL lines 334-348 / CII lines 339-343.

    UBL takes the VAT category codes of the lines (BT-151) and of the document-level allowances and charges
    (BT-95, BT-102; the writer always follows ``cbc:ID`` with ``cac:TaxScheme/cbc:ID`` ``VAT``). The CII test
    compares the *string value* of ``ram:CategoryTradeTax`` (its TypeCode, CategoryCode and rate text
    concatenated) to ``'VAT'``. The CII writer always writes a non-empty CategoryCode there, so the comparison
    never matches and only the line codes (BT-151) count.
    """
    seller = invoice.seller
    codes = {line.vat_information.category_code for line in invoice.lines}
    if syntax == Syntax.UBL:
        codes |= {a.vat_category_code for a in invoice.allowances} | {c.vat_category_code for c in invoice.charges}
    if (
        codes & _BR_DE_16_CODES
        and _blank(seller.vat_identifier)
        and _blank(seller.tax_registration_identifier)
        and invoice.seller_tax_representative is None
    ):
        yield _fatal(
            "BR-DE-16",
            "seller",
            f"VAT category codes {sorted(codes & _BR_DE_16_CODES)} require the Seller VAT identifier (BT-31), "
            'the Seller tax registration identifier (BT-32) or the "SELLER TAX REPRESENTATIVE PARTY" (BG-11).',
        )


@dataclasses.dataclass(frozen=True, slots=True)
class _Means:
    """What the writers put into the payment means elements of one invoice, in one syntax.

    Both writers emit one payment means per credit transfer (at least one), with the card (BG-18) and the
    debited account (BT-91) in the first only. UBL puts BT-89 and BT-91 in ``cac:PaymentMandate`` (written
    when either is set, in the first means) and BT-90 in a ``SEPA`` party identifier; CII puts BT-89 and BT-90
    at header level and has no BG-19 element: any of BT-89, BT-90, BT-91 counts as BG-19 (CII comment, lines
    315-317). The rules test element existence, so a blank value counts as present.
    """

    code: str
    transfers: bool
    card: bool
    several: bool  # more than one means: the later ones carry neither card nor BT-91 (nor, in UBL, BT-89)
    debit_in_first: bool  # the first means carries BG-19, as the rule sees it
    debit_in_every: bool  # every means carries BG-19, as the rule sees it


def _means(payment: PaymentInstructions, invoice: Invoice, syntax: Syntax) -> _Means:
    bt89, bt90, bt91 = _debit_terms(invoice)
    several = len(payment.credit_transfers) > 1
    if syntax == Syntax.UBL:
        debit_in_first = bt89 or bt91  # cac:PaymentMandate
        debit_in_every = debit_in_first and not several
    else:
        debit_in_first = bt89 or bt90 or bt91
        debit_in_every = bt89 or bt90 or (bt91 and not several)
    return _Means(
        code=payment.payment_means_type_code,
        transfers=bool(payment.credit_transfers),
        card=payment.payment_card is not None,
        several=several,
        debit_in_first=debit_in_first,
        debit_in_every=debit_in_every,
    )


def _payment(invoice: Invoice, syntax: Syntax) -> Iterator[Finding]:
    """BR-DE-1, then BR-DE-23, BR-DE-24 or BR-DE-25 by payment means type code (BT-81), per binding."""
    payment = invoice.payment_instructions
    # BR-DE-1: UBL line 328 / CII lines 333-335.
    if payment is None:
        yield _fatal("BR-DE-1", "payment_instructions", 'An invoice must contain "PAYMENT INSTRUCTIONS" (BG-16).')
        return
    means = _means(payment, invoice, syntax)
    if means.code in _CREDIT_TRANSFER_CODES:
        yield from _credit_transfer(means)
    elif means.code in _CARD_CODES:
        yield from _card(means)
    elif means.code in _DIRECT_DEBIT_CODES:
        yield from _direct_debit_means(means)


def _credit_transfer(means: _Means) -> Iterator[Finding]:
    # BR-DE-23-a / -b: UBL lines 431-439 / CII lines 423-432.
    if not means.transfers:
        yield _fatal(
            "BR-DE-23-a",
            "payment_instructions.credit_transfers",
            f'BT-81 {means.code} requires "CREDIT TRANSFER" (BG-17).',
        )
    if means.card or means.debit_in_first:
        yield _fatal(
            "BR-DE-23-b",
            "payment_instructions",
            f'BT-81 {means.code} excludes "PAYMENT CARD INFORMATION" (BG-18) and "DIRECT DEBIT" (BG-19).',
        )


def _card(means: _Means) -> Iterator[Finding]:
    # BR-DE-24-a / -b: UBL lines 441-445 / CII lines 434-440.
    if not means.card or means.several:
        yield _fatal(
            "BR-DE-24-a",
            "payment_instructions.payment_card",
            f'BT-81 {means.code} requires "PAYMENT CARD INFORMATION" (BG-18) in its one payment means.',
        )
    if means.transfers or means.debit_in_first:
        yield _fatal(
            "BR-DE-24-b",
            "payment_instructions",
            f'BT-81 {means.code} excludes "CREDIT TRANSFER" (BG-17) and "DIRECT DEBIT" (BG-19).',
        )


def _direct_debit_means(means: _Means) -> Iterator[Finding]:
    # BR-DE-25-a / -b: UBL lines 447-454 / CII lines 442-451.
    if not means.debit_in_every:
        yield _fatal(
            "BR-DE-25-a",
            "payment_instructions.direct_debit",
            f'BT-81 {means.code} requires "DIRECT DEBIT" (BG-19) in its one payment means.',
        )
    if means.transfers or means.card:
        yield _fatal(
            "BR-DE-25-b",
            "payment_instructions",
            f'BT-81 {means.code} excludes "CREDIT TRANSFER" (BG-17) and "PAYMENT CARD INFORMATION" (BG-18).',
        )


def _debit_terms(invoice: Invoice) -> tuple[bool, bool, bool]:
    """Whether BT-89, BT-90 and BT-91 are present (the direct debit rules test element existence)."""
    payment = invoice.payment_instructions
    debit = payment.direct_debit if payment else None
    if debit is None:
        return False, False, False
    return (
        debit.mandate_reference_identifier is not None,
        debit.bank_assigned_creditor_identifier is not None,
        debit.debited_account_identifier is not None,
    )


def _direct_debit(invoice: Invoice, syntax: Syntax) -> Iterator[Finding]:
    """BR-DE-30 / BR-DE-31, per binding.

    UBL lines 366-371: a ``cac:PaymentMandate`` (written when BT-89 or BT-91 is set) needs the SEPA creditor
    id BT-90 and ``cac:PayerFinancialAccount`` BT-91. CII lines 315-331: with any of BT-89/90/91, BR-DE-30
    requires (BT-89 or BT-91) and BT-90, BR-DE-31 requires (BT-89 or BT-90) and BT-91.
    """
    bt89, bt90, bt91 = _debit_terms(invoice)
    if syntax == Syntax.UBL:
        missing_bt90 = (bt89 or bt91) and not bt90
        missing_bt91 = bt89 and not bt91
    else:
        missing_bt90 = (bt89 or bt90 or bt91) and not ((bt89 or bt91) and bt90)
        missing_bt91 = (bt89 or bt90 or bt91) and not ((bt89 or bt90) and bt91)
    if missing_bt90:
        yield _fatal(
            "BR-DE-30",
            "payment_instructions.direct_debit.bank_assigned_creditor_identifier",
            'With "DIRECT DEBIT" (BG-19) the "Bank assigned creditor identifier" (BT-90) must be provided.',
        )
    if missing_bt91:
        yield _fatal(
            "BR-DE-31",
            "payment_instructions.direct_debit.debited_account_identifier",
            'With "DIRECT DEBIT" (BG-19) the "Debited account identifier" (BT-91) must be provided.',
        )


def _document(invoice: Invoice) -> Iterator[Finding]:
    # PEPPOL-EN16931-R001, re-asserted by XRechnung (fatal): UBL line 198 tests cbc:ProfileID, CII lines
    # 173-175 test ram:BusinessProcessSpecifiedDocumentContextParameter/ram:ID; both only for existence.
    if invoice.process_control.business_process_type is None:
        yield _fatal(
            "PEPPOL-EN16931-R001",
            "process_control.business_process_type",
            "Business process (BT-23) must be provided; the XRechnung profiles set no default (#67).",
        )
    # BR-DE-15: UBL lines 329-331 / CII lines 336-338.
    if _blank(invoice.buyer_reference):
        yield _fatal("BR-DE-15", "buyer_reference", 'The "Buyer reference" (BT-10) must be provided.')
    # BR-DE-14: UBL lines 456-459 / CII lines 453-456.
    for index, breakdown in enumerate(invoice.vat_breakdown):
        if breakdown.rate is None:
            yield _fatal(
                "BR-DE-14", f"vat_breakdown[{index}].rate", 'The "VAT category rate" (BT-119) must be provided.'
            )
    # BR-DE-22: UBL lines 360-362 / CII lines 350-352: attachment filenames (BT-125) must be unique.
    seen: set[str] = set()
    for index, document in enumerate(invoice.additional_supporting_documents):
        filename = document.attached_document.filename if document.attached_document else None
        if filename is None:
            continue
        if filename in seen:
            yield _fatal(
                "BR-DE-22",
                f"additional_supporting_documents[{index}].attached_document.filename",
                f"The filename {filename!r} of an attached document (BT-125) must be unique.",
            )
        seen.add(filename)


_CIUS_RULES: t.Final[frozenset[str]] = frozenset(
    {
        "BR-DE-1", "BR-DE-2", "BR-DE-3", "BR-DE-4", "BR-DE-5", "BR-DE-6", "BR-DE-7", "BR-DE-8", "BR-DE-9",
        "BR-DE-10", "BR-DE-11", "BR-DE-14", "BR-DE-15", "BR-DE-16", "BR-DE-22", "BR-DE-23-a", "BR-DE-23-b",
        "BR-DE-24-a", "BR-DE-24-b", "BR-DE-25-a", "BR-DE-25-b", "BR-DE-30", "BR-DE-31", "PEPPOL-EN16931-R001",
    }
)  # fmt: skip
_CVD_RULES: t.Final[frozenset[str]] = frozenset({"BR-DE-CVD-01", "BR-DE-CVD-02", "BR-DE-CVD-03"})
_RULES: t.Final[frozenset[str]] = _CIUS_RULES | _CVD_RULES
"""Every official rule id an XRechnung pre-flight check can report (the CVD ones only under the CVD profile)."""


def _preflight(invoice: Invoice, syntax: Syntax) -> tuple[Finding, ...]:
    """Pre-flight of the XRechnung CIUS and Extension profiles (the BR-DE rules apply to both).

    Call contract: run it on the result of :meth:`~euinvoice.profiles.Profile.prepare`; ``to_xml`` (#27)
    calls it before writing; :func:`euinvoice.validate.validate` never does (the Schematron is the oracle
    there, D8). ``syntax`` selects the binding where the UBL and CII rules differ (BR-DE-16, the
    payment rules), so each finding matches what the official rule reports on that writer's output.

    Args:
        invoice: The prepared invoice.
        syntax: The syntax it will be written in.

    Returns:
        One ``fatal`` finding per violated rule occurrence, with source :data:`PREFLIGHT_SOURCE`.

    Raises:
        ValueError: ``syntax`` is not UBL or CII.
    """
    if syntax not in (Syntax.UBL, Syntax.CII):
        raise ValueError(f"unknown syntax {syntax!r} for XRechnung; expected 'ubl' or 'cii'")
    # ponytail: fatal rules of the XRechnung rule set that are not pre-flighted, left to the Schematron:
    # BR-DE-18 (Skonto lines in BT-20) and BR-TMP-2 (BT-124 URL), which are regex-based; BR-TMP-3 (CII gross
    # and net base quantity), which the CII writer satisfies by construction; the Extension rules BR-DEX-*;
    # and the re-asserted PEPPOL-EN16931-R* rules other than R001 (R005, R008, R010, R020, R040-R046, R053-R055,
    # R061, R101, R110, R111, R121, R130). Add a check here when an early message for one of them is wanted.
    return (
        *_document(invoice),
        *_seller(invoice),
        *_buyer_and_delivery(invoice),
        *_seller_tax_ids(invoice, syntax),
        *_payment(invoice, syntax),
        *_direct_debit(invoice, syntax),
    )


def _cvd_preflight(invoice: Invoice, syntax: Syntax) -> tuple[Finding, ...]:
    """:func:`_preflight` plus BR-DE-CVD-01..03 (UBL lines 549-565 / CII lines 522-526, 560-569).

    Same call contract, arguments and result as :func:`_preflight`.

    Raises:
        ValueError: ``syntax`` is not UBL or CII.
    """
    # ponytail: BR-DE-CVD-04/05/06 and BR-TMP-CVD-01 (per-line code checks) are left to the Schematron.
    # XRECHNUNG_CVD cannot be satisfied yet: BR-DE-CVD-03 needs item classification list id 'CVD', which the
    # model rejects under CEN BR-CL-13 (KoSIT downgrades BR-CL-13 in its CVD scenarios; #49).
    findings = list(_preflight(invoice, syntax))
    if _blank(invoice.contract_reference):
        findings.append(
            _fatal("BR-DE-CVD-01", "contract_reference", 'The "Contract reference" (BT-12) must be provided.')
        )
    if _blank(invoice.tender_or_lot_reference):
        findings.append(
            _fatal("BR-DE-CVD-02", "tender_or_lot_reference", 'The "Tender or lot reference" (BT-17) must be provided.')
        )
    # Both bindings compare the classification list id to 'CVD' and the attribute name to 'cva' exactly.
    if not any(
        any(c.scheme_id == "CVD" for c in line.item.classification_identifiers)
        and any(a.name == "cva" for a in line.item.attributes)
        for line in invoice.lines
    ):
        findings.append(
            _fatal(
                "BR-DE-CVD-03",
                "lines",
                "At least one INVOICE LINE (BG-25) needs an item classification identifier (BT-158) with scheme "
                "identifier 'CVD' and an item attribute name (BT-160) 'cva'.",
            )
        )
    return tuple(findings)


def _always(invoice: Invoice) -> bool:
    """BR-DE-14 (UBL lines 456-459 / CII lines 453-456) requires BT-119 on every VAT breakdown (issue #75)."""
    return True


XRECHNUNG: t.Final = Profile(
    id="xrechnung",
    title="XRechnung 3.0 (CIUS)",
    specification_identifier=_CIUS_ID,  # XR-CIUS-ID, common.sch line 7
    syntaxes=_SYNTAXES,
    rule_sets=_RULE_SETS,
    preflight=_preflight,
    vat_breakdown_rate_required=_always,
)
"""XRechnung 3.0 CIUS, BT-24 ``urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0``."""

XRECHNUNG_EXTENSION: t.Final = Profile(
    id="xrechnung-extension",
    title="XRechnung 3.0 Extension",
    # XR-EXTENSION-ID, common.sch line 8.
    specification_identifier=f"{_CIUS_ID}#conformant#urn:xeinkauf.de:kosit:extension:xrechnung_3.0",
    syntaxes=_SYNTAXES,
    rule_sets=_RULE_SETS,
    preflight=_preflight,
    vat_breakdown_rate_required=_always,
)
"""XRechnung 3.0 Extension (adds sub invoice lines, third party payments and more; BR-DEX-* rules)."""

XRECHNUNG_CVD: t.Final = Profile(
    id="xrechnung-cvd",
    title="XRechnung 3.0 CVD (Clean Vehicles Directive)",
    # XR-CVD-ID, common.sch line 9 (CVD-MAJOR-MINOR-VERSION '0.9', line 6).
    specification_identifier=f"{_CIUS_ID}#compliant#urn:xeinkauf.de:kosit:xrechnung:cvd_0.9",
    syntaxes=_SYNTAXES,
    rule_sets=_RULE_SETS,
    preflight=_cvd_preflight,
    vat_breakdown_rate_required=_always,
)
"""XRechnung 3.0 CVD, for invoices under the Clean Vehicles Directive (BR-DE-CVD-* rules)."""
