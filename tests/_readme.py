"""Runs the ``python`` code blocks of README.md as doctests, with a synthetic setup the README does not show.

Every block is a doctest; the blocks share one namespace, in README order (``tests/_markdown_doctest.py``). A block
right after the HTML comment ``<!-- readme-doctest: needs-artifacts -->`` needs the official artifacts
(``validate``): the unit run (``tests/test_readme.py``) skips it, the conformance run
(``tests/conformance/test_readme_examples.py``) runs every block.
"""

import datetime
import pathlib
import typing as t

import _markdown_doctest
from _calc_drafts import draft
from _pdfa import pdf
from _xrechnung_cases import PEPPOL_BILLING_01, buyer, payment, seller
from euinvoice.model import DeliveryInformation, InvoiceDraft, ProcessControl

README: t.Final = pathlib.Path(__file__).resolve().parents[1] / "README.md"
PREFIX: t.Final = "readme-doctest"


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


def blocks() -> list[_markdown_doctest.Block]:
    """The ``python`` blocks of the README."""
    return _markdown_doctest.blocks(README, prefix=PREFIX)


def run(*, with_artifacts: bool) -> int:
    """Run the README doctests; skip the blocks that need artifacts unless ``with_artifacts``.

    Returns:
        The number of examples that ran.

    Raises:
        AssertionError: An example failed; the message is doctest's report.
    """
    globs: dict[str, t.Any] = {"draft": readme_draft(), "rendered_pdf": pdf()}
    return _markdown_doctest.run(README, globs, prefix=PREFIX, with_artifacts=with_artifacts)
