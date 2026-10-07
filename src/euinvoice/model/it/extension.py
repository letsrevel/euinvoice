"""The ``Invoice.it`` extension: FatturaPA data with no EN 16931 business term (D3 as amended, ADR 0001, #118).

Scope is the FatturaPA v1 subset (FPR12; TD01, TD04, TD24, TD17; plan M11). Every field cites its FatturaPA
element id as numbered in the "Rappresentazione tabellare del tracciato FatturaPA" (the copy linked from the AE
Specifiche tecniche 1.9.1 page; the table has no version of its own), in
``json_schema_extra={"fatturapa": "<id>"}`` (:func:`fatturapa`). Each concept is ``EXT`` in App. 4.1 of the SdI
"Regole tecniche fatture europee" v2.6 (no business term), or maps to one only lossily (see each field).

Where the data hangs:

* Document level: :class:`ItalianExtension` on ``Invoice.it`` / ``InvoiceDraft.it``.
* Line level: :class:`ItalianLineExtension` on ``InvoiceLine.it`` / ``LineDraft.it``. Lines are input data, one
  FatturaPA ``DettaglioLinee`` (2.2.1) per INVOICE LINE (BG-25) (App. 4.1). Keying them from the root would need
  a unique line id, and no CEN rule makes BT-126 unique (BR-21 only requires it, ``EN16931-model.sch`` 1.3.16).
* VAT summary level: :attr:`ItalianExtension.vat_summaries`, keyed by rate, ``Natura`` and split payment (see
  :class:`ItalianVatSummary`). BG-23 is derived by
  :func:`euinvoice.calc.complete` and cannot carry it: one BG-23 per VAT category and rate (BR-CO-17) can stand
  for several ``DatiRiepilogo`` (2.2.2), which FatturaPA groups by rate and, at rate zero, by ``Natura``
  (Rappresentazione tabellare, row 2.2.2), e.g. N2.2 and N4 both map to category E at 0 % (App. 5.1).

Transmission data (IdTrasmittente, ProgressivoInvio, CodiceDestinatario, PECDestinatario) are writer options
(#119), not model data. Withholding (DatiRitenuta), social-security funds (DatiCassaPrevidenziale), Art73 and
instalments beyond one ``DettaglioPagamento`` are not modelled in v1. Stamp duty (DatiBollo, 2.1.1.6) needs no
extension field: App. 4.1 maps it to a document-level charge with BT-105 = SAE and amount BT-99 (credit note:
BT-98 = 95, BT-92). The writer (#119) maps it.

The model checks only what the XSD makes local and unambiguous (code lists, ``RateType``,
``String100LatinType``) plus the uniqueness its keying needs. The SdI checks of Allegato A 1.9.1 (e.g. 00413/00414
Natura vs rate, 00420 N6 with EsigibilitaIVA S, 00443/00444 summary vs lines, 00445 generic Natura) are
findings of the FatturaPA validator (#121), so a document that the SdI would refuse can still be read.
"""

import re
import typing as t
from decimal import Decimal

import pydantic
from pydantic.fields import FieldInfo

from euinvoice.errors import ModelError
from euinvoice.model._base import EuInvoiceModel
from euinvoice.model.amounts import Percentage
from euinvoice.model.datatypes import Text
from euinvoice.model.it.codes import (
    CondizioniPagamento,
    EsigibilitaIVA,
    ModalitaPagamento,
    Natura,
    RegimeFiscale,
    SoggettoEmittente,
    TipoCessionePrestazione,
    TipoDocumento,
)

__all__ = [
    "ItalianExtension",
    "ItalianLineExtension",
    "ItalianPayment",
    "ItalianVatSummary",
    "fatturapa",
    "fatturapa_id",
]

_ELEMENT_ID = re.compile(r"[1-9][0-9]*(?:\.[1-9][0-9]*)*")
_LATIN_100 = re.compile(r"[\u0000-ÿ]{1,100}")
_RATE_MAX = Decimal(100)
_CENT = Decimal("0.01")


