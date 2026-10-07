"""Every document the FPR12 writer produces passes the pinned XSD 1.2.3 and the offline SdI checks (#119, D8).

``validate()`` runs the FatturaPA 1.2.3 schema and then the Allegato A 1.9.1 checks of ``euinvoice.validation.sdi``;
a written document must get no finding at all. Needs ``make artifacts``.
"""

import pathlib
import typing as t

import pytest
from hypothesis import given, settings

from _fatturapa_strategies import v1_invoices
from _fatturapa_write import TRANSMISSION, Sample, samples
from euinvoice import detect, parse_all, to_xml, validate
from euinvoice.errors import (
    ArtifactsNotAvailableError,
    ModelError,
    ParseError,
    PreflightError,
    UnsupportedDocumentError,
)
from euinvoice.model import Invoice
from euinvoice.syntax import Syntax
from euinvoice.syntax.fatturapa import write
from euinvoice.validation import artifacts

pytestmark = pytest.mark.conformance

SAMPLES: t.Final = samples()


@pytest.mark.parametrize("sample", SAMPLES.values(), ids=SAMPLES.keys())
def test_written_samples_pass_the_xsd_and_the_sdi_checks(sample: Sample) -> None:
    data = write(sample.invoice, sample.options)

    assert validate(data).findings == ()
    detection = detect(data)
    assert (detection.syntax, detection.fatturapa_version) == (Syntax.FATTURAPA, "FPR12")


def _official() -> list[pathlib.Path]:
    try:
        directory = artifacts.source_dir("zugferd-corpus") / "fatturaPA" / "official" / "valid"
    except ArtifactsNotAvailableError:  # collected but deselected by `make test`
        return []
    return sorted(directory.glob("*FPR*.xml"))


@pytest.mark.parametrize("path", _official(), ids=lambda p: p.name)
def test_official_fpr12_examples_write_back_or_are_refused(path: pathlib.Path) -> None:
    """FPR12 → model → FPR12 on the fatturapa.gov.it examples: written back as the same invoice, or refused."""
    try:
        results = parse_all(path.read_bytes())
    except (ParseError, UnsupportedDocumentError):
        return  # FPR02 fails the XSD-level structure the reader needs; see test_sdi_official.py
    for result in results:
        try:
            again = to_xml(result.invoice, syntax=Syntax.FATTURAPA, fatturapa_transmission=TRANSMISSION)
        except (PreflightError, ModelError):
            continue  # outside the v1 subset: refused, never dropped
        (back,) = parse_all(again)
        assert back.invoice == result.invoice
        assert validate(again).findings == ()


@settings(max_examples=60)
@given(v1_invoices())
def test_random_v1_invoices_pass_the_xsd_and_the_sdi_checks(invoice: Invoice) -> None:
    assert validate(write(invoice, TRANSMISSION)).findings == ()
