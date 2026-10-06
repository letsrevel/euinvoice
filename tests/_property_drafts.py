"""Hypothesis strategies of valid-by-construction invoice drafts, completed with ``calc.complete`` (issue #31).

Unlike :mod:`_strategies` (structurally valid models whose amounts are random), every invoice drawn here is
meant to pass the official rules of its :class:`Target`: the VAT categories, rates and exemption reasons
follow the CEN category rules, and the parties carry what the categories and the target profile require.
:func:`invoices` draws a draft, completes it with :func:`euinvoice.calc.complete` and returns the invoice.

Each requirement encoded here, with its source (CEN ``validation-1.3.16`` ``EN16931-model.sch`` and
``EN16931-UBL-codes.sch``; Peppol BIS ``3.0.21`` ``PEPPOL-EN16931-UBL.sch``; XRechnung Schematron ``2.6.0``):

* VAT categories S, Z, E, AE, K, G, O with the rates of BR-<x>-05/06/07 (S above zero; Z, E, AE, K, G zero;
  O none). O stands alone (BR-O-11 … 14). E, AE, K, G and O get a VATEX exemption reason code from BR-CL-22
  (``VATEX-EU-132``, ``-AE``, ``-IC``, ``-G``, ``-O``), S and Z none (BR-<x>-10).
* A seller VAT identifier BT-31 unless the category is O (BR-S/Z/E/AE/IC/G-02 require it, BR-O-02 forbids
  it); a buyer VAT identifier BT-48 with AE or K (BR-AE-02/03/04, BR-IC-02/03/04), none with O
  (BR-O-02/03/04). VAT ids carry their country prefix (BR-CO-09). Without BT-31 the seller has a seller
  identifier BT-29 (BR-CO-26).
* K: an actual delivery date BT-72 (BR-IC-11) and a deliver-to country code BT-80 (BR-IC-12).
* BT-20 always present, so EN 16931-1 BR-CO-25 (BT-9 or BT-20 when the amount due is positive) holds whatever
  the amount due; BR-CO-25 is not implemented in the pinned CEN 1.3.16 Schematron. BT-9 is optional, and
  absent from a credit note without BG-16: UBL has no place for it there (the UBL writer raises,
  ``ubl/_write.py``).
* Allowances and charges carry a reason or a reason code (BR-33, BR-38, BR-42, BR-44); codes ``95``
  (UNCL 5189, BR-CL-19) and ``FC`` / ``ABL`` (UNCL 7161, BR-CL-20). A drawn base amount and percentage give
  the amount as base * percentage / 100, rounded half up (PEPPOL-EN16931-R040 allows a 0.02 slack).
* Price details: the gross price BT-148 only with its discount BT-147 and BT-146 = BT-148 - BT-147
  (PEPPOL-EN16931-R046); a base quantity BT-149 above zero (R121) with the line's unit code (R130). Both
  writers then emit the model as is, with no normalization (``docs/reference/bt-mapping.md``).
* Line periods lie within the invoicing period (PEPPOL-EN16931-R110, R111).
* At most one note, without subject code (PEPPOL-EN16931-R002 in CII). Payment means are pure, as
  XRechnung BR-DE-23-a/b, BR-DE-24-a/b and BR-DE-25-a/b want: 30/58 with one credit transfer, 48 with a card,
  59 with a direct debit and its mandate reference (PEPPOL-EN16931-R061).
* BT-6 differs from BT-5 (PEPPOL-EN16931-R005), BT-111 is present with BT-6 (BR-53) and has the sign of BT-110
  (PEPPOL-EN16931-R055).
* Seller in DE or AT, buyer in DE, AT or FR. Of the Peppol national rule sets only the German one (DE-R-*,
  seller and buyer both in DE, in ``PEPPOL-EN16931-UBL.sch`` only; the CII file has no DE-R rules) applies; it
  mirrors the XRechnung terms generated for Peppol anyway. Type code 384 only between German parties
  (PEPPOL-EN16931-P0112).
* No category O where the target requires BT-119 on every VAT breakdown (:attr:`Target.needs_bt119`):
  XRechnung BR-DE-14 (UBL and CII), and Peppol DE-R-014 between German parties (UBL only). The official
  XRechnung instance ``01.04a-INVOICE_ubl.xml`` writes an O breakdown with ``cbc:Percent`` 0, but
  :func:`euinvoice.calc.complete` derives an O breakdown without BT-119, so it cannot build those invoices
  (issue #75).

ponytail: deliberate narrowings beyond the rules above, each a possible later widening: K always gets BT-72
(BR-IC-11 also accepts an invoicing period BG-14); BT-20 is one of two fixed strings (no XRechnung BR-DE-18
Skonto lines); type codes 380, 381 and 384 only; no whole-unit currencies such as HUF (``calc.complete``
rounds VAT to cents); text is BMP only (issue #74, see :data:`text`). Factur-X targets are not covered yet
(issue #42).

Profile-mandatory terms (:attr:`Target.mandatory`): BT-10 (BR-DE-15, PEPPOL-EN16931-R003), BT-23
(PEPPOL-EN16931-R001, re-asserted by XRechnung), BT-34 and BT-49 as GS1 GLNs with valid check digits
(PEPPOL-EN16931-R020, R010; PEPPOL-COMMON-R040), the seller contact BG-6 with BT-41, BT-42, BT-43
(BR-DE-2, BR-DE-5 … 7), seller and buyer city and post code (BR-DE-3, 4, 8, 9), deliver-to city and post
code (BR-DE-10, 11) and payment instructions BG-16 (BR-DE-1). Without :attr:`Target.mandatory` each of them
is drawn optionally.

Fixtures are synthetic (CLAUDE.md): example.com, zero VAT ids, the test IBAN.
"""

