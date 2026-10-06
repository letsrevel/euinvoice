# Factur-X / ZUGFeRD

A Factur-X (or ZUGFeRD 2.x) invoice is a PDF/A-3 that people can read, with the CII XML of the same invoice
embedded as an associated file. euinvoice does the embedding and the extraction. It does **not** render the
human-readable PDF; your renderer does.

```bash
uv add 'euinvoice[pdf]'   # pypdf
```

## Levels

| Profile | Embedded file | XMP `fx:ConformanceLevel` | Write | Read |
|---|---|---|---|---|
| `profiles.FACTURX_EN16931` | `factur-x.xml` | `EN 16931` | yes | yes |
| `profiles.FACTURX_XRECHNUNG` | `xrechnung.xml` | `XRECHNUNG` | yes | yes |
| `profiles.FACTURX_MINIMUM`, `FACTURX_BASIC_WL`, `FACTURX_BASIC`, `FACTURX_EXTENDED` | `factur-x.xml` | `MINIMUM`, `BASIC WL`, `BASIC`, `EXTENDED` | no | yes (the EN 16931 subset) |

## 1. Render a PDF/A-3

The PDF you embed into must already be PDF/A-3 (its XMP must say `pdfaid:part` 3); `embed` raises `PdfError`
otherwise. [WeasyPrint](https://weasyprint.org/) can render HTML straight to PDF/A-3b.

!!! info "Illustration, not run"
    euinvoice does not depend on WeasyPrint, so this block is **not executed** by the documentation tests (they
    only check that it is valid Python). Check the WeasyPrint documentation for your version.

<!-- doctest: illustration -->
```python
from weasyprint import HTML  # not a dependency of euinvoice

invoice_html = "<html><body><h1>Invoice 2026-0001</h1>...</body></html>"  # your template
rendered_pdf = HTML(string=invoice_html).write_pdf(pdf_variant="pdf/a-3b")
```

The examples below continue the [Quickstart](quickstart.md) (`invoice` is its EN 16931 invoice). In the
documentation tests, `rendered_pdf` is a blank one-page PDF/A-3B made with pypdf instead of WeasyPrint's output.

## 2. Embed the invoice

[`facturx.embed`](reference/api.md#euinvoice.facturx.embed) writes the CII XML for the level, attaches it under
the level's file name and adds the Factur-X properties to the XMP. The rest of the PDF stays as it is.

```python
>>> from euinvoice import facturx, parse, profiles
>>> hybrid_pdf = facturx.embed(rendered_pdf, invoice, profile=profiles.FACTURX_EN16931)
>>> hybrid_pdf[:5]
b'%PDF-'
```

`embed` does not run the pre-flight checks. To get them, write the XML with `to_xml` first and embed the bytes:
`facturx.embed(rendered_pdf, to_xml(invoice, profile=profiles.FACTURX_EN16931), profile=profiles.FACTURX_EN16931)`.

```python
>>> from euinvoice import to_xml
>>> xml = to_xml(invoice, profile=profiles.FACTURX_EN16931)  # CII, the only syntax of the level
>>> facturx.embed(rendered_pdf, xml, profile=profiles.FACTURX_EN16931) == hybrid_pdf
True
```

## 3. Read it back

[`facturx.extract`](reference/api.md#euinvoice.facturx.extract) finds the invoice attachment through the XMP,
and [`parse`](reference/api.md#euinvoice.parse) accepts a PDF directly.

```python
>>> found = facturx.extract(hybrid_pdf)
>>> found.filename, found.conformance_level, found.profile.id
('factur-x.xml', 'EN 16931', 'facturx-en16931')
>>> found.xml == xml
True
>>> parse(hybrid_pdf) == profiles.FACTURX_EN16931.prepare(invoice)
True
```

## 4. Validate the embedded XML

The Factur-X Schematron is not pinned yet ([#42](https://github.com/letsrevel/euinvoice/issues/42)). The EN 16931
level uses the EN 16931 BT-24, so validate the extracted XML against the EN 16931 rules:

<!-- doctest: needs-artifacts -->
```python
>>> from euinvoice import validate
>>> validate(found.xml, profiles.EN16931).ok
True
```

Whether the PDF itself is valid PDF/A-3 is up to your renderer; euinvoice's own conformance suite checks the
PDFs it writes with veraPDF.
