# Example: ticketing

A synthetic event organiser sells tickets and merchandise online. Its checkout shows **VAT-inclusive** prices,
and one order can mix VAT rates. After the event, one ticket is refunded with a **credit note**.

The rates are assumptions of the example (13 % on admission, 20 % on merchandise and the booking fee), not tax
advice. Everything is written under the EN 16931 core profile and, in the conformance suite, validated against the
official CEN rules.

## The order

```python
import datetime
from decimal import ROUND_HALF_UP, Decimal

from euinvoice import calc, parse, profiles, to_xml
from euinvoice.model import (
    Buyer,
    BuyerPostalAddress,
    InvoiceDraft,
    ItemInformation,
    LineDraft,
    LineVatInformation,
    PaymentInstructions,
    PrecedingInvoiceReference,
    PriceDetails,
    ProcessControl,
    Seller,
    SellerPostalAddress,
)

# What the checkout stored: (item, quantity, VAT-inclusive unit price, VAT rate in %)
ORDER = [
    ("Admission, Synthetic Jazz Night", "3", "25.00", "13"),
    ("Tour T-shirt", "1", "24.90", "20"),
    ("Booking fee", "1", "2.50", "20"),
]
CHECKOUT_TOTAL = sum(Decimal(quantity) * Decimal(gross) for _, quantity, gross, _ in ORDER)

SELLER = Seller(
    name="Example Events GmbH",
    vat_identifier="ATU00000000",  # BT-31, required for category S (BR-S-02)
    postal_address=SellerPostalAddress(city="Wien", post_code="1010", country_code="AT"),
)
BUYER = Buyer(name="Max Example", postal_address=BuyerPostalAddress(country_code="AT"))
```

## Gross to net

