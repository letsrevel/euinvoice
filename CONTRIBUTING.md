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

## Releasing (maintainers)

1. Create a `release/vX.Y.Z` branch from `main`.
2. `uv version --bump <part>`.
3. Promote the CHANGELOG `[Unreleased]` section to `[X.Y.Z] - date` and update the compare links.
4. Update the version in the README ("Status", "What X.Y.Z supports") and in `docs/index.md`.
5. Review `docs/compliance.md` (status line, table rows, "Next up") against the tracker issue. The unit test
   `tests/test_docs.py::test_compliance_page_states_the_released_version` enforces the status line, so the version bump fails until the page is reviewed.
6. Open the PR. The maintainer merges it.
7. `release.yaml` then tags, creates the GitHub release, publishes to PyPI (after approval in the `pypi`
   environment) and deploys the docs for the tag (requires the repository variable `DOCS_DEPLOY=true`).