import dataclasses
import datetime
import typing as t
from decimal import ROUND_HALF_UP, Decimal

from hypothesis import strategies as st

import _strategies as strategies
from _invoices import TEST_IBAN
from euinvoice import calc, profiles
from euinvoice.model import (
    Buyer,
    BuyerPostalAddress,
    CreditTransfer,
    DeliverToAddress,
    DeliveryInformation,
    DirectDebit,
    DocumentLevelAllowance,
    DocumentLevelCharge,
    Identifier,
    Invoice,
    InvoiceDraft,
    InvoiceLineAllowance,
    InvoiceLineCharge,
    InvoiceLinePeriod,
    InvoiceNote,
    InvoicingPeriod,
    ItemInformation,
    LineDraft,
    LineVatInformation,
    PaymentCardInformation,
    PaymentInstructions,
    PrecedingInvoiceReference,
    PriceDetails,
    ProcessControl,
    Seller,
    SellerContact,
    SellerPostalAddress,
)
from euinvoice.profiles.peppol import BILLING_PROCESS
from euinvoice.syntax import Syntax


@dataclasses.dataclass(frozen=True, slots=True)
class Target:
    """A profile and what the drawn invoices must satisfy for it beyond EN 16931 core.

    Attributes:
        profile: The profile; its BT-24 is written.
        business_process: BT-23, always written; ``None`` draws it optionally.
        mandatory: Always draw the Peppol and XRechnung mandatory terms (module docstring).
        needs_bt119: When every VAT breakdown needs a VAT category rate BT-119: never, between German parties
            in UBL only (Peppol DE-R-014), or always (XRechnung BR-DE-14).
    """

    profile: profiles.Profile
    business_process: str | None
    mandatory: bool
    needs_bt119: t.Literal["never", "between German parties in UBL", "always"]


CORE: t.Final = Target(profiles.EN16931, None, mandatory=False, needs_bt119="never")
PEPPOL: t.Final = Target(profiles.PEPPOL, BILLING_PROCESS, mandatory=True, needs_bt119="between German parties in UBL")
# XRechnung fixes no BT-23 value, but its rule set re-asserts PEPPOL-EN16931-R001 (BT-23 present); every
# instance of the pinned testsuite uses the Peppol billing 01 process.
XRECHNUNG: t.Final = Target(profiles.XRECHNUNG, BILLING_PROCESS, mandatory=True, needs_bt119="always")
TARGETS: t.Final = (CORE, PEPPOL, XRECHNUNG)
"""Every target; adding a profile to the property tests is one entry here."""

