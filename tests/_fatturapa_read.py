"""Synthetic FatturaPA 1.2.3 documents for the reader tests (#120): fake parties and placeholder identifiers only.

:func:`document` renders a whole document in the XSD 1.2.3 element order from parts, so each variant stays
schema-valid; ``tests/conformance/test_fatturapa_read_official.py`` validates every document of :data:`DOCUMENTS`
against the pinned XSD. :data:`FULL` maps every row the reader maps at least once.
"""

import typing as t

from euinvoice import _xml

ADDRESS: t.Final = (
    "<Sede><Indirizzo>Via Esempio</Indirizzo><NumeroCivico>1</NumeroCivico><CAP>00100</CAP><Comune>Roma</Comune>"
    "<Provincia>RM</Provincia><Nazione>IT</Nazione></Sede>"
)
TRANSMISSION: t.Final = (
    "<DatiTrasmissione><IdTrasmittente><IdPaese>IT</IdPaese><IdCodice>00000000001</IdCodice></IdTrasmittente>"
    "<ProgressivoInvio>00001</ProgressivoInvio><FormatoTrasmissione>FPR12</FormatoTrasmissione>"
    "<CodiceDestinatario>0000000</CodiceDestinatario></DatiTrasmissione>"
)
SELLER_VAT: t.Final = "<IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>00000000001</IdCodice></IdFiscaleIVA>"
BUYER_VAT: t.Final = "<IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>00000000002</IdCodice></IdFiscaleIVA>"
BUYER_CF: t.Final = "<CodiceFiscale>AAAAAA00A00A000A</CodiceFiscale>"
COMPANY: t.Final = "<Anagrafica><Denominazione>Example Srl</Denominazione></Anagrafica>"
PERSON: t.Final = "<Anagrafica><Nome>Mario</Nome><Cognome>De Rossi</Cognome><Titolo>Dott.</Titolo></Anagrafica>"


def line(
    number: int = 1,
    *,
    quantity: str | None = "2.00",
    unit: str = "50.00",
    total: str = "100.00",
    rate: str = "22.00",
    natura: str | None = None,
    before: str = "",
    middle: str = "",
    adjustments: str = "",
    after: str = "",
    description: str = "Ticket",
) -> str:
    """A DettaglioLinee (2.2.1) in XSD order; ``before`` goes after NumeroLinea, ``middle`` after Quantita, ``after``
    after Natura."""
    return (
        f"<DettaglioLinee><NumeroLinea>{number}</NumeroLinea>{before}<Descrizione>{description}</Descrizione>"
        + ("" if quantity is None else f"<Quantita>{quantity}</Quantita>")
        + f"{middle}<PrezzoUnitario>{unit}</PrezzoUnitario>{adjustments}<PrezzoTotale>{total}</PrezzoTotale>"
        + f"<AliquotaIVA>{rate}</AliquotaIVA>"
        + ("" if natura is None else f"<Natura>{natura}</Natura>")
        + f"{after}</DettaglioLinee>"
    )


def summary(
    rate: str = "22.00",
    taxable: str = "100.00",
    tax: str = "22.00",
    *,
    natura: str | None = None,
    chargeability: str | None = None,
    legal: str | None = None,
) -> str:
    """A DatiRiepilogo (2.2.2) in XSD order."""
    return (
        f"<DatiRiepilogo><AliquotaIVA>{rate}</AliquotaIVA>"
        + ("" if natura is None else f"<Natura>{natura}</Natura>")
        + f"<ImponibileImporto>{taxable}</ImponibileImporto><Imposta>{tax}</Imposta>"
        + ("" if chargeability is None else f"<EsigibilitaIVA>{chargeability}</EsigibilitaIVA>")
        + ("" if legal is None else f"<RiferimentoNormativo>{legal}</RiferimentoNormativo>")
        + "</DatiRiepilogo>"
    )


