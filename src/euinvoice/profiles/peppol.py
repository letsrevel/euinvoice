r"""Peppol BIS Billing 3.0: the OpenPeppol CIUS of EN 16931, in UBL and (optionally) CII.

Identifiers (Peppol BIS Billing 3.0.21, docs.peppol.eu/poacc/billing/3.0/bis/ §13.2 "Profile 01 -
Billing"): BT-24 ``urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0``, BT-23
``urn:fdc:peppol.eu:2017:poacc:billing:01:1.0``. The pinned rules agree: PEPPOL-EN16931-R004 requires
BT-24 to start with that value, and R007's ``$profile`` maps that BT-23 to profile ``01``. Syntaxes: UBL
2.1 is mandatory; Appendix B "Cross Industry Invoice" of the same document allows CII D16B ("receivers of
invoices can register in the SMP to receive CII invoices alongside the mandatory UBL version"), validated
against the Peppol rules like UBL, with the same BT-23 and BT-24, so the profile declares both.

Pre-flight (``PEPPOL.preflight``, D5, D8): the ``fatal`` PEPPOL-EN16931-R\* rules of the pinned
``rules/sch/PEPPOL-EN16931-UBL.sch`` / ``PEPPOL-EN16931-CII.sch`` (peppol-bis 3.0.21) that the model can
answer and that neither the model nor the CEN rules already enforce. Findings carry the official rule id,
severity ``fatal`` (every rule below is ``flag="fatal"`` in both files) and source
:data:`PREFLIGHT_SOURCE`; their location is a model path. Each rule follows the XPath of the target
syntax's binding, through what the writers in :mod:`euinvoice.syntax` emit, so the pre-flight never
reports a ``fatal`` official id that the Schematron would not raise for the written document (line
numbers: UBL / CII):

* R001 (265 / 207): BT-23 present. R007 (266 / 208): BT-23, whitespace-normalized, is an approved
  process. UBL's ``$profile`` (lines 18-29) approves billing ``01:1.0``, ``urn:peppol:france:billing:
  regulated``, ``urn:peppol:france:billing:non-regulated`` and ``urn:peppol:bis:billing_with_response``;
  CII's (lines 16-23) only ``01:1.0`` and ``billing_with_response``. A missing BT-23 fails both.
* R002 (267 / 229). UBL: at most one ``cbc:Note``, unless seller and buyer postal country (BT-40, BT-55)
  are both ``DE``. CII: at most one ``ram:IncludedNote`` and none with a ``ram:SubjectCode`` (BT-21), no
  exception. Only notes the writer emits count (the UBL writer drops a note with neither BT-21 nor BT-22
  text, the CII writer one with neither set).
* R003 (268 / 213): UBL ``cbc:BuyerReference or cac:OrderReference/cbc:ID``, CII ``ram:BuyerReference or
  ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID``. The UBL writer fills ``cac:OrderReference/
  cbc:ID`` with ``NA`` when only BT-14 is set (Peppol's guidance for that element), so in UBL a model with
  BT-14 but neither BT-10 nor BT-13 passes R003 and gets the ``warning``
  :data:`R003_NA_WARNING` instead (no purchase order reference is really given, and the same model
  fails R003 in CII). Without BT-10, BT-13 and BT-14, R003 is ``fatal`` in both.
* R004 (269 / 209): BT-24, whitespace-normalized, starts with :data:`SPECIFICATION_IDENTIFIER` and has no
  ``::``.
* R005 (275 / 218): BT-6, when given, differs from BT-5.
* R008 (241, UBL only; the CII file has no R008): no element without child elements and with only
  whitespace text (``//*[not(*) and not(normalize-space())]``). Blank model text can end up in many
  elements, so this rule is checked on the UBL writer's output; its locations are XPaths, not model paths.
* R010 (279 / 232): BT-49 present. R020 (283 / 235): BT-34 present.
* R041 (287 / 238), R042 (290 / 242): a document or line level allowance or charge with a percentage
  needs a base amount, and one with a base amount needs a percentage.
* R061 (304 / 259): payment means code (BT-81) ``49`` or ``59`` needs the mandate reference BT-89. UBL
  tests it per ``cac:PaymentMeans``; the writer repeats that element per credit transfer (BG-17) and puts
  the mandate in the first only (CEN UBL-SR-55 allows one), so in UBL more than one credit transfer
  fails R061 too.
* R110 (312 / 262), R111 (315 / 265): a line period start (BT-134) is not before the invoicing period
  start (BT-73), a line period end (BT-135) not after its end (BT-74), when both are given.
* R121 (356 / 303): the item price base quantity (BT-149), when given, is above zero.

Not pre-flighted: rules the writers satisfy by construction (R006, R043, R044, R051, R053, R080, R100,
R101) or that CEN rules already report (R054/R055 with BR-53 and BR-CO-15), R040, R046 and R120 (decimal
arithmetic with a slack; ``calc`` and the Schematron own them), R130, and the ``P``, ``CL``, ``F``,
``COMMON`` and national rules. The Schematron run by ``validate()`` reports them all.

``prepare()`` defaults: BT-24, the BT-23 above, and BT-119 = 0 on a "Not subject to VAT" (O) breakdown when
seller and buyer are both in Germany, where DE-R-014 requires BT-119 (see ``_german_parties``; issue #75).
"""

