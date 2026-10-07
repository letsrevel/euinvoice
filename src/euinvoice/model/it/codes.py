"""FatturaPA code lists used by ``Invoice.it`` (D3 as amended, ADR 0001, #118).

Each enum equals the ``xs:enumeration`` list of its ``xs:simpleType`` in the pinned FatturaPA XSD 1.2.3
(``Schema_VFPR12_v1.2.3.xsd``, source ``fatturapa-xsd``), in the same order; ``tests/conformance/test_it_codes_xsd.py``
checks this against the fetched file. A member is named after its code (``.`` becomes ``_``, so ``N2.1`` is
``N2_1``) and its docstring starts with the XSD's ``xs:documentation`` text, verbatim (typographic apostrophes
included). Naming members after the codes keeps
them unambiguous: the official meaning is the Italian text, and a translation would be ours.

The enums list every code the XSD accepts, so a reader can represent any FPR12 document. Which codes the SdI still
accepts, and which ones the v1 writer emits (TD01, TD04, TD24, TD17), are checked elsewhere (#119, #121).
"""

import enum

__all__ = [
    "CondizioniPagamento",
    "EsigibilitaIVA",
    "ModalitaPagamento",
    "Natura",
    "RegimeFiscale",
    "SoggettoEmittente",
    "TipoCessionePrestazione",
    "TipoDocumento",
]


class TipoDocumento(enum.StrEnum):
    """2.1.1.1 ``<TipoDocumento>``, XSD ``TipoDocumentoType``.

    Several codes map to one invoice type code BT-3 (Regole tecniche fatture europee v2.6, App. 5.4: TD01, TD06,
    TD16..TD29 all map to 380), which is why the code lives in the extension.
    """

    TD01 = "TD01"
    """Fattura"""
    TD02 = "TD02"
    """Acconto / anticipo su fattura"""
    TD03 = "TD03"
    """Acconto / anticipo su parcella"""
    TD04 = "TD04"
    """Nota di credito"""
    TD05 = "TD05"
    """Nota di debito"""
    TD06 = "TD06"
    """Parcella"""
    TD16 = "TD16"
    """Integrazione fattura reverse charge interno"""
    TD17 = "TD17"
    """Integrazione/autofattura per acquisto servizi dall'estero"""
    TD18 = "TD18"
    """Integrazione per acquisto di beni intracomunitari"""
    TD19 = "TD19"
    """Integrazione/autofattura per acquisto di beni ex art.17 c.2 DPR 633/72"""
    TD20 = "TD20"
    """Autofattura per regolarizzazione e integrazione delle fatture (ex art. 6 c.9-bis d.lgs. 471/97 o art.46 c.5
    D.L. 331/93)"""
    TD21 = "TD21"
    """Autofattura per splafonamento"""
    TD22 = "TD22"
    """Estrazione benida Deposito IVA"""
    TD23 = "TD23"
    """Estrazione beni da Deposito IVA con versamento dell'IVA"""
    TD24 = "TD24"
    """Fattura differita di cui all'art.21, comma 4, terzo periodo lett. a) DPR 633/72"""
    TD25 = "TD25"
    """Fattura differita di cui all'art.21, comma 4, terzo periodo lett. b) DPR 633/72"""
    TD26 = "TD26"
    """Cessione di beni ammortizzabili e per passaggi interni (ex art.36 DPR 633/72)"""
    TD27 = "TD27"
    """Fattura per autoconsumo o per cessioni gratuite senza rivalsa"""
    TD28 = "TD28"
    """Acquisti da San Marino con IVA (fattura cartacea)"""
    TD29 = "TD29"
    """Comunicazione per omessa o irregolare fatturazione da parte del cedente/prestatore italiano (art. 6, comma 8,
    D.Lgs. 471/97)"""