def payment(*details: str, conditions: str = "TP02") -> str:
    """A DatiPagamento (2.4) with the given DettaglioPagamento blocks."""
    return f"<DatiPagamento><CondizioniPagamento>{conditions}</CondizioniPagamento>{''.join(details)}</DatiPagamento>"


def detail(method: str = "MP05", amount: str = "122.00", *, before: str = "", middle: str = "", after: str = "") -> str:
    """A DettaglioPagamento (2.4.2): ``before`` precedes ModalitaPagamento, ``middle`` ImportoPagamento, ``after``
    follows it."""
    return (
        f"<DettaglioPagamento>{before}<ModalitaPagamento>{method}</ModalitaPagamento>{middle}"
        f"<ImportoPagamento>{amount}</ImportoPagamento>{after}</DettaglioPagamento>"
    )


def body(
    *,
    tipo: str = "TD01",
    number: str = "FT-1",
    document_extra: str = "",
    general: str = "",
    lines: str | None = None,
    summaries: str | None = None,
    after: str = "",
) -> str:
    """A FatturaElettronicaBody: by default one 22 % line of 100.00. ``document_extra`` follows Numero, ``general``
    follows DatiGeneraliDocumento and ``after`` follows DatiBeniServizi (DatiPagamento, Allegati)."""
    return (
        "<FatturaElettronicaBody><DatiGenerali><DatiGeneraliDocumento>"
        f"<TipoDocumento>{tipo}</TipoDocumento><Divisa>EUR</Divisa><Data>2026-01-15</Data>"
        f"<Numero>{number}</Numero>{document_extra}</DatiGeneraliDocumento>{general}</DatiGenerali>"
        f"<DatiBeniServizi>{line() if lines is None else lines}{summary() if summaries is None else summaries}"
        f"</DatiBeniServizi>{after}</FatturaElettronicaBody>"
    )


def document(
    *bodies: str,
    version: str = "FPR12",
    seller_ids: str = SELLER_VAT,
    seller_name: str = COMPANY,
    seller_after: str = "",
    seller_address: str = ADDRESS,
    regime: str = "RF01",
    buyer_ids: str = BUYER_CF,
    buyer_name: str = COMPANY,
    header_after: str = "",
) -> bytes:
    """A FatturaPA document; ``seller_after`` follows the seller's Sede, ``header_after`` the CessionarioCommittente."""
    return (
        f'<p:FatturaElettronica xmlns:p="{_xml.FATTURAPA}" versione="{version}"><FatturaElettronicaHeader>'
        f"{TRANSMISSION.replace('FPR12', version)}"
        f"<CedentePrestatore><DatiAnagrafici>{seller_ids}{seller_name}<RegimeFiscale>{regime}</RegimeFiscale>"
        f"</DatiAnagrafici>{seller_address}{seller_after}</CedentePrestatore>"
        f"<CessionarioCommittente><DatiAnagrafici>{buyer_ids}{buyer_name}</DatiAnagrafici>{ADDRESS}"
        f"</CessionarioCommittente>{header_after}</FatturaElettronicaHeader>"
        + "".join(bodies or (body(),))
        + "</p:FatturaElettronica>"
    ).encode()


