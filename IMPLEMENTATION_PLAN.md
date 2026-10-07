# euinvoice: Implementation Plan (v0.1.0)

This is the design spec and the work breakdown for the first release. It is written to be executed
by an autonomous agent orchestrating subagents (see [§9 Execution protocol](#9-execution-protocol)).
Every task in [§8](#8-work-breakdown) becomes one GitHub issue and one PR.

**Status:** approved by the maintainer on 2026-10-05. Design decisions in §2 are locked. Change them
only with an ADR in `docs/adr/` and a `needs-human` issue.

**Amended by the maintainer on 2026-10-07 ([#115](https://github.com/letsrevel/euinvoice/issues/115)):**
FatturaPA becomes a third syntax (M11), with matching changes to D3 and D8. ADR:
[`docs/adr/0001-fatturapa-d3-d8.md`](docs/adr/0001-fatturapa-d3-d8.md).

---

## 1. Goal and scope

**euinvoice** is an MIT-licensed, framework-free Python library for European e-invoicing based on
**EN 16931**. It lets you:

1. **build** an invoice or credit note as a typed semantic model, with totals and VAT breakdown
   computed per EN 16931 rules;
2. **serialize** it to **UBL 2.1** or **UN/CEFACT CII**, under a **profile** (CIUS/extension);
3. **validate** any e-invoice against the **official** XSD and Schematron artifacts;
4. **parse** UBL, CII and Factur-X/ZUGFeRD PDFs back into the same model;
5. **embed** the CII XML into a PDF/A-3 (Factur-X / ZUGFeRD) and extract it again.

### v0.1.0 profiles

| Profile | Syntax(es) | Generate | Parse | Validate |
|---|---|---|---|---|
| EN 16931 core (`urn:cen.eu:en16931:2017`) | UBL, CII | ✅ | ✅ | ✅ |
| Peppol BIS Billing 3.0 | UBL, CII | ✅ | ✅ | ✅ |
| XRechnung 3.0 | UBL, CII | ✅ | ✅ | ✅ |
| Factur-X / ZUGFeRD: EN16931 (COMFORT) | CII in PDF/A-3 | ✅ | ✅ | ✅ |
| Factur-X / ZUGFeRD: XRECHNUNG | CII in PDF/A-3 | ✅ | ✅ | ✅ |
| Factur-X / ZUGFeRD: BASIC, EXTENDED | CII in PDF/A-3 | ❌ | ✅ (EN 16931 subset; out-of-model content reported, never silently dropped) | ✅ (v0.1.0: ❌ until the Factur-X Schematron is pinned, [#42](https://github.com/letsrevel/euinvoice/issues/42)) |
| Factur-X / ZUGFeRD: MINIMUM, BASIC WL | CII in PDF/A-3 | ❌ | detect + extract only in v0.1.0: they carry no lines (and MINIMUM no VAT breakdown), which the canonical model requires (D1); `parse` raises `ParseError` ([#69](https://github.com/letsrevel/euinvoice/issues/69)) | ✅ (v0.1.0: ❌ until the Factur-X Schematron is pinned, [#42](https://github.com/letsrevel/euinvoice/issues/42)) |
| FatturaPA 1.2.3, FPR12 only (Italy, SdI); TD01, TD04, TD24, TD17 (M11, after v0.1.0) | FatturaPA XML | ✅ one body per file, unsigned; no FPA12, no transmission | ✅ 1..n bodies (API shape for several bodies decided in #120, see 11.5); the rest in `ParseResult.unmapped` | ✅ XSD 1.2.3 + offline SdI checks (D8) |

### Non-goals for v0.1.0 (later waves, each a separate spec)

- **Wave 2:** ebInterface (AT), other EN 16931 CIUSes (CIUS-RO, CIUS-HR, FR 2026 reform profiles,
  OIOUBL/DK, NLCIUS, …).
- **Wave 3:** national non-EN 16931 syntaxes: KSeF FA(3) (PL), Facturae (ES). FatturaPA (IT) moved
  forward to M11 (maintainer, 2026-10-07, #115).
- **Wave 4:** transports / clearance: Peppol access-point integrations (AS4 via providers), SDI, KSeF
  API, NAV, myDATA, VERI\*FACTU/TicketBAI, SAF-T.
- Consumer integrations (Revel, the maintainer's invoice CLI). They consume this library later and
  are explicitly out of scope here.
- Rendering human-readable PDFs. The consumer renders and euinvoice only embeds.
- Invoice numbering, persistence, e-mail, network delivery.

The architecture must make waves 2–3 additive: a new syntax is a new `syntax/` module plus profiles,
and a new CIUS is a new profile. Neither may require model rewrites.

---

## 2. Locked design decisions

- **D1 · Semantic model at the centre (approach A).** One canonical EN 16931 model with hand-written,
  bidirectional mappers per syntax. No generated XSD bindings (xsdata) and no templates.
- **D2 · Framework-free, side-effect-free core.** The core never imports Django, never performs I/O
  and never touches the network. Bytes go in and bytes come out. The only network code is the explicit
  artifact fetcher (D7).
- **D3 · Pydantic v2, frozen models, `Decimal` everywhere.** Floats are rejected at the boundary;
  validators must reject `float` inputs for amounts, quantities, prices and rates. Field names are
  readable snake_case (`seller.vat_identifier`), and every field carries its EN 16931 id in metadata
  (`json_schema_extra={"bt": "BT-31"}`). Error messages and docs cite BT/BG ids.
  *Amended by the maintainer on 2026-10-07 (#115, ADR 0001):* data with no EN 16931 business term lives
  only in optional, frozen per-country extension objects (`.it`), rooted at `Invoice.it` (also on the
  draft). Line-level concepts nest on `InvoiceLine.it` (also on `LineDraft`), and VAT-breakdown
  concepts are keyed from `Invoice.it` by rate, `Natura` and split payment, because BG-23 is derived
  by `calc.complete` (decided in #118). Each extension field cites its national element id in its
  metadata under a per-syntax key instead of `bt`, e.g.
  `json_schema_extra={"fatturapa": "2.1.1.1"}` (`TipoDocumento`). EN terms stay in the core model;
  `bt_index` skips extensions, and a test asserts every extension field carries such an id.
- **D4 · One document model.** Invoice and credit note share one model. The document type code
  (BT-3, UNTDID 1001: 380, 381, 384, 389, 751, …) decides the UBL root (`Invoice` vs `CreditNote`).
  There is no class hierarchy.
- **D5 · Profiles are plugins.** A `Profile` declares: id, supported syntaxes, specification identifier
  (BT-24), business process (BT-23) default, extra mandatory fields, the official rule sets to run and,
  for Factur-X, the attachment filename and XMP conformance level. Profiles may add *pre-flight* checks
  for good error messages, but the official Schematron is the oracle (D8).
- **D6 · Dependencies.** Core: `pydantic`, `lxml`. Extra `[validate]`: `saxonche` (SaxonC-HE, MPL-2.0,
  XSLT 3.0). Extra `[pdf]`: `pypdf` (BSD). **No `factur-x` package**: it pulls `python-stdnum` (LGPL)
  and `requests`. Factur-X embedding is implemented directly on pypdf. **No pretix code or packages**
  (maintainer decision). New runtime dependencies need a `needs-human` issue.
- **D7 · Official artifacts are fetched, never vendored.** CEN artifacts are EUPL-1.2, the Peppol rules
  repo carries no licence file, and others vary. So the library ships a **manifest**
  (`src/euinvoice/validation/manifest.toml`) of pinned sources (URL, version, sha256, member paths, licence).
  `euinvoice artifacts fetch` downloads them into `$EUINVOICE_ARTIFACTS_DIR` (default
  `~/.cache/euinvoice`), verifies them and precompiles Schematron → XSLT where needed. `validate()` never
  downloads implicitly. It raises `ArtifactsNotAvailableError` with the exact command to run. Test
  corpora follow the same rule: upstream examples are fetched, and only small **synthetic** fixtures are
  committed.
- **D8 · The official Schematron is the source of truth.** Python-side checks are a convenience layer
  that must never contradict it. If our pre-flight check and the Schematron disagree, the Schematron
  wins and we fix our code. We never suppress, filter or downgrade an official rule to make a test pass.
  Known upstream bugs (e.g. CEN issue #508, worked around by XRechnung's BR-TMP rules) are handled
  exactly as the upstream workaround does, documented and linked.
  *Amended by the maintainer on 2026-10-07 (#115, ADR 0001):* FatturaPA has no official Schematron and
  no public validator. Its oracle is the pinned **XSD 1.2.3** plus the offline-decidable SdI checks of
  **Allegato A 1.9.1, Appendix 1**, which we encode ourselves as `Finding`s whose `rule_id` is the SdI
  error code (e.g. `00421`) and whose message cites it. They are our reading of official prose, so each
  cites its code and has a passing and a failing test. Every such finding is an `error` (decided in
  #121: SdI rejects the file for each code, and `fatal` stays the flag of official machine-readable
  artifacts). FatturaPA is validated by syntax, not by profile (it has no BT-24). This
  includes 00409 (duplicate invoice within the lotto), which is decidable from the file's bodies. Out of
  scope, each with its reason, and documented as such:
  - **tax register or SdI state** (#115 decision 2): identifiers and VAT groups (00300–00306,
    00320–00327); `CodiceDestinatario` not existing or not active in SdI (00311, 00312); a duplicate of
    an invoice sent earlier (00404); invalidated declaration of intent (00477); a `PECDestinatario` that
    is one of SdI's own mailboxes (00330: the set of SdI mailboxes is SdI's data, Allegato A only shows
    their form `sdixx@pec.fatturapa.it`);
  - **file name** (00001, 00002): `validate()` receives bytes, not a file name, and 00002 needs SdI
    state. The #119 file-name helper checks the 00001 syntax separately;
  - **signature** (00100–00105, 00107): v1 is unsigned (#115 decision 1), and certificate checks need
    CA state;
  - **compressed file** (00106, empty or unreadable archive): `validate()` receives the XML, not the
    ZIP a sender may transmit;
  - **file size** (00003, decided in #121): the limit applies to the transmitted file (possibly a signed
    envelope), and "5MB" (Allegato A §1.3.1) does not say 10^6 or 2^20 bytes; the #119 file helper owns it;
  - **SdI receipt date** (00403): the invoice date is compared with the date SdI receives the file;
  - **format** (00200, 00201): the XSD step, reported as `XSD` findings;
  - **simplified invoices** (00460): FSM10 is not in scope;
  - **ambiguous prose** (00424, and the parts of 00409, 00423, 00471–00473 that Allegato A leaves open):
    listed in [#130](https://github.com/letsrevel/euinvoice/issues/130) (`needs-human`).
- **D9 · Validation results are data, not exceptions.** `validate()` returns a `ValidationReport`
  (list of `Finding(rule_id, severity: fatal|error|warning|information, location (XPath), message, source
  rule set)`, `.ok` = no fatal/error). Exceptions are only for misuse (bad input type, malformed XML,
  missing artifacts).
- **D10 · Hardened XML.** All parsing goes through one factory: `lxml.etree.XMLParser(resolve_entities=False,
  no_network=True, load_dtd=False, huge_tree=False, remove_blank_text=False)`, and any document with a
  DOCTYPE is rejected. Saxon only ever receives XML that has already passed this parser (as an XDM node
  built from the lxml-serialized bytes). Tests prove XXE / billion-laughs inputs are rejected.
- **D11 · Calculation per EN 16931.** `euinvoice.calc` derives line net amounts, document totals and
  the VAT breakdown, rounding monetary amounts to 2 decimals with `ROUND_HALF_UP`. Verify the
  exact expectations and tolerances against the BR-CO-\* / BR-DEC-\* rules in the pinned
  Schematron, not from memory. Consumers may supply totals themselves. Then
  `calc.check(invoice)` reports inconsistencies with BR ids.
- **D12 · Python ≥ 3.12**, CI on 3.12 / 3.13 / 3.14. `import typing as t` convention. mypy `--strict`
  over `src` and `tests`. Google-style docstrings on public API.
- **D13 · Licence: MIT**, package name `euinvoice`, GitHub `letsrevel/euinvoice`.

---

## 3. Normative and reference sources

EN 16931-1 (semantic model) and CEN/TS 16931-3-2/-3-3 (syntax bindings) are **paywalled CEN
standards**. Do not reproduce their text. Use these free, authoritative equivalents:

| What | Source | Licence | Pin (verify latest at implementation time) |
|---|---|---|---|
| CEN validation artifacts (UBL + CII Schematron, compiled XSLT, code lists, official examples) | github.com/ConnectingEurope/eInvoicing-EN16931, release assets `en16931-ubl-<v>.zip`, `en16931-cii-<v>.zip` | EUPL-1.2 | `validation-1.3.16` (2026-04-13) |
| Peppol BIS Billing 3.0 rules + examples + **UBL syntax binding docs** (BT ↔ XPath) | github.com/OpenPEPPOL/peppol-bis-invoice-3 (`rules/sch/*.sch`, `rules/examples`, `rules/unit-*`), docs.peppol.eu/poacc/billing/3.0/ | no licence file → fetch only | tag `v3.0.20` (2026-03-16); XRechnung 2.6.0 already references 3.0.21, so check for newer tags/commits |
| XRechnung Schematron (UBL + CII, compiled XSL) | github.com/itplr-kosit/xrechnung-schematron, release asset `xrechnung-3.0.2-schematron-2.6.0.zip` | Apache-2.0 | `v2.6.0` (2026-08-31) |
| XRechnung test suite (valid/invalid instances, UBL + CII) | github.com/itplr-kosit/xrechnung-testsuite | Apache-2.0 | `v2026-08-31` |
| XRechnung specification (semantic model table with **both** UBL and CII XPaths per BT) | xeinkauf.de (XRechnung 3.0.x spec PDF) | free to use | 3.0.2 |
| KoSIT validator configuration (scenarios: which XSD + Schematron per document type; useful oracle) | github.com/itplr-kosit/validator-configuration-xrechnung | Apache-2.0 | `v2026-08-31` |
| Factur-X / ZUGFeRD specification, XSDs and Schematron per profile | FNFE-MPE (fnfe-mpe.org) Factur-X package; FeRD (ferd-net.de) ZUGFeRD package | check the package licence; fetch only | Factur-X 1.07.x / ZUGFeRD 2.3.x as of writing, verify the newest and record the exact version |
| ZUGFeRD / Factur-X sample corpus | github.com/ZUGFeRD/corpus | Apache-2.0 | pin a commit sha |
| UBL 2.1 XSD | OASIS, docs.oasis-open.org/ubl/os-UBL-2.1/ (UBL-2.1.zip) | OASIS IPR (redistributable) | 2.1 |
| UN/CEFACT CII XSD (D16B for EN 16931 CII) | unece.org (CEFACT XML schemas); the Factur-X package ships its own CII XSD, so use the one each profile mandates | UNECE terms | D16B (+ whatever Factur-X mandates; verify) |
| Code lists | Derived from the pinned CEN Schematron code-list files (`EN16931-UBL-codes.sch`, `EN16931-CII-codes.sch`); cross-check with the EC "EN 16931 code lists" publication | n/a | same as CEN pin |
| Schematron → XSLT compiler (only for rule sets shipped as `.sch` only, e.g. Peppol) | SchXslt (github.com/schxslt/schxslt), run on Saxon | MIT | latest 1.x release |
| FatturaPA XSD (one schema for FPA12 and FPR12; namespace `http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2`, root `FatturaElettronica`; imports xmldsig by absolute http URL, resolved to a local copy per D10) | Agenzia Entrate (AE) file `https://www.agenziaentrate.gov.it/portale/documents/d/guest/schema_vfpr12_v1-2-3` (preferred), linked from the AE page for the 1.9.1 specs, agenziaentrate.gov.it/portale/specifiche-tecniche-versione-1.9.1-%C2%A0-utilizzabili-dal-15-maggio-2026-; byte-identical copy at fatturapa.gov.it `/export/documenti/fatturapa/v1.4/Schema_VFPR12_v1.2.3.xsd` | fatturapa.gov.it reserves all rights; fetch only, never committed or redistributed, AE copies preferred (maintainer, 2026-10-07, #115) | 1.2.3 (valid from 2025-04-01), sha256 `152944f6eef9f5d69ef6e955ee173b32142b00a8c1c5222fc97dfab5910e8a8c` |
| SdI checks and error codes (**Allegato A**, Specifiche tecniche, Appendix 1; prose). This is the check list we follow for FPR12 (D8). The fatturapa.gov.it "Elenco dei controlli" PDF v2.0 (31/01/2025, `/export/documenti/fatturapa/v1.4/Elenco-Controlli-versione-2.0.pdf`) is a different list: it also has the IPA checks 00398/00399 for public-administration buyers and lacks 00313, 00325, 00326, 00327 and 00330. It is not used | AE file `https://www.agenziaentrate.gov.it/portale/documents/d/guest/allegato-a-specifiche-tecniche-vers-1-9-1`, linked from the same 1.9.1 page | as above: fetch only | 1.9.1 (31/03/2026, usable from 15/05/2026) |
| FatturaPA example invoices (corpus for 11.5/11.6): `IT01234567890_FPR01.xml`, `_FPR02.xml`, `_FPR03.xml` (and `_FPA01`–`_FPA03`), linked from the fatturapa.gov.it "Formato FatturaPA" page | fatturapa.gov.it `/export/documenti/fatturapa/v1.2/IT01234567890_FPR0{1,2,3}.xml` | as above: fetch only | as published; FPR02 is known-invalid against XSD 1.2.3 (`ContattiTrasmittente` not expected); FPR03 has 2 bodies. Not pinned separately (#117): the conformance tests use the copies in the pinned `zugferd-corpus` (`fatturaPA/official/valid/`), content-identical to the fatturapa.gov.it files apart from line endings (FPA02 byte-identical; verified 2026-10-07) |
| Official EN 16931 ↔ FatturaPA mapping: SdI rules for European invoices, "Regole tecniche relative alla gestione delle fatture di cui all'art. 3, comma 1, d.lgs. 148/2018" (App. 4.1 FatturaPA ↔ semantic model; App. 5 code tables: Natura, Ritenuta, Cassa previdenziale, TipoDocumento, RegimeFiscale, ModalitaPagamento). Written for UBL/CII to public administration; applies to FPR12 by analogy (same XSD) | fatturapa.gov.it `/export/documenti/Specifiche-Tecniche-Fatturazione-Europea-v2.6.pdf` | as above: fetch only | 2.6 (15/05/2025) |

**Facts verified during scoping (2026-10-05):** with `saxonche` 13.0.0 on macOS arm64, the compiled CEN
`EN16931-UBL-validation.xslt` compiles in about 0.14 s and validates `ubl-tc434-example1.xml` in about
6 ms with 0 failed asserts. Removing `cbc:ID` from that example yields exactly `BR-02` (flag `fatal`). Use
`transform_to_string(xdm_node=…)` and parse the SVRL with lxml
(`http://purl.oclc.org/dsdl/svrl`, elements `failed-assert` / `successful-report`, attributes `id`, `flag`,
`location`, child `text`).

**Mapping-table rule:** every BT/BG in the model must cite, in a code comment or the mapping table
`docs/reference/bt-mapping.md`, its UBL XPath (from Peppol BIS docs) and its CII XPath (from the
XRechnung spec). Where the two sources disagree, the CEN Schematron's syntax-binding rules decide.
For FatturaPA, mapped BTs cite App. 4.1 of the Regole tecniche v2.6, and `Invoice.it` fields cite
their FatturaPA element id (D3).

---

## 4. Architecture

```
src/euinvoice/
  __init__.py        # public API re-exports (to_xml, parse, validate, detect, Invoice, …)
  __main__.py        # CLI: python -m euinvoice {validate,convert,info,artifacts fetch}
  errors.py          # exception hierarchy: EuInvoiceError → ModelError, ParseError, UnsupportedDocumentError,
                     #   ArtifactsNotAvailableError, ArtifactIntegrityError, PdfError
  _xml.py            # D10 hardened parser factory, namespace maps, small element builders
  model/
    __init__.py
    _base.py         # frozen BaseModel config, BT metadata helper, Decimal-only validators
    amounts.py       # Amount / Quantity / Percentage / UnitPrice annotated Decimal types
    codes/           # code lists: _generated.py (from CEN code-list Schematron) + hand-written enums
                     #   for the small semantic ones (VatCategory, DocumentType, …)
    invoice.py       # Invoice (BG-0 root): BT-1..BT-25 header, references, notes (BG-1), process (BG-2)
    parties.py       # Seller BG-4, Buyer BG-7, Payee BG-10, TaxRepresentative BG-11, PostalAddress
                     #   BG-5/8/12/15, Contacts BG-6/9, electronic addresses BT-34/BT-49 with scheme
    delivery.py      # BG-13 delivery, BG-14 invoicing period
    payment.py       # BG-16 payment instructions, BG-17 credit transfer, BG-18 card, BG-19 direct debit
    allowances.py    # BG-20 document allowances, BG-21 document charges, BG-27/BG-28 line level
    tax.py           # BG-23 VAT breakdown, exemption reason (BT-120/121)
    totals.py        # BG-22 document totals
    lines.py         # BG-25 line, BG-26 line period, BG-29 price details, BG-30 line VAT, BG-31 item,
                     #   BG-32 item attributes
    documents.py     # BG-24 additional supporting documents (incl. embedded binary objects BT-125)
    bt_index.py      # registry: every BT/BG id → model path; drives coverage tests and error messages
    it/              # M11: Invoice.it extension (EXT-IT concepts with no BT, D3); fields cite FatturaPA
                     #   element ids; code enums (TD, RF, Natura, MP, TP) checked against XSD 1.2.3
  calc/              # D11: build/derive totals + VAT breakdown; check() → findings with BR-CO ids
  report.py          # ValidationReport, Finding, Severity (pure data; used by calc and validate)
  syntax/
    __init__.py      # Syntax enum {UBL, CII, FATTURAPA}; FATTURAPA is detected and validated (11.6), read/written in 11.5/11.4
    ubl.py           # write(invoice, profile) -> bytes ; read(root) -> Invoice   (Invoice + CreditNote)
    cii.py           # write / read for rsm:CrossIndustryInvoice
    fatturapa/       # M11: FPR12 write (one body; transmission header from writer options) / read
                     #   (1..n bodies); pure SdI file-name, 5 MB and ASCII/Latin-1 helpers. No signing and no
                     #   transmission: delivery stays outside the core (#114)
  profiles/
    __init__.py      # Profile protocol + registry, lookup by BT-24 value
    en16931.py
    peppol.py
    xrechnung.py
    facturx.py       # MINIMUM, BASIC_WL, BASIC, EN16931, EXTENDED, XRECHNUNG levels
  detection.py       # bytes → (syntax, document kind, profile) from root element + BT-24
  validation/        # was validate/ (and detect.py) until #93: the functions shadow no module
    __init__.py      # validate(xml_bytes, profile=None) -> ValidationReport
    manifest.toml    # D7 pinned artifact sources
    artifacts.py     # cache dir resolution, fetch + sha256 verify + unzip (or single file) + SchXslt precompile
    xsd.py           # lxml XMLSchema per syntax/profile
    schematron.py    # saxonche runner, per-process compiled-executable cache, SVRL → Finding
    sdi.py           # M11: offline SdI checks for FatturaPA (Allegato A 1.9.1), rule_id = SdI code (D8)
  facturx/
    __init__.py      # embed(pdf, xml|invoice, profile) -> bytes ; extract(pdf) -> (xml, profile)
    xmp.py           # Factur-X/ZUGFeRD XMP extension schema + PDF/A extension schema description
```

**Public API (target):**

```python
from euinvoice import Invoice, to_xml, parse, validate, detect, profiles, calc

invoice = calc.complete(draft)  # fills BG-22 totals + BG-23 breakdown
xml: bytes = to_xml(invoice, profile=profiles.XRECHNUNG, syntax="cii")
report = validate(xml)  # profile auto-detected from BT-24
assert report.ok, report.findings
same = parse(xml)  # UBL / CII / Factur-X PDF bytes
assert same == invoice

from euinvoice import facturx

pdf_a3: bytes = facturx.embed(rendered_pdf_a3, invoice, profile=profiles.FACTURX_EN16931)
xml2, prof = facturx.extract(pdf_a3)
```

**Data flow:** `Invoice` (validated model) → `profile.prepare(invoice)` (defaults such as BT-23/BT-24, plus
pre-flight checks) → `syntax.write()` → bytes → `validate()` (XSD → CEN Schematron → profile Schematron) →
`ValidationReport`. Parsing runs in reverse: `detect()` → `syntax.read()` → `Invoice`. Unknown or out-of-model
elements are collected into `ParseResult.unmapped` (XPath list) rather than dropped silently. `parse()`
returns the `Invoice` and exposes `parse_detailed()` for the full result.

**Round-trip invariant (the core quality bar):** for every valid upstream example X in the corpus,
`validate(write(read(X)))` has no fatal or error findings, and `read(write(read(X))) == read(X)`.
For FatturaPA, the 11.5 AC replaces it: FPR12 → model → FPR12 is lossless for the v1 subset, per body.

---

## 5. Factur-X / ZUGFeRD specifics (verify against the official spec package)

- The input PDF **must already be PDF/A-3** (e.g. WeasyPrint `pdf_variant="pdf/a-3b"`). euinvoice
  does not convert to PDF/A. `embed()` checks the XMP `pdfaid:part == 3` and raises `PdfError` otherwise.
- Embedded file name: `factur-x.xml` for Factur-X / ZUGFeRD ≥ 2.1 profiles, and `xrechnung.xml` for the
  ZUGFeRD XRECHNUNG profile. Verify both in the spec.
- The file spec must carry `/AFRelationship` (allowed values and the default per spec: `Data`, `Source`,
  `Alternative`; verify), be referenced from the catalog `/AF` array, have MIME subtype `text/xml`, and
  carry `ModDate`.
- XMP: the Factur-X extension schema (`urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#`, prefix
  `fx`) with `DocumentType=INVOICE`, `DocumentFileName`, `Version`, `ConformanceLevel`, **plus** the
  PDF/A extension schema description (`pdfaExtension:schemas`) declaring it. Verify the exact property
  set and the conformance-level strings per profile.
- Guideline IDs (BT-24) per profile come from the spec, e.g. EN16931 `urn:cen.eu:en16931:2017`, BASIC
  `urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic`, MINIMUM `urn:factur-x.eu:1p0:minimum`,
  BASIC WL `urn:factur-x.eu:1p0:basicwl`, EXTENDED `urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended`.
  Verify every one.
- CI conformance job: run **veraPDF** (Docker image `verapdf/cli`, PDF/A-3B flavour) on every
  generated Factur-X fixture.

## 6. Profile identifiers (verify against the pinned artifacts)

- EN 16931 core: BT-24 `urn:cen.eu:en16931:2017`
- Peppol BIS Billing 3.0: BT-24 `urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0`,
  BT-23 `urn:fdc:peppol.eu:2017:poacc:billing:01:1.0`
- XRechnung 3.0: BT-24 `urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0`
- Do not hand-transcribe profile-specific mandatory fields from memory (e.g. XRechnung's BT-10
  Leitweg-ID, BG-6 seller contact, BG-16; Peppol's BT-34/BT-49 electronic addresses). Derive them from
  the pinned Schematron and cite the rule ids in the pre-flight checks.

---

## 7. Quality bar

- `make check` (ruff format/lint incl. flake8-bandit, mypy strict on src + tests, file length ≤ 600)
  and `make test` (≥ 95 % branch coverage) pass on Python 3.12, 3.13 and 3.14.
- TDD. A test that fails for the right reason comes first, and every bug fix gets a regression test.
- **Every BT** (≈ 160) is covered by at least one write test and one read test in **each** syntax
  (enforced by a test that walks `bt_index` against a coverage registry).
- Property tests (Hypothesis): random valid invoices built through `calc` validate with no
  fatal or error findings against EN 16931 core in both syntaxes, and round-trip exactly.
- Conformance suite green against the pinned upstream corpora (see §4 round-trip invariant). Known
  upstream-invalid samples are asserted to *fail* with their documented rule ids.
- Security: D10 tests (XXE, external DTD, billion laughs, oversized input), no `eval`/`exec`, no
  shelling out.
- Public API fully typed and documented. `py.typed` ships.

---

## 8. Work breakdown

The notation is **ID · title** → *depends on* → acceptance criteria. Each item is one GitHub issue
(title prefix `[Mx.y]`) and one PR. Items in the same wave with satisfied dependencies may run in
parallel. Each touches a disjoint set of files.

### M0 · Repository bootstrap
- **0.1 · GitHub hygiene.** *deps: none.* Labels: `m0`…`m11`, `area:model`, `area:ubl`, `area:cii`,
  `area:validate`, `area:profiles`, `area:pdf`, `area:api`, `area:docs`, `area:fatturapa`, `needs-human`,
  `artifacts`, `dependencies`, `security`. Branch protection on `main`: PR required, required checks = `Lint & type
  checks`, `Tests (py3.12)`, `Tests (py3.13)`, `Tests (py3.14)`, `Build sdist + wheel`, `Conformance
  (official artifacts)`; squash-merge only; delete branch on merge. Repo description + topics.
  *AC:* `gh api` shows the protection; a test PR cannot merge red.

### M1 · Foundations
- **1.1 · Artifact manifest + fetcher + CLI stub.** *deps: none.* `validation/manifest.toml` with every
  §3 source (URL, version, sha256, licence, member globs), `validation/artifacts.py`
  (stdlib `urllib` only, atomic write, sha256 verify, zip-slip-safe extraction, cache layout
  `<dir>/<source>/<version>/`), `python -m euinvoice artifacts fetch [--only NAME]`, `make artifacts`.
  SchXslt precompile step for `.sch`-only sources, cached as `.xslt` next to the source. *AC:* fetch is
  idempotent, a corrupted file is detected, offline with a warm cache works, unit tests mock the network,
  and a conformance-marked test does the real fetch.
- **1.2 · Code lists.** *deps: 1.1.* `scripts/gen_codelists.py` extracts every code list from the
  pinned CEN code-list Schematron into `model/codes/_generated.py` (frozensets, header comment citing
  the source version), plus hand-written `StrEnum`s for VatCategory (UNCL5305 subset used by EN 16931),
  DocumentType (UNTDID 1001 subset), etc. *AC:* regenerating is deterministic, and a test asserts the
  generated file matches the generator output for the pinned version.
- **1.3 · Hardened XML utilities (`_xml.py`).** *deps: none.* D10 parser factory, DOCTYPE rejection,
  namespace constants for UBL Invoice/CreditNote/cac/cbc and CII rsm/ram/udt/qdt. *AC:* a test fails if `etree.fromstring`, `etree.parse`, `etree.XML` or `XMLParser(` appears in `src/` outside `_xml.py`; XXE /
  billion-laughs / external-DTD tests.
- **1.4 · Amount types + errors.** *deps: none.* `model/amounts.py`, `model/_base.py`, `errors.py`.
  Decimal-only (floats rejected with a clear message), quantization helpers, BT metadata helper.
  *AC:* unit + Hypothesis tests.

### M2 · Semantic model
- **2.1 · Full EN 16931 semantic model + `bt_index`.** *deps: 1.2, 1.4.* All BG-0…BG-32 / BT-1…BT-165
  with correct cardinalities, BT metadata, the EN 16931 data types (Amount, UnitPriceAmount, Quantity,
  Percentage, Identifier with scheme, Date, Code, Text, BinaryObject with mime + filename) and
  `bt_index` completeness. Write `docs/reference/bt-mapping.md` (BT → model path → UBL XPath → CII XPath).
  *AC:* a test asserts every BT/BG id appears exactly once in `bt_index`, and models are frozen, hashable
  where sensible and `==`-comparable.
- **2.2 · `calc`.** *deps: 2.1.* `complete(draft)` and `check(invoice)` per D11. *AC:* worked examples from
  the CEN/Peppol example files reproduce their totals exactly (including `CII-BR-CO-10-RoundingIssue.xml`),
  and Hypothesis invariants hold for BR-CO-10…BR-CO-17 equivalents.

### M3 · UBL 2.1
- **3.1 · UBL writer.** *deps: 2.1, 1.3.* Invoice and CreditNote roots (CreditNote uses
  `CreditNoteTypeCode`, `CreditNoteLine`, `CreditedQuantity`), element order per the UBL 2.1 XSD sequence,
  every BT. *AC:* per-BT write tests, and output passes the UBL 2.1 XSD (3.3) once available.
- **3.2 · UBL reader.** *deps: 3.1.* *AC:* per-BT read tests, `unmapped` reporting, and round-trip of every
  CEN UBL example (conformance-marked).
- **3.3 · UBL XSD validation.** *deps: 1.1, 1.3.* `validation/xsd.py` for UBL. *AC:* official examples pass,
  and a mutated example fails with a located error.

### M4 · UN/CEFACT CII (parallel with M3)
- **4.1 · CII writer.** *deps: 2.1, 1.3.* `rsm:CrossIndustryInvoice`, element order per XSD, date
  `format="102"`, every BT. *AC:* as 3.1.
- **4.2 · CII reader.** *deps: 4.1.* *AC:* as 3.2 over the CEN CII examples.
- **4.3 · CII XSD validation.** *deps: 1.1, 1.3.* *AC:* as 3.3.

### M5 · Schematron validation
- **5.1 · Schematron runner + report.** *deps: 1.1, 1.3.* `validation/schematron.py`, `report.py`.
  Compiled executables cached per process (keyed by artifact path + version), thread safety documented,
  SVRL → `Finding`. *AC:* reproduces the scoping facts (example1 → 0 findings; drop `cbc:ID` → `BR-02`
  fatal).
- **5.2 · `validate()` orchestration.** *deps: 5.1, 3.3, 4.3, 6.1.* Detect → XSD → CEN rules → profile
  rules (Peppol / XRechnung / Factur-X). A failed XSD step short-circuits with its findings. *AC:*
  correct rule sets per profile, and findings are tagged with their source rule set.
- **5.3 · Upstream drift check.** *deps: 1.1.* `scripts/check_upstream.py`: compares manifest pins with the
  latest upstream releases/tags (GitHub API via `GH_TOKEN`) and exits non-zero on drift (the nightly
  workflow opens an issue). *AC:* unit tests with mocked API.

### M6 · Profiles
- **6.1 · Profile protocol + registry + EN 16931 core.** *deps: 2.1.* *AC:* lookup by BT-24, unknown
  BT-24 → `UnsupportedDocumentError` listing the known ones.
- **6.2 · Peppol BIS Billing 3.0 (UBL, CII).** *deps: 6.1, 3.1, 5.1.* Pre-flight checks derived from
  PEPPOL-EN16931-R\* rules (cite ids). *AC:* Peppol examples + `unit-UBL-PEPPOL` test cases behave as
  upstream expects.
- **6.3 · XRechnung 3.0 (UBL + CII).** *deps: 6.1, 3.1, 4.1, 5.1.* Pre-flight from BR-DE-\* rules. *AC:*
  the XRechnung test suite's valid instances pass, and invalid ones fail with the expected ids.
- **6.4 · Factur-X / ZUGFeRD levels.** *deps: 6.1, 4.1, 4.2, 5.1.* Generate EN16931 + XRECHNUNG, parse
  all levels (EXTENDED/BASIC/WL/MINIMUM → model subset + `unmapped`). *AC:* ZUGFeRD corpus round-trip for
  supported levels. *Decided for v0.1.0 (#69):* MINIMUM and BASIC WL are detected and extracted but not parsed
  (`ParseError`), since they lack terms D1's model requires; a separate subset reader can be added later.

### M7 · Factur-X PDF
- **7.1 · `facturx.embed`.** *deps: 4.1, 6.4.* pypdf implementation per §5. *AC:* veraPDF PDF/A-3B passes
  on fixtures (conformance job), and non-PDF/A input raises `PdfError`.
- **7.2 · `facturx.extract`.** *deps: 7.1.* Handles `factur-x.xml`, `zugferd-invoice.xml` (ZUGFeRD 1/2.0
  legacy names, extract only) and `xrechnung.xml`. *AC:* corpus PDFs extract.
- **7.3 · veraPDF in CI.** *deps: 7.1.* Add to the `conformance` job. *AC:* job fails on a deliberately
  broken PDF.

### M8 · Public API + CLI
- **8.1 · `detect`.** *deps: 6.1.* *AC:* every corpus file is classified correctly, and garbage is rejected
  with `UnsupportedDocumentError`.
- **8.2 · Top-level API** (`to_xml`, `parse`, `parse_detailed`, `validate`, re-exports, `__all__`).
  *deps: 3.2, 4.2, 5.2, 7.2, 8.1.* *AC:* README examples run as doctests.
- **8.3 · CLI** `python -m euinvoice validate FILE [--profile]`, `convert FILE --to ubl|cii [--profile]`,
  `info FILE`, `artifacts fetch`. Exit codes 0 / 1 (findings) / 2 (usage). JSON output flag. *deps: 8.2.*

### M9 · Conformance suite
- **9.1 · Corpus harness.** *deps: 3.2, 4.2, 5.2.* Parametrised conformance tests over every fetched
  upstream example (CEN UBL/CII, Peppol, XRechnung test suite, ZUGFeRD corpus) asserting the §4
  invariant. Expected-invalid lists are kept in `tests/conformance/expected_invalid.toml` with a reason and
  upstream link per entry.
- **9.2 · Cross-syntax.** *deps: 9.1.* UBL → model → CII → model is lossless for every BT expressible in
  both, and validates.
- **9.3 · Property-based conformance.** *deps: 2.2, 5.2.* Hypothesis-generated invoices validate against
  EN 16931 core, Peppol and XRechnung (with their mandatory fields generated), in both syntaxes.
- **9.4 · BT coverage gate.** *deps: 3.2, 4.2.* A test fails if any BT lacks a write and a read test per
  syntax. It generates `docs/reference/bt-coverage.md`. For FatturaPA (M11) the gate covers only the
  BTs that App. 4.1 of the Regole tecniche v2.6 maps; the BTs with no FatturaPA home are reported (writer
  pre-flight findings, `ParseResult.unmapped`), not round-tripped.

### M10 · Docs + release prep
- **10.1 · Docs site.** *deps: 8.2.* mkdocs-material in `docs/`, published to GitHub Pages by a
  `docs.yaml` workflow (build `--strict` on PRs, deploy on main). Pages: quickstart; concepts (model, BTs,
  profiles, syntaxes); how to validate; Factur-X with WeasyPrint `pdf/a-3b`; mapping guide for consumers
  ("from your billing model to `Invoice`"), with a **synthetic** freelancer example (domestic 20 % VAT,
  intra-EU reverse charge AE with exemption text, non-EU export/out-of-scope) and a **synthetic** ticketing
  example (per-line VAT rates, VAT-inclusive prices converted to net, credit note referencing the invoice
  BT-25); reference (API, bt-mapping, bt-coverage, artifact licences).
- **10.2 · README polish + CHANGELOG `[0.1.0]`.** *deps: 10.1.*
- **10.3 · Release PR `release/v0.1.0`.** *deps: everything in M0–M10.* Bump with `uv version`, promote the CHANGELOG,
  open the PR, **and stop. Do not merge** (human-gated: PyPI trusted-publisher setup + final review).

### M11 · FatturaPA (Italy)
Added by the maintainer on 2026-10-07 (#115, option 1). v1 scope: FPR12 only; TD01, TD04, TD24, TD17;
write and read; a single body per file on write, 1..n bodies on read; no signing, no transmission. Mapping
policies (decimals on read, BG-20/21 on write, VAT categories O/L/M, default TD for BT-3 380, withholding
vs BR-CO-16, splitting first and last names) are settled during design and raised as `needs-human` where
the §3 sources do not settle them.
- **11.1 · Plan amendment** ([#116](https://github.com/letsrevel/euinvoice/issues/116)). *deps: none.*
  D3, D8, §1, §3, §4 and this milestone. *AC:* `uv run mkdocs build --strict`; the plan is internally
  consistent.
- **11.2 · Pin the FatturaPA artifacts** ([#117](https://github.com/letsrevel/euinvoice/issues/117)).
  *deps: none.* Single-file (non-zip) sources in the manifest, sha256-verified, same cache layout; the
  XSD 1.2.3 from the AE copy; the xmldsig import resolved locally with no network (D10); the
  fatturapa.gov.it example invoices (§3) come from the pinned `zugferd-corpus` copies, not a separate pin. *AC:*
  `make artifacts` fetches them, `make conformance` is green, and a test proves validation never touches
  the network.
- **11.3 · `Invoice.it` extension model** ([#118](https://github.com/letsrevel/euinvoice/issues/118)).
  *deps: 11.1.* The v1 subset of the EXT-IT concepts per D3; transmission data (IdTrasmittente,
  ProgressivoInvio, CodiceDestinatario fallback, PEC) are writer options, not model data. UBL/CII writers
  report a set `.it`, never drop it silently. *AC:* the `bt_index` test exempts extensions explicitly;
  model tests.
- **11.4 · FPR12 writer** ([#119](https://github.com/letsrevel/euinvoice/issues/119)). *deps: 11.2, 11.3.*
  Per App. 4–5 of the Regole tecniche v2.6 and the XSD element order; pre-flight findings for what FPR12
  cannot express. *AC:* every test document passes XSD 1.2.3; round trips with 11.5.
- **11.5 · FatturaPA reader** ([#120](https://github.com/letsrevel/euinvoice/issues/120)). *deps: 11.3
  (11.4 for round trips).* Reads 1..n bodies and fills `Invoice.it`; the rest goes to
  `ParseResult.unmapped`. *Open API decision for #120:* `parse()` / `ParseResult.invoice` are singular,
  so for example `parse()` raises `UnsupportedDocumentError` on a lotto with several bodies and a
  FatturaPA entry point returns the list. *AC:* the
  official examples (except the known-invalid FPR02) parse; FPR12 → model → FPR12 is lossless for the
  v1 subset.
- **11.6 · Validation and detection** ([#121](https://github.com/letsrevel/euinvoice/issues/121)).
  *deps: 11.2 (11.4 for test documents).* `detect()` recognizes FatturaPA; `validate()` runs XSD 1.2.3,
  then the offline SdI checks per D8 (excluded codes listed with reasons). FatturaPA has no BT-24, so
  profile resolution (D5) works differently; how is decided in #121. *AC:* a passing and a failing
  test per check; `make conformance` green.
- **11.7 · Docs, CLI and conformance corpus** ([#122](https://github.com/letsrevel/euinvoice/issues/122)).
  *deps: 11.4, 11.5, 11.6.* Docs page (scope, `Invoice.it`, writer options, what the validator does and
  does not check, out-of-scope compliance items), CLI `convert --to fatturapa` and `validate`, README
  matrix, CHANGELOG. *AC:* doctests; `mkdocs build --strict`.

**Deferred** (maintainer, 2026-10-07, #115): the Italian UBL profile, Peppol BIS Italia / CIUS-IT + EXT-IT
([#123](https://github.com/letsrevel/euinvoice/issues/123)); a Fatture in Cloud adapter in a delivery
package ([#124](https://github.com/letsrevel/euinvoice/issues/124)); FPA12 and signing; writing batch
files (lotti, several bodies per file). Transmission to SdI stays in
[#114](https://github.com/letsrevel/euinvoice/issues/114), and compliance outside the library (ticket-sales
regime, delivery channel) in [#125](https://github.com/letsrevel/euinvoice/issues/125).

### Waves (dependency-respecting parallel schedule)
1. 0.1 · 1.1 · 1.3 · 1.4
2. 1.2 · 5.1 · 5.3 · 3.3 · 4.3
3. 2.1
4. 2.2 · 3.1 · 4.1 · 6.1
5. 3.2 · 4.2 · 6.2 · 6.3 · 8.1
6. 6.4 · 5.2 · 9.4
7. 7.1 · 9.1 · 9.3
8. 7.2 · 7.3 · 9.2
9. 8.2
10. 8.3 · 10.1
11. 10.2 → 10.3

The waves are a guide. The dependency lists in each item are authoritative, so always schedule from
the "blocked by" graph.

2.1 is the critical path and is deliberately **one** issue for model coherence. Its implementer may
split the work into internal sub-PRs (`[M2.1a]`, `[M2.1b]`, …) by BG group if that is cleaner, but one
agent owns the whole model.

---

## 9. Execution protocol

This is for the orchestrating agent. It is also mirrored in CLAUDE.md.

1. **Setup.** Read CLAUDE.md, this plan and README. Run `zsh -ic gitsign` once in the main checkout
   (worktrees share `.git/config`, so every commit is SSH-signed). Verify `make check && make test` pass on
   `main`.
2. **Issues.** Create GitHub milestones `M0`…`M11` and one issue per §8 item. Use the title `[Mx.y] <title>`
   and paste the item verbatim into the body, plus a "Blocked by #n" line per dependency, the AC as a
   checklist, and a link to this plan section. Apply labels. Then create a tracking issue
   **"v0.1.0 build-out"** with a task list of all issues.
3. **Loop until every issue except 10.3 is closed:**
   - Pick the ready issues (all blockers closed). Run **at most 4 implementers in parallel**, each with
     `isolation: "worktree"`.
   - **Implementer subagent** (one issue): branch `feature/<issue#>-<slug>`, TDD, `make check` +
     targeted tests + `make conformance` when relevant, conventional commits, push, open a PR
     "Closes #n" with a summary and a verification section (commands run + outputs).
   - **Reviewer subagents** (fresh context, never the implementer): `spec-auditor` (conformance to
     EN 16931/profiles/§2 decisions; checks every claim against the pinned artifacts) and `pr-reviewer`
     (code quality, tests, simplicity). Findings go back to an implementer. Loop until both approve.
   - **Merge** when CI is fully green and both reviewers approve: `gh pr merge --squash --delete-branch`.
     The maintainer explicitly authorized self-merge for this repo (2026-10-05). Then tick the tracking issue.
   - After each wave, pull `main` and re-run `make check && make test && make conformance` on it. If
     anything is red, fix it before starting new work.
4. **Blockers.** If a question cannot be settled from the pinned artifacts and free specs (§3), comment
   on the issue, label it `needs-human`, note it in the tracking issue and continue with other ready
   work. Never guess on conformance and never weaken a test, rule or threshold to get green.
5. **Finish.** Open the 10.3 release PR (unmerged). Post a final summary on the tracking issue (what
   shipped, the BT coverage numbers, open `needs-human` items, upstream pins used), then notify the
   maintainer (push notification if available).

**M11 (after v0.1.0 shipped)** runs under this same protocol: milestone M11, issues #116–#122, tracked on
the dashboard issue #36. It ends when 11.7 merges. Any release is a separate, human-gated PR.

**Never:** push to `main` directly, merge a red PR, merge the release PR, publish to PyPI, add a
runtime dependency without `needs-human`, commit upstream artifacts or corpora, commit personal or
real-company invoice data (fixtures are synthetic only), or touch other repositories.
