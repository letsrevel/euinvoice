# ADR 0001: FatturaPA, per-country extensions (D3) and the FatturaPA oracle (D8)

- **Status:** accepted, decided by the maintainer on 2026-10-07
  ([#115](https://github.com/letsrevel/euinvoice/issues/115), comment "Maintainer decisions (2026-10-07)").
- **Amends:** D3 and D8 in `IMPLEMENTATION_PLAN.md` §2. Recorded by
  [#116](https://github.com/letsrevel/euinvoice/issues/116); the work is milestone M11 (#116–#122).

## Context

The #115 research (official sources only) found:

- FatturaPA, Italy's SdI format, is not an EN 16931 syntax. About a dozen of its concepts have no EN
  16931 business term (RegimeFiscale, the TipoDocumento code, Natura, EsigibilitaIVA, …), so neither
  direction of the mapping round-trips without an Italian extension layer. Locked D3 requires every
  model field to carry a BT id.
- There is no official Schematron and no public validator for FatturaPA. The official material is the
  XSD 1.2.3 (structure only) and the SdI checks in Allegato A 1.9.1, Appendix 1, which is prose. Locked
  D8 names the official Schematron as the oracle.

## Decision

1. FatturaPA becomes a third syntax with a narrow v1: FPR12 only; TD01, TD04, TD24, TD17; write and
   read; one body per file on write, 1..n bodies on read; no signing, no transmission.
2. **D3:** data with no EN 16931 business term lives only in optional, frozen per-country extension
   objects rooted at `Invoice.it` (also on the draft). Each extension field cites its national element
   id in its metadata instead of a BT.
   Refined in #118 under the delegation in plan D3: line-level concepts (2.2.1.x) hang on
   `InvoiceLine.it` (also on `LineDraft`). VAT-summary concepts (2.2.2.x) are keyed from
   `Invoice.it.vat_summaries` by (rate, Natura, split payment or not), because BG-23 is derived.
   Every hook carries the `extension("it")` marker.
3. **D8:** for FatturaPA, the oracle is the pinned XSD 1.2.3 plus the offline-decidable SdI checks,
   encoded as findings that each cite their Allegato A 1.9.1 error code. Registry and state checks are
   out of scope.
4. The fatturapa.gov.it and Agenzia Entrate artifacts are pinned fetch-only, never committed or
   redistributed, preferring the Agenzia Entrate copies.

## Consequences

- `bt_index` skips extensions, and a test checks that every extension field cites a national id.
- The SdI checks are our reading of official prose. Each one cites its error code and has a passing and
  a failing test; an ambiguous check becomes a `needs-human` issue, never a guess.
- `validate()` can accept a FatturaPA file that SdI still rejects for register or SdI-state reasons.
  The excluded codes are listed with reasons in D8 and in the user docs (#122).
- Mapping policies the sources do not settle (decimals on read, BG-20/21 on write, VAT categories
  O/L/M, the default TD for BT-3 380, withholding vs BR-CO-16, splitting names) are decided in design
  and raised as `needs-human`.
- Deferred: the Italian UBL profile (#123), a Fatture in Cloud adapter (#124), FPA12 and signing, and
  writing batch files (lotti). Transmission stays outside the core (#114).