class RegimeFiscale(enum.StrEnum):
    """1.2.1.8 ``<RegimeFiscale>`` of the seller (cedente/prestatore), XSD ``RegimeFiscaleType``.

    There is no RF03: XSD 1.2.3 goes from RF02 to RF04 (as does App. 5.5 of the Regole tecniche v2.6).
    """

    RF01 = "RF01"
    """Regime ordinario"""
    RF02 = "RF02"
    """Regime dei contribuenti minimi (art. 1,c.96-117, L. 244/2007)"""
    RF04 = "RF04"
    """Agricoltura e attività connesse e pesca (artt. 34 e 34-bis, D.P.R. 633/1972)"""
    RF05 = "RF05"
    """Vendita sali e tabacchi (art. 74, c.1, D.P.R. 633/1972)"""
    RF06 = "RF06"
    """Commercio dei fiammiferi (art. 74, c.1, D.P.R. 633/1972)"""
    RF07 = "RF07"
    """Editoria (art. 74, c.1, D.P.R. 633/1972)"""
    RF08 = "RF08"
    """Gestione di servizi di telefonia pubblica (art. 74, c.1, D.P.R. 633/1972)"""
    RF09 = "RF09"
    """Rivendita di documenti di trasporto pubblico e di sosta (art. 74, c.1, D.P.R. 633/1972)"""
    RF10 = "RF10"
    """Intrattenimenti, giochi e altre attività di cui alla tariffa allegata al D.P.R. 640/72 (art. 74, c.6, D.P.R.
    633/1972)"""
    RF11 = "RF11"
    """Agenzie di viaggi e turismo (art. 74-ter, D.P.R. 633/1972)"""
    RF12 = "RF12"
    """Agriturismo (art. 5, c.2, L. 413/1991)"""
    RF13 = "RF13"
    """Vendite a domicilio (art. 25-bis, c.6, D.P.R. 600/1973)"""
    RF14 = "RF14"
    """Rivendita di beni usati, di oggetti d’arte, d’antiquariato o da collezione (art. 36, D.L. 41/1995)"""  # ruff: ignore[ambiguous-unicode-character-string] - verbatim XSD
    RF15 = "RF15"
    """Agenzie di vendite all’asta di oggetti d’arte, antiquariato o da collezione (art. 40-bis, D.L.
    41/1995)"""  # ruff: ignore[ambiguous-unicode-character-string] - verbatim XSD
    RF16 = "RF16"
    """IVA per cassa P.A. (art. 6, c.5, D.P.R. 633/1972)"""
    RF17 = "RF17"
    """IVA per cassa (art. 32-bis, D.L. 83/2012)"""
    RF18 = "RF18"
    """Altro"""
    RF19 = "RF19"
    """Regime forfettario"""
    RF20 = "RF20"
    """Regime transfrontaliero di Franchigia IVA (Direttiva UE 2020/285)"""


class SoggettoEmittente(enum.StrEnum):
    """1.6 ``<SoggettoEmittente>``, XSD ``SoggettoEmittenteType``.

    "Da valorizzare in tutti i casi in cui la fattura è emessa da un soggetto diverso dal cedente/prestatore"
    (Rappresentazione tabellare 1.9.1, row 1.6), e.g. by the buyer for TD17.
    """

    CC = "CC"
    """Cessionario / Committente"""
    TZ = "TZ"
    """Terzo"""


class Natura(enum.StrEnum):
    """2.2.1.14 / 2.2.2.2 ``<Natura>``, XSD ``NaturaType``: why a line or summary carries no VAT.

    The generic codes ``N2``, ``N3`` and ``N6`` are still in XSD 1.2.3, but the SdI refuses them in ordinary
    invoices issued from 1 January 2021 (check 00445, Allegato A 1.9.1, Appendix 1: "non è più ammesso il valore
    generico N2, N3 o N6 come codice natura dell'operazione"). They are kept so that older documents can be read;
    the check belongs to the SdI checks (#121).
    """

    N1 = "N1"
    """Escluse ex. art. 15 del D.P.R. 633/1972"""
    N2 = "N2"
    """Non soggette (refused by SdI check 00445 since 2021-01-01)"""
    N2_1 = "N2.1"
    """Non soggette ad IVA ai sensi degli artt. da 7 a 7-septies del DPR 633/72"""
    N2_2 = "N2.2"
    """Non soggette - altri casi"""
    N3 = "N3"
    """Non imponibili (refused by SdI check 00445 since 2021-01-01)"""
    N3_1 = "N3.1"
    """Non Imponibili - esportazioni"""
    N3_2 = "N3.2"
    """Non Imponibili - cessioni intracomunitarie"""
    N3_3 = "N3.3"
    """Non Imponibili - cessioni verso San Marino"""
    N3_4 = "N3.4"
    """Non Imponibili - operazioni assimilate alle cessioni all'esportazione"""
    N3_5 = "N3.5"
    """Non Imponibili - a seguito di dichiarazioni d'intento"""
    N3_6 = "N3.6"
    """Non Imponibili - altre operazioni che non concorrono alla formazione del plafond"""
    N4 = "N4"
    """Esenti"""
    N5 = "N5"
    """Regime del margine/IVA non esposta in fattura"""
    N6 = "N6"
    """Inversione contabile (per le operazioni in reverse charge ovvero nei casi di autofatturazione per acquisti
    extra UE di servizi ovvero per importazioni di beni nei soli casi previsti) (refused by SdI check 00445 since
    2021-01-01)"""
    N6_1 = "N6.1"
    """Inversione contabile - cessione di rottami e altri materiali di recupero"""
    N6_2 = "N6.2"
    """Inversione contabile - cessione di oro e argento ai sensi della legge 7/2000 nonché di oreficeria usata ad
    OPO"""
    N6_3 = "N6.3"
    """Inversione contabile - subappalto nel settore edile"""
    N6_4 = "N6.4"
    """Inversione contabile - cessione di fabbricati"""
    N6_5 = "N6.5"
    """Inversione contabile - cessione di telefoni cellulari"""
    N6_6 = "N6.6"
    """Inversione contabile - cessione di prodotti elettronici"""
    N6_7 = "N6.7"
    """Inversione contabile - prestazioni comparto edile e settori connessi"""
    N6_8 = "N6.8"
    """Inversione contabile - operazioni settore energetico"""
    N6_9 = "N6.9"
    """Inversione contabile - altri casi"""
    N7 = "N7"
    """IVA assolta in altro stato UE (prestazione di servizi di telecomunicazioni, tele-radiodiffusione ed
    elettronici ex art. 7-octies lett. a, b, art. 74-sexies DPR 633/72)"""