import typing as t
from collections.abc import Iterator

from lxml import etree

from euinvoice import _xml
from euinvoice.model import Invoice
from euinvoice.model.allowances import (
    DocumentLevelAllowance,
    DocumentLevelCharge,
    InvoiceLineAllowance,
    InvoiceLineCharge,
)
from euinvoice.model.datatypes import normalize_space
from euinvoice.profiles._base import Profile
from euinvoice.report import Finding, Severity
from euinvoice.syntax import Syntax, ubl

__all__ = ["BILLING_PROCESS", "PEPPOL", "PREFLIGHT_SOURCE", "R003_NA_WARNING", "SPECIFICATION_IDENTIFIER"]

SPECIFICATION_IDENTIFIER: t.Final = "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
"""BT-24 of Peppol BIS Billing 3.0 (PEPPOL-EN16931-R004)."""
BILLING_PROCESS: t.Final = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
"""BT-23 of profile 01 "Billing", the default written by :meth:`Profile.prepare` (PEPPOL-EN16931-R007)."""
PREFLIGHT_SOURCE: t.Final = "peppol-preflight"
"""``source`` of the pre-flight findings."""
R003_NA_WARNING: t.Final = "EUINV-PEPPOL-R003-NA"
"""Rule id of the ``warning`` for a UBL invoice whose only order reference is BT-14 (see R003 above)."""

_BILLING_WITH_RESPONSE: t.Final = "urn:peppol:bis:billing_with_response"
# The values each binding's ``$profile`` variable maps to '01' or '02' (see the module docstring).
_APPROVED_PROCESSES: t.Final[t.Mapping[Syntax, frozenset[str]]] = {
    Syntax.UBL: frozenset(
        {
            BILLING_PROCESS,
            "urn:peppol:france:billing:regulated",
            "urn:peppol:france:billing:non-regulated",
            _BILLING_WITH_RESPONSE,
        }
    ),
    Syntax.CII: frozenset({BILLING_PROCESS, _BILLING_WITH_RESPONSE}),
}
_DIRECT_DEBIT: t.Final = frozenset({"49", "59"})
_RULES: t.Final[frozenset[str]] = frozenset(
    f"PEPPOL-EN16931-{rule}"
    for rule in (
        *("R001", "R002", "R003", "R004", "R005", "R007", "R008", "R010"),
        *("R020", "R041", "R042", "R061", "R110", "R111", "R121"),
    )
)
"""The official rule ids the pre-flight covers (the module docstring lists how each is checked)."""

