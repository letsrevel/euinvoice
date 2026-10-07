"""Every term in ``WRITTEN`` reaches the FPR12 output, or is a listed derived term (#119; the walker's guarantee).

``_write_refuse.WRITTEN`` lets a term through the pre-flight. If a term were added to it without writer code that
fills its element, it would be dropped silently; this test fails instead.
"""

import typing as t

import pydantic
import pytest
from lxml import etree

from _fatturapa_write import TRANSMISSION, every_written_term, samples, written
from euinvoice import _xml, to_xml
from euinvoice.errors import PreflightError
from euinvoice.model import Invoice
from euinvoice.model._base import bt_id
from euinvoice.model.bt_index import BT_INDEX
from euinvoice.syntax import Syntax
from euinvoice.syntax.fatturapa._write_refuse import WRITTEN
from euinvoice.syntax.fatturapa._write_rules import UNWRITTEN

_H: t.Final = "FatturaElettronicaHeader"
_SELLER: t.Final = f"{_H}/CedentePrestatore"
_BUYER: t.Final = f"{_H}/CessionarioCommittente"
_B: t.Final = "FatturaElettronicaBody"
_GEN: t.Final = f"{_B}/DatiGenerali"
_DOC: t.Final = f"{_GEN}/DatiGeneraliDocumento"
_LINE: t.Final = f"{_B}/DatiBeniServizi/DettaglioLinee"
_SUM: t.Final = f"{_B}/DatiBeniServizi/DatiRiepilogo"
_PAY: t.Final = f"{_B}/DatiPagamento/DettaglioPagamento"

# The element each written term fills (App. 4.1 rows), in every_written_term() or, for BT-92/BT-98, the TD04 sample.
ELEMENTS: t.Final[dict[str, str]] = {
    "BT-1": f"{_DOC}/Numero",
    "BT-2": f"{_DOC}/Data",
    "BT-5": f"{_DOC}/Divisa",
    "BT-8": f"{_SUM}/EsigibilitaIVA",
    "BT-9": f"{_PAY}/DataScadenzaPagamento",
    "BT-12": f"{_GEN}/DatiContratto/IdDocumento",
    "BT-13": f"{_GEN}/DatiOrdineAcquisto/IdDocumento",
    "BT-15": f"{_GEN}/DatiRicezione/IdDocumento",
    "BT-19": f"{_SELLER}/RiferimentoAmministrazione",
    "BT-22": f"{_DOC}/Causale",
    "BT-25": f"{_GEN}/DatiFattureCollegate/IdDocumento",
    "BT-26": f"{_GEN}/DatiFattureCollegate/Data",
    "BT-27": f"{_SELLER}/DatiAnagrafici/Anagrafica/Denominazione",
    "BT-30": f"{_SELLER}/DatiAnagrafici/CodiceFiscale",
    "BT-31": f"{_SELLER}/DatiAnagrafici/IdFiscaleIVA/IdCodice",
    "BT-35": f"{_SELLER}/Sede/Indirizzo",
    "BT-36": f"{_SELLER}/Sede/NumeroCivico",
    "BT-37": f"{_SELLER}/Sede/Comune",
    "BT-38": f"{_SELLER}/Sede/CAP",
    "BT-39": f"{_SELLER}/Sede/Provincia",
    "BT-40": f"{_SELLER}/Sede/Nazione",
    "BT-42": f"{_SELLER}/Contatti/Telefono",
    "BT-43": f"{_SELLER}/Contatti/Email",
    "BT-44": f"{_BUYER}/DatiAnagrafici/Anagrafica/Denominazione",
    "BT-47": f"{_BUYER}/DatiAnagrafici/CodiceFiscale",
    "BT-48": f"{_BUYER}/DatiAnagrafici/IdFiscaleIVA/IdCodice",
    "BT-50": f"{_BUYER}/Sede/Indirizzo",
    "BT-51": f"{_BUYER}/Sede/NumeroCivico",
    "BT-52": f"{_BUYER}/Sede/Comune",
    "BT-53": f"{_BUYER}/Sede/CAP",
    "BT-54": f"{_BUYER}/Sede/Provincia",
    "BT-55": f"{_BUYER}/Sede/Nazione",
    "BT-59": f"{_PAY}/Beneficiario",
    "BT-81": f"{_PAY}/ModalitaPagamento",
    "BT-83": f"{_PAY}/CodicePagamento",
    "BT-84": f"{_PAY}/IBAN",
    "BT-86": f"{_PAY}/BIC",
    "BT-92": f"{_DOC}/DatiBollo/ImportoBollo",
    "BT-98": f"{_DOC}/DatiBollo/BolloVirtuale",
    "BT-99": f"{_DOC}/DatiBollo/ImportoBollo",
    "BT-105": f"{_DOC}/DatiBollo/BolloVirtuale",
    "BT-112": f"{_DOC}/ImportoTotaleDocumento",
    "BT-114": f"{_DOC}/Arrotondamento",
    "BT-115": f"{_PAY}/ImportoPagamento",
    "BT-116": f"{_SUM}/ImponibileImporto",
    "BT-117": f"{_SUM}/Imposta",
    "BT-119": f"{_SUM}/AliquotaIVA",
    "BT-120": f"{_SUM}/RiferimentoNormativo",
    "BT-126": f"{_LINE}/NumeroLinea",
    "BT-129": f"{_LINE}/Quantita",
    "BT-130": f"{_LINE}/UnitaMisura",
    "BT-131": f"{_LINE}/PrezzoTotale",
    "BT-133": f"{_LINE}/RiferimentoAmministrazione",
    "BT-134": f"{_LINE}/DataInizioPeriodo",
    "BT-135": f"{_LINE}/DataFinePeriodo",
    "BT-146": f"{_LINE}/PrezzoUnitario",
    "BT-147": f"{_LINE}/ScontoMaggiorazione/Importo",
    "BT-148": f"{_LINE}/PrezzoUnitario",
    "BT-152": f"{_LINE}/AliquotaIVA",
    "BT-153": f"{_LINE}/Descrizione",
}