def fatturapa(ident: str) -> FieldInfo:
    """Return field metadata carrying a FatturaPA element id (D3 as amended), e.g. ``"2.1.1.1"``.

    Use it inside ``typing.Annotated`` like :func:`euinvoice.model._base.bt`.

    Args:
        ident: The element number from the Rappresentazione tabellare, e.g. ``"2.2.1.14"``.

    Returns:
        The pydantic ``FieldInfo``, ``json_schema_extra={"fatturapa": ident}``.

    Raises:
        ValueError: ``ident`` is not a dotted element number.
    """
    if not _ELEMENT_ID.fullmatch(ident):
        raise ValueError(f"FatturaPA element id must look like 2.1.1.1, got {ident!r}")
    return t.cast(FieldInfo, pydantic.Field(json_schema_extra={"fatturapa": ident}))


def fatturapa_id(model: type[pydantic.BaseModel], field: str) -> str | None:
    """Return the FatturaPA element id declared with :func:`fatturapa` on ``model.field``, or ``None``.

    Args:
        model: The model class.
        field: The field name.

    Returns:
        The id, e.g. ``"1.2.1.8"``, or ``None``.

    Raises:
        KeyError: ``model`` has no field called ``field``.
    """
    extra = model.model_fields[field].json_schema_extra
    ident = extra.get("fatturapa") if isinstance(extra, dict) else None
    return ident if isinstance(ident, str) else None


def _rate(value: Decimal) -> Decimal:
    # RateType's pattern [0-9]{1,3}\.[0-9]{2} has no sign, so a negative zero ("-0.00") does not fit either.
    if value.is_signed() or value > _RATE_MAX or value != value.quantize(_CENT):
        raise ModelError(
            f"rate {format(value, 'f')} does not fit RateType (FatturaPA XSD 1.2.3: 0 to 100.00, two decimals)"
        )
    return value


def _latin_100(value: str) -> str:
    if not _LATIN_100.fullmatch(value):
        raise ModelError(
            "must be 1 to 100 characters of Basic Latin and Latin-1 Supplement (U+0000..U+00FF), "
            f"String100LatinType of the FatturaPA XSD 1.2.3; got {len(value)} characters"
        )
    return value


Rate = t.Annotated[Percentage, pydantic.AfterValidator(_rate)]
"""A FatturaPA VAT rate (``AliquotaIVA``, XSD ``RateType``): a percentage from 0 to 100 with at most two decimals."""

Latin100Text = t.Annotated[Text, pydantic.AfterValidator(_latin_100)]
"""Text of XSD ``String100LatinType`` (``xs:normalizedString``, pattern
``[\\p{IsBasicLatin}\\p{IsLatin-1Supplement}]{1,100}``)."""


class ItalianLineExtension(EuInvoiceModel):
    """FatturaPA data of one line, 2.2.1 ``<DettaglioLinee>`` (``InvoiceLine.it``)."""

    supply_type: t.Annotated[TipoCessionePrestazione | None, fatturapa("2.2.1.2")] = None
    """``TipoCessionePrestazione`` <0.1>: the line is a discount, premium, rebate or ancillary charge. App. 4.1
    carries it in an ITEM ATTRIBUTE (BT-160 "TipoCessionePrestazione", BT-161 the code)."""
    nature: t.Annotated[Natura | None, fatturapa("2.2.1.14")] = None
    """``Natura`` <0.1>: why the line carries no VAT. App. 4.1 carries it in an ITEM ATTRIBUTE (BT-160 "Natura")
    or, cross-border, derives it from BT-151 (App. 5.1); the category alone cannot tell N2.2 from N4."""


