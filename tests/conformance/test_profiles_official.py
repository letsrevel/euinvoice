"""Profile identifiers against the pinned official examples (``make conformance``)."""

import collections

import pytest

from euinvoice import _xml, profiles
from euinvoice.validate import artifacts

pytestmark = pytest.mark.conformance

# BT-24 locations: UBL ``cbc:CustomizationID``, CII ``ram:GuidelineSpecifiedDocumentContextParameter/ram:ID``
# (the BR-01 params of the CEN 1.3.16 ``EN16931-UBL-model.sch`` / ``EN16931-CII-model.sch``).
_UBL_BT24 = f"{{{_xml.UBL_CBC}}}CustomizationID"
_CII_BT24 = (
    f"{{{_xml.CII_RSM}}}ExchangedDocumentContext/{{{_xml.CII_RAM}}}GuidelineSpecifiedDocumentContextParameter"
    f"/{{{_xml.CII_RAM}}}ID"
)


def _bt24_counts(source: artifacts.SourceName, path: str) -> collections.Counter[str]:
    directory = artifacts.fetch([source])[source] / "examples"
    counts: collections.Counter[str] = collections.Counter()
    for example in sorted(p for p in directory.iterdir() if p.suffix.lower() == ".xml"):
        value = _xml.parse(example.read_bytes()).findtext(path)
        assert value is not None, example.name
        counts[value.strip()] += 1
    return counts


@pytest.mark.parametrize(("source", "path", "core_examples"), [("cen-ubl", _UBL_BT24, 15), ("cen-cii", _CII_BT24, 12)])
def test_the_core_bt24_of_the_cen_examples_resolves_to_en16931(
    source: artifacts.SourceName, path: str, core_examples: int
) -> None:
    counts = _bt24_counts(source, path)
    assert counts[profiles.EN16931.specification_identifier] == core_examples
    assert profiles.get(profiles.EN16931.specification_identifier) is profiles.EN16931
