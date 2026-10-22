"""Hypothesis strategies for the FatturaPA writer's v1 subset (#119): synthetic invoices the writer accepts."""

import datetime
import typing as t
from decimal import Decimal

from hypothesis import strategies as st

from _fatturapa_write import BUYER_VAT, buyer, it_draft, it_line, italian, seller
from euinvoice import calc
from euinvoice.model import (
    Buyer,
    BuyerPostalAddress,
    DocumentLevelAllowance,
    DocumentLevelCharge,
    Identifier,
    Invoice,
    InvoiceLineAllowance,
    InvoiceLineCharge,
    ItemInformation,
    LineDraft,
    PaymentInstructions,
    ProcessControl,
    Seller,
    SellerPostalAddress,
)
from euinvoice.model.amounts import quantize_amount
from euinvoice.model.it import (
    CondizioniPagamento,
    ItalianExtension,
    ItalianLineExtension,
    ItalianPayment,
    ModalitaPagamento,
    Natura,
    RegimeFiscale,
    SoggettoEmittente,
    TipoDocumento,
)
from euinvoice.syntax.fatturapa._write_codes import (
    INSTRUMENT_NOT_DEFINED,
    METHODS_WITHOUT_MEANS,
    PAYMENT_METHOD_OF_MEANS,
    VATEX_OF_NATURA,
)

# (VAT category, rate, Natura): App. 5.1 pairs and the Italian rates, the v1 subset the writer accepts. Split payment
# (B) gets a rate S never uses: B and S at one rate are refused (their lines could not be told apart on reading).
_VAT: t.Final[list[tuple[str, str, Natura | None]]] = [
    ("S", "22", None),
    ("S", "5", None),
    ("S", "4", None),
    ("B", "10", None),
    ("Z", "0", Natura.N1),
    ("E", "0", Natura.N2_1),
    ("E", "0", Natura.N2_2),
    ("E", "0", Natura.N4),
    ("E", "0", Natura.N5),
    ("G", "0", Natura.N3_1),
    ("G", "0", Natura.N3_4),
    ("K", "0", Natura.N3_2),
    ("K", "0", Natura.N7),
    ("AE", "0", Natura.N6_1),
    ("AE", "0", Natura.N6_9),
]
_QUANTITIES = st.decimals(min_value=Decimal("0.001"), max_value=Decimal(1000), places=3)
_PRICES = st.decimals(min_value=Decimal("0.0001"), max_value=Decimal(10000), places=4)


# Quantities whose reciprocal has at most 6 decimals, so any amount in cents divides into an Amount8DecimalType exactly
# (a line allowance or charge is written as an Importo per unit, #151).
_EXACT_QUANTITIES = st.sampled_from(
    [Decimal(q) for q in ("1", "2", "4", "5", "8", "10", "20", "25", "0.5", "2.5", "0.25")]
)
_REASONS = st.text(alphabet=st.characters(min_codepoint=33, max_codepoint=126), min_size=1, max_size=60)
_AMOUNTS = st.decimals(min_value=Decimal("0.01"), max_value=Decimal(50), places=2)


@st.composite
def _reasons(draw: st.DrawFn, codes: list[str]) -> tuple[str | None, str | None]:
    """A reason, a reason code or both (BR-42, BR-44: at least one)."""
    text = draw(st.none() | _REASONS)
    code = draw(st.none() | st.sampled_from(codes))
    return text or ("Motivo" if code is None else None), code


@st.composite
def _adjusted_line(draw: st.DrawFn, number: int, category: str, rate: str, nature: Natura | None) -> LineDraft:
    """A line with up to two allowances and two charges, each over a quantity that divides every amount exactly."""
    allowances = []
    for _ in range(draw(st.integers(min_value=0, max_value=2))):
        reason, code = draw(_reasons(["95", "100", "41"]))
        allowances.append(InvoiceLineAllowance(amount=draw(_AMOUNTS), reason=reason, reason_code=code))
    charges = []
    for _ in range(draw(st.integers(min_value=0, max_value=2))):
        reason, code = draw(_reasons(["AA", "FC"]))
        charges.append(InvoiceLineCharge(amount=draw(_AMOUNTS), reason=reason, reason_code=code))
    price = draw(st.decimals(min_value=Decimal(20), max_value=Decimal(10000), places=2))
    quantity = draw(_EXACT_QUANTITIES)
    return it_line(
        str(number),
        str(quantity),
        str(price),
        category,
        rate,
        nature=nature,
        allowances=tuple(allowances),
        charges=tuple(charges),
    )


