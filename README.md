# euinvoice

**EN 16931 e-invoicing for Python.** You can build European e-invoices as typed models, serialize them
to **UBL** or **CII**, validate them against the **official** rule sets, parse them back, and embed them
in **Factur-X / ZUGFeRD** PDFs.

> **Status: 0.1.0, not yet released.** The API can still change before the release; see
> [`CHANGELOG.md`](CHANGELOG.md) and the [known limitations](#known-limitations).

## Why

EU e-invoicing mandates are arriving country by country, and the reference tooling is mostly Java. euinvoice
is a small, typed, MIT-licensed Python library with three principles:

- **One semantic model.** The EN 16931 business terms form a frozen, `Decimal`-only Pydantic model. UBL and CII
  are just two ways of writing it down.
- **The official rules are the judge.** Validation runs the pinned official XSD and Schematron artifacts (CEN,
  Peppol, KoSIT XRechnung) on SaxonC-HE, not a reimplementation that drifts after the next rule release.
- **Framework-free and side-effect-free.** Bytes go in and bytes come out, with no Django, no network and no
  file system in the core.

## What 0.1.0 supports

| Profile | Syntax | Generate | Parse | Validate |
|---|---|---|---|---|
| EN 16931 core | UBL 2.1, CII D16B | ✅ | ✅ | ✅ XSD + CEN |
| Peppol BIS Billing 3.0 | UBL 2.1, CII D16B | ✅ | ✅ | ✅ XSD + CEN + Peppol |
| XRechnung 3.0 (CIUS) | UBL 2.1, CII D16B | ✅ | ✅ | ✅ XSD + CEN + XRechnung |
| XRechnung 3.0 Extension | UBL 2.1, CII D16B | ✅ EN 16931 content only | ✅ extension content listed as unmapped; content outside the CEN code lists (e.g. ICD `XR03`, testsuite `04.05a` CII) raises `ParseError` | ⚠️ raw flags ([#49](https://github.com/letsrevel/euinvoice/issues/49)) |
| XRechnung 3.0 CVD | UBL 2.1, CII D16B | ❌ | ❌ conforming documents (BR-CL-13) | ⚠️ raw flags, see below |
| Factur-X 1.0 / ZUGFeRD 2.1+ EN 16931, XRECHNUNG | CII in PDF/A-3 | ✅ | ✅ | ⚠️ EN 16931 / XRechnung rules only |
| Factur-X 1.0 / ZUGFeRD 2.1+ BASIC, EXTENDED | CII in PDF/A-3 | ❌ | ✅ EXTENDED-only content listed as unmapped | ❌ |
| Factur-X 1.0 / ZUGFeRD 2.1+ MINIMUM, BASIC WL | CII in PDF/A-3 | ❌ | ❌ detected and extracted only | ❌ |
| ZUGFeRD 2.0 MINIMUM, BASIC, EXTENDED | CII in PDF/A-3 | ❌ | ✅ BASIC, EXTENDED (EXTENDED-only content listed as unmapped; corpus EXTENDED samples with codes outside the CEN lists, ABK BR-CL-19 and 9958 BR-CL-25, raise `ParseError` like their 2.1 twins, [#69](https://github.com/letsrevel/euinvoice/issues/69)); ❌ MINIMUM | ❌ |

- **Parse** means read into the EN 16931 model. Readers never drop input silently: every element or attribute
  without a business term is listed in `parse_detailed(...).unmapped`.
- **Validate** reports the raw severities of the official rule sets. KoSIT's per-scenario severity overrides are
  not applied ([#49](https://github.com/letsrevel/euinvoice/issues/49)): for example, 2 of the 6 official XRechnung Extension instances get fatal findings
  that KoSIT downgrades.
- **XRechnung CVD:** BR-DE-CVD-03 (fatal, `XRechnung-UBL-validation.sch` lines 560-562) needs an item
  classification with list id `CVD`, which BR-CL-13 (fatal, CEN `EN16931-UBL-codes.sch` lines 67-68) and
  therefore the model refuse. No *conforming* CVD invoice can be built or read. `validate()` rejects every CVD
  document: BR-CL-13 when it carries the `CVD` item classification, BR-DE-CVD-03 (fatal) when it does not
  (KoSIT downgrades BR-CL-13, [#49](https://github.com/letsrevel/euinvoice/issues/49)).
- **Factur-X:** the rows above cover the Factur-X 1.0 / ZUGFeRD 2.1+ BT-24s. `facturx.embed` / `facturx.extract`
  write and read the PDF container (the `[pdf]` extra). The
  Factur-X XSD and Schematron are not pinned yet ([#42](https://github.com/letsrevel/euinvoice/issues/42)), so
  `validate()` checks the embedded XML of the EN 16931 and XRECHNUNG levels against the EN 16931 / XRechnung
  rules only, and raises `ArtifactsNotAvailableError` for MINIMUM, BASIC WL, BASIC and EXTENDED. MINIMUM and
  BASIC WL carry no invoice lines, so they cannot become an `Invoice`: `parse()` raises `ParseError`
  ([#69](https://github.com/letsrevel/euinvoice/issues/69)). The library does not check PDF/A-3 conformance
  (the test suite runs veraPDF on `embed()` output). ZUGFeRD 2.0 PDFs are extract-only (not generated). Their
  MINIMUM, BASIC and EXTENDED BT-24s (`urn:zugferd.de:2p0:*`) and the colon spellings of BASIC and EXTENDED
  (`urn:cen.eu:en16931:2017:compliant:factur-x.eu:1p0:*`) are not registered as profiles, but `validate()` raises
  `ArtifactsNotAvailableError` for them as for the levels above (CLI exit 2;
  [#98](https://github.com/letsrevel/euinvoice/issues/98)). A ZUGFeRD 2.0 EN 16931 invoice carries the core BT-24
  and is validated as EN 16931 core.
  ZUGFeRD 1.0 PDFs are extract-only (`parse()` raises `UnsupportedDocumentError`).

Planned later: ebInterface, more national CIUSes (RO, HR, FR, DK, …), FatturaPA, KSeF, Facturae, and
clearance/transport integrations.

## Install

```bash
uv add euinvoice                    # model + UBL/CII serialize/parse
uv add 'euinvoice[validate]'        # + official Schematron validation (SaxonC-HE)
uv add 'euinvoice[pdf]'             # + Factur-X / ZUGFeRD PDF embedding
```

Until 0.1.0 is on PyPI: `uv add 'euinvoice @ git+https://github.com/letsrevel/euinvoice'`.

The official validation artifacts are **downloaded, not bundled**, because of their licences. Fetch them
once (pinned and sha256-verified):

```bash
python -m euinvoice artifacts fetch   # cache: $EUINVOICE_ARTIFACTS_DIR or ~/.cache/euinvoice
```

## Usage

`draft` is an `euinvoice.InvoiceDraft`: the invoice without its derived totals. These examples run as tests
(`tests/_readme.py` builds the synthetic XRechnung draft they use); see the [quickstart](docs/quickstart.md) for
building a draft.

```python
>>> from euinvoice import calc, detect, parse, parse_detailed, profiles, to_xml, validate
>>> invoice = calc.complete(draft)  # derive line totals, document totals and the VAT breakdown (EN 16931)
>>> xml = to_xml(invoice, profile=profiles.XRECHNUNG, syntax="cii")  # raises PreflightError on blocking findings
>>> parse(xml) == profiles.XRECHNUNG.prepare(invoice)  # lossless; to_xml wrote the profile's BT-24 (prepare)
True
>>> parse_detailed(xml).unmapped  # XPaths of input with no business term; parse() discards them
()
>>> found = detect(xml)  # syntax and profile from the root element and BT-24
>>> found.syntax, found.profile.id
(<Syntax.CII: 'cii'>, 'xrechnung')
```

Validation needs the `[validate]` extra and the fetched artifacts. `validate()` takes XML; for a PDF, pass
`facturx.extract(pdf).xml` or use the CLI.

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

## Command line

`python -m euinvoice` wraps the same functions. `FILE` is UBL, CII or a Factur-X / ZUGFeRD PDF (`-` reads
stdin), and `--profile` takes a profile id such as `xrechnung` or `peppol`.

```bash
python -m euinvoice validate invoice.xml [--profile ID] [--json]   # one line per finding, then the verdict
python -m euinvoice convert invoice.xml --to ubl|cii [--profile ID] [-o OUT]
python -m euinvoice info invoice.pdf [--json]                      # syntax, BT-24, profile, container, totals
python -m euinvoice artifacts fetch [--only NAME]
```

Exit codes: `0` success (warnings allowed); `1` the document was rejected (a `fatal` or `error` finding, a
refused conversion, an unreadable invoice) or an artifact failed its integrity check; `2` no verdict (usage
error, unknown profile, unreadable file, failed download, missing artifacts or extras, a Factur-X level whose
rules are not pinned). `--help` on each subcommand lists them.

## Documentation

The [`docs/`](docs/index.md) folder holds the guide: [quickstart](docs/quickstart.md),
[concepts](docs/concepts.md), [validation](docs/validation.md), [Factur-X](docs/facturx.md), a
[mapping guide](docs/mapping/index.md) with synthetic freelancer and ticketing examples, and the
[BT mapping](docs/reference/bt-mapping.md). It builds with `make docs` (mkdocs-material). The GitHub Pages site goes live
once the maintainer enables Pages for the repository and sets the repository variable `DOCS_DEPLOY=true`.

## Known limitations

Open questions waiting for a maintainer decision (`needs-human`) and one parked enhancement:

- [#42](https://github.com/letsrevel/euinvoice/issues/42): the Factur-X / ZUGFeRD XSD and Schematron have no
  pinnable official download, so Factur-X levels are not validated against Factur-X rules (see above).
- [#69](https://github.com/letsrevel/euinvoice/issues/69): Factur-X MINIMUM and BASIC WL cannot be read into the
  model.
- [#49](https://github.com/letsrevel/euinvoice/issues/49): KoSIT's XRechnung severity overrides are not applied,
  so the verdict can differ from the KoSIT validator in both directions (e.g. BR-CL-21/23, XRechnung Extension
  and CVD).
- [#67](https://github.com/letsrevel/euinvoice/issues/67): the XRechnung profiles set no default BT-23; the caller
  must provide it (the pre-flight reports PEPPOL-EN16931-R001 otherwise).
- [#74](https://github.com/letsrevel/euinvoice/issues/74): SaxonC-HE 13.0.0 crashes in `normalize-space()` on
  text that combines leading whitespace, a character above U+00FF and one above U+FFFF, so `validate()` reports a
  false `SCHEMATRON-RUNTIME` fatal for such invoices.
- [#40](https://github.com/letsrevel/euinvoice/issues/40): the hardened parser rejects a single text node over
  10,000,000 bytes, i.e. a BT-125 attachment over about 7.5 MB.
- [#87](https://github.com/letsrevel/euinvoice/issues/87) (parked): the UBL writer refuses an invoice without
  BT-110 (no VAT, BT-112 = BT-109), which CII can express, instead of writing `0.00`.

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
