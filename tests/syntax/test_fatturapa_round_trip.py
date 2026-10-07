"""FatturaPA round trips between the writer (#119) and the reader (#120): plan 11.5's lossless-per-body AC.

* model → FPR12 → model: every writer sample and Hypothesis invoice, written with ``to_xml`` and read with
  ``parse_all``, gives one result whose ``unmapped`` holds only :data:`UNMAPPED`, and an invoice that differs from the
  original only by the documented normalizations of :data:`NORMALIZED`. Writing the read invoice again gives the same
  bytes, so the normalized form is a fixed point and nothing more is lost.
* FPR12 → model → FPR12: every synthetic SdI-check document (tests/_fatturapa.py) that reads is written again; either
  the writer refuses it (with an error, never by dropping content) or it reads back as the same invoice.
"""

import re
import typing as t

import pydantic
import pytest
from hypothesis import given, settings

from _fatturapa import CASES, Doc
from _fatturapa_strategies import v1_invoices
from _fatturapa_write import TRANSMISSION, samples
from euinvoice import parse_all, to_xml
from euinvoice.errors import ModelError, ParseError, PreflightError
from euinvoice.model import Invoice
from euinvoice.syntax import Syntax
from euinvoice.syntax.fatturapa import Transmission

UNMAPPED: t.Final = re.compile(
    r"/p:FatturaElettronica/FatturaElettronicaHeader/DatiTrasmissione"  # the Transmission, not invoice data
    # SpeseAccessorie, the sum of the AC lines, derived from them (App. 4.1 row 2.2.2.3)
    r"|/p:FatturaElettronica/FatturaElettronicaBody/DatiBeniServizi/DatiRiepilogo(\[\d+\])?/SpeseAccessorie"
)
"""What the reader lists as unmapped in a written document: the transmission header and the derived SpeseAccessorie."""

NORMALIZED: t.Final = re.compile(
    r"\.payment_terms"  # BT-20: None → the CondizioniPagamento code (App. 4.1 row 2.4.1)
    r"|\.payment_instructions(\.payment_means_type_code)?"  # BT-81 ↔ ModalitaPagamento, App. 5.6 many-to-one
    r"|\.it\.payment\.method"  # ModalitaPagamento derived from BT-81 becomes explicit
    r"|\.it\.vat_summaries"  # one entry per DatiRiepilogo (Natura, EsigibilitaIVA, RiferimentoNormativo)
    r"|\.vat_point_date_code"  # BT-8 3/35 → EsigibilitaIVA I in it.vat_summaries; D → BT-8 432
    r"|\.vat_breakdown\[\d+\]\.exemption_reason(_code)?"  # BT-120/121 as App. 4.1 / 5.1 build them from Natura
    r"|\.(seller|buyer)\.legal_registration_identifier\.(value|scheme_id)"  # "CF:x" → x with scheme 0210
)
"""The paths where a read-back invoice may differ from the one written, each an App. 4.1 / 5 normalization."""


def _diff(a: object, b: object, path: str = "") -> t.Iterator[str]:
    """The paths where two models differ."""
    if isinstance(a, pydantic.BaseModel) and type(a) is type(b):
        for name in type(a).model_fields:
            yield from _diff(getattr(a, name), getattr(b, name), f"{path}.{name}")
    elif isinstance(a, tuple) and isinstance(b, tuple) and len(a) == len(b):
        for index, (x, y) in enumerate(zip(a, b, strict=True)):
            yield from _diff(x, y, f"{path}[{index}]")
    elif a != b:
        yield path


def _write(invoice: Invoice, transmission: Transmission = TRANSMISSION) -> bytes:
    return to_xml(invoice, syntax=Syntax.FATTURAPA, fatturapa_transmission=transmission)


def _assert_round_trip(invoice: Invoice, transmission: Transmission = TRANSMISSION) -> None:
    data = _write(invoice, transmission)
    (result,) = parse_all(data)

    assert all(UNMAPPED.fullmatch(path) for path in result.unmapped), result.unmapped
    assert [path for path in _diff(invoice, result.invoice) if not NORMALIZED.fullmatch(path)] == []
    assert _write(result.invoice, transmission) == data


@pytest.mark.parametrize("name", list(samples()))
def test_written_samples_read_back(name: str) -> None:
    sample = samples()[name]
    _assert_round_trip(sample.invoice, sample.options)


def test_the_maximal_sample_reads_back_unnormalized_where_written() -> None:
    invoice = samples()["TD01 every written term"].invoice
    (result,) = parse_all(_write(invoice))

    assert result.invoice.totals == invoice.totals
    assert result.invoice.lines == invoice.lines
    assert result.invoice.seller.postal_address == invoice.seller.postal_address
    assert result.invoice.buyer == invoice.buyer
    assert result.invoice.charges == invoice.charges


@settings(max_examples=60)
@given(v1_invoices())
def test_random_v1_invoices_read_back(invoice: Invoice) -> None:
    _assert_round_trip(invoice)


_DOCS: t.Final = [(f"{code}-{i}", doc) for code, case in CASES.items() for i, doc in enumerate(case.passing)]


@pytest.mark.parametrize("doc", [d for _, d in _DOCS], ids=[name for name, _ in _DOCS])
def test_read_documents_write_back_or_are_refused(doc: Doc) -> None:
    try:
        results = parse_all(doc.xml())
    except ParseError:
        return  # the reader refuses it (#132); nothing to write back
    transmission = TRANSMISSION.model_copy(update={"recipient_code": doc.recipient})
    for result in results:
        try:
            again = _write(result.invoice, transmission)
        except (PreflightError, ModelError):
            continue  # content outside the writer's v1 subset: refused, never dropped
        (back,) = parse_all(again)
        assert back.invoice == result.invoice


def test_how_many_read_bodies_write_back() -> None:
    written = 0
    for _, doc in _DOCS:
        try:
            results = parse_all(doc.xml())
        except ParseError:
            continue
        transmission = TRANSMISSION.model_copy(update={"recipient_code": doc.recipient})
        for result in results:
            try:
                _write(result.invoice, transmission)
            except (PreflightError, ModelError):
                continue
            written += 1
    # 31 of the bodies the reader accepts are in the writer's v1 subset; the rest carry cassa, a summary Arrotondamento,
    # a TipoDocumento outside v1, FPA12 routing, … and are refused with an error. A change here is a coverage change.
    assert written == 31
