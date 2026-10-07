"""The FatturaPA reader on the official fatturapa.gov.it examples, and its synthetic documents against XSD 1.2.3 (#120).

Needs ``make artifacts``: the examples come from the pinned ZUGFeRD corpus (plan §3) and the schema from the pinned
``fatturapa-xsd``. FPR02 is left out: XSD 1.2.3 rejects it (``tests/conformance/test_xsd_fatturapa.py``).
"""

import datetime
import re
import typing as t
from decimal import Decimal

import pytest
from lxml import etree

from _fatturapa import CASES, EXTRA_FAILING, Doc
from _fatturapa_read import (
    FULL,
    VARIANTS,
    adjusted_document,
    body,
    document,
    natura_document,
    other_data_document,
    payment_document,
)
from _fatturapa_read_cases import REFUSED, REPORTED
from euinvoice import _xml, parse, parse_all, validate
from euinvoice.errors import ArtifactsNotAvailableError, ParseError, UnsupportedDocumentError
from euinvoice.model import Invoice, without_extensions
from euinvoice.model.it import EsigibilitaIVA, ModalitaPagamento, RegimeFiscale, TipoDocumento
from euinvoice.profiles import EN16931
from euinvoice.report import Severity
from euinvoice.syntax import cii, ubl
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
    # Body 1 declares ImponibileImporto 27.00 / Imposta 5.95 for lines adding up to 25.00 (SdI 00422): the reader keeps
    # the declared amounts, and validation reports it (INCONSISTENT, test_a_read_invoice_adds_no_cen_violation).
    (group,) = first.invoice.vat_breakdown
    assert (group.taxable_amount, group.tax_amount, first.invoice.totals.amount_due) == (D(27), D("5.95"), D("32.95"))
    assert not any("DatiRiepilogo" in path or "ImportoPagamento" in path for path in first.unmapped)
    (line,) = second.invoice.lines
    assert (second.invoice.number, line.invoiced_quantity, line.net_amount) == ("456", D(1), D("2000.00"))
    assert second.invoice.payment_instructions is not None
    assert second.invoice.payment_instructions.payment_means_type_code == "59"  # MP19
    assert second.invoice.totals.amount_due == D("2440.00")
    assert not any("Body[1]" in path for path in second.unmapped)


# (file, body) → (BT-1, BT-2, BT-8, BT-15, line BT-131s, BG-23 (BT-116, BT-117), BT-81, BT-9, BT-115)
_JAN18: t.Final = datetime.date(2017, 1, 18)
FPA_VALUES: t.Final = {
    ("IT01234567890_FPA01.xml", 0): (
        "123", _JAN18, None, "789", [D(5)], [(D(5), D("1.10"))], "10", datetime.date(2017, 2, 18), D("6.10")
    ),
    ("IT01234567890_FPA02.xml", 0): (
        "123", _JAN18, "432", "789", [D(5), D(20)], [(D(25), D("5.50"))], "10", datetime.date(2017, 3, 30), D("30.50")
    ),
    ("IT01234567890_FPA03.xml", 0): (
        "12", _JAN18, None, "789", [D(5), D(20)], [(D(25), D("5.50"))], "10", datetime.date(2017, 2, 18), D("30.50")
    ),
    ("IT01234567890_FPA03.xml", 1): (
        "456", datetime.date(2017, 1, 20), None, "987", [D(2000)], [(D(2000), D(440))], "59",
        datetime.date(2017, 2, 20), D("2440.00"),
    ),
}  # fmt: skip


@pytest.mark.parametrize(("name", "index"), FPA_VALUES, ids=[f"{n} body {i + 1}" for n, i in FPA_VALUES])
def test_fpa_field_values(name: str, index: int) -> None:
    result = parse_all(official(name))[index]
    i = result.invoice

    assert (
        i.number,
        i.issue_date,
        i.vat_point_date_code,  # FPA02: EsigibilitaIVA D → 432 (row 2.2.2.7)
        i.receiving_advice_reference,  # DatiRicezione/IdDocumento, its RiferimentoNumeroLinea reported (row 2.1.5)
        [line.net_amount for line in i.lines],
        [(g.taxable_amount, g.tax_amount) for g in i.vat_breakdown],
        i.payment_instructions.payment_means_type_code if i.payment_instructions else None,
        i.payment_due_date,
        i.totals.amount_due,
    ) == FPA_VALUES[name, index]
    assert (i.buyer.name, i.payment_terms) == ("AMMINISTRAZIONE BETA", "TP01")
    assert i.it is not None
    assert i.it.payment is not None
    assert i.it.payment.method in ("MP01", "MP19")


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


def _sdi_documents() -> list[tuple[str, Doc]]:
    found = [(f"{code} passing {i}", doc) for code, case in CASES.items() for i, doc in enumerate(case.passing)]
    found += [(f"{code} failing", case.failing) for code, case in CASES.items()]
    return found + list(EXTRA_FAILING.items())


