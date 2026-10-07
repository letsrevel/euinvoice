# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `ArtifactsNotAvailableError` takes a keyword-only `fallback_profile_id` and exposes it, with `reason` (the message
  without the fallback hint), as attributes. The unpinned Factur-X / ZUGFeRD refusal sets it to `"en16931"`, and the
  CLI builds its `--profile` hint from it instead of rewriting the message; the messages are unchanged
  ([#108](https://github.com/letsrevel/euinvoice/issues/108)).
- `ValidationReport.kosit`: for the XRECHNUNG, XRECHNUNG_EXTENSION and XRECHNUNG_CVD profiles, the verdict of the
  KoSIT validator next to the raw official flags, as a `KositAssessment` (matched scenario, `SeverityOverride`s
  pairing each finding with its `customLevel`, blocking findings, `accepted`). The scenario and the overrides are
  read at run time from the pinned `xrechnung-validator-configuration` `scenarios.xml`; `findings` and `ok` are
  unchanged. The CLI prints a `kosit:` line and adds a `kosit` key to `--json`; the exit code still follows `ok`.
  This resolves the 0.1.0 known issue on KoSIT's severity overrides
  ([#49](https://github.com/letsrevel/euinvoice/issues/49)).
- New pinned artifact `fatturapa-xsd` 1.2.3: the FatturaPA XML Schema (FPA12 and FPR12), fetched from Agenzia delle
  Entrate's copy (sha256 `152944f6…8a8c`, byte-identical to the fatturapa.gov.it file). `python -m euinvoice artifacts
  fetch` now also supports single-file sources (`file` in `manifest.toml` instead of `members`), with the same cache
  layout and sha256 check; the fingerprints of existing entries are unchanged, so warm caches stay warm. The
  schema's xmldsig import by W3C `http://` URL is redirected to the pinned UBL 2.1 copy (the same schema without the
  DOCTYPE's external identifiers), so it compiles offline. `validate()` does not use it yet
  ([#117](https://github.com/letsrevel/euinvoice/issues/117)).
- `euinvoice.model.it`: the optional, frozen Italian extension for FatturaPA data with no EN 16931 business term
  (D3 as amended, ADR 0001). `Invoice.it` / `InvoiceDraft.it` take an `ItalianExtension` (RegimeFiscale,
  SoggettoEmittente, TipoDocumento, VAT summary data keyed by rate, Natura and split payment, with EsigibilitaIVA and
  RiferimentoNormativo, and CondizioniPagamento / ModalitaPagamento); `InvoiceLine.it` / `LineDraft.it` take an
  `ItalianLineExtension` (TipoCessionePrestazione, Natura). Every field cites its FatturaPA element id in
  `json_schema_extra={"fatturapa": …}`; the code enums equal the pinned XSD 1.2.3 lists. `BT_INDEX` skips the
  extension hooks, and `calc.complete` carries them over. The UBL and CII writers (and so `to_xml` and
  `facturx.embed`) raise `ModelError` for an invoice that sets one instead of dropping it
  ([#118](https://github.com/letsrevel/euinvoice/issues/118)).
- FatturaPA detection and validation ([#121](https://github.com/letsrevel/euinvoice/issues/121)).
  - `detect()` recognizes a FatturaPA 1.2 `FatturaElettronica` root by its namespace as `Syntax.FATTURAPA`;
    `Detection.fatturapa_version` holds its `versione` (`FPA12` / `FPR12`).
  - `validate()` validates FatturaPA by syntax, not by profile: the pinned XSD 1.2.3, then the new
    `euinvoice.validation.sdi` checks. These are the offline-decidable SdI checks of Allegato A 1.9.1, Appendix 1,
    each an `error` finding whose `rule_id` is the SdI code (e.g. `00421`) and whose message quotes Allegato A.
  - Registry, SdI-state, file-name, file-size, signature and compressed-file checks are out of scope (D8). The
    ambiguous parts are tracked in [#130](https://github.com/letsrevel/euinvoice/issues/130).
  - FPA12 gets the same checks, after an `information` finding `EUINVOICE-FATTURAPA-FPA12`.
  - Passing a profile for a FatturaPA document raises `UnsupportedDocumentError`.
  - The CLI `validate` command accepts FatturaPA.
  - `calc.check(syntax="fatturapa")` raises `ValueError`.
- FatturaPA FPR12 writer ([#119](https://github.com/letsrevel/euinvoice/issues/119)).
  - `euinvoice.syntax.fatturapa.write(invoice, transmission)` writes an `Invoice` with `Invoice.it` as one unsigned FPR12
    file with one body, for TipoDocumento TD01, TD04, TD24 and TD17. The mapping follows App. 4.1 and the App. 5
    code tables of the SdI "Regole tecniche fatture europee" v2.6; the element order and the lexical forms (exactly
    two decimals for amounts, two to eight for prices and quantities, Basic Latin / Latin-1 text, lengths) follow
    the XSD 1.2.3. Values that do not fit are refused, never rounded or cut.
  - `Transmission` holds the transmission header: IdTrasmittente, `transmission_number` (ProgressivoInvio),
    CodiceDestinatario (default `RECIPIENT_UNKNOWN` `0000000`, or `RECIPIENT_FOREIGN` `XXXXXXX`) and
    PECDestinatario.
  - `preflight(invoice)` reports, as `error` findings by model path, everything that keeps the invoice from being
    written: what FatturaPA needs and the invoice lacks (`Invoice.it`, TipoDocumento vs BT-3, required elements,
    Natura vs VAT category per App. 5.1, CondizioniPagamento / ModalitaPagamento); every business term FPR12
    cannot carry (generic document level allowances and charges, VAT categories O, L and M, line allowances and
    charges, BT-20, BT-154 and every term with no App. 4.1 row the writer fills); DatiRiepilogo that cannot be
    built; and totals that disagree with the summaries written (BR-CO-10/13/14/15/16 through App. 4.1:
    ImportoTotaleDocumento, ImportoPagamento and the derived BT-106..BT-110). Every set term is written or reported:
    BT-120 becomes RiferimentoNormativo when its VAT breakdown has one summary, or is accepted when it is the App. 4.1
    concatenation of the Natura and RiferimentoNormativo written (the reader's form); BT-121 must be the App. 5.1
    VATEX code of the group's Natura; BT-20 is accepted only as the CondizioniPagamento code it carries. So an
    invoice read from FatturaPA is written back unchanged: model → FPR12 → model is lossless up to the documented
    App. 4.1 / 5 normalizations, and FPR12 → model → FPR12 is a fixed point wherever the writer supports the
    content (round-trip tests with the #120 reader). `write` raises `ModelError` for the errors and for values
    that do not fit their XSD type.
    The policies behind the refusals are open in [#133](https://github.com/letsrevel/euinvoice/issues/133)
    (`needs-human`).
  - DatiRiepilogo blocks are keyed by rate, Natura and split payment (category B → EsigibilitaIVA S) and filled
    from `Invoice.it.vat_summaries`. Split payment and ordinary VAT at one rate are refused: FatturaPA lines carry
    no EsigibilitaIVA, so a reader could not tell which line is which. ModalitaPagamento comes from `it.payment.method` or BT-81 through App. 5.6.
    The stamp duty (BG-21 SAE, credit notes BG-20 95) is DatiBollo.
  - `to_xml(invoice, syntax=Syntax.FATTURAPA, fatturapa_transmission=...)` runs the pre-flight, writes, then runs
    the offline SdI checks of `euinvoice.validation.sdi` on the result; an `error` from either raises
    `PreflightError` with `profile_id` `"fatturapa"`. FatturaPA takes no profile, and the CEN checks do not run.
  - `file_name(country, identifier, file_number)` builds an SdI file name and `check_file()` reports SdI 00001 (file
    name, Allegato A §1.2.2) and 00003 (file size over `MAX_FILE_SIZE`, 5 000 000 bytes, the smaller reading of
    "5MB").
- FatturaPA reader ([#120](https://github.com/letsrevel/euinvoice/issues/120)).
  - `parse()` / `parse_detailed()` read a FatturaPA 1.2 document (FPR12, and FPA12 since the schema is shared) into
    `Invoice` with `Invoice.it` / `InvoiceLine.it`, following App. 4.1 of the SdI "Regole tecniche fatture europee"
    v2.6 in reverse and the App. 5 code tables (Natura → VAT category and VATEX, TipoDocumento → BT-3,
    ModalitaPagamento → BT-81). The #121 refusal is gone.
  - The reader adds no CEN violation of its own: a document whose declared figures agree reads, after
    `without_extensions()`, as a UBL / CII invoice the CEN rules accept. One BG-23 per VAT category and rate (the
    per-Natura and EsigibilitaIVA detail stays in `Invoice.it.vat_summaries`). Declared amounts are kept exactly as
    declared, as the UBL and CII readers do; a document whose figures disagree (e.g. a payment net of withholding)
    keeps them for `validate()` / `calc.check` to report. BT-24 is `urn:cen.eu:en16931:2017`.
  - Also mapped: social-security funds (`DatiCassaPrevidenziale` → BG-21, App. 4.1 rows 2.1.1.7.x), the stamp duty
    (`DatiBollo` → a zero BG-21 SAE / BOLLO in category Z, a BG-20 95 on TD04, BR-IT-DC-480), negative unit prices
    (as a negative BT-129 with a positive BT-146), BT-8 432 from EsigibilitaIVA D, BT-10, BT-15, BT-20, BT-60 and
    BT-61.
  - Transmission data, the EXT rows outside the v1 extension (withholding, Art73, the
    intermediary, …), attachments, line-level document references and every "Mappatura non considerabile" row are
    listed in `ParseResult.unmapped`, never dropped.
  - Values the model cannot hold without rounding or guessing are refused with `ParseError` naming the element:
    `PrezzoTotale` with more than two decimals, the generic Natura N2/N3/N6, a Natura with a rate other than 0,
    several `ScontoMaggiorazione` on one line, rate 0 without Natura, split payment and ordinary VAT at the same
    rate (a line has no EsigibilitaIVA). At different rates they read as categories B and S, as declared, and
    validation reports BR-B-02. The mapping-policy questions are in
    [#132](https://github.com/letsrevel/euinvoice/issues/132) (`needs-human`).
  - New `parse_all()`: one `ParseResult` per invoice. A FatturaPA lotto (several `FatturaElettronicaBody`) gives
    one per body, and `parse()` / `parse_detailed()` refuse it with `UnsupportedDocumentError` naming
    `parse_all()`; UBL, CII and Factur-X give a single result.
  - A signed `.p7m` (CMS SignedData in DER, base64 or PEM; `euinvoice.detection.is_signed`) is refused by
    `parse*()`, `detect()`, `validate()` and the CLI with `UnsupportedDocumentError` saying how to extract the XML;
    reading it would need a CMS parser, a new dependency (D6).
  - New `euinvoice.model.without_extensions(model)` (the model with every set extension hook cleared) and
    `euinvoice.model.extension_paths(model)` (the paths of the set hooks), so a read FatturaPA invoice can be written
    as UBL or CII on purpose. The UBL / CII refusal of a set extension now names `without_extensions()`.

### Changed

- `profiles._base.SYNTAXES`, the syntaxes a profile can support, is now `{UBL, CII}` explicitly, no longer every
  `Syntax`. Every profile still supports what it did, and `convert --to` still offers `ubl` and `cii` (#121).
- A single-file artifact source whose `file` starts with a dot is refused, so the cache marker
  `.euinvoice-fingerprint` can never be a source's file ([#128](https://github.com/letsrevel/euinvoice/issues/128)).

## [0.1.0] - 2026-10-06

First release: the EN 16931 semantic model, totals and VAT calculation, UBL 2.1 and CII D16B writers and readers,
the EN 16931 core, Peppol BIS Billing 3.0, XRechnung 3.0 and Factur-X / ZUGFeRD profiles, validation against the
pinned official XSD and Schematron, Factur-X PDF embedding and extraction, a top-level API and a CLI. What is
generated, parsed and validated per profile is in the README table; the open questions are under Known issues below.

### Added

#### Model
- `euinvoice.model.Invoice`: the full EN 16931 semantic model, one model for invoices and credit notes, with all
  32 business groups and 164 business terms ([#8](https://github.com/letsrevel/euinvoice/issues/8)). Models are immutable, hashable and reject unknown fields; every
  field carries its BT/BG id in its JSON schema. A term is required only where a fatal CEN rule requires it. Codes
  are checked against the CEN code lists (BR-CL-*), and identifier schemes (ICD, EAS, UNTDID 1153/7143), binary
  attachments and the sign and reason rules BR-27/28, BR-33/38/42/44 are enforced.
- `InvoiceDraft` / `LineDraft`: the same fields as `Invoice` / `InvoiceLine` without the derived BG-22, BG-23 and
  BT-131, as the input of `calc` ([#8](https://github.com/letsrevel/euinvoice/issues/8)).
- `euinvoice.model.amounts` ([#7](https://github.com/letsrevel/euinvoice/issues/7)): `Decimal`-only `Amount`, `UnitPriceAmount`, `Quantity` and `Percentage`. Floats
  are rejected. `Amount` allows at most two decimals (BR-DEC-*, UBL-DT-01) and is never rounded implicitly;
  `quantize_amount()` rounds half up to two decimals. In JSON they are fixed-point `xs:decimal` strings (never
  exponent notation) that reload exactly.
- Text, code, identifier (value and scheme ids) and binary object (filename, mime code) fields refuse characters
  outside the XML 1.0 `Char` production (NUL and other C0 controls except tab, LF and CR, lone surrogates,
  U+FFFE, U+FFFF) with a `ModelError` naming the code point and its index ([#57](https://github.com/letsrevel/euinvoice/issues/57)).
- `euinvoice.model.codes` ([#5](https://github.com/letsrevel/euinvoice/issues/5), [#52](https://github.com/letsrevel/euinvoice/issues/52)): every EN 16931 code list (BR-CL-01…26) as frozensets, generated from the
  pinned CEN 1.3.16 Schematron (code-list and model files), with the UBL/CII differences kept apart (UBL Invoice
  vs CreditNote type codes, VAT point date codes, country lists, the UBL-only `SEPA` scheme, the UBL note subject
  codes of BR-CL-08 in `UNTDID_4451_NOTE_SUBJECT_UBL`). Hand-written `VatCategory` (UNTDID 5305 as restricted by
  BR-CL-17/18) and `DocumentType` (a named UNTDID 1001 subset) enums.
- `euinvoice.model.bt_index` maps every BT/BG id to its model path and back ([#8](https://github.com/letsrevel/euinvoice/issues/8));
  `euinvoice.model.datatypes.normalize_space()` implements XPath `normalize-space` ([#20](https://github.com/letsrevel/euinvoice/issues/20)).
- `euinvoice.errors`: the exception hierarchy (`EuInvoiceError`, `ModelError`, `ParseError`,
  `UnsupportedDocumentError`, `ArtifactsNotAvailableError`, `PreflightError`, `PdfError`, …) ([#7](https://github.com/letsrevel/euinvoice/issues/7), [#27](https://github.com/letsrevel/euinvoice/issues/27)).

#### Calculation
- `calc.complete(draft, *, paid_amount, rounding_amount, vat_total_in_accounting_currency, exemption_reasons)`
  ([#9](https://github.com/letsrevel/euinvoice/issues/9)): derives the line net amounts (BT-131, Peppol R120 formula), the document totals (BG-22, BR-CO-10…16) and
  the VAT breakdown per category and rate (BG-23, BR-CO-17, BR-<x>-08), rounding half up to cents, and returns a
  validated `Invoice` that passes the CEN rules in UBL and CII. `ExemptionReason` carries BT-120/BT-121 per
  category. It reproduces the totals of every CEN 1.3.16 and Peppol 3.0.21 example except one HUF example that
  rounds VAT to whole forints.
- `calc.check(invoice, *, syntax=None)` ([#9](https://github.com/letsrevel/euinvoice/issues/9), [#62](https://github.com/letsrevel/euinvoice/issues/62)): evaluates BR-CO-10…17, BR-48, BR-53, BR-<x>-01/05/06/07/08/09/10
  (S, Z, E, AE, K, G, O, L, M), BR-O-11…14, BR-B-02 and the period date rules BR-29, BR-30, BR-CO-19 and
  BR-CO-20 as the UBL and the CII binding test them (including CII's first-match rule shadowing). With a syntax,
  that binding's failures are `fatal`; without one, a rule is `fatal` when both bindings reject it and an
  `EUINV-CALC-PORTABILITY` warning when only one does. A conformance test cross-checks it against the official
  CEN Schematron.

#### UBL and CII
- `syntax.ubl.write()` ([#10](https://github.com/letsrevel/euinvoice/issues/10)): UBL 2.1 for every business term, in XSD order. BT-3 picks the root (`CreditNote`
  for the CEN credit note codes, including 81; `Invoice` otherwise). A gross price (BT-148) without a discount is
  written with the implied discount. It raises `ModelError` ("BT-n cannot be written in UBL: …") for content UBL
  cannot express (BT-87 or the BT-125 mime code / filename missing, BT-110 missing with VAT, BT-111 without BT-6,
  BT-6 equal to BT-5 with BT-111, BT-148 below BT-146, BT-150 without BT-149, BT-9 in a credit note without BG-16).
  An absent purchase order reference (BT-13) under a sales order reference is written as `NA`; an empty one
  stays empty ([#79](https://github.com/letsrevel/euinvoice/issues/79)). An absent BT-110 with no VAT (BT-112 =
  BT-109 and Σ BT-117 = 0) is written as `cbc:TaxAmount` 0.00, as CEN's `ubl-tc434-example7.xml` does for
  `CII_example7.xml`, and reads back as 0.00; `calc.check()` accepts it for UBL
  ([#87](https://github.com/letsrevel/euinvoice/issues/87)).
- `syntax.cii.write()` ([#13](https://github.com/letsrevel/euinvoice/issues/13)): UN/CEFACT CII D16B `rsm:CrossIndustryInvoice` in XSD order, every date as
  `format="102"`, BT-8 mapped to UNTDID 2475, BT-148 derived as BT-146 + BT-147 when only the discount is given.
  It raises `ModelError` for content CII cannot carry (more than one BG-3, BT-150 without BT-149, BT-111 without
  BT-6, BT-6 equal to BT-5 with BT-111 (BR-53, [#71](https://github.com/letsrevel/euinvoice/issues/71))). Both writers skip empty notes.
- `syntax.ubl.read()` ([#11](https://github.com/letsrevel/euinvoice/issues/11)) and `syntax.cii.read()` ([#14](https://github.com/letsrevel/euinvoice/issues/14)) return a `ParseResult` (`euinvoice.syntax.result`):
  the invoice plus the XPath of every element or attribute that carries no business term (`unmapped`), so
  out-of-model content is reported, never dropped. An empty contact becomes an empty BG-6 / BG-9 ([#30](https://github.com/letsrevel/euinvoice/issues/30)). Model
  errors become `ParseError` with the BT/BG id and the element's XPath. Both read every CEN, Peppol BIS,
  XRechnung testsuite and ZUGFeRD corpus file of their syntax and round-trip them, except the files listed with
  their rule ids in `tests/conformance/expected_invalid.toml`. Reading is linear in the number of lines (a
  25 MB, 26,813-line Peppol sample reads in about 6 s CPU; the two Peppol stress samples are measured, not run in
  the suite; issue [#80](https://github.com/letsrevel/euinvoice/issues/80)).
- `euinvoice.syntax.Syntax` names the syntaxes. The binding decisions and normalizations are documented in
  `docs/reference/bt-mapping.md`.

#### Profiles
- `euinvoice.profiles.Profile` ([#19](https://github.com/letsrevel/euinvoice/issues/19)): id, title, BT-24, supported syntaxes (`frozenset[Syntax]`), official rule sets, BT-23
  default, Factur-X file name and conformance level, `requires_vat_breakdown_rate` ([#75](https://github.com/letsrevel/euinvoice/issues/75)), an optional `preflight(invoice, syntax)` hook ([#20](https://github.com/letsrevel/euinvoice/issues/20)) and
  `prepare(invoice)`, which sets BT-24 and a missing BT-23. `profiles.get(bt24)` looks a profile up by BT-24 and
  raises `UnsupportedDocumentError` listing the known identifiers.
- `profiles.EN16931`: the EN 16931 core (`urn:cen.eu:en16931:2017`, UBL and CII, CEN rules) ([#19](https://github.com/letsrevel/euinvoice/issues/19)).
- `profiles.PEPPOL`: Peppol BIS Billing 3.0 (UBL and CII; default BT-23 `urn:fdc:peppol.eu:2017:poacc:billing:01:1.0`;
  CEN then Peppol rules) ([#20](https://github.com/letsrevel/euinvoice/issues/20)). Its pre-flight reports PEPPOL-EN16931-R001/R002/R003/R004/R005/R007/R008/R010/
  R020/R041/R042/R061/R110/R111/R121 on the model as each syntax binding tests them, and the warning
  `EUINV-PEPPOL-R003-NA` for a UBL invoice whose only order reference is BT-14.
- `profiles.XRECHNUNG`, `XRECHNUNG_EXTENSION` and `XRECHNUNG_CVD`: XRechnung 3.0 (UBL and CII; CEN then XRechnung
  rules), one per accepted BT-24, so `prepare()` never rewrites an Extension or CVD claim ([#21](https://github.com/letsrevel/euinvoice/issues/21)). Their pre-flight
  reports the fatal BR-DE-* rules checkable on the model (BR-DE-1..11, 14..16, 22, 23..25, 30, 31;
  BR-DE-CVD-01..03 for CVD) and the re-asserted PEPPOL-EN16931-R001 under the official ids, exactly when the
  official rule fires on that syntax's output.
- `prepare()` of the XRechnung profiles, and of `PEPPOL` when seller and buyer are both in `DE`, writes BT-119 = 0
  on a "Not subject to VAT" (O) breakdown, so O invoices from `calc.complete()` pass BR-DE-14 and DE-R-014 ([#75](https://github.com/letsrevel/euinvoice/issues/75)).
- Factur-X / ZUGFeRD levels `profiles.FACTURX_MINIMUM`, `FACTURX_BASIC_WL`, `FACTURX_BASIC`, `FACTURX_EN16931`,
  `FACTURX_EXTENDED` and `FACTURX_XRECHNUNG` (CII only), with BT-24, embedded file name and XMP conformance level
  taken from the pinned ZUGFeRD corpus ([#22](https://github.com/letsrevel/euinvoice/issues/22)). `profiles.by_conformance_level()` looks a level up by its XMP
  `fx:ConformanceLevel`. EN 16931 and XRECHNUNG are generated and validated with the CEN (and XRechnung) rules;
  BASIC and EXTENDED read into the model (EXTENDED-only content in `unmapped`).

#### Validation
- `euinvoice.validate(data, profile=None)` ([#17](https://github.com/letsrevel/euinvoice/issues/17)): the official XSD, then (unless the XSD step failed) each
  Schematron rule set of the profile in order, with the raw official severities. Without a profile it is picked
  by BT-24; an unregistered or missing BT-24 falls back to EN 16931 core with an `information` finding
  `EUINVOICE-PROFILE-FALLBACK`. Factur-X MINIMUM, BASIC WL, BASIC and EXTENDED documents raise
  `ArtifactsNotAvailableError` instead (their Schematron is not pinned, [#42](https://github.com/letsrevel/euinvoice/issues/42)), and so do auto-detected CII documents
  with a ZUGFeRD 2.0 MINIMUM, BASIC or EXTENDED BT-24 or a colon-spelled BASIC / EXTENDED BT-24
  (neither is registered as a profile, [#98](https://github.com/letsrevel/euinvoice/issues/98)); pass
  `profile=profiles.EN16931` to run the core rules. It takes XML (for a PDF, pass `facturx.extract(pdf).xml`),
  returns a `ValidationReport` and never raises on rule failures.
- XSD validation (`euinvoice.validation.xsd`) of UBL 2.1 `Invoice` / `CreditNote` (OASIS schemas, [#12](https://github.com/letsrevel/euinvoice/issues/12)) and CII D16B
  (the SCRDM Subset schema of the pinned KoSIT configuration, [#15](https://github.com/letsrevel/euinvoice/issues/15)): each schema error is a fatal `XSD` finding
  located by line and element path.
- Schematron runner (`euinvoice.validation.schematron`, the `[validate]` extra, SaxonC-HE) ([#16](https://github.com/letsrevel/euinvoice/issues/16)): CEN EN 16931,
  Peppol BIS 3.0 and XRechnung rule sets for UBL and CII. Each SVRL failed assert or successful report becomes a
  `Finding` with rule id, severity (from `@flag`; missing or unknown counts as `error`), XPath and message. A
  document a stylesheet cannot evaluate yields one fatal `SCHEMATRON-RUNTIME` finding instead of an exception.
  Compiled schemas and stylesheets are cached per process and thread-safe.
- The `[validate]` extra requires `saxonche>=12.9,!=13.0.0`: SaxonC-HE 13.0.0 crashes in `normalize-space()` on
  text that combines leading whitespace, a character above U+00FF and one above U+FFFF, so the official
  stylesheets aborted and `validate()` reported a false `SCHEMATRON-RUNTIME` fatal; 12.9 and 12.10 are
  not affected, and a fixed 13.0.x is accepted ([#74](https://github.com/letsrevel/euinvoice/issues/74)).
- `euinvoice.report`: `Finding`, `Severity` and `ValidationReport` ([#16](https://github.com/letsrevel/euinvoice/issues/16)).
- Artifact manifest (`euinvoice/validation/manifest.toml`) pinning the official artifacts and corpora by URL and
  sha256 ([#4](https://github.com/letsrevel/euinvoice/issues/4)): CEN EN 16931 1.3.16 (UBL, CII), Peppol BIS Billing 3.0.21, XRechnung Schematron 2.6.0, XRechnung
  testsuite and KoSIT validator configuration 2026-08-31 (incl. the CII D16B XSD), OASIS UBL 2.1 XSD, ZUGFeRD
  corpus, SchXslt 1.10.1. They are downloaded, never bundled.
- `python -m euinvoice artifacts fetch [--only NAME]` ([#4](https://github.com/letsrevel/euinvoice/issues/4)): downloads into `$EUINVOICE_ARTIFACTS_DIR` (default
  `~/.cache/euinvoice/<source>/<version>/`), verifies sha256, extracts zip-slip-safely and precompiles the
  Peppol Schematron with SchXslt from hardened-parsed XML (a `.sch` that pulls in other files is refused).
  Idempotent and offline on a warm cache. `validate()` never downloads; a missing artifact raises
  `ArtifactsNotAvailableError` naming the fetch command. `euinvoice.validation.artifacts.source_dir()` looks a
  fetched source up.

#### Factur-X / ZUGFeRD
- `facturx.embed()` (the `[pdf]` extra, pypdf) ([#23](https://github.com/letsrevel/euinvoice/issues/23)): embeds an invoice's CII XML, given as bytes or as an
  `Invoice` (EN 16931 and XRECHNUNG levels), into a PDF that is already PDF/A-3 (anything else raises `PdfError`),
  with the associated file (`factur-x.xml` / `xrechnung.xml`, `/AFRelationship`, `text/xml`, `/ModDate`, catalog
  `/AF`) and the Factur-X XMP with its PDF/A extension schema. The output passes veraPDF (PDF/A-3B) in the
  conformance suite ([#25](https://github.com/letsrevel/euinvoice/issues/25)).
- `facturx.extract()` ([#24](https://github.com/letsrevel/euinvoice/issues/24)): takes the invoice XML out of a Factur-X 1.0 / ZUGFeRD 2.1+, ZUGFeRD 2.0 or ZUGFeRD
  1.0 PDF and returns an `Extracted` with the bytes, the file name, the XMP schema and level, and the profile.
  The XMP `DocumentFileName` selects the attachment; anything ambiguous raises `PdfError`. The input need not be
  PDF/A. All 125 PDFs of the ZUGFeRD corpus's `correct` directories extract.

#### Detection
- `euinvoice.detect(data)` / `euinvoice.detection.detect_root(root)` ([#26](https://github.com/letsrevel/euinvoice/issues/26)): classify XML as UBL `Invoice` / `CreditNote` or CII
  `CrossIndustryInvoice`, read BT-24 (`normalize-space`) and resolve the registered profile by exact match, or
  `None`. Only PDF input and an unsupported root raise `UnsupportedDocumentError`. `euinvoice.detection.is_pdf` is
  the PDF sniff `detect` and `parse` share.

#### API
- Top-level API ([#27](https://github.com/letsrevel/euinvoice/issues/27)): `euinvoice.to_xml(invoice, *, profile=None, syntax=None)` prepares the invoice for the
  profile (default: the one registered for its BT-24), runs the profile's pre-flight and `calc.check`, and raises
  `PreflightError` (with the findings, the profile id and the syntax; picklable) on any `fatal` / `error`
  finding before writing UBL or CII. It refuses the Factur-X levels that are not generated. `euinvoice.parse()` /
  `parse_detailed()` read UBL, CII and Factur-X / ZUGFeRD 2.x PDFs (ZUGFeRD 2.0 is extract-only: no profile is registered for its BT-24s; ZUGFeRD 1.0 PDFs are
  extract-only: `parse()` raises `UnsupportedDocumentError`); `parse()` discards `unmapped`.
- `euinvoice` re-exports `to_xml`, `parse`, `parse_detailed`, `validate`, `detect`, `Invoice`, `InvoiceDraft`,
  `ParseResult`, `Syntax`, `ValidationReport`, `calc`, `profiles` and a lazily imported `facturx`; `import
  euinvoice` loads neither pypdf nor saxonche. The functions `detect` and `validate` live in the modules
  `euinvoice.detection` and `euinvoice.validation` (`euinvoice.validation.artifacts`, `.xsd`, `.schematron`), named
  so that no function shadows its module ([#93](https://github.com/letsrevel/euinvoice/issues/93)).

#### Security
- Hardened XML input ([#6](https://github.com/letsrevel/euinvoice/issues/6)): every document is parsed with entity resolution, DTD loading and network access
  disabled. A DOCTYPE, malformed XML and input over libxml2's safety limits raise `ParseError`. Hostile element
  names or prefixes no longer crash readers or XSD validation: a node path that libxml2 cuts inside a UTF-8
  character ends in U+FFFD ([#90](https://github.com/letsrevel/euinvoice/issues/90)).

#### CLI
- `python -m euinvoice validate FILE [--profile ID] [--json]`, `convert FILE --to ubl|cii [--profile ID] [-o OUT]`
  and `info FILE [--json]`, next to `artifacts fetch` ([#28](https://github.com/letsrevel/euinvoice/issues/28)). `FILE` may be XML or a Factur-X / ZUGFeRD PDF (`-`
  reads stdin); for a PDF, `validate` and `info` default to the profile of its Factur-X level. Exit codes: 0 ok (warnings allowed); 1 document rejected or artifact integrity failure; 2 usage
  or setup error. `convert` lists every unmapped input element on stderr and writes `-o` only on success. Text
  the terminal cannot encode is backslash-escaped. The JSON shapes are documented in `euinvoice/__main__.py`.

#### Documentation
- Documentation site in `docs/` (mkdocs-material, built with `--strict` in CI; GitHub Pages deploy is opt-in via
  the `DOCS_DEPLOY` repository variable) ([#33](https://github.com/letsrevel/euinvoice/issues/33)): quickstart, concepts, validation, Factur-X, a mapping guide with
  synthetic freelancer and ticketing examples, and a reference (API from the docstrings, BT mapping, BT coverage,
  artifact licences). Every Python example runs as a test, and validation examples run against the official
  rules in `make conformance`.
- README with a support table, known limitations and doctested usage examples ([#27](https://github.com/letsrevel/euinvoice/issues/27), [#34](https://github.com/letsrevel/euinvoice/issues/34)).

#### Quality gates (for contributors)
- Conformance suite (`make conformance`): the corpus round-trip harness over every pinned upstream example (the two Peppol
  stress samples are measured, not run in the suite; issue [#80](https://github.com/letsrevel/euinvoice/issues/80)) with
  `tests/conformance/expected_invalid.toml` as the only list of failures ([#29](https://github.com/letsrevel/euinvoice/issues/29)); UBL ↔ CII cross-syntax round
  trips ([#30](https://github.com/letsrevel/euinvoice/issues/30)); Hypothesis invoices that validate under EN 16931, Peppol and XRechnung in both syntaxes and
  round-trip exactly ([#31](https://github.com/letsrevel/euinvoice/issues/31), [#89](https://github.com/letsrevel/euinvoice/issues/89)); veraPDF on the Factur-X PDFs ([#25](https://github.com/letsrevel/euinvoice/issues/25)).
- BT coverage gate: every EN 16931 term and group has a write and a read test in UBL and CII ([#32](https://github.com/letsrevel/euinvoice/issues/32)).
- `scripts/check_upstream.py` (nightly) reports manifest pins that are behind upstream ([#18](https://github.com/letsrevel/euinvoice/issues/18), [#45](https://github.com/letsrevel/euinvoice/issues/45)).
- Tooling and CI: ruff, mypy strict, 3.12–3.14 test matrix, ≥ 95 % branch coverage, conformance and build jobs,
  dependency audits, release workflow with PyPI trusted publishing.

### Known issues
- Factur-X 1.0 / ZUGFeRD 2.1+: the Factur-X XSD and Schematron are not pinned ([#42](https://github.com/letsrevel/euinvoice/issues/42)). MINIMUM, BASIC WL, BASIC and EXTENDED
  are not validated (`ArtifactsNotAvailableError`), nor are ZUGFeRD 2.0 MINIMUM, BASIC and EXTENDED or the
  colon-spelled BASIC / EXTENDED BT-24s ([#98](https://github.com/letsrevel/euinvoice/issues/98)); EN 16931 and XRECHNUNG get the EN 16931 / XRechnung verdict.
  No ZUGFeRD 2.0 BASIC WL sample is in the pinned corpus, so its BT-24 is not recognised and still falls back to
  EN 16931 core.
- Factur-X MINIMUM and BASIC WL are detected and extracted but cannot be read into the model ([#69](https://github.com/letsrevel/euinvoice/issues/69)).
- XRechnung: KoSIT's per-scenario severity overrides are not applied ([#49](https://github.com/letsrevel/euinvoice/issues/49)), so the verdict can differ from KoSIT's
  (e.g. 2 of the 6 official Extension instances get fatal findings KoSIT downgrades). No *conforming* CVD invoice
  can be built or read. `validate()` rejects every CVD document: BR-CL-13 when it carries the `CVD` item
  classification, BR-DE-CVD-03 (fatal) when it does not (`XRechnung-UBL-validation.sch` lines 560-562, CEN
  `EN16931-UBL-codes.sch` lines 67-68). No default BT-23 for XRechnung ([#67](https://github.com/letsrevel/euinvoice/issues/67)).
- A BT-125 attachment over about 7.5 MB exceeds the hardened parser's text node limit ([#40](https://github.com/letsrevel/euinvoice/issues/40)).

[Unreleased]: https://github.com/letsrevel/euinvoice/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/letsrevel/euinvoice/releases/tag/v0.1.0
