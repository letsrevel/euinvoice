"""The Peppol rule-file hash duplicated in scripts/check_upstream.py matches the fetched pin (issue #45)."""

import hashlib

import pytest

import check_upstream as cu
from euinvoice.validation import artifacts

pytestmark = pytest.mark.conformance


def test_peppol_published_sha256_matches_the_pinned_rule_file() -> None:
    # A re-pin of peppol-bis in manifest.toml must bump Check.sha256 too, or the nightly check would
    # compare docs.peppol.eu against a stale hash.
    sch = artifacts.fetch(["peppol-bis"])["peppol-bis"] / "rules/sch/PEPPOL-EN16931-UBL.sch"
    (check,) = (c for c in cu.CHECKS["peppol-bis"] if c.strategy == "published-sha256")
    assert hashlib.sha256(sch.read_bytes()).hexdigest() == check.sha256
