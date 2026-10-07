"""What the FatturaPA reader reports, refuses and how it reads lotti and signed files (#120).

Nothing is dropped silently: content with no model home is listed in ``ParseResult.unmapped``; values the model
cannot hold without rounding or guessing are refused with ``ParseError`` (policy questions: #132).
"""

import base64
import re
import typing as t
from decimal import Decimal

import hypothesis
import pytest
from hypothesis import strategies as st

from _fatturapa_read import (
    FULL,
    REFUSED,
    REPORTED,
    ROOT,
    SUMMARY,
    VARIANTS,
    body,
    document,
)
from euinvoice import _xml, detect, parse, parse_all, parse_detailed, validate
from euinvoice.detection import is_signed
from euinvoice.errors import ModelError, ParseError, UnsupportedDocumentError
from euinvoice.model import extension_paths, without_extensions
from euinvoice.model.it import EsigibilitaIVA
from euinvoice.syntax import fatturapa, ubl


def unmapped(data: bytes) -> tuple[str, ...]:
    """The unmapped paths without the transmission data every document carries."""
    found = parse_detailed(data).unmapped
    assert found[0] == f"{ROOT}/FatturaElettronicaHeader/DatiTrasmissione"
    return found[1:]


# ---------------------------------------------------------------------------------------------------- reported


@pytest.mark.parametrize(("name", "data", "expected"), REPORTED, ids=[name for name, _, _ in REPORTED])
def test_content_without_a_model_home_is_reported(name: str, data: bytes, expected: tuple[str, ...]) -> None:
    found = unmapped(data)

    assert found == expected


def test_fpa12_the_intermediary_and_the_registry_data_are_reported() -> None:
    data = VARIANTS["FPA12"]

    assert parse_detailed(data).unmapped == (
        f"{ROOT}/@versione",
        f"{ROOT}/FatturaElettronicaHeader/DatiTrasmissione",
        f"{ROOT}/FatturaElettronicaHeader/CedentePrestatore/IscrizioneREA",
        f"{ROOT}/FatturaElettronicaHeader/TerzoIntermediarioOSoggettoEmittente",
    )


def test_instalments_derive_the_amount_due() -> None:
    assert parse(VARIANTS["instalments"]).totals.amount_due == Decimal("122.00")


def test_a_d_vs_i_split_is_one_breakdown_and_reports_the_second_chargeability() -> None:
    # One BG-23 per category and rate (BR-S-08); the extension keeps one entry per rate, Natura and split payment.
    result = parse_detailed(VARIANTS["D vs I split"])

    (group,) = result.invoice.vat_breakdown
    assert (group.taxable_amount, group.tax_amount) == (Decimal("200.00"), Decimal("44.00"))
    assert result.invoice.it is not None
    assert [s.vat_chargeability for s in result.invoice.it.vat_summaries] == [EsigibilitaIVA.D]
    assert result.unmapped[1:] == (f"{SUMMARY}[2]/EsigibilitaIVA",)


def test_declared_amounts_that_break_the_cen_rules_are_derived_and_reported() -> None:
    summary = parse_detailed(VARIANTS["inconsistent summary"])  # ImponibileImporto 102.00 for lines of 100.00
    totals = parse_detailed(VARIANTS["inconsistent totals"])  # ImportoTotaleDocumento and ImportoPagamento 100.00

    (group,) = summary.invoice.vat_breakdown
    assert (group.taxable_amount, group.tax_amount) == (Decimal("100.00"), Decimal("22.00"))
    assert summary.unmapped[1:] == (f"{SUMMARY}/ImponibileImporto", f"{SUMMARY}/Imposta")
    assert (totals.invoice.totals.total_with_vat, totals.invoice.totals.amount_due) == (Decimal(122), Decimal(122))
    assert totals.unmapped[1:] == (
        f"{ROOT}/FatturaElettronicaBody/DatiGenerali/DatiGeneraliDocumento/ImportoTotaleDocumento",
        f"{ROOT}/FatturaElettronicaBody/DatiPagamento/DettaglioPagamento/ImportoPagamento",
    )


def test_a_repeated_identical_summary_reports_nothing() -> None:
    data = VARIANTS["same summary twice"]

    assert unmapped(data) == ()


# ---------------------------------------------------------------------------------------------------- refused


