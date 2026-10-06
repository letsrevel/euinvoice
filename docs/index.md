# euinvoice

**EN 16931 e-invoicing for Python.** Build European e-invoices as typed models, serialize them to **UBL 2.1**
or **UN/CEFACT CII**, validate them against the **official** rule sets, parse them back, and embed them in
**Factur-X / ZUGFeRD** PDFs.

!!! warning "Pre-alpha"
    The library is being built in the open towards v0.1.0. APIs can still change. See the
    [changelog](https://github.com/letsrevel/euinvoice/blob/main/CHANGELOG.md).

## What it does

| Step | Function | Needs |
|---|---|---|
| Build an invoice and derive its totals | [`calc.complete`](reference/api.md#euinvoice.calc.complete) | core |
| Write UBL or CII under a profile | [`to_xml`](reference/api.md#euinvoice.to_xml) | core |
| Validate against the official XSD and Schematron | [`validate`](reference/api.md#euinvoice.validate) | `[validate]` extra and fetched artifacts |
| Read UBL, CII or a Factur-X PDF back | [`parse`](reference/api.md#euinvoice.parse) | core (`[pdf]` for PDFs) |
| Embed the CII XML into a PDF/A-3 | [`facturx.embed`](reference/api.md#euinvoice.facturx.embed) | `[pdf]` extra |

## Install

```bash
uv add euinvoice                    # model + UBL/CII serialize/parse
uv add 'euinvoice[validate]'        # + official Schematron validation (SaxonC-HE)
uv add 'euinvoice[pdf]'             # + Factur-X / ZUGFeRD PDF embedding
```

The official validation artifacts are downloaded, not bundled, because of their licences
([Artifact licences](reference/artifacts.md)). Fetch them once:

```bash
python -m euinvoice artifacts fetch   # cache: $EUINVOICE_ARTIFACTS_DIR or ~/.cache/euinvoice
```

## Where to go next

- [Quickstart](quickstart.md): one invoice from draft to validated XML.
- [Concepts](concepts.md): the model, business terms, profiles and syntaxes.
- [Validation](validation.md): artifacts, `validate()` and findings.
- [Factur-X / ZUGFeRD](facturx.md): hybrid PDF invoices.
- [Mapping guide](mapping/index.md): from your billing model to `Invoice`, with a freelancer and a ticketing
  example.

Every Python example in these pages runs as a test (`tests/test_docs.py`), and the ones that claim an invoice is
valid are validated against the official rules in the conformance suite (`make conformance`). All data in them
is synthetic.
