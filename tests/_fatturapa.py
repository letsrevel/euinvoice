"""Synthetic FatturaPA 1.2.3 documents for the SdI check tests (#121): fake parties and placeholder identifiers only.

:class:`Doc` renders a document in the XSD 1.2.3 element order, so every document here is schema-valid
(``tests/conformance/test_sdi_official.py`` proves it). :data:`CASES` holds, per SdI code, documents that pass the
check and one that fails it, with the codes the failing one is expected to raise.
"""

import dataclasses
import typing as t

from euinvoice import _xml

SELLER_IT: t.Final = "<IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>00000000001</IdCodice></IdFiscaleIVA>"
SELLER_DE: t.Final = "<IdFiscaleIVA><IdPaese>DE</IdPaese><IdCodice>000000000</IdCodice></IdFiscaleIVA>"
BUYER_CF: t.Final = "<CodiceFiscale>AAAAAA00A00A000A</CodiceFiscale>"
BUYER_IT: t.Final = "<IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>00000000002</IdCodice></IdFiscaleIVA>"
BUYER_FR: t.Final = "<IdFiscaleIVA><IdPaese>FR</IdPaese><IdCodice>00000000000</IdCodice></IdFiscaleIVA>"


def line(
    number: int = 1,
    *,
    quantity: str | None = "2.00",
    unit: str = "50.00",
    total: str = "100.00",
    rate: str = "22.00",
    natura: str | None = None,
    withholding: bool = False,
    adjustments: str = "",
) -> str:
    """A DettaglioLinee (2.2.1) in XSD order."""
    return (
        f"<DettaglioLinee><NumeroLinea>{number}</NumeroLinea><Descrizione>Ticket</Descrizione>"
        + ("" if quantity is None else f"<Quantita>{quantity}</Quantita>")
        + f"<PrezzoUnitario>{unit}</PrezzoUnitario>{adjustments}<PrezzoTotale>{total}</PrezzoTotale>"
        + f"<AliquotaIVA>{rate}</AliquotaIVA>"
        + ("<Ritenuta>SI</Ritenuta>" if withholding else "")
        + ("" if natura is None else f"<Natura>{natura}</Natura>")
        + "</DettaglioLinee>"
    )


def summary(
    rate: str = "22.00",
    taxable: str = "100.00",
    tax: str = "22.00",
    *,
    natura: str | None = None,
    rounding: str | None = None,
    chargeability: str | None = None,
) -> str:
    """A DatiRiepilogo (2.2.2) in XSD order."""
    return (
        f"<DatiRiepilogo><AliquotaIVA>{rate}</AliquotaIVA>"
        + ("" if natura is None else f"<Natura>{natura}</Natura>")
        + ("" if rounding is None else f"<Arrotondamento>{rounding}</Arrotondamento>")
        + f"<ImponibileImporto>{taxable}</ImponibileImporto><Imposta>{tax}</Imposta>"
        + ("" if chargeability is None else f"<EsigibilitaIVA>{chargeability}</EsigibilitaIVA>")
        + "</DatiRiepilogo>"
    )


def cassa(rate: str = "22.00", amount: str = "4.00", *, natura: str | None = None, withholding: bool = False) -> str:
    """A DatiCassaPrevidenziale (2.1.1.7) in XSD order."""
    return (
        f"<DatiCassaPrevidenziale><TipoCassa>TC22</TipoCassa><AlCassa>4.00</AlCassa>"
        f"<ImportoContributoCassa>{amount}</ImportoContributoCassa><AliquotaIVA>{rate}</AliquotaIVA>"
        + ("<Ritenuta>SI</Ritenuta>" if withholding else "")
        + ("" if natura is None else f"<Natura>{natura}</Natura>")
        + "</DatiCassaPrevidenziale>"
    )


def adjustment(kind: str = "SC", *, percent: str | None = None, amount: str | None = None) -> str:
    """A ScontoMaggiorazione (2.1.1.8 / 2.2.1.10)."""
    return (
        f"<ScontoMaggiorazione><Tipo>{kind}</Tipo>"
        + ("" if percent is None else f"<Percentuale>{percent}</Percentuale>")
        + ("" if amount is None else f"<Importo>{amount}</Importo>")
        + "</ScontoMaggiorazione>"
    )


