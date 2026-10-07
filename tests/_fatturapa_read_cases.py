"""The ``unmapped`` and refusal cases of the FatturaPA reader tests (#120): synthetic, XSD 1.2.3-valid documents.

``tests/conformance/test_fatturapa_read_official.py`` validates every one against the pinned XSD.
"""

import typing as t

from _fatturapa_read import body, cassa_block, detail, document, line, payment, summary

ROOT: t.Final = "/p:FatturaElettronica"
GENERAL: t.Final = f"{ROOT}/FatturaElettronicaBody/DatiGenerali"
LINE: t.Final = f"{ROOT}/FatturaElettronicaBody/DatiBeniServizi/DettaglioLinee"
SUMMARY: t.Final = f"{ROOT}/FatturaElettronicaBody/DatiBeniServizi/DatiRiepilogo"
DETAIL: t.Final = f"{ROOT}/FatturaElettronicaBody/DatiPagamento/DettaglioPagamento"

REPORTED: t.Final[list[tuple[str, bytes, tuple[str, ...]]]] = [
    (
        "line-level purchase order",
        document(
            body(
                general="<DatiOrdineAcquisto><RiferimentoNumeroLinea>1</RiferimentoNumeroLinea>"
                "<IdDocumento>PO-1</IdDocumento></DatiOrdineAcquisto>"
            )
        ),
        (f"{GENERAL}/DatiOrdineAcquisto",),
    ),
    (
        "two contracts",
        document(
            body(
                general="<DatiContratto><IdDocumento>C-1</IdDocumento></DatiContratto>"
                "<DatiContratto><IdDocumento>C-2</IdDocumento></DatiContratto>"
            )
        ),
        (f"{GENERAL}/DatiContratto[1]", f"{GENERAL}/DatiContratto[2]"),
    ),
    (
        "DatiSAL",
        document(body(general="<DatiSAL><RiferimentoFase>1</RiferimentoFase></DatiSAL>")),
        (f"{GENERAL}/DatiSAL",),
    ),
    (
        "carrier only",
        document(body(general="<DatiTrasporto><MezzoTrasporto>Van</MezzoTrasporto></DatiTrasporto>")),
        (f"{GENERAL}/DatiTrasporto",),
    ),
    (
        "line references of a preceding invoice",
        document(
            body(
                general="<DatiFattureCollegate><RiferimentoNumeroLinea>1</RiferimentoNumeroLinea>"
                "<IdDocumento>FT-0</IdDocumento></DatiFattureCollegate>"
            )
        ),
        (f"{GENERAL}/DatiFattureCollegate/RiferimentoNumeroLinea",),
    ),
    (
        "withholding, stamp duty and Art73",
        document(
            body(
                document_extra="<DatiRitenuta><TipoRitenuta>RT01</TipoRitenuta><ImportoRitenuta>20.00"
                "</ImportoRitenuta><AliquotaRitenuta>20.00</AliquotaRitenuta>"
                "<CausalePagamento>A</CausalePagamento></DatiRitenuta><DatiBollo>"
                "<BolloVirtuale>SI</BolloVirtuale><ImportoBollo>2.00</ImportoBollo></DatiBollo>"
                "<Art73>SI</Art73>",
                lines=line(after=""),
            )
        ),
        (
            f"{GENERAL}/DatiGeneraliDocumento/DatiRitenuta",
            f"{GENERAL}/DatiGeneraliDocumento/DatiBollo/ImportoBollo",  # BR-IT-DC-480: the EN charge is 0
            f"{GENERAL}/DatiGeneraliDocumento/Art73",
        ),
    ),
    (
        "a unit that is no Rec 20 code",
        document(body(lines=line(middle="<UnitaMisura>pz</UnitaMisura>"))),
        (f"{LINE}/UnitaMisura",),
    ),
    (
        "line withholding flag",
        document(body(lines=line().replace("</AliquotaIVA>", "</AliquotaIVA><Ritenuta>SI</Ritenuta>"))),
        (f"{LINE}/Ritenuta",),
    ),
    (
        "a second CodiceArticolo",
        document(
            body(
                lines=line(
                    before="<CodiceArticolo><CodiceTipo>EAN</CodiceTipo><CodiceValore>1</CodiceValore>"
                    "</CodiceArticolo><CodiceArticolo><CodiceTipo>SKU</CodiceTipo>"
                    "<CodiceValore>2</CodiceValore></CodiceArticolo>"
                )
            )
        ),
        (f"{LINE}/CodiceArticolo[2]",),
    ),
    (
        "AltriDatiGestionali without a value, and a second value",
        document(
            body(
                lines=line(
                    after="<AltriDatiGestionali><TipoDato>EMPTY</TipoDato></AltriDatiGestionali>"
                    "<AltriDatiGestionali><TipoDato>TWO</TipoDato><RiferimentoTesto>a"
                    "</RiferimentoTesto><RiferimentoNumero>1.00</RiferimentoNumero>"
                    "</AltriDatiGestionali>"
                )
            )
        ),
        (f"{LINE}/AltriDatiGestionali[1]", f"{LINE}/AltriDatiGestionali[2]/RiferimentoNumero"),
    ),
    (
        "a percentage next to an amount",
        document(
            body(
                lines=line(
                    total="90.00",
                    adjustments="<ScontoMaggiorazione><Tipo>SC</Tipo><Percentuale>10.00"
                    "</Percentuale><Importo>5.00</Importo></ScontoMaggiorazione>",
                ),
                summaries=summary("22.00", "90.00", "19.80"),
            )
        ),
        (f"{LINE}/ScontoMaggiorazione/Percentuale",),
    ),
    (
        "an empty adjustment",
        document(body(lines=line(adjustments="<ScontoMaggiorazione><Tipo>SC</Tipo></ScontoMaggiorazione>"))),
        (f"{LINE}/ScontoMaggiorazione",),
    ),
    (
        "summary rounding and ancillary costs",
        document(
            body(
                summaries=summary().replace(
                    "<ImponibileImporto>",
                    "<SpeseAccessorie>1.00</SpeseAccessorie><Arrotondamento>0.00</Arrotondamento><ImponibileImporto>",
                )
            )
        ),
        (f"{SUMMARY}/SpeseAccessorie", f"{SUMMARY}/Arrotondamento"),
    ),
    (
        "a second legal reference for one Natura",
        document(
            body(
                lines=line(rate="0.00", natura="N4") + line(2, rate="0.00", natura="N4"),
                summaries=summary("0.00", "100.00", "0.00", natura="N4", legal="Art. 10")
                + summary("0.00", "100.00", "0.00", natura="N4", legal="Art. 10 c.1"),
            )
        ),
        (f"{SUMMARY}[2]/RiferimentoNormativo",),
    ),
    (
        "instalments",
        document(body(after=payment(detail(amount="61.00"), detail(amount="61.00"), conditions="TP01"))),
        (f"{DETAIL}[1]/ImportoPagamento", f"{DETAIL}[2]"),
    ),
    (
        "a second DatiPagamento and a BIC without IBAN",
        document(
            body(
                after=payment(
                    detail(middle="<GiorniTerminiPagamento>30</GiorniTerminiPagamento>", after="<BIC>BYLADEM1001</BIC>")
                )
                + payment(detail())
            )
        ),
        (
            f"{ROOT}/FatturaElettronicaBody/DatiPagamento[1]/DettaglioPagamento/ImportoPagamento",
            f"{ROOT}/FatturaElettronicaBody/DatiPagamento[1]/DettaglioPagamento/BIC",
            f"{ROOT}/FatturaElettronicaBody/DatiPagamento[2]",
        ),
    ),
    (
        "attachments",
        document(
            body(after="<Allegati><NomeAttachment>a.pdf</NomeAttachment><Attachment>JVBERi0=</Attachment></Allegati>")
        ),
        (f"{ROOT}/FatturaElettronicaBody/Allegati",),
    ),
    (
        "an issue date with a time zone",
        document(body().replace("<Data>2026-01-15</Data>", "<Data>2026-01-15+01:00</Data>")),
        (f"{GENERAL}/DatiGeneraliDocumento/Data/text()",),
    ),
]
"""(name, document, the unmapped paths besides DatiTrasmissione): content with no model home is reported."""