type _AllowanceOrCharge = DocumentLevelAllowance | DocumentLevelCharge | InvoiceLineAllowance | InvoiceLineCharge


def _preflight(invoice: Invoice, syntax: Syntax) -> tuple[Finding, ...]:
    """Check ``invoice`` against the Peppol BIS rules listed in the module docstring.

    Run it on the invoice that will be written, i.e. after :meth:`Profile.prepare`, which sets BT-24 and
    the BT-23 default. An empty result does not mean the invoice is valid: ``validate()`` with the
    official Schematron decides (D8).

    Args:
        invoice: The invoice to check.
        syntax: ``Syntax.UBL`` or ``Syntax.CII``; rules are evaluated as that binding tests them.

    Returns:
        One ``fatal`` finding per violated rule occurrence, plus the :data:`R003_NA_WARNING` ``warning``,
        with source :data:`PREFLIGHT_SOURCE`.

    Raises:
        ValueError: ``syntax`` is not ``Syntax.UBL`` or ``Syntax.CII``.
        ModelError: ``syntax`` is ``Syntax.UBL`` and the UBL writer cannot express the invoice (R008 is checked
            on its output).
    """
    if syntax not in _APPROVED_PROCESSES:
        raise ValueError(f"unknown syntax {syntax!r} for Peppol BIS; expected 'ubl' or 'cii'")
    findings = [
        *_process_control(invoice, syntax),
        *_notes(invoice, syntax),
        *_references(invoice, syntax),
        *_parties(invoice),
        *_allowances_and_charges(invoice),
        *_payment(invoice, syntax),
        *_lines(invoice),
    ]
    if syntax == Syntax.UBL:
        findings.extend(_empty_elements(invoice))
    return tuple(findings)


def _fatal(rule: str, location: str, text: str, hint: str) -> Finding:
    """A finding with the official rule text (``[id]-text``) and a hint naming the model terms."""
    return Finding(
        rule_id=f"PEPPOL-EN16931-{rule}",
        severity=Severity.FATAL,
        location=location,
        message=f"[PEPPOL-EN16931-{rule}]-{text}{' ' if text.endswith('.') else '. '}{hint}",
        source=PREFLIGHT_SOURCE,
    )


def _process_control(invoice: Invoice, syntax: Syntax) -> Iterator[Finding]:
    bt23 = invoice.process_control.business_process_type
    location = "process_control.business_process_type"
    if bt23 is None:
        yield _fatal("R001", location, "Business process MUST be provided.", f"Set BT-23, e.g. to {BILLING_PROCESS!r}.")
    if bt23 is None or normalize_space(bt23) not in _APPROVED_PROCESSES[syntax]:
        approved = ", ".join(sorted(_APPROVED_PROCESSES[syntax]))
        yield _fatal(
            "R007",
            location,
            "Business process MUST have an approved identifier.",
            f"BT-23 is {bt23!r}; approved in {syntax.upper()}: {approved}.",
        )
    bt24 = normalize_space(invoice.process_control.specification_identifier)
    if not bt24.startswith(SPECIFICATION_IDENTIFIER) or "::" in bt24:
        yield _fatal(
            "R004",
            "process_control.specification_identifier",
            f"Specification identifier MUST begin with the value '{SPECIFICATION_IDENTIFIER}' and follow the "
            "format rules for the identifier.",
            f"BT-24 is {bt24!r}; PEPPOL.prepare() sets it.",
        )


