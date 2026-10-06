# Example: a freelancer

A synthetic freelancer in Vienna bills hours of software development to three customers:

1. an Austrian company, with Austrian VAT (category `S`, 20 % in this example);
2. a German company, under the intra-EU **reverse charge** (category `AE`);
3. a company in the United States, **not subject to VAT** (category `O`).

The examples assume these treatments to show how each is encoded; they are not tax advice. Everything is
written under the EN 16931 core profile and, in the conformance suite, validated against the official CEN rules.

## Shared setup

Your billing model probably has a customer table and time entries. Here, small helpers stand in for them.

```python
import datetime
from decimal import Decimal

from euinvoice import calc, profiles, to_xml
from euinvoice.calc import ExemptionReason
from euinvoice.model import (
    Buyer,
    BuyerPostalAddress,
    CreditTransfer,
    Identifier,
    InvoiceDraft,
    InvoicingPeriod,
    DeliveryInformation,
    ItemInformation,
    LineDraft,
    LineVatInformation,
    PaymentInstructions,
    PriceDetails,
    ProcessControl,
    Seller,
    SellerContact,
    SellerPostalAddress,
)

HOURLY_RATE = Decimal("90.00")
ADDRESS = SellerPostalAddress(address_line_1="Example Gasse 1", city="Wien", post_code="1010", country_code="AT")
SELLER = Seller(
    name="Anna Example IT Services",
    vat_identifier="ATU00000000",  # BT-31, a synthetic id
    postal_address=ADDRESS,
    contact=SellerContact(email="anna@example.com"),
)


def hours(quantity: str, category: str, rate: str | None) -> LineDraft:
    """One line of development hours in VAT category ``category`` (BT-151) at ``rate`` (BT-152)."""
    return LineDraft(
        identifier="1",
        invoiced_quantity=Decimal(quantity),
        invoiced_quantity_unit_code="HUR",
        price_details=PriceDetails(item_net_price=HOURLY_RATE),
        vat_information=LineVatInformation(category_code=category, rate=None if rate is None else Decimal(rate)),
        item=ItemInformation(name="Software development (hours)"),
    )


def invoice_draft(number: str, buyer: Buyer, line: LineDraft, seller: Seller = SELLER) -> InvoiceDraft:
    """A March 2026 invoice from ``seller`` to ``buyer``, payable by SEPA credit transfer."""
    return InvoiceDraft(
        number=number,
        issue_date=datetime.date(2026, 3, 31),
        type_code="380",
        currency_code="EUR",
        payment_due_date=datetime.date(2026, 4, 30),
        process_control=ProcessControl(specification_identifier="urn:cen.eu:en16931:2017"),
        seller=seller,
        buyer=buyer,
        delivery=DeliveryInformation(
            invoicing_period=InvoicingPeriod(start_date=datetime.date(2026, 3, 1), end_date=datetime.date(2026, 3, 31))
        ),
        payment_instructions=PaymentInstructions(
            payment_means_type_code="58",  # a credit transfer code of BR-61, which then requires BT-84
            credit_transfers=(CreditTransfer(payment_account_identifier="DE02120300000000202051"),),
        ),
        lines=(line,),
    )
```

## 1. Domestic customer: standard rated (`S`)

The common case. The seller VAT identifier (BT-31), tax registration identifier (BT-32) or tax representative VAT
identifier (BT-63) is required (BR-S-02), the rate must be greater than zero
(BR-S-05), and no exemption reason is allowed (BR-S-10).

```python
domestic = calc.complete(
    invoice_draft(
        "2026-001",
        Buyer(
            name="Kunde Example GmbH",
            vat_identifier="ATU11111111",
            postal_address=BuyerPostalAddress(city="Graz", post_code="8010", country_code="AT"),
        ),
        hours("12.5", "S", "20"),
    )
)
domestic_xml = to_xml(domestic, profile=profiles.EN16931, syntax="ubl")
```

```python
>>> domestic.totals.total_without_vat, domestic.totals.total_vat, domestic.totals.amount_due
(Decimal('1125.00'), Decimal('225.00'), Decimal('1350.00'))
```

## 2. Business customer in another EU country: reverse charge (`AE`)

Under the reverse charge the buyer accounts for the VAT, so the invoice carries none. The CEN rules for category
`AE`:

| Rule | Requires |
|---|---|
| BR-AE-02 | the seller VAT identifier (BT-31), tax registration identifier (BT-32) or tax representative VAT identifier (BT-63), and the buyer VAT identifier (BT-48) or legal registration identifier (BT-47) |
| BR-AE-05 | line VAT rate (BT-152) 0 |
| BR-AE-08, BR-AE-09 | taxable amount = sum of the `AE` lines; tax amount 0 (`calc.complete` derives both) |
| BR-AE-10 | an exemption reason code (BT-121) meaning "Reverse charge", or the reason text (BT-120) "Reverse charge" |

The code comes from the CEF VATEX list (BR-CL-22): `VATEX-EU-AE`, which Peppol pairs with category `AE`
(PEPPOL-EN16931-P0107). Give both the code and the text:

```python
reverse_charge = calc.complete(
    invoice_draft(
        "2026-002",
        Buyer(
            name="Kunde Example GmbH",
            vat_identifier="DE000000000",  # BT-48, required by BR-AE-02
            postal_address=BuyerPostalAddress(city="Berlin", post_code="10115", country_code="DE"),
        ),
        hours("10", "AE", "0"),
    ),
    exemption_reasons={"AE": ExemptionReason(code="VATEX-EU-AE", text="Reverse charge")},  # BT-121, BT-120
)
reverse_charge_xml = to_xml(reverse_charge, profile=profiles.EN16931, syntax="cii")
```