class TipoCessionePrestazione(enum.StrEnum):
    """2.2.1.2 ``<TipoCessionePrestazione>``, XSD ``TipoCessionePrestazioneType``.

    "Da valorizzare nei soli casi in cui si voglia utilizzare la riga per rappresentare uno sconto/premio/abbuono
    ovvero una spesa accessoria" (Rappresentazione tabellare 1.9.1, row 2.2.1.2).
    """

    SC = "SC"
    """Sconto"""
    PR = "PR"
    """Premio"""
    AB = "AB"
    """Abbuono"""
    AC = "AC"
    """Spesa accessoria"""


class EsigibilitaIVA(enum.StrEnum):
    """2.2.2.7 ``<EsigibilitaIVA>``, XSD ``EsigibilitaIVAType``: when the VAT of a summary becomes due."""

    D = "D"
    """esigibilità differita"""
    I = "I"  # ruff: ignore[ambiguous-variable-name] - the XSD code, see the module docstring
    """esigibilità immediata"""
    S = "S"
    """scissione dei pagamenti"""


class CondizioniPagamento(enum.StrEnum):
    """2.4.1 ``<CondizioniPagamento>``, XSD ``CondizioniPagamentoType``."""

    TP01 = "TP01"
    """pagamento a rate"""
    TP02 = "TP02"
    """pagamento completo"""
    TP03 = "TP03"
    """anticipo"""


class ModalitaPagamento(enum.StrEnum):
    """2.4.2.2 ``<ModalitaPagamento>``, XSD ``ModalitaPagamentoType``.

    App. 5.6 of the Regole tecniche v2.6 maps the payment means code BT-81 to these codes many-to-one, so a code
    read from FatturaPA cannot be recovered from BT-81 alone.
    """

    MP01 = "MP01"
    """contanti"""
    MP02 = "MP02"
    """assegno"""
    MP03 = "MP03"
    """assegno circolare"""
    MP04 = "MP04"
    """contanti presso Tesoreria"""
    MP05 = "MP05"
    """bonifico"""
    MP06 = "MP06"
    """vaglia cambiario"""
    MP07 = "MP07"
    """bollettino bancario"""
    MP08 = "MP08"
    """carta di pagamento"""
    MP09 = "MP09"
    """RID"""
    MP10 = "MP10"
    """RID utenze"""
    MP11 = "MP11"
    """RID veloce"""
    MP12 = "MP12"
    """RIBA"""
    MP13 = "MP13"
    """MAV"""
    MP14 = "MP14"
    """quietanza erario"""
    MP15 = "MP15"
    """giroconto su conti di contabilità speciale"""
    MP16 = "MP16"
    """domiciliazione bancaria"""
    MP17 = "MP17"
    """domiciliazione postale"""
    MP18 = "MP18"
    """bollettino di c/c postale"""
    MP19 = "MP19"
    """SEPA Direct Debit"""
    MP20 = "MP20"
    """SEPA Direct Debit CORE"""
    MP21 = "MP21"
    """SEPA Direct Debit B2B"""
    MP22 = "MP22"
    """Trattenuta su somme già riscosse"""
    MP23 = "MP23"
    """PagoPA"""