FULL: t.Final = document(
    body(
        document_extra=(
            "<ImportoTotaleDocumento>119.80</ImportoTotaleDocumento><Arrotondamento>0.00</Arrotondamento>"
            "<Causale>First note</Causale><Causale>Second note</Causale>"
        ),
        general=(
            "<DatiOrdineAcquisto><IdDocumento>PO-1</IdDocumento><CodiceCommessaConvenzione>BR-1"
            "</CodiceCommessaConvenzione></DatiOrdineAcquisto>"
            "<DatiContratto><IdDocumento>C-1</IdDocumento><CodiceCUP>CUP-1</CodiceCUP><CodiceCIG>CIG-1</CodiceCIG>"
            "</DatiContratto>"
            "<DatiConvenzione><IdDocumento>CV-1</IdDocumento></DatiConvenzione>"
            "<DatiRicezione><IdDocumento>R-1</IdDocumento></DatiRicezione>"
            "<DatiFattureCollegate><IdDocumento>FT-0</IdDocumento><Data>2025-12-01</Data></DatiFattureCollegate>"
            "<DatiDDT><NumeroDDT>DDT-1</NumeroDDT><DataDDT>2026-01-10</DataDDT></DatiDDT>"
            "<DatiTrasporto><IndirizzoResa><Indirizzo>Via Consegna</Indirizzo><NumeroCivico>2</NumeroCivico>"
            "<CAP>20100</CAP><Comune>Milano</Comune><Provincia>MI</Provincia><Nazione>IT</Nazione></IndirizzoResa>"
            "<DataOraConsegna>2026-01-12T10:00:00</DataOraConsegna></DatiTrasporto>"
        ),
        lines=line(
            1,
            total="90.00",
            before=(
                "<TipoCessionePrestazione>AC</TipoCessionePrestazione><CodiceArticolo><CodiceTipo>Identificativo del "
                "prodotto</CodiceTipo><CodiceValore>SKU-1</CodiceValore></CodiceArticolo>"
            ),
            middle="<UnitaMisura>C62</UnitaMisura><DataInizioPeriodo>2026-01-01</DataInizioPeriodo>"
            "<DataFinePeriodo>2026-01-31</DataFinePeriodo>",
            adjustments="<ScontoMaggiorazione><Tipo>SC</Tipo><Importo>5.00</Importo></ScontoMaggiorazione>",
            after="<RiferimentoAmministrazione>ACC-1</RiferimentoAmministrazione><AltriDatiGestionali><TipoDato>CUSTOM"
            "</TipoDato><RiferimentoTesto>Row text</RiferimentoTesto></AltriDatiGestionali>",
        )
        + line(2, quantity="1.00", unit="10.00", total="10.00", rate="0.00", natura="N2.2"),
        summaries=summary("22.00", "90.00", "19.80", chargeability="I")
        + summary("0.00", "10.00", "0.00", natura="N2.2", legal="Art. 7 DPR 633/72"),
        after=payment(
            detail(
                "MP05",
                "119.80",
                before="<Beneficiario>Payee Srl</Beneficiario>",
                middle="<GiorniTerminiPagamento>30</GiorniTerminiPagamento>"
                "<DataScadenzaPagamento>2026-02-15</DataScadenzaPagamento>",
                after="<CognomeQuietanzante>Rossi</CognomeQuietanzante><NomeQuietanzante>Anna</NomeQuietanzante>"
                "<CFQuietanzante>BBBBBB00B00B000B</CFQuietanzante>"
                "<IBAN>DE02120300000000202051</IBAN><BIC>BYLADEM1001</BIC><CodicePagamento>RF-1</CodicePagamento>",
            )
        ),
    ),
    seller_ids=SELLER_VAT + "<CodiceFiscale>00000000001</CodiceFiscale>",
    seller_name="<Anagrafica><Denominazione>Example Srl</Denominazione><CodEORI>IT00000000001</CodEORI></Anagrafica>",
    seller_after="<Contatti><Telefono>0600000000</Telefono><Email>info@example.com</Email></Contatti>"
    "<RiferimentoAmministrazione>ADM-1</RiferimentoAmministrazione>",
    regime="RF19",
    buyer_ids=BUYER_VAT + BUYER_CF,
    buyer_name="<Anagrafica><Denominazione>Buyer Spa</Denominazione><CodEORI>IT00000000002</CodEORI></Anagrafica>",
    header_after="<SoggettoEmittente>CC</SoggettoEmittente>",
)
"""A document that uses every row the reader maps (see ``tests/syntax/test_fatturapa_read.py``)."""

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
    (
        "a summary no line has (a social-security fund)",
        document(
            body(
                document_extra="<DatiCassaPrevidenziale><TipoCassa>TC22</TipoCassa><AlCassa>4.00</AlCassa>"
                "<ImportoContributoCassa>4.00</ImportoContributoCassa><AliquotaIVA>10.00</AliquotaIVA>"
                "</DatiCassaPrevidenziale>",
                summaries=summary() + summary("10.00", "4.00", "0.40"),
            )
        ),
        (f"{GENERAL}/DatiGeneraliDocumento/DatiCassaPrevidenziale", f"{SUMMARY}[2]"),
    ),
    (
        "a Natura summary no line has, in a category lines have",
        document(
            body(
                lines=line(rate="0.00", natura="N2.2"),
                summaries=summary("0.00", "100.00", "0.00", natura="N2.2")
                + summary("0.00", "0.00", "0.00", natura="N4", legal="Art. 10"),
            )
        ),
        (f"{SUMMARY}[2]/Natura", f"{SUMMARY}[2]/RiferimentoNormativo"),
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
        "Natura is required for a line with AliquotaIVA 0",
    ),
    (
        "split and ordinary at one rate",
        document(body(summaries=summary(chargeability="S") + summary())),
        "both a split-payment",
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


_INTRA_EU: t.Final = frozenset({"N3.2", "N3.6", "N7"})  # category K (App. 5.1)
_FR_BUYER: t.Final = "<IdFiscaleIVA><IdPaese>FR</IdPaese><IdCodice>00000000000</IdCodice></IdFiscaleIVA>"
_DELIVERY: t.Final = (
    "<DatiTrasporto><IndirizzoResa><Indirizzo>Rue Exemple 1</Indirizzo><CAP>75001</CAP><Comune>Paris</Comune>"
    "<Nazione>FR</Nazione></IndirizzoResa><DataOraConsegna>2026-01-12T10:00:00</DataOraConsegna></DatiTrasporto>"
)


def natura_document(code: str) -> bytes:
    """One 0 % line and its summary with ``Natura`` ``code``; for category K, an EU buyer with a VAT id and the
    delivery data BR-IC-02, BR-IC-11 and BR-IC-12 require."""
    intra = code in _INTRA_EU
    return document(
        body(
            general=_DELIVERY if intra else "",
            lines=line(rate="0.00", natura=code),
            summaries=summary("0.00", "100.00", "0.00", natura=code),
        ),
        buyer_ids=_FR_BUYER if intra else BUYER_CF,
    )


def adjusted_document(adjustment: str, total: str) -> bytes:
    """One line with a single ScontoMaggiorazione made of ``adjustment`` and PrezzoTotale ``total``."""
    sm = f"<ScontoMaggiorazione>{adjustment}</ScontoMaggiorazione>"
    return document(body(lines=line(total=total, adjustments=sm)))


def other_data_document(reference: str) -> bytes:
    """One line with an AltriDatiGestionali ``KIND`` carrying ``reference``."""
    return document(
        body(lines=line(after=f"<AltriDatiGestionali><TipoDato>KIND</TipoDato>{reference}</AltriDatiGestionali>"))
    )


def payment_document(method: str) -> bytes:
    """A DatiPagamento with one DettaglioPagamento of ModalitaPagamento ``method``."""
    return document(body(after=payment(detail(method))))


_DE_ADDRESS: t.Final = (
    "<Sede><Indirizzo>Strasse 1</Indirizzo><CAP>10115</CAP><Comune>Berlin</Comune><Nazione>DE</Nazione></Sede>"
)

VARIANTS: t.Final[dict[str, bytes]] = {
    "split payment": document(body(summaries=summary(chargeability="S"))),
    "person": document(buyer_name=PERSON),
    "foreign seller": document(
        body(tipo="TD17"), seller_ids=SELLER_VAT.replace(">IT<", ">DE<"), seller_address=_DE_ADDRESS
    ),
    "no quantity": document(body(lines=line(quantity=None, unit="100.00"))),
    "unit HUR": document(body(lines=line(middle="<UnitaMisura>HUR</UnitaMisura>"))),
    "article CARB": document(
        body(
            lines=line(
                before="<CodiceArticolo><CodiceTipo>CARB</CodiceTipo><CodiceValore>27101249</CodiceValore>"
                "</CodiceArticolo>"
            )
        )
    ),
    "credit note": document(body(tipo="TD04"), buyer_ids=BUYER_VAT),
    "FPA12": document(
        version="FPA12",
        seller_after="<IscrizioneREA><Ufficio>RM</Ufficio><NumeroREA>1</NumeroREA><StatoLiquidazione>LN"
        "</StatoLiquidazione></IscrizioneREA>",
        header_after="<TerzoIntermediarioOSoggettoEmittente><DatiAnagrafici><Anagrafica><Denominazione>Third"
        "</Denominazione></Anagrafica></DatiAnagrafici></TerzoIntermediarioOSoggettoEmittente>",
    ),
    "D vs I split": document(
        body(lines=line() + line(2), summaries=summary(chargeability="D") + summary(chargeability="I"))
    ),
    "same summary twice": document(body(lines=line() + line(2), summaries=summary(chargeability="I") * 2)),
    "lotto": document(body(number="FT-1"), body(number="FT-2", tipo="TD04")),
    "lotto with Art73": document(body(), body(document_extra="<Art73>SI</Art73>")),
    "instalments": document(body(after=payment(detail(amount="61.00"), detail(amount="61.00"), conditions="TP01"))),
}
"""Single-purpose documents of the reader tests, by name."""

VARIANTS.update(
    {
        "payee is the seller": document(body(after=payment(detail(before="<Beneficiario>Example Srl</Beneficiario>")))),
        "MP05 without IBAN": payment_document("MP05"),
        "two Natura in category E": document(
            body(
                lines=line(rate="0.00", natura="N4") + line(2, rate="0.00", natura="N2.2"),
                summaries=summary("0.00", "100.00", "0.00", natura="N4", legal="Art. 10")
                + summary("0.00", "100.00", "0.00", natura="N2.2"),
            )
        ),
        "negative unit price": document(
            body(
                lines=line() + line(2, quantity="1.00", unit="-10.00", total="-10.00", description="Discount"),
                summaries=summary("22.00", "90.00", "19.80"),
                document_extra="<ImportoTotaleDocumento>109.80</ImportoTotaleDocumento>",
            )
        ),
        "negative unit price with an adjustment": document(
            body(
                lines=line(
                    quantity="1.00",
                    unit="-10.00",
                    total="-11.00",
                    adjustments="<ScontoMaggiorazione><Tipo>SC</Tipo><Importo>1.00</Importo></ScontoMaggiorazione>",
                )
                + line(2),
                summaries=summary("22.00", "89.00", "19.58"),
            )
        ),
        "deferred VAT": document(body(summaries=summary(chargeability="D"))),
        "inconsistent summary": document(body(summaries=summary("22.00", "102.00", "22.44"))),
        "inconsistent totals": document(
            body(
                document_extra="<ImportoTotaleDocumento>100.00</ImportoTotaleDocumento>",
                after=payment(detail(amount="100.00")),
            )
        ),
        "stamp duty": document(
            body(
                document_extra="<DatiBollo><BolloVirtuale>SI</BolloVirtuale><ImportoBollo>0.00</ImportoBollo></DatiBollo>"
            )
        ),
        "stamp duty on a credit note": document(
            body(
                tipo="TD04",
                document_extra="<DatiBollo><BolloVirtuale>SI</BolloVirtuale><ImportoBollo>2.00</ImportoBollo></DatiBollo>",
            )
        ),
        "line-level receipt": document(
            body(
                general="<DatiRicezione><RiferimentoNumeroLinea>1</RiferimentoNumeroLinea><IdDocumento>R-1</IdDocumento>"
                "</DatiRicezione>"
            )
        ),
    }
)
