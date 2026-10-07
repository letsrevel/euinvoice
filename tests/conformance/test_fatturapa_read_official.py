"""The FatturaPA reader on the official fatturapa.gov.it examples, and its synthetic documents against XSD 1.2.3 (#120).

Needs ``make artifacts``: the examples come from the pinned ZUGFeRD corpus (plan §3) and the schema from the pinned
``fatturapa-xsd``. FPR02 is left out: XSD 1.2.3 rejects it (``tests/conformance/test_xsd_fatturapa.py``).
"""

import datetime
import typing as t
from decimal import Decimal

import pytest
from lxml import etree

from _fatturapa import CASES, EXTRA_FAILING
from _fatturapa_read import (
    FULL,
    REFUSED,
    REPORTED,
    VARIANTS,
    adjusted_document,
    body,
    document,
    natura_document,
    other_data_document,
    payment_document,
)
from euinvoice import _xml, parse, parse_all, validate
from euinvoice.errors import ArtifactsNotAvailableError, ParseError, UnsupportedDocumentError
from euinvoice.model.it import EsigibilitaIVA, ModalitaPagamento, RegimeFiscale, TipoDocumento
from euinvoice.report import Severity
from euinvoice.syntax.fatturapa._read_codes import NATURE_CATEGORY
from euinvoice.validation import artifacts, xsd

pytestmark = pytest.mark.conformance

D = Decimal
ROOT: t.Final = "/p:FatturaElettronica"


def official(name: str) -> bytes:
    try:
        directory = artifacts.source_dir("zugferd-corpus") / "fatturaPA" / "official" / "valid"
    except ArtifactsNotAvailableError:  # collected but deselected by `make test`
        pytest.skip("artifacts not fetched")
    return (directory / name).read_bytes()


READABLE: t.Final = [f"IT01234567890_{kind}0{n}.xml" for kind in ("FPA", "FPR") for n in (1, 2, 3)]
READABLE.remove("IT01234567890_FPR02.xml")


@pytest.mark.parametrize("name", READABLE)
def test_official_example_reads(name: str) -> None:
    results = parse_all(official(name))

    assert len(results) == (2 if name.endswith("03.xml") else 1)
    for result in results:
        assert result.invoice.it is not None
        assert result.invoice.it.document_type is TipoDocumento.TD01
        assert result.invoice.seller.vat_identifier == "IT01234567890"
        fpa = name.startswith("IT01234567890_FPA")  # versione FPA12 is reported; the v1 writer emits FPR12
        head = (f"{ROOT}/@versione",) if fpa else ()
        assert result.unmapped[: len(head) + 2] == (
            *head,
            f"{ROOT}/@xsi:schemaLocation",
            f"{ROOT}/FatturaElettronicaHeader/DatiTrasmissione",
        )


def test_fpr01_field_values() -> None:
    (result,) = parse_all(official("IT01234567890_FPR01.xml"))
    invoice = result.invoice

    assert (invoice.number, invoice.issue_date, invoice.type_code) == ("123", datetime.date(2014, 12, 18), "380")
    assert (invoice.seller.vat_identifier, invoice.seller.postal_address.city) == ("IT01234567890", "SASSARI")
    assert invoice.buyer.name == "DITTA BETA"
    assert invoice.buyer.legal_registration_identifier is not None
    assert invoice.buyer.legal_registration_identifier.model_dump() == {"value": "09876543210", "scheme_id": "0210"}
    assert [(note.note or "")[:10] for note in invoice.notes] == ["LA FATTURA", "SEGUE DESC"]
    assert invoice.seller.name == "SOCIETA' ALPHA SRL"
    assert invoice.delivery is not None
    assert invoice.delivery.actual_delivery_date == datetime.date(2012, 10, 22)
    (line,) = invoice.lines
    assert (line.invoiced_quantity, line.price_details.item_net_price, line.net_amount) == (D("5.00"), D("1.00"), D(5))
    assert (line.vat_information.category_code, line.vat_information.rate) == ("S", D(22))
    (group,) = invoice.vat_breakdown
    assert (group.taxable_amount, group.tax_amount, group.category_code) == (D("5.00"), D("1.10"), "S")
    assert invoice.payment_instructions is not None
    assert invoice.payment_instructions.payment_means_type_code == "10"
    assert (invoice.payment_due_date, invoice.totals.amount_due) == (datetime.date(2015, 1, 30), D("6.10"))
    assert invoice.it is not None
    assert invoice.it.tax_regime is RegimeFiscale.RF19
    assert invoice.it.vat_summaries[0].vat_chargeability is EsigibilitaIVA.I
    assert invoice.it.payment is not None
    assert invoice.it.payment.method is ModalitaPagamento.MP01
    body_path = f"{ROOT}/FatturaElettronicaBody/DatiGenerali"
    assert result.unmapped == (
        f"{ROOT}/@xsi:schemaLocation",
        f"{ROOT}/FatturaElettronicaHeader/DatiTrasmissione",
        f"{body_path}/DatiOrdineAcquisto",  # refers to line 1 (App. 4.1: a line-level reference is an extension)
        f"{body_path}/DatiContratto",
        f"{body_path}/DatiTrasporto/DatiAnagraficiVettore",
        f"{body_path}/DatiTrasporto/DataOraConsegna/text()",
    )