```python
>>> [(g.category_code, g.taxable_amount, g.tax_amount, g.exemption_reason_code, g.exemption_reason)
...  for g in reverse_charge.vat_breakdown]
[('AE', Decimal('900.00'), Decimal('0.00'), 'VATEX-EU-AE', 'Reverse charge')]
>>> reverse_charge.totals.amount_due
Decimal('900.00')
```

Forgetting the exemption reason is caught before writing (BR-AE-10 is one of the VAT category rules
`calc.check` evaluates):

```python
>>> from euinvoice.errors import PreflightError
>>> no_reason = calc.complete(invoice_draft("2026-002", reverse_charge.buyer, hours("10", "AE", "0")))
>>> try:
...     to_xml(no_reason, profile=profiles.EN16931, syntax="cii")
... except PreflightError as error:
...     print([finding.rule_id for finding in error.findings])
['BR-AE-10']
```

A missing buyer VAT identifier is not among the rules `calc.check` evaluates, so `to_xml` writes the document;
the official rules reject it (BR-AE-02). This is why you validate before sending:

<!-- doctest: needs-artifacts -->
```python
>>> from euinvoice import validate
>>> anonymous_buyer = Buyer(name="Kunde Example GmbH", postal_address=reverse_charge.buyer.postal_address)
>>> no_buyer_vat = calc.complete(
...     invoice_draft("2026-002", anonymous_buyer, hours("10", "AE", "0")),
...     exemption_reasons={"AE": ExemptionReason(code="VATEX-EU-AE", text="Reverse charge")},
... )
>>> sorted(f.rule_id for f in validate(to_xml(no_buyer_vat, profile=profiles.EN16931, syntax="cii")).findings)
['BR-AE-02']
```

## 3. Customer outside the EU: not subject to VAT (`O`) or export (`G`)?

For a supply to a customer outside the EU, the categories most often considered are `G` (Export outside the EU)
and `O` (Not subject to VAT; the Peppol example `rules/examples/vat-category-O.xml` labels it "Outside scope of
VAT"). Their rules differ:

| | `G` Export outside the EU | `O` Not subject to VAT |
|---|---|---|
| VAT identifiers | seller VAT identifier (BT-31) or tax representative's (BT-63) **required** (BR-G-02) | seller (BT-31), tax representative (BT-63) and buyer (BT-48) VAT identifiers **forbidden** (BR-O-02) |
| Line VAT rate (BT-152) | 0 (BR-G-05) | absent (BR-O-05) |
| Other categories on the invoice | allowed | **none**: no other VAT breakdown, line, allowance or charge category (BR-O-11 … BR-O-14) |
| Exemption reason | a code meaning "Export outside the EU" (e.g. `VATEX-EU-G`, paired with `G` by PEPPOL-EN16931-P0104) or that text (BR-G-10) | a code meaning "Not subject to VAT" (e.g. `VATEX-EU-O`, paired with `O` by PEPPOL-EN16931-P0105) or that text (BR-O-10) |

Which one a supply is, is a tax question.
This example assumes the freelancer's services to a US business are outside the scope of Austrian VAT, so it
uses `O`. Two consequences follow from the rules above:

- The invoice must not show the seller's VAT identifier (BR-O-02). BR-CO-26 still requires a way to identify
  the seller: the seller identifier (BT-29), the legal registration identifier (BT-30) or the VAT identifier. The
  example uses a synthetic seller identifier.
- `O` lines cannot share an invoice with `S` or `AE` lines (BR-O-11 … BR-O-14). Bill them separately.

```python
SELLER_WITHOUT_VAT_ID = Seller(
    name=SELLER.name,
    identifiers=(Identifier(value="SELLER-0001"),),  # BT-29, for BR-CO-26
    postal_address=ADDRESS,
    contact=SELLER.contact,
)
outside_scope = calc.complete(
    invoice_draft(
        "2026-003",
        Buyer(
            name="Client Example Inc.",
            postal_address=BuyerPostalAddress(city="New York", post_code="10001", country_code="US"),
        ),
        hours("8", "O", None),  # no rate: BR-O-05
        seller=SELLER_WITHOUT_VAT_ID,
    ),
    exemption_reasons={"O": ExemptionReason(code="VATEX-EU-O", text="Not subject to VAT")},
)
outside_scope_xml = to_xml(outside_scope, profile=profiles.EN16931, syntax="ubl")
```

```python
>>> [(g.category_code, g.rate, g.taxable_amount, g.tax_amount) for g in outside_scope.vat_breakdown]
[('O', None, Decimal('720.00'), Decimal('0.00'))]
```

With the usual seller (and its VAT identifier) the official rules reject the invoice:

<!-- doctest: needs-artifacts -->
```python
>>> with_vat_id = calc.complete(
...     invoice_draft("2026-003", outside_scope.buyer, hours("8", "O", None)),
...     exemption_reasons={"O": ExemptionReason(code="VATEX-EU-O", text="Not subject to VAT")},
... )
>>> sorted(f.rule_id for f in validate(to_xml(with_vat_id, profile=profiles.EN16931, syntax="ubl")).findings)
['BR-O-02']
```

## Validate all three

<!-- doctest: needs-artifacts -->
```python
>>> [validate(xml).ok for xml in (domestic_xml, reverse_charge_xml, outside_scope_xml)]
[True, True, True]
```
