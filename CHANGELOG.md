# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Top-level API (#27): `euinvoice.to_xml(invoice, *, profile=None, syntax=None)` prepares the invoice for the
  profile (default: the one registered for its BT-24), runs the profile's pre-flight checks and
  `calc.check(prepared, syntax=...)`, and refuses with the new `euinvoice.errors.PreflightError` (carrying the
  findings, the profile id and the syntax; picklable) on any `fatal` / `error` finding before writing UBL or
  CII (`syntax` may be omitted when the profile has one syntax); it refuses the Factur-X levels that are not
  generated (MINIMUM, BASIC WL, BASIC, EXTENDED). `euinvoice.parse()` / `parse_detailed()` read UBL, CII and
  Factur-X / ZUGFeRD PDFs (via `facturx.extract`, imported lazily); `parse()` discards `ParseResult.unmapped`.
  `euinvoice` re-exports `validate`, `detect`, `Invoice`, `InvoiceDraft`, `ParseResult`, `Syntax`,
  `ValidationReport`, `calc`, `profiles` and a lazily imported `facturx` (not in `__all__`; `import euinvoice` and
  `from euinvoice import *` load neither pypdf nor saxonche), with an explicit `__all__`.
  `from euinvoice.detect import is_pdf` is the PDF sniff `detect` and `parse` share.