def _notes(invoice: Invoice, syntax: Syntax) -> Iterator[Finding]:
    text = "No more than one note is allowed on document level"
    if syntax == Syntax.UBL:
        written = [n for n in invoice.notes if n.subject_code is not None or n.note]
        german = invoice.seller.postal_address.country_code == "DE" == invoice.buyer.postal_address.country_code
        if len(written) > 1 and not german:
            yield _fatal(
                "R002",
                "notes",
                f"{text}, unless both the buyer and seller are German organizations.",
                f"The invoice has {len(written)} notes (BG-1); seller (BT-40) and buyer (BT-55) are not both DE.",
            )
        return
    written = [n for n in invoice.notes if n.subject_code is not None or n.note is not None]
    if len(written) > 1 or any(n.subject_code is not None for n in written):
        yield _fatal(
            "R002",
            "notes",
            f"{text}.",
            f"The invoice has {len(written)} notes (BG-1); in CII at most one is allowed and it may not carry "
            "a subject code (BT-21).",
        )


def _references(invoice: Invoice, syntax: Syntax) -> Iterator[Finding]:
    no_order = invoice.buyer_reference is None and invoice.purchase_order_reference is None
    if no_order and syntax == Syntax.UBL and invoice.sales_order_reference is not None:
        # The UBL writer's cac:OrderReference/cbc:ID "NA" passes R003 officially: never a fatal R003 here (D8).
        yield Finding(
            rule_id=R003_NA_WARNING,
            severity=Severity.WARNING,
            location="purchase_order_reference",
            message=(
                "PEPPOL-EN16931-R003 (a buyer reference or purchase order reference MUST be provided) passes in "
                "UBL only because cac:OrderReference/cbc:ID is written as 'NA', the value Peppol prescribes when "
                "a sales order reference (BT-14) is given without a purchase order reference (BT-13). No buyer "
                "reference (BT-10) or purchase order reference is given, and the same invoice fails R003 in CII. "
                "Set BT-10 or BT-13."
            ),
            source=PREFLIGHT_SOURCE,
        )
    elif no_order:
        yield _fatal(
            "R003",
            "buyer_reference",
            "A buyer reference or purchase order reference MUST be provided.",
            "Set buyer_reference (BT-10) or purchase_order_reference (BT-13); a sales order reference (BT-14) "
            "does not count.",
        )
    bt6 = invoice.vat_accounting_currency_code
    if bt6 is not None and bt6 == invoice.currency_code:
        yield _fatal(
            "R005",
            "vat_accounting_currency_code",
            "VAT accounting currency code MUST be different from invoice currency code when provided.",
            f"BT-6 and BT-5 are both {bt6!r}; leave BT-6 out.",
        )


def _parties(invoice: Invoice) -> Iterator[Finding]:
    if invoice.buyer.electronic_address is None:
        yield _fatal("R010", "buyer.electronic_address", "Buyer electronic address MUST be provided", "Set BT-49.")
    if invoice.seller.electronic_address is None:
        yield _fatal("R020", "seller.electronic_address", "Seller electronic address MUST be provided", "Set BT-34.")


def _allowances_and_charges(invoice: Invoice) -> Iterator[Finding]:
    entries: list[tuple[str, _AllowanceOrCharge]] = [
        *((f"allowances[{i}]", a) for i, a in enumerate(invoice.allowances)),
        *((f"charges[{i}]", c) for i, c in enumerate(invoice.charges)),
    ]
    for n, line in enumerate(invoice.lines):
        entries.extend((f"lines[{n}].allowances[{i}]", a) for i, a in enumerate(line.allowances))
        entries.extend((f"lines[{n}].charges[{i}]", c) for i, c in enumerate(line.charges))
    for location, entry in entries:
        if entry.percentage is not None and entry.base_amount is None:
            yield _fatal(
                "R041",
                location,
                "Allowance/charge base amount MUST be provided when allowance/charge percentage is provided.",
                "Set its base_amount.",
            )
        if entry.percentage is None and entry.base_amount is not None:
            yield _fatal(
                "R042",
                location,
                "Allowance/charge percentage MUST be provided when allowance/charge base amount is provided.",
                "Set its percentage.",
            )


