"""Runs the ``python`` code blocks of README.md as doctests, with a synthetic setup the README does not show.

Every block is a doctest; the blocks share one namespace, in README order. A block right after the HTML comment
``<!-- readme-doctest: needs-artifacts -->`` needs the official artifacts (``validate``): the unit run
(``tests/test_readme.py``) skips it, the conformance run (``tests/conformance/test_readme_examples.py``) runs every
block.
"""

import datetime
import doctest
import pathlib
import re
import typing as t

from _calc_drafts import draft
from _pdfa import pdf
from _xrechnung_cases import PEPPOL_BILLING_01, buyer, payment, seller
from euinvoice.model import DeliveryInformation, InvoiceDraft, ProcessControl

README: t.Final = pathlib.Path(__file__).resolve().parents[1] / "README.md"
NEEDS_ARTIFACTS: t.Final = "<!-- readme-doctest: needs-artifacts -->"
_BLOCK: t.Final = re.compile(
    r"(?P<marker>" + re.escape(NEEDS_ARTIFACTS) + r"\n)?```python\n(?P<body>.*?)^```", re.M | re.S
)


def readme_draft() -> InvoiceDraft:
    """The README's ``draft``: a synthetic German invoice with the terms XRechnung requires.

    BT-10, BG-6 seller contact, seller and buyer city and post code, BG-16 credit transfer, the electronic
    addresses and BT-23 that the XRechnung rule set requires (see ``tests/_xrechnung_cases.py`` for their rule ids),
    plus BT-72, without which XRechnung reports BR-DE-TMP-32 (``information``).
    """
    return draft(
        number="RE-2026-0001",
        issue_date=datetime.date(2026, 1, 15),
        buyer_reference="04011000-12345-34",
        process_control=ProcessControl(
            business_process_type=PEPPOL_BILLING_01, specification_identifier="urn:cen.eu:en16931:2017"
        ),
        seller=seller(),
        buyer=buyer(),
        payment_instructions=payment(),
        delivery=DeliveryInformation(actual_delivery_date=datetime.date(2026, 1, 14)),
    )


def blocks() -> list[tuple[bool, doctest.DocTest]]:
    """``(needs_artifacts, doctest)`` per ``python`` block of the README, all with one namespace.

    ``DocTest`` copies the globals it is given, so the shared namespace is set on each test afterwards.
    """
    text = README.read_text(encoding="utf-8")
    globs: dict[str, t.Any] = {"draft": readme_draft(), "rendered_pdf": pdf()}
    parser = doctest.DocTestParser()
    found = []
    for match in _BLOCK.finditer(text):
        line = text.count("\n", 0, match.start("body"))
        test = parser.get_doctest(match["body"], globs, f"README.md:{line + 1}", str(README), line)
        test.globs = globs
        found.append((match["marker"] is not None, test))
    return found


def run(*, with_artifacts: bool) -> int:
    """Run the README doctests; skip the blocks that need artifacts unless ``with_artifacts``.

    Returns:
        The number of examples that ran.

    Raises:
        AssertionError: An example failed; the message is doctest's report.
    """
    runner = doctest.DocTestRunner(optionflags=doctest.ELLIPSIS)
    report: list[str] = []
    ran = 0
    for needs_artifacts, test in blocks():
        if needs_artifacts and not with_artifacts:
            continue
        result = runner.run(test, out=report.append, clear_globs=False)
        assert result.failed == 0, "".join(report)
        ran += result.attempted
    return ran
