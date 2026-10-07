"""The ``Invoice.it`` extension (D3 as amended, ADR 0001, #118): FatturaPA element ids, invariants, plumbing."""

import re
import typing as t
from decimal import Decimal

import pydantic
import pytest
from hypothesis import given
from hypothesis import strategies as st

from _calc_drafts import draft, line
from euinvoice import calc
from euinvoice.errors import ModelError
from euinvoice.model import BT_INDEX, Invoice, InvoiceDraft, InvoiceLine, LineDraft
from euinvoice.model._base import EuInvoiceModel, bt, bt_id, extension, extension_of, set_extensions
from euinvoice.model.bt_index import _unwrap, build_index
from euinvoice.model.it import (
    CondizioniPagamento,
    EsigibilitaIVA,
    ItalianExtension,
    ItalianLineExtension,
    ItalianPayment,
    ItalianVatSummary,
    ModalitaPagamento,
    Natura,
    RegimeFiscale,
    SoggettoEmittente,
    TipoCessionePrestazione,
    TipoDocumento,
    fatturapa_id,
)

# Every extension field and the FatturaPA element it carries, as numbered in the "Rappresentazione tabellare del
# tracciato FatturaPA" 1.9.1 (Agenzia delle Entrate, AE_RappTab_1.9.1.xlsx, sheet 1, column D/C/B).
EXPECTED_IDS: t.Final = {
    (ItalianExtension, "tax_regime"): "1.2.1.8",
    (ItalianExtension, "issuer"): "1.6",
    (ItalianExtension, "document_type"): "2.1.1.1",
    (ItalianExtension, "vat_summaries"): "2.2.2",
    (ItalianExtension, "payment"): "2.4",
    (ItalianLineExtension, "supply_type"): "2.2.1.2",
    (ItalianLineExtension, "nature"): "2.2.1.14",
    (ItalianVatSummary, "rate"): "2.2.2.1",
    (ItalianVatSummary, "nature"): "2.2.2.2",
    (ItalianVatSummary, "vat_chargeability"): "2.2.2.7",
    (ItalianVatSummary, "legal_reference"): "2.2.2.8",
    (ItalianPayment, "conditions"): "2.4.1",
    (ItalianPayment, "method"): "2.4.2.2",
}

_ELEMENT_ID = re.compile(r"[1-9][0-9]*(?:\.[1-9][0-9]*)*")


def _extension_models(model: type[pydantic.BaseModel]) -> t.Iterator[type[pydantic.BaseModel]]:
    yield model
    for field in model.model_fields.values():
        inner, _ = _unwrap(field.annotation)
        if isinstance(inner, type) and issubclass(inner, EuInvoiceModel):
            yield from _extension_models(inner)


EXTENSION_MODELS: t.Final = {*_extension_models(ItalianExtension), *_extension_models(ItalianLineExtension)}


def _it(**changes: t.Any) -> ItalianExtension:
    data: dict[str, t.Any] = {"tax_regime": "RF01", "document_type": "TD01", **changes}
    return ItalianExtension.model_validate(data)


class TestElementIds:
    def test_every_extension_field_cites_a_fatturapa_element_id_and_no_bt(self) -> None:
        assert {ItalianExtension, ItalianLineExtension, ItalianVatSummary, ItalianPayment} == EXTENSION_MODELS
        for model in EXTENSION_MODELS:
            for name in model.model_fields:
                ident = fatturapa_id(model, name)
                assert ident is not None, (model.__name__, name)
                assert _ELEMENT_ID.fullmatch(ident), (model.__name__, name)
                assert bt_id(model, name) is None, (model.__name__, name)

    def test_the_ids_are_the_official_element_numbers(self) -> None:
        found = {(model, name): fatturapa_id(model, name) for model in EXTENSION_MODELS for name in model.model_fields}
        assert found == EXPECTED_IDS

    def test_an_id_must_look_like_an_element_number(self) -> None:
        from euinvoice.model.it.extension import fatturapa

        assert fatturapa("2.2.1.14").json_schema_extra == {"fatturapa": "2.2.1.14"}
        for bad in ("BT-1", "2.", "02.1", "", "2.1.x"):
            with pytest.raises(ValueError, match="FatturaPA element id"):
                fatturapa(bad)

    def test_fatturapa_id_is_none_without_metadata(self) -> None:
        assert fatturapa_id(Invoice, "number") is None


