"""The FatturaPA code enums of ``Invoice.it`` (#118). ``tests/conformance/test_it_codes_xsd.py`` checks them against
the pinned XSD 1.2.3; these tests pin their shape offline."""

import enum
import typing as t

import pytest

from euinvoice.model import it

ENUMS: t.Final[dict[type[enum.StrEnum], int]] = {
    # enum: number of enumeration values of its simpleType in Schema_VFPR12_v1.2.3.xsd
    it.TipoDocumento: 20,
    it.RegimeFiscale: 19,
    it.SoggettoEmittente: 2,
    it.Natura: 24,
    it.TipoCessionePrestazione: 4,
    it.EsigibilitaIVA: 3,
    it.CondizioniPagamento: 3,
    it.ModalitaPagamento: 23,
}


@pytest.mark.parametrize(("codes", "size"), ENUMS.items(), ids=lambda x: getattr(x, "__name__", str(x)))
def test_member_names_spell_their_codes(codes: type[enum.StrEnum], size: int) -> None:
    assert len(codes) == size
    for member in codes:
        assert member.name == member.value.replace(".", "_"), member


def test_every_enum_is_exported() -> None:
    assert {codes.__name__ for codes in ENUMS} <= set(it.__all__)


def test_generic_natura_codes_are_kept_for_reading() -> None:
    # SdI check 00445 (Allegato A 1.9.1, Appendix 1) refuses N2, N3 and N6 in ordinary invoices issued from
    # 2021-01-01, but XSD 1.2.3 still lists them, so documents that use them can be read.
    assert {it.Natura.N2, it.Natura.N3, it.Natura.N6} <= set(it.Natura)
