"""Synthetic XRechnung invoices: one that passes the XRechnung rules, and one violation per pre-flight rule.

Shared by the profile unit tests and the conformance tests that check each pre-flight rule against the
official XRechnung Schematron through both writers.
"""

import typing as t
from collections.abc import Callable
from decimal import Decimal

from _calc_drafts import not_subject_to_vat
from _invoices import TEST_IBAN, minimal_invoice, rebuild
from euinvoice import profiles
from euinvoice.model import (
    AdditionalSupportingDocument,
    BinaryObject,
    Buyer,
    BuyerPostalAddress,
    CreditTransfer,
    DeliverToAddress,
    DeliveryInformation,
    DirectDebit,
    DocumentLevelAllowance,
    Identifier,
    Invoice,
    PaymentCardInformation,
    PaymentInstructions,
    ProcessControl,
    Seller,
    SellerContact,
    SellerPostalAddress,
    VatBreakdown,
)
from euinvoice.syntax import Syntax

PEPPOL_BILLING_01: t.Final = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
"""BT-23 of every instance of the pinned XRechnung testsuite; PEPPOL-EN16931-R001 (in the XRechnung rule set)
requires a BT-23."""

_SELLER_ADDRESS: t.Final = SellerPostalAddress(city="Example City", post_code="10000", country_code="DE")
_CONTACT: t.Final = SellerContact(contact_point="Sales", telephone="+49 000 000000", email="sales@example.com")
_BUYER_ADDRESS: t.Final = BuyerPostalAddress(city="Sample Town", post_code="20000", country_code="DE")
_TRANSFER: t.Final = CreditTransfer(payment_account_identifier=TEST_IBAN)
_CARD: t.Final = PaymentCardInformation(primary_account_number="0000000000")
_CREDITOR_ID: t.Final = "DE98ZZZ09999999999"


def xrechnung_invoice(**changes: t.Any) -> Invoice:
    """An invoice with no blocking finding under XRechnung (CEN and XRechnung rules), in UBL and CII.

    It has the XRechnung mandatory terms (BT-10, BG-6, seller and buyer city and post code, BG-16), the
    electronic addresses and BT-23 that the re-asserted PEPPOL-EN16931-R010 / R020 / R001 require, and is
    prepared for :data:`euinvoice.profiles.XRECHNUNG`.
    """
    data: dict[str, t.Any] = {
        "buyer_reference": "04011000-12345-34",
        "process_control": ProcessControl(
            business_process_type=PEPPOL_BILLING_01,
            specification_identifier=profiles.XRECHNUNG.specification_identifier,
        ),
        "seller": seller(),
        "buyer": buyer(),
        "payment_instructions": payment(),
    }
    return minimal_invoice(**{**data, **changes})


def xrechnung_o_invoice(**changes: t.Any) -> Invoice:
    """A "Not subject to VAT" (O) invoice with the XRechnung terms of :func:`xrechnung_invoice`, from ``complete()``.

    Its O breakdown has no BT-119, so it fails BR-DE-14 until :meth:`~euinvoice.profiles.Profile.prepare` (#75).
    The seller has a legal registration id (BR-CO-26) and no VAT id (BR-O-02).
    """
    data: dict[str, t.Any] = {
        "buyer_reference": "04011000-12345-34",
        "process_control": ProcessControl(
            business_process_type=PEPPOL_BILLING_01,
            specification_identifier=profiles.XRECHNUNG.specification_identifier,
        ),
        "seller": seller(vat_identifier=None, legal_registration_identifier=Identifier(value="HRB 00000")),
        "buyer": buyer(),
        "payment_instructions": payment(),
    }
    return not_subject_to_vat(**{**data, **changes})


def seller(**changes: t.Any) -> Seller:
    data: dict[str, t.Any] = {
        "name": "Seller Example GmbH",
        "vat_identifier": "DE000000000",
        "electronic_address": Identifier(value="seller@example.com", scheme_id="EM"),
        "postal_address": _SELLER_ADDRESS,
        "contact": _CONTACT,
    }
    return Seller(**{**data, **changes})


def buyer(**changes: t.Any) -> Buyer:
    data: dict[str, t.Any] = {
        "name": "Buyer Example AG",
        "electronic_address": Identifier(value="buyer@example.com", scheme_id="EM"),
        "postal_address": _BUYER_ADDRESS,
    }
    return Buyer(**{**data, **changes})


def payment(code: str = "58", **changes: t.Any) -> PaymentInstructions:
    data: dict[str, t.Any] = {"payment_means_type_code": code, "credit_transfers": (_TRANSFER,)}
    return PaymentInstructions(**{**data, **changes})


def _attachment(reference: str) -> AdditionalSupportingDocument:
    return AdditionalSupportingDocument(
        reference=reference,
        attached_document=BinaryObject(content=b"%PDF-1.7", mime_code="application/pdf", filename="same.pdf"),
    )


def _deliver_to(**address: t.Any) -> DeliveryInformation:
    return DeliveryInformation(deliver_to_address=DeliverToAddress(country_code="DE", **address))


