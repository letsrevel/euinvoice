# Quickstart

This page builds one invoice, derives its totals, writes it as UBL and CII, validates it against the
official rules, and reads it back. The seller, buyer and identifiers are synthetic.

## 1. Build a draft

An [`InvoiceDraft`](reference/api.md#euinvoice.model.InvoiceDraft) is an invoice without the amounts that
can be derived: the line net amounts (BT-131), the document totals (BG-22) and the VAT breakdown (BG-23).
Amounts, quantities, prices and rates are `Decimal`; a `float` is rejected.

```python
import datetime
from decimal import Decimal

from euinvoice import calc, parse, profiles, to_xml
from euinvoice.model import (
    Buyer,
    BuyerPostalAddress,
    CreditTransfer,
    InvoiceDraft,
    ItemInformation,
    LineDraft,
    LineVatInformation,
    PaymentInstructions,
    PriceDetails,
    ProcessControl,
    Seller,
    SellerPostalAddress,
)

draft = InvoiceDraft(
    number="2026-0001",  # BT-1
    issue_date=datetime.date(2026, 3, 31),  # BT-2
    type_code="380",  # BT-3, UNTDID 1001 (BR-CL-01); see Concepts
    currency_code="EUR",  # BT-5
    payment_due_date=datetime.date(2026, 4, 30),  # BT-9
    process_control=ProcessControl(specification_identifier="urn:cen.eu:en16931:2017"),  # BT-24
    seller=Seller(
        name="Seller Example GmbH",  # BT-27
        vat_identifier="ATU00000000",  # BT-31
        postal_address=SellerPostalAddress(city="Wien", post_code="1010", country_code="AT"),
    ),
    buyer=Buyer(
        name="Buyer Example GmbH",  # BT-44
        vat_identifier="ATU11111111",  # BT-48
        postal_address=BuyerPostalAddress(city="Graz", post_code="8010", country_code="AT"),
    ),
    payment_instructions=PaymentInstructions(
        payment_means_type_code="58",  # BT-81
        credit_transfers=(CreditTransfer(payment_account_identifier="DE02120300000000202051"),),  # BT-84
    ),
    lines=(
        LineDraft(
            identifier="1",  # BT-126
            invoiced_quantity=Decimal("10"),  # BT-129
            invoiced_quantity_unit_code="HUR",  # BT-130, UN/ECE Rec 20/21 (BR-CL-23)
            price_details=PriceDetails(item_net_price=Decimal("95.00")),  # BT-146
            vat_information=LineVatInformation(category_code="S", rate=Decimal("20")),  # BT-151, BT-152
            item=ItemInformation(name="Consulting (hours)"),  # BT-153
        ),
        LineDraft(
            identifier="2",
            invoiced_quantity=Decimal("1"),
            invoiced_quantity_unit_code="C62",
            price_details=PriceDetails(item_net_price=Decimal("25.00")),
            vat_information=LineVatInformation(category_code="S", rate=Decimal("20")),
            item=ItemInformation(name="Hosting, March 2026"),
        ),
    ),
)
```

## 2. Derive the totals

[`calc.complete`](reference/api.md#euinvoice.calc.complete) derives every line net amount, the document
totals and one VAT breakdown per VAT category and rate, using the EN 16931 rules (BR-CO-10 … BR-CO-17) and
rounding money to two decimals, half up.

```python
>>> invoice = calc.complete(draft)
>>> [line.net_amount for line in invoice.lines]
[Decimal('950.00'), Decimal('25.00')]
>>> invoice.totals.total_without_vat, invoice.totals.total_vat, invoice.totals.amount_due
(Decimal('975.00'), Decimal('195.00'), Decimal('1170.00'))
>>> [(group.category_code, group.rate, group.taxable_amount, group.tax_amount) for group in invoice.vat_breakdown]
[('S', Decimal('20'), Decimal('975.00'), Decimal('195.00'))]
>>> calc.check(invoice)  # the CEN arithmetic and VAT category rules: no findings
()
```

## 3. Write XML

[`to_xml`](reference/api.md#euinvoice.to_xml) writes the invoice under a [profile](concepts.md#profiles).
Before writing, it runs the profile's pre-flight checks and `calc.check`, and raises `PreflightError` when
the official rules would reject the document.

```python
>>> ubl = to_xml(invoice, profile=profiles.EN16931, syntax="ubl")
>>> cii = to_xml(invoice, profile=profiles.EN16931, syntax="cii")
>>> ubl.decode().splitlines()[1][:60]
'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd'
>>> parse(ubl) == parse(cii) == profiles.EN16931.prepare(invoice)  # both read back to the same model
True
```

## 4. Validate

Validation runs the official XSD and Schematron. It needs the `[validate]` extra and the fetched artifacts
(see [Validation](validation.md)).

<!-- doctest: needs-artifacts -->
```python
>>> from euinvoice import validate
>>> validate(ubl).ok, validate(cii).ok
(True, True)
```
