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
  rounded implicitly; `quantize_amount()` rounds half up to two decimals.
- `euinvoice.model._base`: frozen, strict `EuInvoiceModel` base and the `bt()` BT/BG metadata helper.