class TestHooks:
    @pytest.mark.parametrize("model", [Invoice, InvoiceDraft, InvoiceLine, LineDraft])
    def test_the_it_hook_is_an_optional_extension_field_without_bt(self, model: type[pydantic.BaseModel]) -> None:
        assert extension_of(model, "it") == "it"
        assert bt_id(model, "it") is None
        assert not model.model_fields["it"].is_required()

    def test_core_fields_are_not_extensions(self) -> None:
        assert extension_of(Invoice, "number") is None
        assert extension_of(InvoiceLine, "identifier") is None

    def test_extension_marker_rejects_a_bad_country(self) -> None:
        with pytest.raises(ValueError, match="country"):
            extension("IT")

    def test_bt_index_skips_extensions(self) -> None:
        segments = {segment.removesuffix("[]") for path in BT_INDEX.values() for segment in path.split(".")}
        assert "it" not in segments
        assert "item" in segments  # the segments are what the check above relies on

    def test_bt_index_skips_an_extension_explicitly_even_if_it_declares_bts(self) -> None:
        class _Inner(EuInvoiceModel):
            x: t.Annotated[str, bt("BT-2")]

        class _Root(EuInvoiceModel):
            a: t.Annotated[str, bt("BT-1")]
            ext: t.Annotated[_Inner | None, extension("xx")] = None

        assert build_index(_Root) == {"BG-0": "", "BT-1": "a"}


class TestItalianExtension:
    def test_defaults_to_none_on_invoice_and_line(self, invoice: Invoice) -> None:
        assert invoice.it is None
        assert all(item.it is None for item in invoice.lines)

    def test_regime_and_document_type_are_required(self) -> None:
        # 1.2.1.8 <RegimeFiscale> and 2.1.1.1 <TipoDocumento> are <1.1> (Rappresentazione tabellare 1.9.1).
        with pytest.raises(pydantic.ValidationError, match="tax_regime"):
            ItalianExtension.model_validate({"document_type": "TD01"})
        with pytest.raises(pydantic.ValidationError, match="document_type"):
            ItalianExtension.model_validate({"tax_regime": "RF01"})

    def test_codes_are_coerced_to_their_enums(self) -> None:
        it = _it(issuer="CC", payment={"conditions": "TP02", "method": "MP05"})
        assert it.tax_regime is RegimeFiscale.RF01
        assert it.document_type is TipoDocumento.TD01
        assert it.issuer is SoggettoEmittente.CC
        assert it.payment == ItalianPayment(conditions=CondizioniPagamento.TP02, method=ModalitaPagamento.MP05)

    @pytest.mark.parametrize(
        ("field", "value"),
        [("tax_regime", "RF03"), ("document_type", "TD07"), ("issuer", "XX"), ("document_type", " TD01")],
    )
    def test_codes_outside_xsd_1_2_3_are_refused(self, field: str, value: str) -> None:
        # RF03 was removed from the list and TD07 belongs to the simplified-invoice schema (FSM10), not FPR12.
        with pytest.raises(pydantic.ValidationError, match=field):
            _it(**{field: value})

    def test_is_frozen_hashable_and_rejects_unknown_fields(self) -> None:
        it = _it()
        assert hash(it) == hash(_it())
        with pytest.raises(pydantic.ValidationError, match="frozen"):
            it.tax_regime = RegimeFiscale.RF19  # type: ignore[misc]  # assigning to a frozen field is the point
        with pytest.raises(pydantic.ValidationError, match="extra"):
            _it(codice_destinatario="0000000")  # transmission data are writer options (#119), not model data

    def test_payment_method_is_optional_and_conditions_required(self) -> None:
        assert ItalianPayment(conditions=CondizioniPagamento.TP02).method is None
        with pytest.raises(pydantic.ValidationError, match="conditions"):
            ItalianPayment.model_validate({"method": "MP05"})

    def test_json_round_trip(self) -> None:
        it = _it(
            issuer="CC",
            vat_summaries=[
                {"rate": "22.00", "vat_chargeability": "I"},
                {"rate": "0", "nature": "N2.2", "legal_reference": "Art. 7-ter DPR 633/72"},
            ],
            payment={"conditions": "TP02"},
        )
        assert ItalianExtension.model_validate_json(it.model_dump_json()) == it
        assert ItalianExtension.model_validate(it.model_dump(mode="json")) == it