def _without_rate(invoice: Invoice) -> Invoice:
    (breakdown,) = invoice.vat_breakdown
    return rebuild(invoice, vat_breakdown=(VatBreakdown.model_validate({**dict(breakdown), "rate": None}),))


# Each XRechnung pre-flight rule (official id) → an invoice that violates it and no other pre-flight rule.
VIOLATIONS: t.Final[dict[str, Callable[[], Invoice]]] = {
    "BR-DE-1": lambda: xrechnung_invoice(payment_instructions=None),
    "BR-DE-2": lambda: xrechnung_invoice(seller=seller(contact=None)),
    "BR-DE-3": lambda: xrechnung_invoice(
        seller=seller(postal_address=SellerPostalAddress(post_code="1", country_code="DE"))
    ),
    "BR-DE-4": lambda: xrechnung_invoice(
        seller=seller(postal_address=SellerPostalAddress(city="X", country_code="DE"))
    ),
    "BR-DE-5": lambda: xrechnung_invoice(
        seller=seller(contact=SellerContact(telephone="+49 000", email="a@example.com"))
    ),
    "BR-DE-6": lambda: xrechnung_invoice(
        seller=seller(contact=SellerContact(contact_point="S", email="a@example.com"))
    ),
    "BR-DE-7": lambda: xrechnung_invoice(seller=seller(contact=SellerContact(contact_point="S", telephone="+49 000"))),
    "BR-DE-8": lambda: xrechnung_invoice(
        buyer=buyer(postal_address=BuyerPostalAddress(post_code="2", country_code="DE"))
    ),
    "BR-DE-9": lambda: xrechnung_invoice(buyer=buyer(postal_address=BuyerPostalAddress(city="Y", country_code="DE"))),
    "BR-DE-10": lambda: xrechnung_invoice(delivery=_deliver_to(post_code="30000")),
    "BR-DE-11": lambda: xrechnung_invoice(delivery=_deliver_to(city="Delivery Town")),
    "BR-DE-14": lambda: _without_rate(xrechnung_invoice()),
    # Blank counts as missing: the rule tests cbc:BuyerReference[boolean(normalize-space(.))].
    "BR-DE-15": lambda: xrechnung_invoice(buyer_reference=" \t"),
    "BR-DE-16": lambda: xrechnung_invoice(seller=seller(vat_identifier=None)),
    "BR-DE-22": lambda: xrechnung_invoice(additional_supporting_documents=(_attachment("A"), _attachment("B"))),
    "BR-DE-23-a": lambda: xrechnung_invoice(payment_instructions=payment(credit_transfers=())),
    "BR-DE-23-b": lambda: xrechnung_invoice(payment_instructions=payment(payment_card=_CARD)),
    "BR-DE-24-a": lambda: xrechnung_invoice(payment_instructions=payment("48", credit_transfers=())),
    "BR-DE-24-b": lambda: xrechnung_invoice(payment_instructions=payment("48", payment_card=_CARD)),
    "BR-DE-25-a": lambda: xrechnung_invoice(payment_instructions=payment("59", credit_transfers=())),
    "BR-DE-25-b": lambda: xrechnung_invoice(
        payment_instructions=payment(
            "59",
            direct_debit=DirectDebit(
                mandate_reference_identifier="M-1",
                bank_assigned_creditor_identifier=_CREDITOR_ID,
                debited_account_identifier=TEST_IBAN,
            ),
        )
    ),
    "BR-DE-30": lambda: xrechnung_invoice(
        payment_instructions=payment(
            "59",
            credit_transfers=(),
            direct_debit=DirectDebit(mandate_reference_identifier="M-1", debited_account_identifier=TEST_IBAN),
        )
    ),
    "BR-DE-31": lambda: xrechnung_invoice(
        payment_instructions=payment(
            "59",
            credit_transfers=(),
            direct_debit=DirectDebit(
                mandate_reference_identifier="M-1", bank_assigned_creditor_identifier=_CREDITOR_ID
            ),
        )
    ),
    "PEPPOL-EN16931-R001": lambda: xrechnung_invoice(
        process_control=ProcessControl(specification_identifier=profiles.XRECHNUNG.specification_identifier)
    ),
}


def cvd_invoice(**changes: t.Any) -> Invoice:
    """:func:`xrechnung_invoice` with BT-12 and BT-17, prepared for the CVD profile.

    No model invoice satisfies BR-DE-CVD-03: it needs an item classification with list id ``CVD``, which the
    model rejects under CEN BR-CL-13 (KoSIT downgrades BR-CL-13 in its CVD scenarios; issue #49).
    """
    data: dict[str, t.Any] = {"contract_reference": "CONTRACT-1", "tender_or_lot_reference": "LOT-1"}
    return profiles.XRECHNUNG_CVD.prepare(xrechnung_invoice(**{**data, **changes}))