@st.composite
def _lines(draw: st.DrawFn) -> tuple[LineDraft, ...]:
    count = draw(st.integers(min_value=1, max_value=5))
    lines = []
    for number in range(1, count + 1):
        category, rate, nature = draw(st.sampled_from(_VAT))
        if draw(st.booleans()):
            lines.append(draw(_adjusted_line(number, category, rate, nature)))
            continue
        # BT-154 joins BT-153 in Descrizione (#149); the reader gives the joined text as BT-153.
        item = ItemInformation(name="Biglietto evento", description=draw(st.none() | st.just("ingresso unico")))
        quantity, price = draw(_QUANTITIES), draw(_PRICES)
        changes: dict[str, t.Any] = {}
        exact = quantity * price  # PrezzoTotale: up to 7 decimals, Amount8DecimalType (#132 item 1)
        if exact != quantize_amount(exact) and draw(st.booleans()):
            changes["it"] = ItalianLineExtension(nature=nature, total_price=exact)
        lines.append(
            it_line(str(number), str(quantity), str(price), category, rate, nature=nature, item=item, **changes)
        )
    return tuple(lines)


@st.composite
def _payments(draw: st.DrawFn) -> tuple[ItalianPayment | None, PaymentInstructions | None]:
    """``Invoice.it.payment`` with any of the 23 ModalitaPagamento codes and a BT-81 consistent with it (#136).

    The 8 codes App. 5.6 has no row for take BT-81 "1" or none; the others take a BT-81 App. 5.6 maps to them or none.
    """
    method = draw(st.sampled_from(list(ModalitaPagamento)))
    means = [None, INSTRUMENT_NOT_DEFINED] if method in METHODS_WITHOUT_MEANS else [None]
    means += [code for code, mapped in PAYMENT_METHOD_OF_MEANS.items() if mapped is method]
    code = draw(st.sampled_from(means))
    payment = ItalianPayment(conditions=draw(st.sampled_from(list(CondizioniPagamento))), method=method)
    return payment, None if code is None else PaymentInstructions(payment_means_type_code=code)


# Foreign post codes: five digits are kept, anything else (and none) is written as CAP 00000 and reads back as none
# (AdE FAQ n. 63 / n. 74, #158).
_FOREIGN_POST_CODES: t.Final = st.sampled_from(["10115", "SW1A 1AA", "1011 AB", "123456", "A-1010", "00000", None])


def _foreign_seller(post_code: str | None) -> Seller:
    return Seller(
        name="Example Hosting GmbH",
        vat_identifier="DE000000000",
        postal_address=SellerPostalAddress(
            address_line_1="Beispielstrasse 1", city="Berlin", post_code=post_code, country_code="DE"
        ),
    )


# Nome / Cognome (String60LatinType): printable Latin-1 without spaces, so "Nome Cognome" splits back on read.
_NAME_PART = st.text(
    alphabet=st.characters(min_codepoint=0x21, max_codepoint=0xFF, exclude_categories=["Cc"]), min_size=1, max_size=30
)
_PERSON = st.none() | st.tuples(_NAME_PART, _NAME_PART)


@st.composite
def _buyers(draw: st.DrawFn) -> Buyer:
    """An Italian buyer (by codice fiscale or partita IVA) or one abroad, whose post code may need CAP 00000."""
    abroad = BuyerPostalAddress(
        address_line_1="Rue Exemple 1", city="Paris", post_code=draw(_FOREIGN_POST_CODES), country_code="FR"
    )
    return draw(
        st.sampled_from(
            [
                buyer(),
                buyer(vat_identifier=BUYER_VAT, legal_registration_identifier=None),
                buyer(vat_identifier=BUYER_VAT, legal_registration_identifier=None, postal_address=abroad),
            ]
        )
    )


# Amount2DecimalType, above 0 (ItalianExtension.stamp_duty_amount, #165).
_STAMP_DUTY_CHARGED = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("99999.99"), places=2)


