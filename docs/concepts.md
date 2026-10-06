# Concepts

## One semantic model

EN 16931-1 defines an invoice as a set of **business terms** (BT-1 … BT-165) grouped into **business groups**
(BG-1 … BG-32). euinvoice models exactly that, once: [`Invoice`](reference/api.md#euinvoice.model.Invoice) is
the root, and UBL and CII are two ways of writing it down. An invoice and a credit note share the model; the
invoice type code BT-3 tells them apart.

The model is a set of frozen Pydantic v2 classes:

- **Immutable.** Build a new object instead of changing one. `model_copy(update=...)` skips validation, so use
  the constructor or `model_validate`.
- **`Decimal` only.** Amounts, quantities, prices and rates are `Decimal` (or a numeric string). A `float` is
  rejected, because binary floats cannot hold most decimal values exactly.
- **Readable names, official ids.** Fields have snake_case names, and each one carries its BT or BG id.
  [`path_of`](reference/api.md#euinvoice.model.path_of) and [`id_of`](reference/api.md#euinvoice.model.id_of)
  translate between the two, and error messages cite the ids.

```python
>>> from decimal import Decimal
>>> from euinvoice.model import PriceDetails, id_of, path_of
>>> path_of("BT-31"), id_of("seller.vat_identifier")
('seller.vat_identifier', 'BT-31')
>>> PriceDetails(item_net_price=1.10)
Traceback (most recent call last):
...
pydantic_core._pydantic_core.ValidationError: 1 validation error for PriceDetails
item_net_price
  Value error, float is not accepted for amounts, quantities, prices or rates (got 1.1): ...
>>> PriceDetails(item_net_price=Decimal("1.10")).item_net_price
Decimal('1.10')
```

[BT mapping](reference/bt-mapping.md) lists every id with its model path, cardinality, UBL XPath and CII XPath.

### Drafts and derived amounts

[`InvoiceDraft`](reference/api.md#euinvoice.model.InvoiceDraft) is the invoice without the amounts that can be
derived: BT-131 per line, the DOCUMENT TOTALS (BG-22) and the VAT BREAKDOWN (BG-23).
[`calc.complete`](reference/api.md#euinvoice.calc.complete) derives them per the CEN rules (pinned
`validation-1.3.16`):

| Derived | Rule |
|---|---|
| BT-131 line net amount | BT-129 × BT-146 / BT-149 + line charges − line allowances, rounded to 2 decimals half up (formula of Peppol rule PEPPOL-EN16931-R120; EN 16931 itself only limits BT-131 to 2 decimals, BR-DEC-23) |
| BT-106 … BT-109 | sums of the line net amounts, allowances and charges (BR-CO-10 … BR-CO-13) |
| BG-23 VAT breakdown | one group per VAT category code and rate; BT-117 = BT-116 × BT-119 / 100, rounded to 2 decimals (BR-CO-17) |
| BT-110, BT-112, BT-115 | BR-CO-14, BR-CO-15, BR-CO-16 |

You can also supply the totals yourself and build an `Invoice` directly;
[`calc.check`](reference/api.md#euinvoice.calc.check) then reports every inconsistency with its official rule id.

### Document types

BT-3 takes any code of UNTDID 1001 that the CEN rules accept (BR-CL-01). The two most common:

| BT-3 | Meaning | UBL root |
|---|---|---|
| `380` | Commercial invoice | `Invoice` |
| `381` | Credit note | `CreditNote` |

The meanings are the names XRechnung rule BR-DE-17 gives the codes; the UBL root follows from the CEN code list
binding of BR-CL-01. [`model.codes.DocumentType`](reference/api.md#euinvoice.model.codes.DocumentType) names
the codes whose meaning the pinned rules state.

### VAT categories

Every line, document level allowance and charge has a VAT category code (UNTDID 5305 as restricted by EN 16931,
BR-CL-17/BR-CL-18). Each category has its own rules `BR-<x>-01` … `BR-<x>-10` in the CEN Schematron. The names
below are the ones those rules use ([`model.codes.VatCategory`](reference/api.md#euinvoice.model.codes.VatCategory)).

| Code | Name | Rate (BT-152) | Exemption reason (BT-120/BT-121) |
|---|---|---|---|
| `S` | Standard rated | greater than zero (BR-S-05) | not allowed (BR-S-10) |
| `Z` | Zero rated | 0 (BR-Z-05) | not allowed (BR-Z-10) |
| `E` | Exempt from VAT | 0 (BR-E-05) | required (BR-E-10) |
| `AE` | Reverse charge | 0 (BR-AE-05) | required (BR-AE-10) |
| `K` | Intra-community supply | 0 (BR-IC-05) | required (BR-IC-10) |
| `G` | Export outside the EU | 0 (BR-G-05) | required (BR-G-10) |
| `O` | Not subject to VAT | absent (BR-O-05) | required (BR-O-10) |
| `L` | IGIC | zero or greater (BR-AF-05; the CII binding tests greater than zero) | not allowed (BR-AF-10) |
| `M` | IPSI | zero or greater (BR-AG-05) | not allowed (BR-AG-10) |

The tenth code, `B` (split payment), is for domestic Italian invoices only (BR-B-01).

`calc.complete` takes the exemption reasons as an argument, per category, and copies them to every VAT
breakdown of that category. The [freelancer example](mapping/freelancer.md) shows `AE` and `O`.

## Profiles

A **profile** is a set of rules on top of EN 16931: a CIUS such as XRechnung or Peppol BIS, or a Factur-X level.
It declares the specification identifier (BT-24) written into the document, the syntaxes it supports and the
official rule sets that validate it.

| Profile | `id` | Syntaxes | Rule sets |
|---|---|---|---|
| `profiles.EN16931` | `en16931` | UBL, CII | CEN |
| `profiles.PEPPOL` | `peppol` | UBL, CII | CEN, Peppol BIS Billing 3.0 |
| `profiles.XRECHNUNG` | `xrechnung` | UBL, CII | CEN, XRechnung 3.0 |
| `profiles.XRECHNUNG_CVD`, `profiles.XRECHNUNG_EXTENSION` | `xrechnung-cvd`, `xrechnung-extension` | UBL, CII | CEN, XRechnung 3.0 |
| `profiles.FACTURX_EN16931` | `facturx-en16931` | CII (in a PDF) | CEN |
| `profiles.FACTURX_XRECHNUNG` | `facturx-xrechnung` | CII (in a PDF) | CEN, XRechnung 3.0 |
| `profiles.FACTURX_MINIMUM`, `FACTURX_BASIC_WL`, `FACTURX_BASIC`, `FACTURX_EXTENDED` | `facturx-minimum`, … | CII (in a PDF) | Factur-X (read only, see [Factur-X](facturx.md)) |

```python
>>> from euinvoice import profiles
>>> profiles.XRECHNUNG.specification_identifier
'urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0'
>>> profiles.get("urn:cen.eu:en16931:2017") is profiles.EN16931  # look a profile up by BT-24
True
```

`to_xml(invoice, profile=...)` first calls `profile.prepare(invoice)`: BT-24 becomes the profile's, and BT-23
gets the profile's default business process when the invoice has none (Peppol:
`urn:fdc:peppol.eu:2017:poacc:billing:01:1.0`). So what you read back is `profile.prepare(invoice)`. The
profile's **pre-flight** checks then report missing terms the profile requires (for example Peppol's electronic
addresses) before anything is written. The official Schematron still decides; pre-flight only gives an earlier,
friendlier message.

## Syntaxes

| Syntax | Standard | Root element |
|---|---|---|
| `Syntax.UBL` / `"ubl"` | OASIS UBL 2.1 | `Invoice` or `CreditNote` |
| `Syntax.CII` / `"cii"` | UN/CEFACT Cross Industry Invoice D16B | `rsm:CrossIndustryInvoice` |

Writing follows the XSD element order of each syntax. Reading detects the syntax from the root element, so
[`parse`](reference/api.md#euinvoice.parse) takes either (or a Factur-X PDF). Input that has no business term
in the model is dropped by `parse` and listed by [`parse_detailed`](reference/api.md#euinvoice.parse_detailed).
[BT coverage](reference/bt-coverage.md) shows the write and read tests behind every term in both syntaxes.

## No I/O in the core

The core does no I/O and no network access: bytes go in and bytes come out. The one exception is the explicit
artifact fetcher (`python -m euinvoice artifacts fetch`). `validate()` never downloads anything.