EN 16931 prices are net: BT-146, the item net price, excludes VAT, and there is no VAT-inclusive price term (see
[Prices are net](index.md#prices-are-net)). So convert each gross unit price to net before it enters the model:

```python
NET_PRICE_DECIMALS = Decimal("0.000001")


def net_unit_price(gross: Decimal, rate: Decimal) -> Decimal:
    """The net unit price (BT-146) of a VAT-inclusive unit price: gross × 100 / (100 + rate), 6 decimals."""
    return (gross * 100 / (100 + rate)).quantize(NET_PRICE_DECIMALS, rounding=ROUND_HALF_UP)


def line(identifier: int, item: str, quantity: str, gross: str, rate: str) -> LineDraft:
    """One order line, its price converted to net, in VAT category S (standard rated) at ``rate``."""
    return LineDraft(
        identifier=str(identifier),
        invoiced_quantity=Decimal(quantity),
        invoiced_quantity_unit_code="C62",
        price_details=PriceDetails(item_net_price=net_unit_price(Decimal(gross), Decimal(rate))),
        vat_information=LineVatInformation(category_code="S", rate=Decimal(rate)),
        item=ItemInformation(name=item),
    )
```

Where the rounding happens, and why:

1. **The net unit price keeps 6 decimals.** No EN 16931 rule limits the decimals of BT-146: the BR-DEC rules
   cover amounts such as BT-131 and BT-116, not unit prices. Keeping precision here means the next rounding
   step decides the cent, not this one.
2. **The line net amount (BT-131)** is quantity × net unit price, rounded to 2 decimals half up by
   `calc.complete` (BR-DEC-23 allows 2 decimals; the formula is Peppol's PEPPOL-EN16931-R120).
3. **The VAT (BT-117)** is computed once per VAT rate, on the sum of the line net amounts at that rate, and
   rounded to 2 decimals half up (BR-CO-17). It is not the sum of per-line VAT amounts.

```python
draft = InvoiceDraft(
    number="TIX-2026-0001",
    issue_date=datetime.date(2026, 5, 2),
    type_code="380",
    currency_code="EUR",
    process_control=ProcessControl(specification_identifier="urn:cen.eu:en16931:2017"),
    seller=SELLER,
    buyer=BUYER,
    payment_instructions=PaymentInstructions(payment_means_type_code="48"),  # BT-81, a card payment code
    lines=tuple(line(number, *entry) for number, entry in enumerate(ORDER, start=1)),
)
invoice = calc.complete(draft, paid_amount=CHECKOUT_TOTAL)  # BT-113: paid at checkout
invoice_xml = to_xml(invoice, profile=profiles.EN16931, syntax="ubl")
```

(`48` is one of the card payment codes XRechnung rule BR-DE-24-a lists; XRechnung then also requires the
PAYMENT CARD INFORMATION group, BG-18.)

```python
>>> [(l.price_details.item_net_price, l.net_amount) for l in invoice.lines]
[(Decimal('22.123894'), Decimal('66.37')), (Decimal('20.750000'), Decimal('20.75')), (Decimal('2.083333'), Decimal('2.08'))]
>>> [(g.rate, g.taxable_amount, g.tax_amount) for g in invoice.vat_breakdown]  # one group per rate
[(Decimal('13'), Decimal('66.37'), Decimal('8.63')), (Decimal('20'), Decimal('22.83'), Decimal('4.57'))]
>>> invoice.totals.total_with_vat, CHECKOUT_TOTAL, invoice.totals.amount_due
(Decimal('102.40'), Decimal('102.40'), Decimal('0.00'))
```

The invoice total with VAT (BT-112) equals what the customer paid, and the amount due (BT-115) is zero.

## When a cent does not come back

Computing VAT from net and rounding twice cannot reproduce every gross price. 24.90 at 13 % is one: its net is
22.04 and the VAT on that is 2.87, so the invoice total is 24.91. **Always compare** BT-112 with what you
charged. (The example copies the order's draft with another number and line through `model_validate`, which
validates the copy; `model_copy(update=...)` would not.)

```python
late_entry = calc.complete(
    InvoiceDraft.model_validate(
        {**dict(draft), "number": "TIX-2026-0002", "lines": (line(1, "Late entry", "1", "24.90", "13"),)}
    )
)
```

```python
>>> late_entry.totals.total_with_vat
Decimal('24.91')
```

euinvoice does not adjust amounts for you. One option, if your tax advisor agrees, is to record the payment as
BT-113 and the cent as the rounding amount BT-114, so that the amount due BT-115 = BT-112 − BT-113 + BT-114
(BR-CO-16) is zero:

```python
charged = Decimal("24.90")
late_entry = calc.complete(
    InvoiceDraft.model_validate(
        {**dict(draft), "number": "TIX-2026-0002", "lines": (line(1, "Late entry", "1", "24.90", "13"),)}
    ),
    paid_amount=charged,
    rounding_amount=charged - Decimal("24.91"),
)
late_entry_xml = to_xml(late_entry, profile=profiles.EN16931, syntax="ubl")
```

```python
>>> late_entry.totals.rounding_amount, late_entry.totals.amount_due
(Decimal('-0.01'), Decimal('0.00'))
```

Other options are to choose gross prices that round-trip, or to let your checkout charge the invoice total.

## The refund: a credit note

One admission is refunded. A credit note is the same model with BT-3 `381`; in UBL it is written as a
`CreditNote` document. Its amounts are positive. BT-25 references the invoice it corrects (BG-3, and each BG-3
needs its BT-25, BR-55); BT-26 adds that invoice's date.

```python
credit_note = calc.complete(
    InvoiceDraft(
        number="TIX-2026-0001-CN1",
        issue_date=datetime.date(2026, 5, 9),
        type_code="381",
        currency_code="EUR",
        process_control=ProcessControl(specification_identifier="urn:cen.eu:en16931:2017"),
        preceding_invoice_references=(
            PrecedingInvoiceReference(reference=invoice.number, issue_date=invoice.issue_date),  # BT-25, BT-26
        ),
        seller=SELLER,
        buyer=BUYER,
        lines=(line(1, "Admission, Synthetic Jazz Night (refund)", "1", "25.00", "13"),),
    )
)
credit_note_ubl = to_xml(credit_note, profile=profiles.EN16931, syntax="ubl")
credit_note_cii = to_xml(credit_note, profile=profiles.EN16931, syntax="cii")
```

```python
>>> credit_note.totals.total_without_vat, credit_note.totals.total_vat, credit_note.totals.total_with_vat
(Decimal('22.12'), Decimal('2.88'), Decimal('25.00'))
>>> credit_note_ubl.decode().splitlines()[1][:69]
'<CreditNote xmlns="urn:oasis:names:specification:ubl:schema:xsd:Credi'
>>> parse(credit_note_ubl).preceding_invoice_references[0].reference
'TIX-2026-0001'
```

## Validate

<!-- doctest: needs-artifacts -->
```python
>>> from euinvoice import validate
>>> [validate(xml).ok for xml in (invoice_xml, late_entry_xml, credit_note_ubl, credit_note_cii)]
[True, True, True, True]
```