@st.composite
def _stamp_duty(draw: st.DrawFn, credit_note: bool, extension: ItalianExtension) -> dict[str, t.Any]:
    """No stamp duty, the zero marker (SAE charge, or 95 allowance on a credit note) or the marker and an amount.

    App. 4.1 row 2.1.1.6: the marker writes DatiBollo; ``Invoice.it.stamp_duty_amount`` needs it (#165).

    It is drawn regardless of BR-IT-DC-480's conditions (seller in IT, document subject to stamp duty, total above
    77.47 EUR) and on TD17: those rows are conditional mappings, not SdI checks, so the documents are accepted even
    when the duty would not be due. The property tests acceptance and the round trip, not tax realism.
    """
    kind = draw(st.sampled_from(["none", "marker", "charged"]))
    if kind == "none":
        return {}
    zero, category, rate = Decimal("0.00"), "Z", Decimal(0)
    changes: dict[str, t.Any] = (
        {
            "allowances": (
                DocumentLevelAllowance(amount=zero, vat_category_code=category, vat_rate=rate, reason_code="95"),
            )
        }
        if credit_note
        else {
            "charges": (
                DocumentLevelCharge(
                    amount=zero, vat_category_code=category, vat_rate=rate, reason="BOLLO", reason_code="SAE"
                ),
            )
        }
    )
    if kind == "charged":
        changes["it"] = extension.model_copy(update={"stamp_duty_amount": draw(_STAMP_DUTY_CHARGED)})
    return changes


@st.composite
def v1_invoices(draw: st.DrawFn) -> Invoice:
    """A completed TD01, TD04, TD24 or TD17 with 1 to 5 lines of the v1 subset.

    The seller (not a TD17's foreign one) and the buyer are each a company (Denominazione) or a natural person
    (Nome, Cognome).
    """
    tipo = draw(st.sampled_from([TipoDocumento.TD01, TipoDocumento.TD04, TipoDocumento.TD24, TipoDocumento.TD17]))
    seller_person = draw(_PERSON) if tipo is not TipoDocumento.TD17 else None
    buyer_person = draw(_PERSON)
    split: dict[str, str] = {}
    for party, person in (("seller", seller_person), ("buyer", buyer_person)):
        if person is not None:
            split |= {f"{party}_first_name": person[0], f"{party}_last_name": person[1]}
    changes: dict[str, t.Any] = {
        "type_code": "381" if tipo is TipoDocumento.TD04 else "380",
        "it": italian(document_type=tipo, **split),
        "issue_date": draw(st.dates(min_value=datetime.date(1970, 1, 1), max_value=datetime.date(2099, 12, 31))),
    }
    if seller_person is not None:
        changes["seller"] = seller(name=" ".join(seller_person))
    buyer_: Buyer = draw(_buyers())
    if tipo is TipoDocumento.TD17:  # the buyer integrates a foreign supplier's invoice (SdI 00473, 00475)
        changes |= {
            "seller": _foreign_seller(draw(_FOREIGN_POST_CODES)),
            "it": italian(document_type=tipo, issuer=SoggettoEmittente.CC, tax_regime=RegimeFiscale.RF18, **split),
        }
        buyer_ = buyer(vat_identifier=BUYER_VAT, legal_registration_identifier=None)
    payment, instructions = draw(st.one_of(st.just((None, None)), _payments()))
    if payment is not None:
        changes |= {"it": changes["it"].model_copy(update={"payment": payment}), "payment_instructions": instructions}
    # BT-23 and BT-34 are accepted and not written; BT-20 with days is carried by 2.4.1 and 2.4.2.4 (#149).
    changes["process_control"] = ProcessControl(
        business_process_type=draw(st.none() | st.just("urn:example.com:process:01")),
        specification_identifier="urn:cen.eu:en16931:2017",
    )
    changes["seller"] = changes.get("seller", seller()).model_copy(
        update={"electronic_address": draw(st.none() | st.just(Identifier(value="seller@example.com", scheme_id="EM")))}
    )
    if payment is not None:
        changes["payment_terms"] = draw(
            st.sampled_from([None, f"{payment.conditions}", f"{payment.conditions} 0", f"{payment.conditions} 999"])
        )
    if buyer_person is not None:
        buyer_ = buyer_.model_copy(update={"name": " ".join(buyer_person)})
    # Keep last among the "it" updates: _stamp_duty copies changes["it"] as it is here and `changes |=` replaces it.
    # Drawn earlier, the TD17 block would drop stamp_duty_amount; computed before the payment merge, the payment.
    changes |= draw(_stamp_duty(tipo is TipoDocumento.TD04, changes["it"]))
    draft = it_draft(*draw(_lines()), buyer=buyer_, **changes)
    # BT-121 where App. 5.1 gives every Natura of the category one VATEX code (Natura carries it); none otherwise.
    codes: dict[str, set[str]] = {}
    for line in draft.lines:
        nature = None if line.it is None else line.it.nature
        if nature is not None and nature in VATEX_OF_NATURA:
            codes.setdefault(str(line.vat_information.category_code), set()).add(VATEX_OF_NATURA[nature])
    reasons = {cat: calc.ExemptionReason(code=next(iter(c))) for cat, c in codes.items() if len(c) == 1}
    return calc.complete(draft, exemption_reasons=reasons)