# (category, rate) pairs that pass BR-<x>-05/06/07, and the VATEX code (BR-CL-22) of the categories whose
# BR-<x>-10 needs an exemption reason.
_PAIRS: t.Final[tuple[tuple[str, str | None], ...]] = (
    *(("S", rate) for rate in ("19", "7", "20", "10", "5.5")),
    *((category, "0") for category in ("Z", "E", "AE", "K", "G")),
)
_VATEX: t.Final = {"E": "VATEX-EU-132", "AE": "VATEX-EU-AE", "K": "VATEX-EU-IC", "G": "VATEX-EU-G", "O": "VATEX-EU-O"}
_VAT_IDS: t.Final = {"DE": "DE000000000", "AT": "ATU00000000", "FR": "FR00000000000"}
# GS1 GLNs with valid check digits (PEPPOL-COMMON-R040), EAS 0088.
_SELLER_GLN: t.Final = Identifier(value="4000001000005", scheme_id="0088")
_BUYER_GLN: t.Final = Identifier(value="4000001000036", scheme_id="0088")

# Non-blank XML text, with TAB, LF and CR (they round-trip and validate in both syntaxes).
# ponytail: BMP only. SaxonC-HE 13.0.0 (12.9 is fine) throws ArrayIndexOutOfBoundsException in normalize-space()
# on a string mixing whitespace, a character above U+00FF and one above U+FFFF (e.g. " \u0100\U000100000000"), so
# validate() reports a false SCHEMATRON-RUNTIME fatal (issue #74, test_saxon_normalize_space_regression). Lift the
# cap once that xfail passes.
text: t.Final = strategies.text(max_codepoint=0xFFFF, include_characters="\t\n\r")


def _decimal(low: str, high: str, places: int) -> st.SearchStrategy[Decimal]:
    return st.decimals(Decimal(low), Decimal(high), places=places, allow_nan=False, allow_infinity=False)


def _optional[T](mandatory: bool, value: st.SearchStrategy[T]) -> st.SearchStrategy[T | None]:
    return value if mandatory else st.none() | value


