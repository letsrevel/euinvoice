"""Every BT/BG id the pinned official rule sets cite exists in the model (``make conformance``)."""

import re
import typing as t
from pathlib import Path

import pytest

from euinvoice.model import BT_INDEX
from euinvoice.validation.artifacts import source_dir

pytestmark = pytest.mark.conformance

# BT-DEX-* / BG-DEX-* (XRechnung extension) do not match: the id must be digits only.
_ID = re.compile(r"\bB[TG]-[0-9]+\b")


def _cited_ids(source: t.Literal["cen-ubl", "cen-cii", "peppol-bis", "xrechnung-schematron"]) -> set[str]:
    files = sorted(Path(source_dir(source)).rglob("*.sch"))
    assert files, source
    return {ident for path in files for ident in _ID.findall(path.read_text(encoding="utf-8"))}


@pytest.mark.parametrize("source", ["cen-ubl", "cen-cii", "peppol-bis", "xrechnung-schematron"])
def test_every_id_cited_by_the_official_rules_is_in_the_model(
    source: t.Literal["cen-ubl", "cen-cii", "peppol-bis", "xrechnung-schematron"],
) -> None:
    cited = _cited_ids(source)
    assert cited, source
    assert cited <= set(BT_INDEX), sorted(cited - set(BT_INDEX))