REFUSED: t.Final[list[tuple[str, bytes, str]]] = [
    (
        "a Natura with a rate",
        document(body(lines=line(natura="N6.1"), summaries=summary(natura="N6.1"))),
        "Natura N6.1 (VAT category AE, App. 5.1) with AliquotaIVA 22.00: EN 16931 requires rate 0 for category AE "
        "(BR-AE-05)",
    ),
    (
        "a line Natura with a rate",
        document(body(lines=line(natura="N4"), summaries=summary())),
        "Natura N4 (VAT category E, App. 5.1) with AliquotaIVA 22.00",
    ),
    (
        "PrezzoTotale with 3 decimals",
        document(body(lines=line(total="100.001"))),
        "2.2.1.11 PrezzoTotale 100.001 has more than two decimals",
    ),
    (
        "generic Natura N2",
        document(body(lines=line(rate="0.00", natura="N2"), summaries=summary("0.00", "100.00", "0.00", natura="N2"))),
        "generic code N2 has no VAT category",
    ),
    (
        "rate 0 without Natura",
        document(body(lines=line(rate="0.00"), summaries=summary("0.00", "100.00", "0.00", natura="N4"))),
        "2.2.1.14 Natura is required with AliquotaIVA 0",
    ),
    (
        "split payment and ordinary VAT at two rates",
        document(
            body(
                lines=line() + line(2, rate="10.00"),
                summaries=summary(chargeability="S") + summary("10.00", "100.00", "10.00", chargeability="D"),
            )
        ),
        "does not allow category B next to S (BR-B-02)",
    ),
    (
        "a social-security fund at rate 0 without Natura",
        document(
            body(
                document_extra=cassa_block("0.00"),
                summaries=summary() + summary("0.00", "4.00", "0.00", natura="N4"),
            )
        ),
        "2.1.1.7.7 Natura is required with AliquotaIVA 0",
    ),
    (
        "split and ordinary at one rate",
        document(body(summaries=summary(chargeability="S") + summary())),
        "does not allow category B next to S (BR-B-02)",
    ),
    (
        "two adjustments on a line",
        document(
            body(
                lines=line(
                    adjustments="<ScontoMaggiorazione><Tipo>SC</Tipo><Importo>1.00</Importo></ScontoMaggiorazione>" * 2
                )
            )
        ),
        "2 ScontoMaggiorazione on one line",
    ),
]
"""(name, XSD-valid document, message): values the model cannot hold without rounding or guessing (#132)."""