CVD_VIOLATIONS: t.Final[dict[str, Callable[[], Invoice]]] = {
    "BR-DE-CVD-01": lambda: cvd_invoice(contract_reference=None),
    "BR-DE-CVD-02": lambda: cvd_invoice(tender_or_lot_reference=" "),
    "BR-DE-CVD-03": cvd_invoice,
}


def _debit_only(code: str = "59", transfers: int = 0, **fields: str) -> Invoice:
    return xrechnung_invoice(
        payment_instructions=payment(
            code, credit_transfers=(_TRANSFER,) * transfers, direct_debit=DirectDebit(**fields)
        )
    )


def _allowance_s() -> Invoice:
    """No line in a BR-DE-16 category, but a document-level allowance in category S, and no seller tax id."""
    invoice = xrechnung_invoice(seller=seller(vat_identifier=None))
    line = invoice.lines[0]
    exempt = line.model_validate({**dict(line), "vat_information": {"category_code": "O"}})
    allowance = DocumentLevelAllowance(
        amount=Decimal("0.00"), vat_category_code="S", vat_rate=Decimal("19"), reason="X"
    )
    return rebuild(invoice, lines=(exempt,), allowances=(allowance,))


def _two_attachments_without_filename() -> Invoice:
    attachment = BinaryObject(content=b"x", mime_code="application/pdf")
    return xrechnung_invoice(
        additional_supporting_documents=tuple(
            AdditionalSupportingDocument(reference=r, attached_document=attachment) for r in "AB"
        )
    )


# Edge cases: name → (invoice, the pre-flight rule ids per syntax). Where the UBL and CII bindings differ, the
# expectations differ; the conformance tests check each against the official Schematron.
EDGES: t.Final[dict[str, tuple[Callable[[], Invoice], dict[Syntax, set[str]]]]] = {
    "bt90-only": (
        lambda: _debit_only(bank_assigned_creditor_identifier=_CREDITOR_ID),
        # UBL writes no cac:PaymentMandate without BT-89/BT-91; CII sees BG-19 and misses BT-89/BT-91.
        {Syntax.UBL: {"BR-DE-25-a"}, Syntax.CII: {"BR-DE-30", "BR-DE-31"}},
    ),
    "bt91-only": (
        lambda: _debit_only(debited_account_identifier=TEST_IBAN),
        {Syntax.UBL: {"BR-DE-30"}, Syntax.CII: {"BR-DE-30", "BR-DE-31"}},
    ),
    "bt90-bt91": (
        lambda: _debit_only(bank_assigned_creditor_identifier=_CREDITOR_ID, debited_account_identifier=TEST_IBAN),
        {Syntax.UBL: set(), Syntax.CII: set()},
    ),
    "empty-direct-debit": (_debit_only, {Syntax.UBL: {"BR-DE-25-a"}, Syntax.CII: {"BR-DE-25-a"}}),
    "direct-debit-two-transfers": (
        # The mandate and BT-91 go into the first payment means only.
        lambda: _debit_only(
            transfers=2,
            mandate_reference_identifier="M-1",
            bank_assigned_creditor_identifier=_CREDITOR_ID,
            debited_account_identifier=TEST_IBAN,
        ),
        {Syntax.UBL: {"BR-DE-25-a", "BR-DE-25-b"}, Syntax.CII: {"BR-DE-25-b"}},
    ),
    "card-two-transfers": (
        lambda: xrechnung_invoice(
            payment_instructions=payment("48", credit_transfers=(_TRANSFER, _TRANSFER), payment_card=_CARD)
        ),
        {Syntax.UBL: {"BR-DE-24-a", "BR-DE-24-b"}, Syntax.CII: {"BR-DE-24-a", "BR-DE-24-b"}},
    ),
    "blank-bt89-with-transfer-code": (
        # BR-DE-23-b tests element existence, so a blank BT-89 still counts.
        lambda: _debit_only("58", transfers=1, mandate_reference_identifier=" ", debited_account_identifier=TEST_IBAN),
        {Syntax.UBL: {"BR-DE-23-b", "BR-DE-30"}, Syntax.CII: {"BR-DE-23-b", "BR-DE-30"}},
    ),
    "other-means-code": (
        lambda: xrechnung_invoice(payment_instructions=payment("1", credit_transfers=(), payment_card=_CARD)),
        {Syntax.UBL: set(), Syntax.CII: set()},
    ),
    "tax-registration-id": (
        lambda: xrechnung_invoice(seller=seller(vat_identifier=None, tax_registration_identifier="000/000/00000")),
        {Syntax.UBL: set(), Syntax.CII: set()},
    ),
    "allowance-category-s": (
        # BT-95 counts for BR-DE-16 in UBL only (see the profile module).
        _allowance_s,
        {Syntax.UBL: {"BR-DE-16"}, Syntax.CII: set()},
    ),
    # The UBL writer rejects an attachment without filename (UBL-DT-07), so this edge is CII only.
    "attachments-without-filename": (_two_attachments_without_filename, {Syntax.CII: set()}),
}