def _payment(invoice: Invoice, syntax: Syntax) -> Iterator[Finding]:
    payment = invoice.payment_instructions
    if payment is None or payment.payment_means_type_code not in _DIRECT_DEBIT:
        return
    debit = payment.direct_debit
    text = "Mandate reference MUST be provided for direct debit."
    if debit is None or debit.mandate_reference_identifier is None:
        hint = f"Payment means code (BT-81) is {payment.payment_means_type_code}; set BT-89."
        yield _fatal("R061", "payment_instructions.direct_debit.mandate_reference_identifier", text, hint)
    elif syntax == Syntax.UBL and len(payment.credit_transfers) > 1:
        hint = (
            "UBL writes one cac:PaymentMeans per credit transfer (BG-17) and the mandate (BT-89) in the first "
            "only (UBL-SR-55); give a direct debit at most one credit transfer."
        )
        yield _fatal("R061", "payment_instructions.credit_transfers", text, hint)


def _lines(invoice: Invoice) -> Iterator[Finding]:
    delivery = invoice.delivery
    period = None if delivery is None else delivery.invoicing_period
    for n, line in enumerate(invoice.lines):
        own = line.period
        if period is not None and own is not None:
            if period.start_date is not None and own.start_date is not None and own.start_date < period.start_date:
                yield _fatal(
                    "R110",
                    f"lines[{n}].period.start_date",
                    "Start date of line period MUST be within invoice period.",
                    f"BT-134 {own.start_date} is before BT-73 {period.start_date}.",
                )
            if period.end_date is not None and own.end_date is not None and own.end_date > period.end_date:
                yield _fatal(
                    "R111",
                    f"lines[{n}].period.end_date",
                    "End date of line period MUST be within invoice period.",
                    f"BT-135 {own.end_date} is after BT-74 {period.end_date}.",
                )
        base = line.price_details.base_quantity
        if base is not None and base <= 0:
            yield _fatal(
                "R121",
                f"lines[{n}].price_details.base_quantity",
                "Base quantity MUST be a positive number above zero.",
                f"BT-149 is {format(base, 'f')}.",
            )


def _empty_elements(invoice: Invoice) -> Iterator[Finding]:
    # ponytail: R008 costs a second UBL serialization (and parse) of the invoice, on top of the one the
    # caller writes. Upgrade path: to_xml (#27) hands the pre-flight the bytes it already wrote.
    root = _xml.parse(ubl.write(invoice))
    tree = root.getroottree()
    for element in root.iter(etree.Element):
        if len(element) == 0 and not normalize_space(element.text or ""):
            yield _fatal(
                "R008",
                tree.getpath(element),
                "Document MUST not contain empty elements.",
                "A blank text value in the invoice is written as this empty element; leave the term out instead.",
            )


def _german_parties(invoice: Invoice) -> bool:
    """Whether DE-R-014 applies: seller and buyer postal country (BT-40, BT-55) are both ``DE``.

    DE-R-014 (``PEPPOL-EN16931-UBL.sch`` lines 799-800, fatal) requires BT-119 on every VAT breakdown under
    ``$supplierCountryIsDE and $customerCountryIsDE`` (lines 50-51). The CII file has no DE-R rules; BT-119 = 0
    on an O breakdown passes the CEN and Peppol rules in both syntaxes, so :meth:`Profile.prepare` (which has no
    syntax) writes it for either (issue #75).
    """
    return invoice.seller.postal_address.country_code == "DE" and invoice.buyer.postal_address.country_code == "DE"


PEPPOL: t.Final = Profile(
    id="peppol",
    title="Peppol BIS Billing 3.0",
    specification_identifier=SPECIFICATION_IDENTIFIER,
    syntaxes=frozenset(Syntax),
    # XSD, then CEN, then Peppol (rule sets per profile verified on issue #17).
    rule_sets=("cen", "peppol"),
    business_process_type=BILLING_PROCESS,
    preflight=_preflight,
    vat_breakdown_rate_required=_german_parties,
)
"""The Peppol BIS Billing 3.0 profile (profile 01 "Billing" by default)."""
