"""Synthetic drafts for the calc tests (fake parties, example.com, test VAT ids; CLAUDE.md fixtures rule)."""

import datetime
import typing as t
from collections.abc import Sequence
from decimal import Decimal

from euinvoice.calc import ExemptionReason, complete
from euinvoice.model import (
    Buyer,
    BuyerPostalAddress,
    DocumentLevelAllowance,
    DocumentLevelCharge,
    DocumentTotals,
    Identifier,
    Invoice,
    InvoiceDraft,
    InvoiceLineAllowance,
    InvoiceLineCharge,
    ItemInformation,
    LineDraft,
    LineVatInformation,
    PriceDetails,
    ProcessControl,
    Seller,
    SellerPostalAddress,
    VatBreakdown,
)


def line(
    quantity: str = "1",
    price: str = "100",
    category: str = "S",
    rate: str | None = "20",
    *,
    identifier: str = "1",
    base_quantity: str | None = None,
    allowances: Sequence[str] = (),
    charges: Sequence[str] = (),
) -> LineDraft:
    """A line draft; amounts are decimal strings, line allowances and charges by amount."""
    return LineDraft(
        identifier=identifier,
        invoiced_quantity=Decimal(quantity),
        invoiced_quantity_unit_code="C62",
        allowances=tuple(InvoiceLineAllowance(amount=Decimal(a), reason="Discount") for a in allowances),
        charges=tuple(InvoiceLineCharge(amount=Decimal(c), reason="Packing") for c in charges),
        price_details=PriceDetails(
            item_net_price=Decimal(price),
            base_quantity=None if base_quantity is None else Decimal(base_quantity),
        ),
        vat_information=LineVatInformation(category_code=category, rate=None if rate is None else Decimal(rate)),
        item=ItemInformation(name="Synthetic item"),
    )


def allowance(amount: str, category: str = "S", rate: str | None = "20") -> DocumentLevelAllowance:
    """A document level allowance (BG-20)."""
    return DocumentLevelAllowance(
        amount=Decimal(amount),
        vat_category_code=category,
        vat_rate=None if rate is None else Decimal(rate),
        reason="Discount",
    )


def charge(amount: str, category: str = "S", rate: str | None = "20") -> DocumentLevelCharge:
    """A document level charge (BG-21)."""
    return DocumentLevelCharge(
        amount=Decimal(amount),
        vat_category_code=category,
        vat_rate=None if rate is None else Decimal(rate),
        reason="Booking fee",
    )


def draft(
    *lines: LineDraft,
    allowances: Sequence[DocumentLevelAllowance] = (),
    charges: Sequence[DocumentLevelCharge] = (),
    seller_country: str = "AT",
    buyer_country: str = "AT",
    **changes: t.Any,
) -> InvoiceDraft:
    """An invoice draft from a synthetic Austrian seller (ATU00000000) to a synthetic buyer."""
    data: dict[str, t.Any] = {
        "number": "INV-1",
        "issue_date": datetime.date(2026, 1, 15),
        "type_code": "380",
        "currency_code": "EUR",
        "process_control": ProcessControl(specification_identifier="urn:cen.eu:en16931:2017"),
        "seller": Seller(
            name="Seller Example GmbH",
            vat_identifier="ATU00000000",
            postal_address=SellerPostalAddress(country_code=seller_country),
        ),
        "buyer": Buyer(name="Buyer Example", postal_address=BuyerPostalAddress(country_code=buyer_country)),
        "allowances": tuple(allowances),
        "charges": tuple(charges),
        "lines": lines or (line(),),
    }
    data.update(changes)
    return InvoiceDraft(**data)


def replace(invoice: Invoice, **changes: t.Any) -> Invoice:
    """``invoice`` with top-level fields replaced, built through validation."""
    return Invoice.model_validate({**dict(invoice), **changes})


def with_totals(invoice: Invoice, **changes: str | None) -> Invoice:
    """``invoice`` with some DOCUMENT TOTALS (BG-22) replaced (decimal strings, ``None`` to drop)."""
    values = {name: None if value is None else Decimal(value) for name, value in changes.items()}
    return replace(invoice, totals=DocumentTotals.model_validate({**dict(invoice.totals), **values}))


def with_breakdown(invoice: Invoice, groups: Sequence[VatBreakdown]) -> Invoice:
    """``invoice`` with another VAT breakdown and BT-110, BT-112 and BT-115 made consistent with it."""
    vat = sum((group.tax_amount for group in groups), Decimal("0.00"))
    totals = invoice.totals
    with_vat = totals.total_without_vat + vat
    due = with_vat - (totals.paid_amount or 0) + (totals.rounding_amount or 0)
    return replace(
        invoice,
        vat_breakdown=tuple(groups),
        totals=DocumentTotals.model_validate(
            {**dict(totals), "total_vat": vat, "total_with_vat": with_vat, "amount_due": due}
        ),
    )


def group(index: int, invoice: Invoice, **changes: t.Any) -> VatBreakdown:
    """VAT breakdown ``index`` of ``invoice`` with fields replaced (decimal strings become Decimals)."""
    values = {
        k: Decimal(v) if isinstance(v, str) and k in {"taxable_amount", "tax_amount", "rate"} else v
        for k, v in changes.items()
    }
    return VatBreakdown.model_validate({**dict(invoice.vat_breakdown[index]), **values})


NOT_SUBJECT_TO_VAT: t.Final = ExemptionReason(code="VATEX-EU-O", text="Not subject to VAT")
"""BT-121 and BT-120 of a category O breakdown (BR-O-10)."""


def not_subject_to_vat(seller_country: str = "AT", buyer_country: str = "AT", **changes: t.Any) -> Invoice:
    """:func:`complete` of a one-line "Not subject to VAT" (O) draft; its O breakdown has no BT-119 (issue #75).

    The seller has a legal registration id (BR-CO-26) and no VAT id (BR-O-02); ``changes`` go to :func:`draft`.
    """
    seller = Seller(
        name="Seller Example GmbH",
        legal_registration_identifier=Identifier(value="HRB 00000"),
        postal_address=SellerPostalAddress(country_code=seller_country),
    )
    data: dict[str, t.Any] = {"seller": seller, **changes}
    return complete(
        draft(line(category="O", rate=None), buyer_country=buyer_country, **data),
        exemption_reasons={"O": NOT_SUBJECT_TO_VAT},
    )