- The README usage examples are doctests (`tests/test_readme.py`; the validation block in `make conformance`).
- Cross-syntax conformance (#30, `tests/conformance/test_cross_syntax.py`): every upstream sample that reads goes
  UBL → model → CII → model (and CII → model → UBL → model) and comes back equal up to the documented writer
  normalizations, with nothing unmapped, and the other syntax's output is validated under the sample's profile.
  Writer refusals and blocking findings are listed exactly in the `[[cross_syntax]]` section of
  `expected_invalid.toml`. A Hypothesis property checks the same round trip for random invoices expressible in both
  syntaxes.
- BT coverage gate (`tests/syntax/test_bt_coverage.py`): fails if any EN 16931 term or group lacks a write
  and a read test in UBL and in CII (or a reasoned exemption), and generates `docs/reference/bt-coverage.md`
  (197 ids, all covered in all four cells, no exemptions).
- Property-based conformance tests (#31): Hypothesis invoices built through `calc.complete` (VAT categories S, Z,
  E, AE, K, G, O, allowances and charges, credit notes, BT-6, payment means) pass `calc.check`, validate without
  fatal or error findings under EN 16931, Peppol BIS and XRechnung in UBL and CII, and round-trip exactly
  through UBL and CII. The test suite's Hypothesis profile has no deadline.
- Conformance corpus harness (`tests/conformance/test_corpus_harness.py`): the plan §4 round-trip invariant over
  every pinned upstream example (CEN UBL/CII, Peppol BIS, KoSIT XRechnung testsuite, ZUGFeRD corpus XML and the
  XML of its Factur-X PDFs). `tests/conformance/expected_invalid.toml` is the only list of invariant failures,
  each with its exact rule ids, a reason and an upstream link.
- `euinvoice.facturx.embed()` (the `[pdf]` extra, pypdf only): embeds an invoice's CII XML, given as bytes or
  as an `Invoice` (EN 16931 and XRECHNUNG levels), into a PDF that is already PDF/A-3 (a non-PDF/A-3 input raises
  `PdfError`). It writes the associated file (`factur-x.xml` / `xrechnung.xml`, `/AFRelationship`, `text/xml`,
  `/ModDate`, catalog `/AF`) and the Factur-X XMP with its PDF/A extension schema, using the values the pinned
  ZUGFeRD corpus attests until the Factur-X spec package is pinned (#42). The conformance suite runs veraPDF
  (PDF/A-3B) on the output when `$EUINVOICE_VERAPDF` (e.g. `scripts/verapdf-docker.sh`) or `verapdf` is available.
- The CI conformance job runs veraPDF (PDF/A-3B) on the Factur-X PDFs through the digest-pinned
  `verapdf/cli` image (#25). With `EUINVOICE_VERAPDF_REQUIRED=1`, as set in CI, a missing veraPDF fails the veraPDF
  tests instead of skipping them.
- `euinvoice.facturx.extract()` (the `[pdf]` extra): takes the invoice XML out of a Factur-X 1.0 / ZUGFeRD 2.1+,
  ZUGFeRD 2.0 or ZUGFeRD 1.0 PDF (`factur-x.xml`, `xrechnung.xml`, `zugferd-invoice.xml`, `ZUGFeRD-invoice.xml`)
  and returns an `Extracted` with the bytes, the file name, the XMP schema and level, and the profile. The XMP
  `DocumentFileName` selects the attachment; anything ambiguous raises `PdfError`. The input need not be PDF/A.
  All 125 PDFs of the pinned ZUGFeRD corpus's `correct` directories extract.
- `euinvoice.syntax.ubl.read()`: the UBL 2.1 reader (`Invoice` and `CreditNote`) returning a `ParseResult`
  (`euinvoice.syntax.result`) with the invoice and the XPath of every element or attribute that carries no
  business term (`unmapped`). Reads every CEN, Peppol BIS and XRechnung UBL example and round-trips them; the
  binding decisions and normalizations are in `docs/reference/bt-mapping.md` ("The UBL reader").
- Project scaffolding: tooling, CI (checks, 3.12–3.14 test matrix, conformance, build), dependency
  audits, release workflow with PyPI trusted publishing, implementation plan.
- `euinvoice.errors`: exception hierarchy (`EuInvoiceError`, `ModelError`, `ParseError`, …).
- `euinvoice.model.amounts`: Decimal-only `Amount`, `UnitPriceAmount`, `Quantity` and `Percentage`
  types. Floats are rejected; `Amount` allows at most two decimals (BR-DEC-*, UBL-DT-01) and is never
  rounded implicitly; `quantize_amount()` rounds half up to two decimals. In JSON they are fixed-point
  `xs:decimal` strings (never exponent notation) that reload exactly.
- Model foundations: models are immutable, hashable and reject unknown fields, and every field
  carries its EN 16931 BT/BG id in its JSON schema.
- The full EN 16931 semantic model, `euinvoice.model.Invoice` (one model for invoices and credit
  notes): all 32 business groups and 164 business terms, with cardinalities taken from the official
  rules (a term is required only where a fatal CEN rule requires it), codes checked against the CEN
  code lists (BR-CL-*), identifier schemes (ICD, EAS, UNTDID 1153/7143), binary attachments, and
  sign and reason rules BR-27/28, BR-33/38/42/44. `euinvoice.model.bt_index` maps every BT/BG id to
  its model path and back. `docs/reference/bt-mapping.md` lists every id with its UBL and CII XPath
  and the source of each fact. `InvoiceDraft` / `LineDraft` share every field with `Invoice` /
  `InvoiceLine` except the derived BG-22, BG-23 and BT-131 (the input of `calc`).
- `euinvoice.syntax.cii.read()`: reads a parsed CII D16B `rsm:CrossIndustryInvoice` into an `Invoice` and returns
  a `euinvoice.syntax.result.ParseResult` whose `unmapped` lists the XPath of every element or attribute no
  business term took (out-of-model content is reported, never dropped). Model errors become `ParseError` with the
  BT/BG id and the element's XPath. Every CII file of the CEN examples, the KoSIT XRechnung testsuite and the
  ZUGFeRD corpus round-trips and validates, except five that break fatal CEN code-list rules.
- `euinvoice.syntax.cii.write()`: serializes an `Invoice` (invoice or credit note) as UN/CEFACT CII
  D16B `rsm:CrossIndustryInvoice`, in XSD element order, every date as `format="102"`, BT-8 mapped to
  UNTDID 2475, empty notes skipped, and BT-148 derived as BT-146 + BT-147 when only the discount is
  given. It raises `ModelError` for values CII cannot carry (more than one BG-3, BT-150 without BT-149,
  BT-111 without BT-6). `euinvoice.syntax.Syntax` names the syntaxes.
- `euinvoice.syntax.ubl.write(invoice)`: UBL 2.1 writer for every business term, in UBL 2.1 XSD order.
  BT-3 picks the root (`CreditNote` for the CEN credit note codes, including 81; `Invoice` otherwise).
  A gross price (BT-148) without a discount is written with the implied discount BT-148 − BT-146.
  It raises `ModelError` ("BT-n cannot be written in UBL: …") for content UBL cannot express (BT-87 or
  the BT-125 mime code/filename missing, BT-110 missing, BT-111 without BT-6, BT-6 equal to BT-5 with BT-111,
  BT-148 below BT-146, BT-150 without BT-149, BT-9 in a credit note without BG-16). Empty notes are
  skipped.
- Artifact manifest (`euinvoice/validate/manifest.toml`) pinning the official validation artifacts and
  corpora by URL + sha256: CEN EN 16931 1.3.16 (UBL, CII), Peppol BIS Billing 3.0.21, XRechnung
  Schematron 2.6.0, XRechnung test suite and KoSIT validator configuration 2026-08-31 (incl. the CII
  D16B XSD), OASIS UBL 2.1 XSD, ZUGFeRD corpus, SchXslt 1.10.1.
- `python -m euinvoice artifacts fetch [--only NAME]`: downloads into `$EUINVOICE_ARTIFACTS_DIR`
  (default `~/.cache/euinvoice/<source>/<version>/`), verifies sha256, extracts zip-slip-safely and
  precompiles Schematron-only rule sets (Peppol) to XSLT with SchXslt. Idempotent and offline on a
  warm cache. `source_dir()` (module `euinvoice.validate.artifacts`) looks entries up and raises
  `ArtifactsNotAvailableError` naming the fetch command.
- Hardened XML input handling: every XML document is parsed with entity resolution, DTD loading and
  network access disabled. Documents with a DOCTYPE, malformed XML and input over libxml2's safety
  limits are rejected with `ParseError`.
- `scripts/check_upstream.py` (run nightly): reports manifest pins that are behind upstream (a release
  or prerelease published after the pinned one, a new corpus commit, a changed Peppol rule file on
  docs.peppol.eu) and exits non-zero on drift or when an upstream cannot be checked.
- `euinvoice.model.codes`: every EN 16931 code list (BR-CL-01…26) as frozensets, generated by
  `scripts/gen_codelists.py` (`make codelists`) from the pinned CEN 1.3.16 code-list Schematron, with
  UBL/CII differences kept apart (UBL Invoice vs CreditNote type codes, VAT point date code lists,
  country lists, UBL-only `SEPA` scheme). Hand-written `VatCategory` (UNTDID 5305 as restricted by
  BR-CL-17/18) and `DocumentType` (named UNTDID 1001 subset) enums.
- `euinvoice.model.codes.UNTDID_4451_NOTE_SUBJECT_UBL`: the UBL note subject codes of BR-CL-08 (383
  codes), which CEN 1.3.16 binds in the UBL model Schematron rather than the codes file. The generator
  now also reads the BR-CL params of `schematron/{UBL,CII}/EN16931-*-model.sch`. The list is a strict
  subset of the CII list `UNTDID_4451_TEXT_SUBJECT` (401 codes), which the syntax-neutral model accepts.
- `validate()` of module `euinvoice.validate.xsd`: UBL 2.1 `Invoice` / `CreditNote` XSD validation against the
  pinned OASIS UBL 2.1 schemas. Each schema error becomes a fatal `XSD` finding located by
  line and element path (libxml2 warnings stay warnings); compiled schemas are cached per process and safe to share across
  threads.
- The XSD `validate()` (module `euinvoice.validate.xsd`) also validates UN/CEFACT CII D16B `CrossIndustryInvoice`
  documents, against the D16B SCRDM Subset schema of the pinned KoSIT validator configuration
  (`resources/cii/16b/xsd/CrossIndustryInvoice_100pD16B.xsd`, used by every KoSIT CII scenario).
- `euinvoice.report`: `Finding`, `Severity` and `ValidationReport` (validation results as data).
- Module `euinvoice.validate.schematron`: runs one official compiled rule set (CEN EN 16931 UBL/CII, Peppol
  BIS 3.0 UBL/CII, XRechnung UBL/CII) on Saxon and maps every SVRL failed assert or successful report
  to a `Finding` with its rule id, severity (from `@flag`; a missing or unknown flag counts as `error`),
  XPath location and message. Input is hardened-parsed before Saxon sees it; compiled stylesheets are
  cached per process and calls are thread-safe. A document a stylesheet cannot evaluate (e.g. a
  non-numeric amount) yields one fatal `SCHEMATRON-RUNTIME` finding instead of an exception. Needs the
  `[validate]` extra.
- `euinvoice.profiles`: the `Profile` type (id, title, BT-24, supported syntaxes, official rule sets
  by name, BT-23 default, Factur-X file name and conformance level) with `prepare(invoice)`, which
  sets BT-24 and a missing BT-23 through model validation; the EN 16931 core profile `EN16931`
  (`urn:cen.eu:en16931:2017`, UBL and CII, CEN rules); and `profiles.get(bt24)`, which raises
  `UnsupportedDocumentError` listing the known identifiers for an unknown BT-24.
- `detect(data)` / `detect_root(root)` (module `euinvoice.detect`; `detect` is also `euinvoice.detect`): classify XML bytes (or an already parsed root)
  as UBL `Invoice` / `CreditNote` or CII `CrossIndustryInvoice`, read BT-24 (XPath `normalize-space`)
  and resolve the registered profile by exact match, or `None` when no profile declares that BT-24. A
  missing, empty or repeated BT-24 gives `specification_identifier=None` and `profile=None` (the
  official rules report it). Only PDF input and an unsupported root raise `UnsupportedDocumentError`;
  malformed XML raises `ParseError`.
- `euinvoice.validate(data, profile=None)` (module `euinvoice.validate.orchestration`): validates a UBL or CII document against the
  official XSD, then (unless the XSD step found an error) each Schematron rule set of the profile in
  order (EN 16931: CEN; Peppol: CEN, Peppol; XRechnung: CEN, XRechnung), with the raw official
  severities. Without a profile it is picked by BT-24; an unregistered or missing BT-24 falls back to
  EN 16931 core and the report says so in an `information` finding (`EUINVOICE-PROFILE-FALLBACK`).
- `euinvoice.calc` (D11): `complete(draft, *, paid_amount, rounding_amount,
  vat_total_in_accounting_currency, exemption_reasons)` derives the line net amounts (BT-131, Peppol
  R120 formula), the document totals (BG-22, BR-CO-10…16) and the VAT breakdown per category and
  rate (BG-23, BR-CO-17, BR-<x>-08), rounding half up to cents, and returns a validated `Invoice`
  that passes the CEN rules in both UBL and CII. `check(invoice)` evaluates BR-CO-10…17, BR-48,
  BR-53, the per-category rules BR-<x>-01/05/06/07/08/09/10 (S, Z, E, AE, K, G, O, L, M), BR-O-11…14
  and BR-B-02 as both the UBL and the CII binding test them (including CII's first-match rule
  shadowing). `check(invoice, syntax=Syntax.UBL | Syntax.CII)` reports that binding's failures as
  `fatal`; without a syntax, a rule is `fatal` when both bindings reject it and a `warning`
  `EUINV-CALC-PORTABILITY` naming the rule and binding when only one does. A conformance test
  cross-checks `check()` against the official CEN UBL and CII Schematron on mutated invoices.
  `ExemptionReason` carries BT-120/BT-121 per category. `complete()` reproduces the totals of every
  CEN 1.3.16 and Peppol 3.0.21 example (except one HUF example that rounds VAT to whole forints).
- `euinvoice.calc.check()` also reports the period date rules BR-29 and BR-CO-19 (invoicing period,
  BG-14) and BR-30 and BR-CO-20 (invoice line period, BG-26). An undated BG-14 with BT-8 passes the
  UBL binding of BR-CO-19 only, so it is a portability warning; the oracle conformance test covers
  all four rules.
- `euinvoice.profiles.PEPPOL`: Peppol BIS Billing 3.0 (UBL and CII, BT-24
  `urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0`, default BT-23
  `urn:fdc:peppol.eu:2017:poacc:billing:01:1.0`; XSD, CEN, then Peppol rules), registered by its BT-24,
  so `detect()` and `validate()` resolve Peppol documents to it. Its pre-flight
  (`PEPPOL.preflight(invoice, syntax)`) reports PEPPOL-EN16931-R001/R002/R003/R004/R005/R007/R008/R010/
  R020/R041/R042/R061/R110/R111/R121 on the model, as each syntax binding tests them, before writing,
  and never a fatal official id the Schematron would not raise. A UBL invoice whose only order
  reference is BT-14 (written as `cbc:ID` "NA", which passes R003) gets the warning
  `EUINV-PEPPOL-R003-NA`.
- `Profile.preflight`: an optional pre-flight hook `(invoice, Syntax) -> findings`, run after
  `prepare()` (`no_preflight` by default, as for EN 16931 core). `Profile.syntaxes` is now a
  `frozenset[Syntax]`; `euinvoice.model.datatypes.normalize_space()` implements XPath `normalize-space`.
- XRechnung 3.0 profiles `profiles.XRECHNUNG`, `XRECHNUNG_EXTENSION` and `XRECHNUNG_CVD` (UBL and CII,
  rule sets CEN then XRechnung), one per accepted BT-24 so `prepare()` never rewrites an Extension or CVD
  claim. `validate()` auto-detects them. Their `preflight(invoice, syntax)` reports the fatal BR-DE-* rules
  checkable on the model (BR-DE-1..11, 14..16, 22, 23..25, 30, 31; BR-DE-CVD-01..03 for CVD) and the
  re-asserted PEPPOL-EN16931-R001 (BT-23 required; no default, #67) under the official ids, exactly when
  the official rule fires on that syntax's writer output.
- Factur-X / ZUGFeRD level profiles `profiles.FACTURX_MINIMUM`, `FACTURX_BASIC_WL`, `FACTURX_BASIC`,
  `FACTURX_EN16931`, `FACTURX_EXTENDED` and `FACTURX_XRECHNUNG` (CII only), with BT-24, embedded file name and
  XMP conformance level taken from the pinned ZUGFeRD corpus. `profiles.by_conformance_level()` looks a level
  up by its XMP `fx:ConformanceLevel`; MINIMUM, BASIC WL, BASIC and EXTENDED are also found by their BT-24,
  while EN 16931 and XRECHNUNG share their BT-24 with the core / XRechnung and are selected by the PDF's XMP
  only; `FACTURX_XRECHNUNG` is `XRECHNUNG` (rule sets, BR-DE pre-flight) restricted to CII with the Factur-X
  container fields. EN 16931 and XRECHNUNG are generated with `prepare()` and the CII writer and validated with the CEN
  (and XRechnung) rules. BASIC, EN 16931, EXTENDED and XRECHNUNG documents read into the model, with EXTENDED
  content beyond EN 16931 listed in `unmapped`; MINIMUM and BASIC WL have no lines and raise a `ParseError`
  naming the missing terms (reading them is open, #69). `validate()` raises `ArtifactsNotAvailableError` for MINIMUM, BASIC WL, BASIC and EXTENDED,
  whose official Schematron is in the Factur-X package, not pinned yet (#42).

### Changed
- `euinvoice.validate` and `euinvoice.detect` now name the functions (plan §4 `from euinvoice import validate,
  detect`), not their modules (#27). Import module members with `from euinvoice.validate import …` /
  `from euinvoice.detect import …`; attribute access such as `euinvoice.detect.Detection` no longer works.
- `validate()` no longer falls back to EN 16931 core for auto-detected Factur-X MINIMUM, BASIC WL, BASIC and
  EXTENDED documents (now registered by their BT-24): it raises `ArtifactsNotAvailableError` until their
  Factur-X Schematron is pinned (#42). Pass `profile=profiles.EN16931` to run the core rules.
- The Peppol Schematron precompile now hands each `.sch` to SchXslt as an XDM node built from
  hardened-parsed XML instead of by file path (same compiled output). A `.sch` that pulls in other
  files (`sch:include`, `sch:extends[@href]`, `sch:pattern[@documents]`) is refused.

### Fixed
- `syntax.ubl.write()` writes an empty purchase order reference (BT-13 `""`) as an empty
  `cac:OrderReference/cbc:ID` instead of the `NA` placeholder, which now stands in for an absent BT-13 only, so
  an invoice with an empty `cbc:ID` (e.g. ZUGFeRD corpus `UBL/EN16931_Elektron.ubl.xml`) round-trips. Under
  Peppol the UBL pre-flight now reports PEPPOL-EN16931-R008 for it, as the official Schematron does (#79).
- `syntax.ubl.read()` maps an empty `cac:Contact` to the empty BG-6 / BG-9 it builds instead of also listing it in
  `unmapped`, as the CII reader does for an empty `ram:DefinedTradeContact` (#30).
- `syntax.ubl.read()` and `syntax.cii.read()` are now linear in the number of invoice lines for ordinary
  element names (a prefixed name over 98 bytes still costs a `getpath`). They no longer call lxml's
  `getpath` (which scans every sibling) once per element and once per built model. `unmapped` XPaths are
  unchanged. The 25 MB Peppol sample with 26,813 lines now reads in about 6 s CPU. Before, it did not finish
  in 30 min (#80).
- Model text, code, identifier (value and scheme ids) and binary object (filename, mime code) fields
  now refuse characters outside the XML 1.0 `Char` production (NUL and other C0 controls except tab,
  LF and CR, lone surrogates, U+FFFE, U+FFFF) with a `ModelError` naming the code point and its index,
  instead of failing late in the UBL/CII writers (#57).
- `syntax.cii.write()` now refuses a VAT accounting currency (BT-6) equal to the invoice currency (BT-5)
  together with BT-111, as `syntax.ubl.write()` already did, with a `ModelError` citing BR-53. It used to
  write two `ram:TaxTotalAmount` in the same currency that no reader can tell apart and that the CEN CII
  Schematron always rejects (BR-53) (#71).
- "Not subject to VAT" (O) invoices from `calc.complete()` now pass XRechnung BR-DE-14 and, between German
  seller and buyer, Peppol DE-R-014: `Profile.prepare()` of the XRechnung profiles (and of `PEPPOL` when
  seller and buyer are both in `DE`) writes BT-119 = 0 on an O VAT breakdown that has none, as the official
  XRechnung instance `01.04a` does. The new `Profile.requires_vat_breakdown_rate` field drives it; the core
  EN 16931 output is unchanged (#75).