class TestVatSummaries:
    def test_keyed_by_rate_and_nature(self) -> None:
        it = _it(vat_summaries=[{"rate": "0", "nature": "N2.2"}, {"rate": "0", "nature": "N4"}, {"rate": "22"}])
        assert [(s.rate, s.nature) for s in it.vat_summaries] == [
            (Decimal("0"), Natura.N2_2),
            (Decimal("0"), Natura.N4),
            (Decimal("22"), None),
        ]

    @pytest.mark.parametrize(
        "pair",
        [
            ({"rate": "22"}, {"rate": "22.00", "vat_chargeability": "D"}),
            ({"rate": "0", "nature": "N4"}, {"rate": "0.0", "nature": "N4", "legal_reference": "Art. 10"}),
        ],
    )
    def test_a_key_twice_is_refused(self, pair: tuple[dict[str, str], dict[str, str]]) -> None:
        with pytest.raises(pydantic.ValidationError, match=r"2\.2\.2.*twice"):
            _it(vat_summaries=list(pair))

    @pytest.mark.parametrize("rate", ["-1", "100.01", "22.555", "1000"])
    def test_rate_must_fit_rate_type(self, rate: str) -> None:
        # RateType (Schema_VFPR12_v1.2.3.xsd): xs:decimal, pattern [0-9]{1,3}\.[0-9]{2}, maxInclusive 100.00.
        with pytest.raises(pydantic.ValidationError, match="RateType"):
            ItalianVatSummary.model_validate({"rate": rate})

    @pytest.mark.parametrize("rate", ["0", "4", "22.00", "100", "5.5"])
    def test_rates_within_rate_type_are_kept_as_given(self, rate: str) -> None:
        assert ItalianVatSummary.model_validate({"rate": rate}).rate == Decimal(rate)

    def test_rate_rejects_float(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="float"):
            ItalianVatSummary.model_validate({"rate": 22.0})

    @pytest.mark.parametrize("text", ["", "x" * 101, "Art. 10 €", "aĀ"])
    def test_legal_reference_must_fit_string100_latin_type(self, text: str) -> None:
        # String100LatinType: pattern [\p{IsBasicLatin}\p{IsLatin-1Supplement}]{1,100}.
        with pytest.raises(pydantic.ValidationError, match="String100LatinType"):
            ItalianVatSummary.model_validate({"rate": "0", "nature": "N4", "legal_reference": text})

    def test_legal_reference_accepts_latin_1(self) -> None:
        text = "Operazione non soggetta, art. 7-ter DPR 633/72 (è)" + "x" * 50
        assert len(text) == 100
        assert ItalianVatSummary(rate=Decimal("0"), legal_reference=text).legal_reference == text

    @given(
        st.lists(
            st.tuples(
                st.decimals(min_value=0, max_value=100, places=2, allow_nan=False, allow_infinity=False),
                st.none() | st.sampled_from(Natura),
            ),
            max_size=6,
        )
    )
    def test_accepted_exactly_when_the_keys_are_distinct(self, keys: list[tuple[Decimal, Natura | None]]) -> None:
        summaries = [{"rate": rate, "nature": nature} for rate, nature in keys]
        distinct = len(set(keys)) == len(keys)
        try:
            it = _it(vat_summaries=summaries)
        except pydantic.ValidationError:
            assert not distinct
        else:
            assert distinct
            assert [(s.rate, s.nature) for s in it.vat_summaries] == keys


class TestLineExtension:
    def test_all_optional(self) -> None:
        assert ItalianLineExtension() == ItalianLineExtension(supply_type=None, nature=None)

    def test_codes(self) -> None:
        ext = ItalianLineExtension.model_validate({"supply_type": "AC", "nature": "N6.9"})
        assert ext.supply_type is TipoCessionePrestazione.AC
        assert ext.nature is Natura.N6_9

    def test_unknown_nature_is_refused(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="nature"):
            ItalianLineExtension.model_validate({"nature": "N8"})


class TestPlumbing:
    def test_calc_complete_carries_the_extension_through(self) -> None:
        it = _it(vat_summaries=[{"rate": "0", "nature": "N2.2", "vat_chargeability": EsigibilitaIVA.I}])
        nature = ItalianLineExtension(nature=Natura.N2_2)
        base = draft(line(category="E", rate="0"), line(identifier="2"))
        lines = (base.lines[0].model_copy(update={"it": nature}), base.lines[1])
        result = calc.complete(InvoiceDraft.model_validate({**dict(base), "lines": lines, "it": it}))
        assert result.it == it
        assert [item.it for item in result.lines] == [nature, None]

    def test_set_extensions_names_every_set_hook(self, invoice: Invoice) -> None:
        assert set_extensions(invoice) == ()
        second = invoice.lines[0].model_copy(
            update={"it": ItalianLineExtension(supply_type=TipoCessionePrestazione.SC)}
        )
        changed = Invoice.model_validate({**dict(invoice), "it": _it(), "lines": (invoice.lines[0], second)})
        assert set_extensions(changed) == ("it", "lines[1].it")

    def test_invoice_rejects_a_wrong_extension_type(self, invoice: Invoice) -> None:
        with pytest.raises(pydantic.ValidationError):
            Invoice.model_validate({**dict(invoice), "it": {"tax_regime": "RF01"}})

    def test_model_error_is_the_cause(self) -> None:
        with pytest.raises(pydantic.ValidationError) as caught:
            _it(vat_summaries=[{"rate": "4"}, {"rate": "4"}])
        assert isinstance(caught.value.errors()[0]["ctx"]["error"], ModelError)