# Terms the writer checks or derives instead of writing (see _write_refuse.WRITTEN and the pre-flight).
DERIVED: t.Final = frozenset(
    {
        "BT-3",  # checked against TipoDocumento (App. 5.4)
        "BT-24",  # the EN 16931 specification identifier
        "BT-121",  # carried by Natura: the pre-flight requires the App. 5.1 VATEX code of the group's Natura
        "BT-95",  # the stamp duty's category, rate and reason: implied by DatiBollo (BR-IT-DC-480)
        "BT-96",
        "BT-97",
        "BT-102",
        "BT-103",
        "BT-104",
        "BT-106",  # sums checked against the summaries (pre-flight TOTALS)
        "BT-107",
        "BT-108",
        "BT-109",
        "BT-110",
        "BT-118",  # becomes Natura / EsigibilitaIVA through the lines
        "BT-151",  # checked against Natura (App. 5.1)
    }
)


def test_every_written_term_is_an_element_or_derived() -> None:
    terms = {i for i in WRITTEN if i.startswith("BT-")}

    assert set(ELEMENTS) | DERIVED == terms
    assert not set(ELEMENTS) & DERIVED


def _set_terms(model: object) -> t.Iterator[str]:
    """The BT ids set anywhere in ``model``."""
    if not isinstance(model, pydantic.BaseModel):
        return
    cls = type(model)
    for name in cls.model_fields:
        value = getattr(model, name)
        ident = bt_id(cls, name)
        if value is None or value == () or ident is None:
            continue
        if ident.startswith("BT-"):
            yield ident
        for item in value if isinstance(value, tuple) else (value,):
            yield from _set_terms(item)


def _maximal() -> dict[str, Invoice]:
    return {"invoice": every_written_term(), "credit note": samples()["TD04 credit note"].invoice}


def _check_written(roots: dict[str, etree._Element], invoices: dict[str, Invoice]) -> None:
    set_terms = set(_set_terms(invoices["invoice"])) | set(_set_terms(invoices["credit note"]))
    assert set(ELEMENTS) <= set_terms
    assert set_terms <= set(ELEMENTS) | DERIVED  # no set term is dropped
    for term, path in ELEMENTS.items():
        root = roots["credit note" if term in {"BT-92", "BT-98"} else "invoice"]
        assert root.find(path) is not None, (term, path, BT_INDEX.get(term))


def test_the_maximal_samples_set_and_write_every_element() -> None:
    invoices = _maximal()
    _check_written({name: written(invoice) for name, invoice in invoices.items()}, invoices)


def test_to_xml_writes_every_set_term_or_refuses() -> None:
    invoices = _maximal()
    roots = {
        name: _xml.parse(to_xml(invoice, syntax=Syntax.FATTURAPA, fatturapa_transmission=TRANSMISSION))
        for name, invoice in invoices.items()
    }

    _check_written(roots, invoices)


@pytest.mark.parametrize(
    "name",
    ["payment_terms", "buyer_reference", "project_reference", "sales_order_reference", "despatch_advice_reference"],
)
def test_to_xml_refuses_a_set_term_it_cannot_write(name: str) -> None:
    invoice = Invoice.model_validate({**dict(every_written_term()), name: "X"})

    with pytest.raises(PreflightError) as raised:
        to_xml(invoice, syntax=Syntax.FATTURAPA, fatturapa_transmission=TRANSMISSION)
    assert (UNWRITTEN, name) in {(f.rule_id, f.location) for f in raised.value.findings}