class ItalianVatSummary(EuInvoiceModel):
    """FatturaPA data of one 2.2.2 ``<DatiRiepilogo>``, identified by its rate, ``Natura`` and split payment.

    The amounts (``ImponibileImporto``, ``Imposta``) are not here: the writer computes them (#119).

    FatturaPA requires a separate summary per payment mode: split payment (EsigibilitaIVA S, from VAT category B,
    App. 4.1 2.2.2.7) versus ordinary (Allegato A 1.9.1, DatiRiepilogo: "per ogni aliquota IVA e modalità di
    versamento dell'imposta ("scissione dei pagamenti" od ordinaria), e/o per ogni natura"). The writer (#119)
    derives that split from the B/S categories. So the key is (:attr:`rate`, :attr:`nature`, whether
    :attr:`vat_chargeability` is ``S``): a split-payment summary and an ordinary one can share a rate. Within those,
    splitting by D vs I is optional (Rappresentazione tabellare, row 2.2.2), and this key cannot express it.
    """

    # ponytail: one ordinary summary per (rate, Natura), so no D vs I split of it. That would need per-line
    # chargeability, which FatturaPA lines do not have. Upgrade path: add vat_chargeability to the key and amounts to
    # the summary.

    rate: t.Annotated[Rate, fatturapa("2.2.2.1")]
    """``AliquotaIVA`` <1.1>, as a percentage (``22`` for 22 %). Part of the key."""
    nature: t.Annotated[Natura | None, fatturapa("2.2.2.2")] = None
    """``Natura`` <0.1>. Part of the key."""
    vat_chargeability: t.Annotated[EsigibilitaIVA | None, fatturapa("2.2.2.7")] = None
    """``EsigibilitaIVA`` <0.1>. App. 4.1 derives it from BT-8 (3 and 35 → I, 432 → D) or category B (→ S) for the
    whole document; this sets it per summary. Whether it is ``S`` (split payment) is part of the key."""
    legal_reference: t.Annotated[Latin100Text | None, fatturapa("2.2.2.8")] = None
    """``RiferimentoNormativo`` <0.1>, the legal reference for :attr:`nature`. App. 4.1 concatenates ``Natura``
    and this into BT-120 of the VAT breakdown."""


class ItalianPayment(EuInvoiceModel):
    """FatturaPA data of 2.4 ``<DatiPagamento>``, with one 2.4.2 ``<DettaglioPagamento>``."""

    # ponytail: one DatiPagamento with one DettaglioPagamento, as BG-16 has one BT-81. XSD 1.2.3 allows 0..n of
    # each (instalments, TP01). Upgrade path: a tuple of details with their amounts and due dates.

    conditions: t.Annotated[CondizioniPagamento, fatturapa("2.4.1")]
    """``CondizioniPagamento`` <1.1> (App. 4.1 folds it into BT-20 as text)."""
    method: t.Annotated[ModalitaPagamento | None, fatturapa("2.4.2.2")] = None
    """``ModalitaPagamento`` <1.1>. App. 5.6 maps BT-81 to it many-to-one; set it to keep the exact code, or leave
    it unset to have it derived from BT-81."""


class ItalianExtension(EuInvoiceModel):
    """FatturaPA data of an invoice with no EN 16931 business term (``Invoice.it``)."""

    tax_regime: t.Annotated[RegimeFiscale, fatturapa("1.2.1.8")]
    """``RegimeFiscale`` <1.1> of the seller (``CedentePrestatore``); FatturaPA requires it, EN 16931 has no term."""
    issuer: t.Annotated[SoggettoEmittente | None, fatturapa("1.6")] = None
    """``SoggettoEmittente`` <0.1>: who issued the document when it is not the seller, e.g. ``CC`` (the buyer)
    for a TD17 self-billed integration."""
    document_type: t.Annotated[TipoDocumento, fatturapa("2.1.1.1")]
    """``TipoDocumento`` <1.1>. Required: App. 5.4 maps many codes to BT-3 ``380``, so BT-3 cannot give it."""
    vat_summaries: t.Annotated[tuple[ItalianVatSummary, ...], fatturapa("2.2.2")] = ()
    """``DatiRiepilogo`` data, at most one per rate, ``Natura`` and split payment or not (rates compared by
    value)."""
    payment: t.Annotated[ItalianPayment | None, fatturapa("2.4")] = None
    """``DatiPagamento`` data (BG-16 in App. 4.1)."""

    @pydantic.field_validator("vat_summaries")
    @classmethod
    def _one_summary_per_key(cls, value: tuple[ItalianVatSummary, ...]) -> tuple[ItalianVatSummary, ...]:
        seen: set[tuple[Decimal, Natura | None, bool]] = set()
        for summary in value:
            split = summary.vat_chargeability is EsigibilitaIVA.S
            key = (summary.rate, summary.nature, split)
            if key in seen:
                mode = "split payment (S)" if split else "ordinary payment"
                raise ModelError(
                    f"2.2.2 DatiRiepilogo: rate {format(summary.rate, 'f')} with Natura {summary.nature} and {mode} "
                    "is given twice; vat_summaries holds at most one entry per rate, Natura and split payment or not"
                )
            seen.add(key)
        return value
