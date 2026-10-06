# euinvoice

**EN 16931 e-invoicing for Python.** You can build European e-invoices as typed models, serialize them
to **UBL** or **CII**, validate them against the **official** rule sets, parse them back, and embed them
in **Factur-X / ZUGFeRD** PDFs.

> 🚧 **Pre-alpha.** The API below is the target design and is being built in the open. See
> [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) and the "v0.1.0 build-out" tracking issue.

## Why

EU e-invoicing mandates are arriving country by country, and the reference tooling is mostly Java. euinvoice
is a small, typed, MIT-licensed Python library with three principles:

- **One semantic model.** The EN 16931 business terms (BT-1…BT-165) form a frozen, `Decimal`-only
  Pydantic model. UBL and CII are just two ways of writing it down.
- **The official rules are the judge.** Validation runs the official CEN, Peppol, XRechnung and
  Factur-X XSD and Schematron artifacts (via SaxonC-HE), not a reimplementation that drifts after
  the next rule release.
- **Framework-free and side-effect-free.** Bytes go in and bytes come out, with no Django, no network
  and no file system in the core.

## Supported (v0.1.0 target)

| Profile | Syntax | Generate | Parse | Validate |
|---|---|---|---|---|
| EN 16931 core | UBL 2.1, CII | ✅ | ✅ | ✅ |
| Peppol BIS Billing 3.0 | UBL 2.1 | ✅ | ✅ | ✅ |
| XRechnung 3.0 | UBL 2.1, CII | ✅ | ✅ | ✅ |
| Factur-X / ZUGFeRD EN16931 + XRECHNUNG | CII in PDF/A-3 | ✅ | ✅ | ✅ |
| Factur-X / ZUGFeRD MINIMUM, BASIC WL, BASIC, EXTENDED | CII in PDF/A-3 | — | ✅ | ✅ |

Planned later: ebInterface, more national CIUSes (RO, HR, FR, DK, …), FatturaPA, KSeF, Facturae, and
clearance/transport integrations.

## Install

```bash
uv add euinvoice                    # model + UBL/CII serialize/parse
uv add 'euinvoice[validate]'        # + official Schematron validation (SaxonC-HE)
uv add 'euinvoice[pdf]'             # + Factur-X / ZUGFeRD PDF embedding
```

The official validation artifacts are **downloaded, not bundled**, because of their licences. Fetch them
once (pinned and sha256-verified):

```bash
python -m euinvoice artifacts fetch   # cache: $EUINVOICE_ARTIFACTS_DIR or ~/.cache/euinvoice
```

## Usage

`draft` is an `euinvoice.InvoiceDraft`: the invoice without its derived totals. These examples run as tests
(`tests/_readme.py` builds the synthetic XRechnung draft they use).

```python
>>> from euinvoice import calc, parse, parse_detailed, profiles, to_xml, validate
>>> invoice = calc.complete(draft)  # derive line totals, document totals and the VAT breakdown (EN 16931)
>>> xml = to_xml(invoice, profile=profiles.XRECHNUNG, syntax="cii")  # raises PreflightError on blocking findings
>>> parse(xml) == profiles.XRECHNUNG.prepare(invoice)  # lossless; to_xml wrote the profile's BT-24 (prepare)
True
>>> parse_detailed(xml).unmapped  # XPaths of input with no business term; parse() discards them
()
```

Validation needs the `[validate]` extra and the fetched artifacts:

<!-- readme-doctest: needs-artifacts -->
```python
>>> report = validate(xml)  # profile auto-detected from BT-24
>>> report.ok
True
>>> for finding in report.findings:
...     print(finding.rule_id, finding.severity, finding.message)
```

Factur-X / ZUGFeRD needs the `[pdf]` extra:

```python
>>> from euinvoice import facturx
>>> # your renderer produces the human-readable PDF/A-3 (e.g. WeasyPrint pdf_variant="pdf/a-3b")
>>> hybrid_pdf = facturx.embed(rendered_pdf, invoice, profile=profiles.FACTURX_EN16931)
>>> found = facturx.extract(hybrid_pdf)
>>> found.filename, found.conformance_level, found.profile.id
('factur-x.xml', 'EN 16931', 'facturx-en16931')
>>> parse(hybrid_pdf) == profiles.FACTURX_EN16931.prepare(invoice)  # parse() reads PDFs too
True
```

## Development

```bash
make setup        # uv sync --all-extras --group dev
make check        # ruff + mypy --strict + file length
make test         # unit tests, ≥95% branch coverage
make artifacts    # fetch official artifacts + corpora
make conformance  # run them
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Security reports: [`SECURITY.md`](SECURITY.md).

## Licence

MIT. Official validation artifacts are third-party works under their own licences (EUPL-1.2,
Apache-2.0 and others). They are fetched at runtime and never redistributed by this package.
