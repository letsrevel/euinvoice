# Contributing

Thanks for helping make European e-invoicing less painful.

1. Read [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) (design decisions + sources) and
   [`CLAUDE.md`](CLAUDE.md) (project rules; they apply to humans too).
2. `make setup`, then `make artifacts` if you will touch serialization, parsing or validation.
3. Branch from `main` (`feature/<issue>-<slug>`), write tests first, then make
   `make check && make test` (and `make conformance` where relevant) pass.
4. Open a PR with `Closes #<issue>`, a short summary and a **Verification** section showing what you ran.

Ground rules: the official Schematron is the source of truth. Fixtures must be synthetic, so never
include real invoices or personal data. Official artifacts are fetched, never committed.
AI-assisted contributions follow the same rules and the same review bar.
