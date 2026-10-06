.DEFAULT_GOAL := help

.PHONY: help
help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: setup
setup: ## Install all extras + dev group
	uv sync --all-extras --group dev

.PHONY: format
format: ## ruff format (writes)
	uv run ruff format .

.PHONY: lint
lint: ## ruff lint with autofix
	uv run ruff check . --fix

.PHONY: mypy
mypy: ## Strict type check (src + tests; flags live in pyproject)
	uv run mypy

.PHONY: file-length
file-length: ## No Python file over 600 lines
	@./scripts/check-file-length.sh 600

.PHONY: check
check: format lint mypy file-length ## All static checks (what CI's "checks" job runs, minus --check modes)

# Unit tests: fast, offline, no official artifacts needed.
.PHONY: test
test: ## Unit tests with branch coverage (parallel)
	uv run pytest -n auto --cov --cov-report=term

.PHONY: test-failed
test-failed: ## Re-run last failures only
	uv run pytest --last-failed

# Official CEN / Peppol / XRechnung / Factur-X artifacts are NOT vendored (licensing, see
# IMPLEMENTATION_PLAN.md D7). `make artifacts` downloads the pinned, sha256-checked set
# into the cache ($$EUINVOICE_ARTIFACTS_DIR, default ~/.cache/euinvoice).
.PHONY: artifacts
artifacts: ## Fetch pinned official validation artifacts + example corpora
	uv run python -m euinvoice artifacts fetch

# Regenerates src/euinvoice/model/codes/_generated.py from the pinned CEN code-list Schematron.
.PHONY: codelists
codelists: ## Regenerate the EN 16931 code lists (needs `make artifacts`)
	uv run python scripts/gen_codelists.py

# Regenerates docs/reference/bt-coverage.md from the per-term row tables (the BT coverage gate, #32).
.PHONY: bt-coverage
bt-coverage: ## Regenerate docs/reference/bt-coverage.md
	EUINVOICE_REGEN_DOCS=1 uv run pytest -q tests/syntax/test_bt_coverage.py

.PHONY: conformance
conformance: ## Conformance suite against official Schematron + upstream corpora
	uv run pytest -n auto -m conformance

# Checks the runtime graph incl. both extras (that is what we redistribute alongside).
# `-r pyproject.toml` is mandatory: without it licensecheck reads stdin under make/CI.
# saxonche is ignored because it ships no licence metadata. SaxonC-HE is MPL-2.0 (file-level
# copyleft; fine as an optional dependency of an MIT library). Re-verify on every major bump.
.PHONY: licensecheck
licensecheck: ## Licence compliance of the runtime graph (core + extras)
	uv run licensecheck -r pyproject.toml --extras validate pdf --ignore-packages saxonche --zero

# pip-audit runs on an exported requirements file: the editable self-package confuses
# --strict. --disable-pip because uv-managed Pythons ship no ensurepip.
.PHONY: audit
audit: ## Known-CVE scan of the locked graph
	@uv export --quiet --locked --all-extras --format requirements-txt --no-emit-project --no-hashes --group dev -o .audit-reqs.txt
	@trap 'rm -f .audit-reqs.txt' EXIT; uv run pip-audit --strict --no-deps --disable-pip -r .audit-reqs.txt

.PHONY: deps-check
deps-check: licensecheck audit ## licensecheck + audit

.PHONY: build
build: ## Build sdist + wheel into dist/
	uv build

.PHONY: dump-issues
dump-issues: ## Open issues → issues.md (handy context for agents)
	gh issue list --state open --limit 1000 --json number,title,labels,body,url --jq '.[] | "## \(.title) (#\(.number))\n\n- URL: \(.url)\n- Labels: \(.labels | map(.name) | join(", "))\n\n\(.body)\n\n---\n"' > issues.md