@pytest.mark.parametrize(("name", "data", "message"), REFUSED, ids=[name for name, _, _ in REFUSED])
def test_values_the_model_cannot_hold_are_refused(name: str, data: bytes, message: str) -> None:
    with pytest.raises(ParseError, match=re.escape(message)):
        parse(data)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("<Natura>N2.2</Natura>", "<Natura>N9</Natura>", "2.2.1.14 Natura: 'N9' is not a NaturaType code"),
        (
            "<TipoDocumento>TD01</TipoDocumento>",
            "<TipoDocumento>TD99</TipoDocumento>",
            "'TD99' is not a TipoDocumentoType",
        ),
        ("<Data>2026-01-15</Data>", "<Data>15/01/2026</Data>", "2.1.1.3 Data: '15/01/2026' is not an xs:date"),
        ("<Data>2026-01-15</Data>", "<Data>2026-02-30</Data>", "'2026-02-30' is not an xs:date"),
        ("<Quantita>2.00</Quantita>", "<Quantita>1e2</Quantita>", "2.2.1.5 Quantita: expected an xs:decimal"),
        ("<Tipo>SC</Tipo>", "<Tipo>XX</Tipo>", "2.2.1.10.1 Tipo: 'XX' is not SC or MG"),
        ("T10:00:00</DataOraConsegna>", "</DataOraConsegna>", "is not an xs:dateTime"),
        ("<RegimeFiscale>RF19</RegimeFiscale>", "<RegimeFiscale>RF03</RegimeFiscale>", "it.tax_regime"),
        ("<TipoDocumento>TD01</TipoDocumento>", "", "BT-3 (type_code): Field required"),
        ("<PrezzoUnitario>50.00</PrezzoUnitario>", "", "price_details.item_net_price"),
        ("<AliquotaIVA>22.00</AliquotaIVA><RiferimentoAmministrazione>", "<RiferimentoAmministrazione>", "BG-30"),
    ],
)
def test_schema_invalid_values_are_refused_with_their_element(old: str, new: str, message: str) -> None:
    assert old.encode() in FULL

    with pytest.raises(ParseError, match=re.escape(message)):
        parse(FULL.replace(old.encode(), new.encode(), 1))


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            b'<p:FatturaElettronica xmlns:p="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"/>',
            "2 FatturaElettronicaBody",
        ),
        (
            f'<p:FatturaElettronica xmlns:p="{_xml.FATTURAPA}">{body()}</p:FatturaElettronica>'.encode(),
            "1 FatturaElettronicaHeader",
        ),
        (
            document().replace(b"<CessionarioCommittente>", b"<X>").replace(b"</CessionarioCommittente>", b"</X>"),
            "BT-44 (name): Field required",
        ),
    ],
    ids=["no body", "no header", "no buyer"],
)
def test_incomplete_documents_are_refused(data: bytes, message: str) -> None:
    with pytest.raises(ParseError, match=re.escape(message)):
        parse(data)


def test_the_reader_refuses_another_root() -> None:
    with pytest.raises(ParseError, match="expected the FatturaPA root"):
        fatturapa.read(_xml.parse(b"<Invoice/>"))


# ---------------------------------------------------------------------------------------------------- lotti


def test_a_lotto_is_refused_by_parse_and_read_by_parse_all() -> None:
    data = VARIANTS["lotto"]

    with pytest.raises(UnsupportedDocumentError, match=r"lotto of 2 invoices .* euinvoice\.parse_all\(\)"):
        parse(data)
    first, second = parse_all(data)

    assert (first.invoice.number, second.invoice.number) == ("FT-1", "FT-2")
    assert (first.invoice.type_code, second.invoice.type_code) == ("380", "381")
    assert first.invoice.seller == second.invoice.seller
    assert first.unmapped == second.unmapped == (f"{ROOT}/FatturaElettronicaHeader/DatiTrasmissione",)


def test_each_body_of_a_lotto_reports_only_its_own_content() -> None:
    first, second = parse_all(VARIANTS["lotto with Art73"])

    assert first.unmapped == (f"{ROOT}/FatturaElettronicaHeader/DatiTrasmissione",)
    assert second.unmapped == (
        f"{ROOT}/FatturaElettronicaHeader/DatiTrasmissione",
        f"{ROOT}/FatturaElettronicaBody[2]/DatiGenerali/DatiGeneraliDocumento/Art73",
    )


@hypothesis.given(st.integers(min_value=1, max_value=6))
def test_a_lotto_of_identical_bodies_reads_as_the_single_body(count: int) -> None:
    single = parse_detailed(document())
    one_body = body()

    results = parse_all(document(*[one_body] * count))

    assert [r.invoice for r in results] == [single.invoice] * count
    for index, result in enumerate(results, start=1):
        step = "FatturaElettronicaBody" if count == 1 else f"FatturaElettronicaBody[{index}]"
        assert result.unmapped == tuple(p.replace("FatturaElettronicaBody", step) for p in single.unmapped)


def test_parse_all_of_one_invoice_is_parse_detailed() -> None:
    assert parse_all(FULL) == (parse_detailed(FULL),)


# ---------------------------------------------------------------------------------------------------- signed input


_SIGNED_HEAD: t.Final = bytes.fromhex("3082100006092a864886f70d010702a0821000")
SIGNED: t.Final = [
    _SIGNED_HEAD + b"\x00" * 64,
    b"\n" + base64.encodebytes(_SIGNED_HEAD + b"\x00" * 90),
    b"-----BEGIN PKCS7-----\nMIIB\n-----END PKCS7-----\n",
]


@pytest.mark.parametrize("data", SIGNED, ids=["DER", "base64", "PEM"])
def test_signed_input_is_refused_with_the_way_out_by_every_entry_point(data: bytes) -> None:
    assert is_signed(data)
    for entry in (parse, parse_all, detect, validate):
        with pytest.raises(UnsupportedDocumentError, match=r"signed \(CAdES, \.p7m\).*openssl cms -verify"):
            entry(data)


@pytest.mark.parametrize("data", [FULL, b"\x30\x03\x02\x01\x00", b"MI!!not base64", b"MIIB" + b"A" * 90])
def test_other_input_is_not_taken_for_signed(data: bytes) -> None:
    assert not is_signed(data)


# ---------------------------------------------------------------------------------------------------- extensions


def test_without_extensions_clears_what_extension_paths_lists() -> None:
    invoice = parse(FULL)

    plain = without_extensions(invoice)

    assert extension_paths(invoice) == ("it", "lines[0].it", "lines[1].it")
    assert extension_paths(plain) == ()
    assert plain.model_copy(update={"it": invoice.it, "lines": invoice.lines}) == invoice
    assert without_extensions(plain) is plain


def test_the_writers_name_without_extensions() -> None:
    with pytest.raises(ModelError, match=r"euinvoice\.model\.without_extensions\(\)"):
        ubl.write(parse(FULL))
