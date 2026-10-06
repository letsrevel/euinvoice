"""``calc`` reproduces the totals of the official CEN and Peppol example files (``make conformance``).

There is no reader yet, so each example's amounts are pulled out with a few XPaths into a synthetic
:class:`~euinvoice.model.InvoiceDraft` (see ``_calc_examples.py``). ``complete()`` then derives BG-22 and
BG-23 from the file's own line net amounts (BT-131), and they must equal the file's values exactly.

Equal by the rules although spelled differently, and normalized before comparing:

* BT-107 / BT-108 stated as 0 without any document level allowance / charge: ``complete()`` leaves them
  out, which BR-CO-11 / BR-CO-12 accept alike.
* BT-110 absent in a CII file whose VAT is 0: ``complete()`` states 0.00 (UBL needs ``cbc:TaxAmount``);
  CII's BR-CO-15 accepts GrandTotalAmount = TaxBasisTotalAmount without it.
* A rate of 0 on a category O breakdown (``XRechnung-O.xml``) whose lines have none: BR-O-05 forbids a
  rate on the lines, so ``complete()`` gives the breakdown none either; no CEN rule tests BT-119 of O.

BT-131 itself has no EN 16931 rule, and the CEN examples do not all follow one (``guide-example3.xml``:
2 x 800.00 = 400.00; several CII examples repeat the net price as BasisQuantity). Peppol enforces
PEPPOL-EN16931-R120, so :func:`calc.line_net_amount` is checked against the Peppol examples.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from _calc_examples import Extracted, extract_cii, extract_ubl
from _pytest.mark import ParameterSet
from lxml import etree

from euinvoice import _xml, calc
from euinvoice.errors import ArtifactsNotAvailableError
from euinvoice.model import VatBreakdown
from euinvoice.validation import artifacts

pytestmark = pytest.mark.conformance

Group = tuple[str, Decimal | None, Decimal, Decimal]


def corpus(name: artifacts.SourceName, subdir: str) -> list[Path]:
    """The example files of a cached source (never fetches at collection time)."""
    try:
        directory = artifacts.source_dir(name) / subdir
    except ArtifactsNotAvailableError:
        return []
    return sorted(p for p in directory.iterdir() if p.suffix.lower() == ".xml")


CEN_UBL = corpus("cen-ubl", "examples")
CEN_CII = corpus("cen-cii", "examples")
PEPPOL = corpus("peppol-bis", "rules/examples")

HUF = pytest.mark.xfail(
    strict=True,
    reason="rounds the VAT to whole forints (18679 for 69180.00 x 27 % = 18678.60), within BR-CO-17's "
    "tolerance of 1; complete() rounds to cents (D11)",
)


def examples(paths: list[Path]) -> list[ParameterSet]:
    return [pytest.param(p, id=p.name, marks=HUF if p.name == "huf_example_cii.xml" else ()) for p in paths]


def extract(path: Path) -> Extracted:
    root: etree._Element = _xml.parse(path.read_bytes())
    return extract_cii(root) if root.tag == f"{{{_xml.CII_RSM}}}CrossIndustryInvoice" else extract_ubl(root)


def test_corpora_are_cached() -> None:
    """Fail instead of passing vacuously on a cold cache."""
    artifacts.fetch(["cen-ubl", "cen-cii", "peppol-bis"])
    assert CEN_UBL
    assert CEN_CII
    assert PEPPOL


def key(group: VatBreakdown) -> Group:
    return (group.category_code, group.rate, group.taxable_amount, group.tax_amount)


def normalized(group: Group) -> Group:
    category, rate, taxable, tax = group
    return (category, None if category == "O" and rate == 0 else rate, taxable, tax)


@pytest.mark.parametrize("path", examples(CEN_UBL + CEN_CII + PEPPOL))
def test_totals_and_vat_breakdown(path: Path) -> None:
    example = extract(path)

    invoice = calc.complete(
        example.with_file_line_nets(),
        paid_amount=example.totals.get("paid_amount"),
        rounding_amount=example.totals.get("rounding_amount"),
        vat_total_in_accounting_currency=example.totals.get("total_vat_in_accounting_currency"),
        exemption_reasons=example.exemption_reasons,
    )

    ours = {name: value for name, value in dict(invoice.totals).items() if value is not None}
    theirs = dict(example.totals)
    for absent_is_zero in ("sum_of_allowances", "sum_of_charges", "total_vat"):
        if absent_is_zero not in theirs and ours.get(absent_is_zero) == 0:
            del ours[absent_is_zero]
        if theirs.get(absent_is_zero) == 0 and absent_is_zero not in ours:
            del theirs[absent_is_zero]
    assert ours == theirs
    assert sorted(map(key, invoice.vat_breakdown)) == sorted(map(normalized, example.breakdown))
    assert calc.check(invoice) == ()


@pytest.mark.parametrize("path", examples(PEPPOL))
def test_line_net_amounts_follow_peppol_r120(path: Path) -> None:
    example = extract(path)

    assert [calc.line_net_amount(line) for line in example.draft.lines] == example.line_net_amounts