def _percent_of(base: Decimal, percentage: Decimal) -> Decimal:
    return (base * percentage / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class _AllowanceCharge(t.TypedDict):
    amount: Decimal
    base_amount: Decimal | None
    percentage: Decimal | None


@st.composite
def _amounts(draw: st.DrawFn) -> _AllowanceCharge:
    """BT-92/93/94 (and their line and charge siblings): an amount, or a base and percentage giving it."""
    if draw(st.booleans()):
        base, percentage = draw(_decimal("0", "5000", 2)), draw(_decimal("0", "100", 2))
        return {"amount": _percent_of(base, percentage), "base_amount": base, "percentage": percentage}
    return {"amount": draw(_decimal("0", "200", 2)), "base_amount": None, "percentage": None}


@st.composite
def _reason(draw: st.DrawFn, code: str) -> dict[str, str | None]:
    """A reason text, a reason code or both (BR-33, BR-38, BR-42, BR-44)."""
    reason, reason_code = draw(st.sampled_from([(True, False), (False, True), (True, True)]))
    return {"reason": draw(text) if reason else None, "reason_code": code if reason_code else None}


@st.composite
def _price(draw: st.DrawFn, unit: str) -> PriceDetails:
    net = draw(_decimal("0", "10000", 4))  # BR-27: not negative
    discount = draw(st.none() | _decimal("0", "100", 4))
    base = draw(st.none() | st.sampled_from([Decimal("1"), Decimal("3"), Decimal("12"), Decimal("0.5")]))
    return PriceDetails(
        item_net_price=net,
        item_price_discount=discount,
        item_gross_price=None if discount is None else net + discount,
        base_quantity=base,
        base_quantity_unit_code=None if base is None else unit,
    )


@st.composite
def _line(draw: st.DrawFn, pairs: list[tuple[str, str | None]], period: InvoicingPeriod | None) -> LineDraft:
    category, rate = draw(st.sampled_from(pairs))
    unit = draw(st.sampled_from(["C62", "HUR", "KGM"]))
    with_period = period is not None and draw(st.booleans())
    return LineDraft(
        identifier="0",  # renumbered by the caller (unique line ids)
        note=draw(st.none() | text),
        invoiced_quantity=draw(_decimal("-100", "1000", 3)),
        invoiced_quantity_unit_code=unit,
        period=InvoiceLinePeriod(start_date=period.start_date, end_date=period.end_date)
        if with_period and period is not None
        else None,
        allowances=tuple(
            InvoiceLineAllowance(**draw(_amounts()), **draw(_reason("95"))) for _ in range(draw(st.integers(0, 2)))
        ),
        charges=tuple(
            InvoiceLineCharge(**draw(_amounts()), **draw(_reason("ABL"))) for _ in range(draw(st.integers(0, 1)))
        ),
        price_details=draw(_price(unit)),
        vat_information=LineVatInformation(category_code=category, rate=None if rate is None else Decimal(rate)),
        item=ItemInformation(
            name=draw(text), description=draw(st.none() | text), sellers_identifier=draw(st.none() | text)
        ),
    )


@st.composite
def _payment(draw: st.DrawFn) -> PaymentInstructions:
    code = draw(st.sampled_from(["30", "58", "48", "59"]))
    transfers: tuple[CreditTransfer, ...] = ()
    card = debit = None
    if code in {"30", "58"}:  # BR-61: BT-84 present
        transfers = (CreditTransfer(payment_account_identifier=TEST_IBAN, payment_account_name=draw(st.none() | text)),)
    elif code == "48":
        card = PaymentCardInformation(primary_account_number="1234", holder_name=draw(st.none() | text))
    else:
        debit = DirectDebit(
            mandate_reference_identifier="MANDATE-1",
            bank_assigned_creditor_identifier="DE98ZZZ09999999999",
            debited_account_identifier=TEST_IBAN,
        )
    return PaymentInstructions(
        payment_means_type_code=code,
        remittance_information=draw(st.none() | text),
        credit_transfers=transfers,
        payment_card=card,
        direct_debit=debit,
    )


@st.composite
def drafts(
    draw: st.DrawFn, target: Target, syntax: Syntax | None = None
) -> tuple[InvoiceDraft, dict[str, calc.ExemptionReason]]:
    """A draft for ``target`` in ``syntax`` (``None``: valid in both) and the exemption reasons it needs."""
    mandatory = target.mandatory
    seller_country = draw(st.sampled_from(["DE", "AT"]))
    buyer_country = draw(st.sampled_from(["DE", "AT", "FR"]))
    german = seller_country == buyer_country == "DE"
    type_code = draw(st.sampled_from(["380", "381", "384"] if german else ["380", "381"]))
    issue_date = draw(st.dates(datetime.date(2020, 1, 1), datetime.date(2030, 12, 31)))
    period = None
    if draw(st.booleans()):
        start = issue_date - datetime.timedelta(days=draw(st.integers(0, 60)))
        period = InvoicingPeriod(start_date=start, end_date=start + datetime.timedelta(days=draw(st.integers(0, 30))))

    # ponytail: no O where BT-119 is required (module docstring, issue #75); lift once calc can write BT-119 = 0
    # for O.
    o_allowed = target.needs_bt119 == "never" or (
        target.needs_bt119 == "between German parties in UBL" and (syntax is Syntax.CII or not german)
    )
    pairs: list[tuple[str, str | None]] = [("O", None)] if o_allowed and draw(st.integers(0, 5)) == 0 else list(_PAIRS)
    lines = draw(st.lists(_line(pairs, period), min_size=1, max_size=4))
    used = sorted({(ln.vat_information.category_code, ln.vat_information.rate) for ln in lines})
    categories = {category for category, _ in used}

    def document_level[K: (DocumentLevelAllowance, DocumentLevelCharge)](kind: type[K], code: str) -> K:
        category, rate = draw(st.sampled_from(used))
        return kind(**draw(_amounts()), vat_category_code=category, vat_rate=rate, **draw(_reason(code)))

    allowances = tuple(document_level(DocumentLevelAllowance, "95") for _ in range(draw(st.integers(0, 2))))
    charges = tuple(document_level(DocumentLevelCharge, "FC") for _ in range(draw(st.integers(0, 2))))

    not_subject = categories == {"O"}
    buyer_vat = None if not_subject else _VAT_IDS[buyer_country]
    if categories.isdisjoint({"AE", "K"}) and buyer_vat is not None:
        buyer_vat = draw(st.none() | st.just(buyer_vat))
    delivery_address = None
    if "K" in categories or draw(st.booleans()):
        delivery_address = DeliverToAddress(
            city=draw(_optional(mandatory, text)),
            post_code=draw(_optional(mandatory, st.just("10115"))),
            country_code=buyer_country,
        )
    delivery_date = draw(st.dates(issue_date - datetime.timedelta(days=30), issue_date))
    delivery = None
    if delivery_address is not None or period is not None:
        delivery = DeliveryInformation(
            deliver_to_party_name=draw(st.none() | text),
            actual_delivery_date=delivery_date if "K" in categories or draw(st.booleans()) else None,
            invoicing_period=period,
            deliver_to_address=delivery_address,
        )

    currency = draw(st.sampled_from(["EUR", "USD", "SEK", "CHF"]))
    preceding: tuple[PrecedingInvoiceReference, ...] = ()
    if type_code == "384" or (type_code == "381" and draw(st.booleans())):
        preceding = (PrecedingInvoiceReference(reference=draw(text), issue_date=draw(st.none() | st.just(issue_date))),)
    payment = draw(_optional(mandatory, _payment()))
    due_date = None
    if (payment is not None or type_code != "381") and draw(st.booleans()):
        due_date = issue_date + datetime.timedelta(days=draw(st.integers(0, 60)))
    draft = InvoiceDraft(
        number=draw(text),
        issue_date=issue_date,
        type_code=type_code,
        currency_code=currency,
        vat_accounting_currency_code=draw(
            st.none() | st.sampled_from(["EUR", "USD", "SEK"]).filter(lambda c: c != currency)
        ),
        payment_due_date=due_date,
        buyer_reference=draw(_optional(mandatory, text)),
        purchase_order_reference=draw(st.none() | text),
        payment_terms=draw(st.sampled_from(["Net 30 days", "Zahlbar sofort ohne Abzug"])),
        notes=tuple(draw(st.lists(st.builds(InvoiceNote, note=text), max_size=1))),
        process_control=ProcessControl(
            business_process_type=target.business_process or draw(st.none() | text),
            specification_identifier=target.profile.specification_identifier,
        ),
        preceding_invoice_references=preceding,
        seller=Seller(
            name=draw(text),
            identifiers=(_SELLER_GLN,) if not_subject else tuple(draw(st.lists(st.just(_SELLER_GLN), max_size=1))),
            vat_identifier=None if not_subject else _VAT_IDS[seller_country],
            electronic_address=draw(_optional(mandatory, st.just(_SELLER_GLN))),
            postal_address=SellerPostalAddress(
                city=draw(_optional(mandatory, text)),
                post_code=draw(_optional(mandatory, st.just("10115"))),
                country_code=seller_country,
            ),
            contact=draw(
                _optional(
                    mandatory,
                    st.builds(
                        SellerContact,
                        contact_point=text,
                        telephone=st.just("+49 000 000000"),
                        email=st.just("sales@example.com"),
                    ),
                )
            ),
        ),
        buyer=Buyer(
            name=draw(text),
            vat_identifier=buyer_vat,
            electronic_address=draw(_optional(mandatory, st.just(_BUYER_GLN))),
            postal_address=BuyerPostalAddress(
                city=draw(_optional(mandatory, text)),
                post_code=draw(_optional(mandatory, st.just("1010"))),
                country_code=buyer_country,
            ),
        ),
        delivery=delivery,
        payment_instructions=payment,
        allowances=allowances,
        charges=charges,
        lines=tuple(ln.model_copy(update={"identifier": str(i)}) for i, ln in enumerate(lines, 1)),
    )
    reasons = {
        category: calc.ExemptionReason(code=_VATEX[category], text=draw(st.none() | text))
        for category in sorted(categories & _VATEX.keys())
    }
    return draft, reasons


@st.composite
def invoices(draw: st.DrawFn, target: Target, syntax: Syntax | None = None) -> Invoice:
    """An invoice for ``target`` in ``syntax``: a :func:`drafts` draft completed with :func:`euinvoice.calc.complete`.

    ``syntax`` ``None`` draws invoices that are valid in both syntaxes.

    With a VAT accounting currency BT-6, BT-111 is the completed BT-110 times a drawn exchange rate, so
    both have the same sign (PEPPOL-EN16931-R055).
    """
    draft, reasons = draw(drafts(target, syntax))
    paid = draw(st.none() | _decimal("0", "100", 2))
    rounding = draw(st.none() | _decimal("-0.99", "0.99", 2))
    bt111 = None
    if draft.vat_accounting_currency_code is not None:
        vat = calc.complete(
            draft.model_copy(update={"vat_accounting_currency_code": None}), exemption_reasons=reasons
        ).totals.total_vat
        assert vat is not None
        bt111 = (vat * draw(_decimal("0.1", "20", 4))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return calc.complete(
        draft,
        paid_amount=paid,
        rounding_amount=rounding,
        vat_total_in_accounting_currency=bt111,
        exemption_reasons=reasons,
    )