# The #121 documents the reader refuses, with the reason: #132 item 6 (generic Natura), item 12 (several
# ScontoMaggiorazione), item 21 (a Natura with a rate other than 0: the TD16 integrations of 00401 / 00430 and
# SdI-refused documents) and a rate 0 without Natura on a line or a fund (SdI 00400, 00413).
_NATURA_RATE: t.Final = "with AliquotaIVA 22.00: EN 16931 requires rate 0"
_NO_NATURA: t.Final = "Natura is required with AliquotaIVA 0"
REFUSED_SDI: t.Final = {
    "00401 passing 0": _NATURA_RATE,
    "00430 passing 0": _NATURA_RATE,
    "00401 failing": _NATURA_RATE,
    "00430 failing": _NATURA_RATE,
    "00414 failing": _NATURA_RATE,
    "00423 passing 4": "2 ScontoMaggiorazione on one line",
    "00400 failing": _NO_NATURA,
    "00413 failing": _NO_NATURA,
    "00445 failing": "the generic code N2 has no VAT category",
    "00445 cassa Natura": "the generic code N2 has no VAT category",
}


@pytest.mark.parametrize(("name", "doc"), _sdi_documents(), ids=[name for name, _ in _sdi_documents()])
def test_the_sdi_check_documents_read_or_are_refused_clearly(name: str, doc: Doc) -> None:
    # #121's documents are XSD-valid, some of them refused by the SdI: each reads, one invoice per body, or is
    # refused with a ParseError.
    if name in REFUSED_SDI:
        with pytest.raises(ParseError, match=re.escape(REFUSED_SDI[name])):
            parse_all(doc.xml())
    else:
        assert [r.invoice.number for r in parse_all(doc.xml())] == [b.number for b in doc.bodies]


# Readable documents whose declared figures break a CEN rule: the reader keeps them as declared (#132 item 22), so
# validation reports exactly these (BR-S-08: summaries vs lines; BR-CO-15/16: declared totals vs the sums).
# ``00422 passing``, ``00423 passing 0``: within the SdI's ±1 € / ±1 cent tolerance, not within EN's exact sums.
# CII's BR-CO-15 does not fire for ``inconsistent totals`` (the CII binding tests BT-112 against its own sums).
INCONSISTENT: t.Final[t.Mapping[str, t.Mapping[str, frozenset[str]]]] = {
    "inconsistent summary": {"ubl": frozenset({"BR-S-08"}), "cii": frozenset({"BR-S-08"})},
    "inconsistent totals": {"ubl": frozenset({"BR-CO-15"}), "cii": frozenset()},
    "professional with a fund and withholding": {"ubl": frozenset({"BR-CO-16"}), "cii": frozenset({"BR-CO-16"})},
    "00422 passing 0": {"ubl": frozenset({"BR-S-08"}), "cii": frozenset({"BR-S-08"})},
    "00422 passing 1": {"ubl": frozenset({"BR-S-08"}), "cii": frozenset({"BR-S-08"})},
    "00423 passing 0": {"ubl": frozenset(), "cii": frozenset({"BR-S-08"})},
    "IT01234567890_FPR03.xml": {"ubl": frozenset({"BR-CO-16", "BR-S-08"}), "cii": frozenset({"BR-CO-16", "BR-S-08"})},
}


def _readable_names() -> list[str]:
    """Every readable document of the reader tests that the SdI would accept, and the official examples (names only:
    nothing is read at collection, so a run without fetched artifacts collects cleanly)."""
    names = [name for name in synthetic() if not name.startswith("refused: ")]
    names += [name for name, _ in _sdi_documents() if "passing" in name and name not in REFUSED_SDI]
    return names + READABLE


def _document(name: str) -> bytes:
    if name in READABLE:
        return official(name)
    found = synthetic().get(name)
    return found if found is not None else dict(_sdi_documents())[name].xml()


@pytest.mark.parametrize("name", _readable_names())
@pytest.mark.parametrize("writer", [ubl.write, cii.write], ids=["ubl", "cii"])
def test_a_read_invoice_adds_no_cen_violation(name: str, writer: t.Callable[[Invoice], bytes]) -> None:
    # The reader adds no CEN violation of its own: a document whose declared figures agree reads as a valid EN 16931
    # invoice in both syntaxes; one whose figures do not gets exactly the findings of INCONSISTENT (FPR03: body 1).
    syntax = "ubl" if writer is ubl.write else "cii"
    for index, result in enumerate(parse_all(_document(name))):
        report = validate(writer(without_extensions(result.invoice)), EN16931)

        blocking = {f.rule_id for f in report.findings if f.severity in (Severity.FATAL, Severity.ERROR)}
        expected = INCONSISTENT[name][syntax] if name in INCONSISTENT and index == 0 else frozenset()
        assert blocking == expected, report.findings
