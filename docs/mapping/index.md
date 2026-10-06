# From your billing model to `Invoice`

Your application has its own idea of an invoice: orders, customers, products, price lists, tax settings. This
guide shows how to map it onto the EN 16931 model. Two worked examples follow:

- [Freelancer](freelancer.md): one seller, three kinds of customer (domestic with VAT, intra-EU reverse charge,
  outside the EU).
- [Ticketing](ticketing.md): VAT-inclusive prices at several rates, converted to net, and a credit note for a
  refund.

!!! warning "Tax decisions are yours"
    euinvoice encodes a VAT treatment; it does not choose one. Which VAT category and rate apply to a supply is a
    tax-law question for you or your advisor. The examples use synthetic parties and assume a treatment so that
    they can show how to encode it. The official rules then check that the encoding is consistent.

## The recipe

1. **Build an [`InvoiceDraft`](../reference/api.md#euinvoice.model.InvoiceDraft)**, not an `Invoice`. Leave the
   line net amounts, totals and VAT breakdown to [`calc.complete`](../reference/api.md#euinvoice.calc.complete),
   so they follow the EN 16931 rounding and sum rules (BR-CO-10 … BR-CO-17).
2. **Use `Decimal` (or strings) for every number.** Convert at your boundary. A `float` is rejected.
3. **Map each line to one VAT category and rate** (BT-151, BT-152). `complete` groups the lines into one VAT
   breakdown per category and rate.
4. **Give the exemption reason for every category that needs one** (E, AE, K, G, O: BR-E-10, BR-AE-10, BR-IC-10,
   BR-G-10, BR-O-10) through `complete(..., exemption_reasons={...})`.
5. **Write with [`to_xml`](../reference/api.md#euinvoice.to_xml)** under the profile your receiver expects, and
   **[`validate`](../reference/api.md#euinvoice.validate)** the result before you send it.

## Where things go

| In your billing model | EN 16931 | Model field |
|---|---|---|
| Invoice number | BT-1 | `number` |
| Invoice date | BT-2 | `issue_date` |
| Invoice or credit note | BT-3 | `type_code` (`"380"`, `"381"`; see [Concepts](../concepts.md#document-types)) |
| Currency | BT-5 | `currency_code` |
| Due date / payment terms | BT-9 / BT-20 | `payment_due_date` / `payment_terms` |
| Customer's PO number / reference | BT-13 / BT-10 | `purchase_order_reference` / `buyer_reference` |
| Your company | BG-4 | `seller` ([`Seller`](../reference/api.md#euinvoice.model.Seller)) |
| Your VAT number | BT-31 | `seller.vat_identifier` |
| Customer | BG-7 | `buyer` ([`Buyer`](../reference/api.md#euinvoice.model.Buyer)) |
| Customer VAT number | BT-48 | `buyer.vat_identifier` |
| Bank account | BG-16, BG-17 | `payment_instructions.credit_transfers` |
| Order line | BG-25 | `lines[]` ([`LineDraft`](../reference/api.md#euinvoice.model.LineDraft)) |
| Quantity and unit | BT-129, BT-130 | `invoiced_quantity`, `invoiced_quantity_unit_code` (UN/ECE Rec 20/21, BR-CL-23) |
| Net unit price | BT-146 | `price_details.item_net_price` |
| Product name | BT-153 | `item.name` |
| Tax class of the line | BT-151, BT-152 | `vat_information.category_code`, `vat_information.rate` |
| Service period | BG-14 / BG-26 | `delivery.invoicing_period` / `lines[].period` |
| Already paid (e.g. at checkout) | BT-113 | `calc.complete(..., paid_amount=...)` |
| Invoice a credit note corrects | BT-25, BT-26 | `preceding_invoice_references` |
| Free-text notes | BG-1 | `notes` |

[BT mapping](../reference/bt-mapping.md) has every term.

## Prices are net

BT-146, the item net price, excludes VAT. EN 16931 has no VAT-inclusive line price: the item gross price BT-148
is the price *before the item price discount* BT-147, not a price with VAT (Peppol rule PEPPOL-EN16931-R046:
BT-146 = BT-148 − BT-147). If your prices include VAT, convert them to net; the
[ticketing example](ticketing.md) shows how, and what that does to rounding.