WITHHOLDING: t.Final = (
    "<DatiRitenuta><TipoRitenuta>RT01</TipoRitenuta><ImportoRitenuta>20.00</ImportoRitenuta>"
    "<AliquotaRitenuta>20.00</AliquotaRitenuta><CausalePagamento>A</CausalePagamento></DatiRitenuta>"
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Body:
    """One FatturaElettronicaBody: by default a TD01 with one 22 % line of 100.00."""

    tipo: str = "TD01"
    date: str = "2026-01-15"
    number: str = "FT-1"
    withholding: str = ""
    cassa: str = ""
    adjustments: str = ""
    art73: bool = False
    linked: str = ""
    lines: str = dataclasses.field(default_factory=line)
    summaries: str = dataclasses.field(default_factory=summary)

    def xml(self) -> str:
        """The body in XSD order."""
        return (
            "<FatturaElettronicaBody><DatiGenerali><DatiGeneraliDocumento>"
            f"<TipoDocumento>{self.tipo}</TipoDocumento><Divisa>EUR</Divisa><Data>{self.date}</Data>"
            f"<Numero>{self.number}</Numero>{self.withholding}{self.cassa}{self.adjustments}"
            + ("<Art73>SI</Art73>" if self.art73 else "")
            + f"</DatiGeneraliDocumento>{self.linked}</DatiGenerali>"
            f"<DatiBeniServizi>{self.lines}{self.summaries}</DatiBeniServizi></FatturaElettronicaBody>"
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Doc:
    """A FatturaPA document: by default an FPR12 from an Italian seller to a consumer known by codice fiscale."""

    version: str = "FPR12"
    format: str = "FPR12"
    recipient: str = "0000000"
    seller: str = SELLER_IT
    seller_cf: str = ""
    buyer: str = BUYER_CF
    bodies: tuple[Body, ...] = (Body(),)

    def xml(self) -> bytes:
        """The serialized document."""
        party = "<Anagrafica><Denominazione>Example</Denominazione></Anagrafica>"
        address = (
            "<Sede><Indirizzo>Via Esempio 1</Indirizzo><CAP>00000</CAP><Comune>Roma</Comune>"
            "<Nazione>IT</Nazione></Sede>"
        )
        return (
            f'<p:FatturaElettronica xmlns:p="{_xml.FATTURAPA}" versione="{self.version}"><FatturaElettronicaHeader>'
            "<DatiTrasmissione><IdTrasmittente><IdPaese>IT</IdPaese><IdCodice>00000000001</IdCodice></IdTrasmittente>"
            f"<ProgressivoInvio>00001</ProgressivoInvio><FormatoTrasmissione>{self.format}</FormatoTrasmissione>"
            f"<CodiceDestinatario>{self.recipient}</CodiceDestinatario></DatiTrasmissione>"
            f"<CedentePrestatore><DatiAnagrafici>{self.seller}{self.seller_cf}{party}<RegimeFiscale>RF01</RegimeFiscale>"
            f"</DatiAnagrafici>{address}</CedentePrestatore>"
            f"<CessionarioCommittente><DatiAnagrafici>{self.buyer}{party}</DatiAnagrafici>{address}"
            "</CessionarioCommittente></FatturaElettronicaHeader>"
            + "".join(body.xml() for body in self.bodies)
            + "</p:FatturaElettronica>"
        ).encode()


def body(**changes: t.Any) -> tuple[Body, ...]:
    """A one-body tuple with ``changes`` applied to the default body."""
    return (dataclasses.replace(Body(), **changes),)


@dataclasses.dataclass(frozen=True)
class Case:
    """Documents that pass an SdI check, one that fails it and every code the failing one raises."""

    passing: tuple[Doc, ...]
    failing: Doc
    codes: frozenset[str]


def case(passing: Doc | tuple[Doc, ...], failing: Doc, *codes: str) -> Case:
    """A :class:`Case`; ``codes`` defaults to the case's own code, filled in by :data:`CASES`."""
    return Case(passing if isinstance(passing, tuple) else (passing,), failing, frozenset(codes))


_ZERO = summary("0.00", "100.00", "0.00", natura="N2.1")
_RAW: t.Final[dict[str, Case]] = {
    "00313": case(Doc(recipient="XXXXXXX", buyer=BUYER_FR), Doc(recipient="XXXXXXX"), "00313"),
    "00400": case(
        Doc(bodies=body(lines=line(rate="0.00", natura="N2.1"), summaries=_ZERO)),
        Doc(bodies=body(lines=line(rate="0.00"), summaries=_ZERO)),
    ),
    "00401": case(
        Doc(bodies=body(tipo="TD16", lines=line(natura="N6.1"), summaries=summary(natura="N6.1")), buyer=BUYER_IT),
        Doc(bodies=body(lines=line(natura="N6.1"), summaries=summary(natura="N6.1"))),
        "00401",
        "00430",
    ),
    "00409": case(
        (
            Doc(bodies=(Body(), Body(tipo="TD04"))),
            Doc(bodies=(Body(), Body(date="2027-01-15"))),
            Doc(bodies=(Body(art73=True), Body(date="2026-02-15", art73=True))),
        ),
        Doc(bodies=(Body(), Body(date="2026-03-01"))),
    ),
    "00411": case(
        Doc(bodies=body(withholding=WITHHOLDING, lines=line(withholding=True))),
        Doc(
            bodies=body(
                lines=line(withholding=True) + line(2, withholding=True), summaries=summary("22.00", "200.00", "44.00")
            )
        ),
    ),
    "00413": case(
        Doc(
            bodies=body(
                cassa=cassa("0.00", natura="N4"), summaries=summary() + summary("0.00", "4.00", "0.00", natura="N4")
            )
        ),
        Doc(bodies=body(cassa=cassa("0.00"), summaries=summary() + summary("0.00", "4.00", "0.00", natura="N4"))),
    ),
    "00414": case(
        Doc(bodies=body(cassa=cassa(), summaries=summary("22.00", "104.00", "22.88"))),
        Doc(bodies=body(cassa=cassa(natura="N4"), summaries=summary("22.00", "104.00", "22.88"))),
        "00414",
        "00444",
    ),
    "00415": case(
        Doc(
            bodies=body(
                withholding=WITHHOLDING, cassa=cassa(withholding=True), summaries=summary("22.00", "104.00", "22.88")
            )
        ),
        Doc(bodies=body(cassa=cassa(withholding=True), summaries=summary("22.00", "104.00", "22.88"))),
    ),
    "00417": case((Doc(), Doc(buyer=BUYER_IT)), Doc(buyer="")),
    "00418": case(
        Doc(
            bodies=body(
                linked="<DatiFattureCollegate><IdDocumento>FT-0</IdDocumento><Data>2026-01-15</Data></DatiFattureCollegate>"
            )
        ),
        Doc(
            bodies=body(
                linked="<DatiFattureCollegate><IdDocumento>FT-0</IdDocumento><Data>2026-01-16</Data></DatiFattureCollegate>"
            )
        ),
    ),
    "00419": case(
        Doc(
            bodies=body(lines=line() + line(2, rate="10.00"), summaries=summary() + summary("10.00", "100.00", "10.00"))
        ),
        Doc(bodies=body(lines=line() + line(2, rate="10.00"))),
        "00419",
        "00443",
    ),
    "00420": case(
        Doc(
            bodies=body(
                lines=line(rate="0.00", natura="N6.1"),
                summaries=summary("0.00", "100.00", "0.00", natura="N6.1", chargeability="I"),
            )
        ),
        Doc(
            bodies=body(
                lines=line(rate="0.00", natura="N6.1"),
                summaries=summary("0.00", "100.00", "0.00", natura="N6.1", chargeability="S"),
            )
        ),
    ),
    "00421": case(
        (
            Doc(bodies=body(summaries=summary(tax="22.01"))),
            # 0.25 * 22 / 100 = 0.055 rounds half up to 0.06, so 0.07 is within ±0.01; half-down 0.05 would reject it.
            Doc(
                bodies=body(
                    lines=line(quantity="1.00", unit="0.25", total="0.25"), summaries=summary("22.00", "0.25", "0.07")
                )
            ),
        ),
        Doc(bodies=body(summaries=summary(tax="22.02"))),
    ),
    "00422": case(
        (
            Doc(bodies=body(summaries=summary("22.00", "101.00", "22.22"))),
            Doc(bodies=body(summaries=summary("22.00", "102.50", "22.55", rounding="2.50"))),
            Doc(
                bodies=body(
                    lines=line(rate="0.00", natura="N2.1") + line(2, rate="0.00", natura="N4"),
                    summaries=_ZERO + summary("0.00", "100.00", "0.00", natura="N4"),
                )
            ),
        ),
        Doc(bodies=body(summaries=summary("22.00", "101.01", "22.22"))),
    ),
    "00423": case(
        (
            Doc(bodies=body(lines=line(total="100.01"))),
            Doc(
                bodies=body(
                    lines=line(total="90.00", adjustments=adjustment(amount="5.00")),
                    summaries=summary("22.00", "90.00", "19.80"),
                )
            ),
            Doc(
                bodies=body(
                    lines=line(total="90.00", adjustments=adjustment(percent="10.00")),
                    summaries=summary("22.00", "90.00", "19.80"),
                )
            ),
            Doc(
                bodies=body(
                    lines=line(total="110.00", adjustments=adjustment("MG", percent="10.00")),
                    summaries=summary("22.00", "110.00", "24.20"),
                )
            ),
            # Two percentages (cascade or sum) and a line without Quantita have no single reading: not checked.
            Doc(bodies=body(lines=line(total="100.00", adjustments=adjustment(percent="10.00") * 2))),
            Doc(bodies=body(lines=line(quantity=None, unit="50.00", total="100.00"))),
        ),
        Doc(bodies=body(lines=line(total="100.02"))),
    ),
    "00425": case(Doc(bodies=body(number="A/1")), Doc(bodies=body(number="FT-A"))),
    "00427": case(
        (Doc(recipient="ABC1234"), Doc(version="FPA12", format="FPA12", recipient="ABC123")),
        Doc(recipient="ABC123"),
    ),
    "00428": case(Doc(version="FPA12", format="FPA12", recipient="ABC123"), Doc(version="FPA12", recipient="ABC1234")),
    "00429": case(
        Doc(bodies=body(lines=line(rate="0.00", natura="N2.1"), summaries=_ZERO)),
        Doc(bodies=body(lines=line(rate="0.00", natura="N2.1"), summaries=summary("0.00", "100.00", "0.00"))),
        "00429",
        "00444",
    ),
    "00430": case(
        Doc(bodies=body(tipo="TD16", summaries=summary(natura="N6.1"), lines=line(natura="N6.1")), buyer=BUYER_IT),
        Doc(bodies=body(summaries=summary(natura="N2.1"))),
    ),
    "00437": case(Doc(bodies=body(adjustments=adjustment(amount="1.00"))), Doc(bodies=body(adjustments=adjustment()))),
    "00438": case(
        Doc(
            bodies=body(
                lines=line(total="90.00", adjustments=adjustment(amount="5.00")),
                summaries=summary("22.00", "90.00", "19.80"),
            )
        ),
        Doc(bodies=body(lines=line(adjustments=adjustment()))),
    ),
    "00443": case(
        Doc(bodies=body(cassa=cassa("10.00"), summaries=summary() + summary("10.00", "4.00", "0.40"))),
        Doc(bodies=body(cassa=cassa("10.00"))),
        "00419",
        "00443",
    ),
    "00444": case(
        Doc(
            bodies=body(
                lines=line(rate="0.00", natura="N2.2"), summaries=summary("0.00", "100.00", "0.00", natura="N2.2")
            )
        ),
        Doc(bodies=body(lines=line(rate="0.00", natura="N2.2"), summaries=_ZERO)),
    ),
    "00445": case(
        Doc(bodies=body(lines=line(rate="0.00", natura="N2.1"), summaries=_ZERO)),
        Doc(
            bodies=body(lines=line(rate="0.00", natura="N2"), summaries=summary("0.00", "100.00", "0.00", natura="N2"))
        ),
    ),
    "00471": case(
        (
            Doc(buyer=BUYER_IT),
            # A VAT group's members share its IdFiscaleIVA and differ by CodiceFiscale: not decided, not reported.
            Doc(
                buyer=SELLER_IT + "<CodiceFiscale>00000000003</CodiceFiscale>",
                seller_cf="<CodiceFiscale>00000000004</CodiceFiscale>",
            ),
        ),
        Doc(buyer=SELLER_IT),
    ),
    "00472": case(Doc(bodies=body(tipo="TD27"), buyer=SELLER_IT), Doc(bodies=body(tipo="TD27"), buyer=BUYER_IT)),
    "00473": case(
        (
            Doc(bodies=body(tipo="TD17"), seller=SELLER_DE, buyer=BUYER_IT),
            Doc(bodies=body(tipo="TD29"), buyer=BUYER_IT),
        ),
        Doc(bodies=body(tipo="TD17"), buyer=BUYER_IT),
    ),
    "00474": case(
        Doc(bodies=body(tipo="TD21"), buyer=SELLER_IT),
        Doc(
            bodies=body(
                tipo="TD21",
                lines=line(rate="0.00", natura="N3.5"),
                summaries=summary("0.00", "100.00", "0.00", natura="N3.5"),
            ),
            buyer=SELLER_IT,
        ),
    ),
    "00475": case(
        Doc(bodies=body(tipo="TD17"), seller=SELLER_DE, buyer=BUYER_IT),
        Doc(bodies=body(tipo="TD17"), seller=SELLER_DE),
    ),
    "00476": case(
        (Doc(seller=SELLER_DE, buyer=BUYER_IT), Doc(seller=SELLER_DE)), Doc(seller=SELLER_DE, buyer=BUYER_FR)
    ),
}

CASES: t.Final[dict[str, Case]] = {
    code: dataclasses.replace(c, codes=c.codes or frozenset({code})) for code, c in _RAW.items()
}
"""Per SdI code: documents that pass its check (and every other), one that fails it, and the codes that one raises."""
