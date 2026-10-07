"""Synthetic FatturaPA 1.2.3 documents for the reader tests (#120): fake parties and placeholder identifiers only.

:func:`document` renders a whole document in the XSD 1.2.3 element order from parts, so each variant stays
schema-valid; ``tests/conformance/test_fatturapa_read_official.py`` validates every document of :data:`DOCUMENTS`
against the pinned XSD. :data:`FULL` maps every row the reader maps at least once.
"""

import typing as t
from decimal import Decimal

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


def cassa_block(rate: str = "22.00", *, natura: str = "", withholding: bool = False) -> str:
    """A DatiCassaPrevidenziale (2.1.1.7) of 4 % (TC04) on 100.00, in XSD order."""
    return (
        "<DatiCassaPrevidenziale><TipoCassa>TC04</TipoCassa><AlCassa>4.00</AlCassa>"
        "<ImportoContributoCassa>4.00</ImportoContributoCassa><ImponibileCassa>100.00</ImponibileCassa>"
        f"<AliquotaIVA>{rate}</AliquotaIVA>"
        + ("<Ritenuta>SI</Ritenuta>" if withholding else "")
        + (f"<Natura>{natura}</Natura>" if natura else "")
        + "</DatiCassaPrevidenziale>"
    )


_WITHHOLDING: t.Final = (
    "<DatiRitenuta><TipoRitenuta>RT01</TipoRitenuta><ImportoRitenuta>20.00</ImportoRitenuta>"
    "<AliquotaRitenuta>20.00</AliquotaRitenuta><CausalePagamento>A</CausalePagamento></DatiRitenuta>"
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
    """One 22 % line with one ScontoMaggiorazione made of ``adjustment``, PrezzoTotale ``total``, and its summary."""
    sm = f"<ScontoMaggiorazione>{adjustment}</ScontoMaggiorazione>"
    tax = format(Decimal(total) * Decimal("0.22"), ".2f")
    return document(body(lines=line(total=total, adjustments=sm), summaries=summary("22.00", total, tax)))


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

VARIANTS.update(
    {
        # A professional's invoice: fee 100.00, 4 % fund contribution, 22 % VAT on 104.00 (App. 4.1 rows 2.1.1.7.x).
        "professional with a fund": document(
            body(
                document_extra=cassa_block() + "<ImportoTotaleDocumento>126.88</ImportoTotaleDocumento>",
                summaries=summary("22.00", "104.00", "22.88"),
                after=payment(detail(amount="126.88", after="<IBAN>DE02120300000000202051</IBAN>")),
            )
        ),
        "fund at another rate with Natura": document(
            body(
                document_extra=cassa_block("0.00", natura="N4"),
                summaries=summary() + summary("0.00", "4.00", "0.00", natura="N4", legal="Art. 10"),
            )
        ),
        # The same with 20 % withholding (not mapped): the declared amount due, net of it, is kept (BR-CO-16).
        "professional with a fund and withholding": document(
            body(
                document_extra=_WITHHOLDING
                + cassa_block(withholding=True)
                + "<ImportoTotaleDocumento>126.88</ImportoTotaleDocumento>",
                lines=line().replace("</AliquotaIVA>", "</AliquotaIVA><Ritenuta>SI</Ritenuta>"),
                summaries=summary("22.00", "104.00", "22.88"),
                after=payment(detail(amount="106.88", after="<IBAN>DE02120300000000202051</IBAN>")),
            )
        ),
    }
)
