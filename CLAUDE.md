# CLAUDE.md

Guidance for Claude Code working in **euinvoice**, an MIT-licensed, framework-free Python library for
EN 16931 European e-invoicing (UBL / CII / Factur-X; Peppol BIS, XRechnung, ZUGFeRD).

> **Read first:** [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md). It holds the locked design
> decisions (§2, cited below as D1…D13), the normative sources (§3), the architecture (§4), the work
> breakdown (§8) and the autonomous execution protocol (§9).

> **This file overrides `../CLAUDE.md` (the letsrevel monorepo file) for this repository** wherever they
> conflict, in particular on merging (see [Git workflow](#git-workflow)). That file describes Django and
> Svelte conventions that do not apply here, except `uv` and `import typing as t`.

---

## Operating principles

1. **Conformance over convenience.** This library exists to produce invoices that tax authorities and
   Peppol access points accept. The pinned **official Schematron is the oracle** (D8); for FatturaPA,
   which has no Schematron, it is the pinned XSD 1.2.3 plus the Allegato A SdI checks (D8, ADR 0001).
   Never suppress, filter or downgrade an official rule, never weaken a test, and never lower a
   threshold to get green. If our code and the oracle disagree, our code is wrong.
2. **Never answer conformance questions from memory.** Verify every identifier, code, XPath, cardinality
   and rounding rule against the pinned artifacts and free specs in plan §3 (fetched with `make artifacts`
   into `$EUINVOICE_ARTIFACTS_DIR`, default `~/.cache/euinvoice`). Cite the source (rule id, file, spec
   section) in a comment or docstring when the code encodes a spec fact. If the sources do not settle a
   question, open or label a `needs-human` issue instead of guessing.
3. **The best code is the code you never wrote.** Use the stdlib, then an installed dependency, then the
   minimum. No speculative abstractions. One canonical model (D1), one place per concern. Boring over
   clever. Leave a `# ponytail:` comment when you knowingly cap something, naming the ceiling and the
   upgrade path.
4. **Goal-driven, test-first.** Write a failing test for the right reason, then the code. Every bug fix
   gets a regression test. State `step → verify` for multi-step work and loop until verified.
5. **Surgical changes.** Touch only what the issue needs. Match the existing style.

---

## Commands

| Command | What it does |
|---|---|
| `make setup` | `uv sync --all-extras --group dev` |
| `make check` | ruff format + lint (incl. flake8-bandit) + mypy strict (src + tests) + file length ≤ 600 |
| `make test` | unit tests, parallel, branch coverage, **≥ 95 %** gate |
| `make test-failed` | re-run last failures |
| `make artifacts` | fetch the pinned official artifacts + corpora (sha256-verified) |
| `make conformance` | `-m conformance` suite against the official Schematron + upstream corpora |
| `make deps-check` | licensecheck + pip-audit |
| `make build` | sdist + wheel |

Run the **targeted** tests for what you changed while iterating, then `make check && make test` before
pushing. Run `make conformance` too when you touch serialization, parsing, validation or profiles.

---

## Architecture (short; full version in plan §4)

```
src/euinvoice/
  model/      EN 16931 semantic model (Pydantic v2, frozen, Decimal-only, BT ids in field metadata)
  model/it/   Invoice.it extension (M11): non-EN data, fields cite FatturaPA element ids (D3)
  calc/       totals + VAT breakdown per EN 16931 rounding rules; check() → findings
  report.py   Finding, Severity, ValidationReport (pure data, shared by calc and validate)
  _syntax.py  the Syntax enum (leaf; calc uses it, euinvoice.syntax re-exports it)
  syntax/     ubl.py, cii.py: bidirectional mappers (write: Invoice → bytes, read: root → Invoice)
  syntax/fatturapa/  FatturaPA FPR12 write/read (M11); no signing, no transmission
  profiles/   en16931, peppol, xrechnung, facturx: BT-24 ids, defaults, pre-flight checks, rule sets
  validation/ manifest.toml (pinned artifacts), artifacts.py (fetch), xsd.py, schematron.py
  facturx/    PDF/A-3 embed/extract on pypdf
  detection.py bytes → syntax + profile (the module behind `detect()`; `validation/` is behind `validate()`)
  _xml.py     THE hardened XML parser factory (D10)
```

Dependency direction: `model` ← `calc` ← `syntax` ← `profiles` ← `validation` / `facturx` ← top-level API.
`model` imports nothing from the other packages, and nothing in the core does I/O or network access
(D2). The artifact fetcher is the one explicit exception.

---

## Project rules

### Typing and style
- `import typing as t` (never `from typing import …`), `t.Any`, `t.cast`, `t.TYPE_CHECKING`.
- Full annotations everywhere, tests included. mypy strict must pass with **no** blanket ignores. A
  `# type: ignore[code]` needs a reason comment.
- Google-style docstrings on every public module member. Error messages cite BT/BG/rule ids.
- Avoid raw dicts across boundaries. Use Pydantic models, dataclasses or `TypedDict`.
- Files stay ≤ 600 lines. Split by BG group or concern before you hit it.

### Money and numbers (D3, D11)
- `Decimal` only. Reject `float` at every boundary. Never construct a `Decimal` from a float.
- Monetary amounts are quantized to 2 decimals with `ROUND_HALF_UP` only where the spec says so (verify in
  the BR-DEC / BR-CO rules). Unit prices and quantities keep their precision.
- Serialize decimals with `format(value, "f")`, never `str()` (which can emit exponent notation).

### XML (D10)
- **Every** parse goes through `euinvoice._xml` (entities off, no network, no DTD, DOCTYPE rejected).
  Never call `etree.fromstring` / `etree.parse` / `XMLParser` anywhere else. A test greps for this.
- Saxon receives only XML that already passed our parser, as an XDM node built from the bytes.
- Element order follows the XSD sequence. Write tests assert the XSD passes, not just the Schematron.
- Namespaces come from the constants in `_xml.py`, never inline URIs.

### Validation (D8, D9)
- `validate()` returns a `ValidationReport` and never raises on rule failures. It raises only for misuse,
  malformed XML or missing artifacts (`ArtifactsNotAvailableError` with the fix command).
- `validate()` never downloads anything. Only `euinvoice artifacts fetch` touches the network.
- FatturaPA exception (D8, `docs/adr/0001-fatturapa-d3-d8.md`): no Schematron exists, so the oracle is
  the pinned XSD 1.2.3 plus the offline SdI checks of Allegato A 1.9.1 App. 1, each a `Finding` whose
  `rule_id` is the SdI error code. Out-of-scope codes are listed with reasons in the plan's D8.

### Artifacts and fixtures (D7)
- **Never commit** official artifacts, XSDs, Schematron, upstream examples or corpora. They are
  fetched via the manifest. `.artifacts/` is gitignored.
- Committed fixtures are **small and synthetic**: fake parties, `example.com` / reserved test VAT ids,
  test IBANs (e.g. `DE02120300000000202051`). Never use real company, personal or client data, including
  anything from the maintainer's own invoices.
- Changing a pin in `manifest.toml` means updating its sha256, running `make conformance`, adding a
  CHANGELOG note and making a dedicated PR.

### Dependencies (D6)
- `uv add` / `uv remove` only, never pip. Core runtime deps are `pydantic` and `lxml`. Extras:
  `[validate]` = `saxonche`, `[pdf]` = `pypdf`.
- A new **runtime** dependency needs a `needs-human` issue first. No LGPL/GPL in the runtime graph
  (`make licensecheck`). No `factur-x` package and nothing from pretix.
- Version bumps: `uv version --bump <part>`, never by hand.

### Testing
- Unit tests in `tests/` mirror `src/euinvoice/`. Conformance tests (need fetched artifacts) are marked
  `@pytest.mark.conformance` and live in `tests/conformance/`.
- Test business behaviour and spec rules, not lines. Coverage is a by-product (≥ 95 % branch).
- Hypothesis for calc/round-trip invariants. Keep the default profile fast and use a `ci` profile with
  more examples if needed.
- Warnings are errors (`filterwarnings = error`).

---

## Git workflow

- **Never push to `main`.** Branches: `feature/<issue#>-<slug>`, `fix/<issue#>-<slug>`. Conventional
  commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`, `ci:`).
- **Commits are SSH-signed.** Run `zsh -ic gitsign` once in the main checkout (worktrees share
  `.git/config`). Verify with `git log --show-signature -1`.
- One issue → one PR → squash merge. The PR body says `Closes #n` and includes a **Verification** section
  listing the commands run and their results.
- **Self-merge is authorized in this repo** (maintainer decision, 2026-10-05; overrides `../CLAUDE.md`).
  Merge with `gh pr merge --squash --delete-branch` only when **all** CI checks are green **and** the
  independent `spec-auditor` and `pr-reviewer` subagents have approved.
- **Human-gated, never do these:** merging a `release/v*` PR, publishing to PyPI, changing branch
  protection after M0, adding runtime dependencies, touching other repositories.

---

## Autonomous mode

When working through the plan autonomously, follow `IMPLEMENTATION_PLAN.md` §9 exactly:
- issues from §8;
- at most 4 parallel implementers in isolated worktrees;
- independent reviewers (`.claude/agents/spec-auditor.md`, `.claude/agents/pr-reviewer.md`);
- self-merge on green;
- `needs-human` for genuine spec ambiguity, while continuing with other ready work;
- stop at the release PR.

Keep the tracking issue "v0.1.0 build-out" current, because it is the maintainer's dashboard.
