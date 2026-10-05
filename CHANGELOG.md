# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Project scaffolding: tooling, CI (checks, 3.12–3.14 test matrix, conformance, build), dependency
  audits, release workflow with PyPI trusted publishing, implementation plan.
- `euinvoice.errors`: exception hierarchy (`EuInvoiceError`, `ModelError`, `ParseError`, …).
- `euinvoice.model.amounts`: Decimal-only `Amount`, `UnitPriceAmount`, `Quantity` and `Percentage`
  types. Floats are rejected; `Amount` allows at most two decimals (BR-DEC-*, UBL-DT-01) and is never
  rounded implicitly; `quantize_amount()` rounds half up to two decimals. In JSON they are fixed-point
  `xs:decimal` strings (never exponent notation) that reload exactly.
- Model foundations: models are immutable, hashable and reject unknown fields, and every field
  carries its EN 16931 BT/BG id in its JSON schema.
- Artifact manifest (`euinvoice/validate/manifest.toml`) pinning the official validation artifacts and
  corpora by URL + sha256: CEN EN 16931 1.3.16 (UBL, CII), Peppol BIS Billing 3.0.21, XRechnung
  Schematron 2.6.0, XRechnung test suite and KoSIT validator configuration 2026-08-31 (incl. the CII
  D16B XSD), OASIS UBL 2.1 XSD, ZUGFeRD corpus, SchXslt 1.10.1.
- `python -m euinvoice artifacts fetch [--only NAME]`: downloads into `$EUINVOICE_ARTIFACTS_DIR`
  (default `~/.cache/euinvoice/<source>/<version>/`), verifies sha256, extracts zip-slip-safely and
  precompiles Schematron-only rule sets (Peppol) to XSLT with SchXslt. Idempotent and offline on a
  warm cache. `euinvoice.validate.artifacts.source_dir()` looks entries up and raises
  `ArtifactsNotAvailableError` naming the fetch command.