def test_fpr03_is_a_lotto_of_two_invoices() -> None:
    data = official("IT01234567890_FPR03.xml")

    with pytest.raises(UnsupportedDocumentError, match="lotto of 2 invoices"):
        parse(data)
    first, second = parse_all(data)

    assert [line.net_amount for line in first.invoice.lines] == [D("5.00"), D("20.00")]
    # Body 1 declares ImponibileImporto 27.00 for lines adding up to 25.00 (SdI 00422): read as declared.
    assert (first.invoice.vat_breakdown[0].taxable_amount, first.invoice.totals.sum_of_line_net_amounts) == (
        D("27.00"),
        D("25.00"),
    )
    (line,) = second.invoice.lines
    assert (second.invoice.number, line.invoiced_quantity, line.net_amount) == ("456", D(1), D("2000.00"))
    assert second.invoice.payment_instructions is not None
    assert second.invoice.payment_instructions.payment_means_type_code == "59"  # MP19
    assert second.invoice.totals.amount_due == D("2440.00")
    assert not any("Body[1]" in path for path in second.unmapped)


@pytest.fixture(scope="module")
def schema() -> etree._Validator:
    try:
        return xsd._load(xsd._FATTURAPA).schema
    except ArtifactsNotAvailableError:  # collected but deselected by `make test`
        pytest.skip("artifacts not fetched")


def synthetic() -> dict[str, bytes]:
    documents = {"full": FULL, **VARIANTS}
    documents.update({f"reported: {name}": data for name, data, _ in REPORTED})
    documents.update({f"refused: {name}": data for name, data, _ in REFUSED})
    documents.update({f"natura {code}": natura_document(code.value) for code in NATURE_CATEGORY})
    documents.update({f"tipo {code}": document(body(tipo=code.value)) for code in TipoDocumento})
    documents.update({f"payment {code}": payment_document(code) for code in ("MP01", "MP09", "MP19", "MP23")})
    documents["adjusted SC %"] = adjusted_document("<Tipo>SC</Tipo><Percentuale>10.00</Percentuale>", "90.00")
    documents["adjusted MG"] = adjusted_document("<Tipo>MG</Tipo><Importo>5.00</Importo>", "110.00")
    documents["other number"] = other_data_document("<RiferimentoNumero> 12.50 </RiferimentoNumero>")
    documents["other date"] = other_data_document("<RiferimentoData>2026-01-01</RiferimentoData>")
    return documents


@pytest.mark.parametrize(("name", "data"), synthetic().items(), ids=list(synthetic()))
def test_every_synthetic_reader_document_passes_the_xsd(name: str, data: bytes, schema: etree._Validator) -> None:
    assert schema.validate(_xml.parse(data)), [e.message for e in t.cast(t.Iterable[t.Any], schema.error_log)]


def test_the_full_document_passes_the_sdi_checks() -> None:
    report = validate(FULL)

    assert [f for f in report.findings if f.severity is not Severity.INFORMATION] == []


def _sdi_documents() -> list[tuple[str, bytes]]:
    found = [(f"{code} passing {i}", doc.xml()) for code, case in CASES.items() for i, doc in enumerate(case.passing)]
    found += [(f"{code} failing", case.failing.xml()) for code, case in CASES.items()]
    return found + [(name, doc.xml()) for name, doc in EXTRA_FAILING.items()]


# The #121 documents the reader refuses, with the reason (#132 items 6 and 12, SdI 00400).
REFUSED_SDI: t.Final = {
    "00423 passing 4": "2 ScontoMaggiorazione on one line",
    "00400 failing": "Natura is required for a line with AliquotaIVA 0",
    "00445 failing": "the generic code N2 has no VAT category",
    "00445 cassa Natura": "the generic code N2 has no VAT category",
}


@pytest.mark.parametrize(("name", "data"), _sdi_documents(), ids=[name for name, _ in _sdi_documents()])
def test_the_sdi_check_documents_read_or_are_refused_clearly(name: str, data: bytes) -> None:
    # #121's documents are XSD-valid, some of them refused by the SdI: each reads, or is refused with a ParseError.
    if name in REFUSED_SDI:
        with pytest.raises(ParseError, match=REFUSED_SDI[name]):
            parse_all(data)
    else:
        assert parse_all(data)
