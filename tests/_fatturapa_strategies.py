"""Hypothesis strategies for the FatturaPA writer's v1 subset (#119): synthetic invoices the writer accepts."""

import datetime
import typing as t
from decimal import Decimal

from hypothesis import strategies as st

from _fatturapa_write import BUYER_VAT, buyer, it_draft, it_line, italian, seller
from euinvoice import calc
from euinvoice.model import (
    Buyer,
    Identifier,
    Invoice,
    ItemInformation,
    LineDraft,
    PaymentInstructions,
    ProcessControl,
    Seller,
    SellerPostalAddress,
)
from euinvoice.model.it import (
    CondizioniPagamento,
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


@st.composite
def _lines(draw: st.DrawFn) -> tuple[LineDraft, ...]:
    count = draw(st.integers(min_value=1, max_value=5))
    lines = []
    for number in range(1, count + 1):
        category, rate, nature = draw(st.sampled_from(_VAT))
        # BT-154 joins BT-153 in Descrizione (#149); the reader gives the joined text as BT-153.
        item = ItemInformation(name="Biglietto evento", description=draw(st.none() | st.just("ingresso unico")))
        lines.append(
            it_line(str(number), str(draw(_QUANTITIES)), str(draw(_PRICES)), category, rate, nature=nature, item=item)
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


_FOREIGN_SELLER: t.Final = Seller(
    name="Example Hosting GmbH",
    vat_identifier="DE000000000",
    postal_address=SellerPostalAddress(
        address_line_1="Beispielstrasse 1", city="Berlin", post_code="10115", country_code="DE"
    ),
)


@st.composite
def v1_invoices(draw: st.DrawFn) -> Invoice:
    """A completed TD01, TD04, TD24 or TD17 with 1 to 5 lines of the v1 subset."""
    tipo = draw(st.sampled_from([TipoDocumento.TD01, TipoDocumento.TD04, TipoDocumento.TD24, TipoDocumento.TD17]))
    changes: dict[str, t.Any] = {
        "type_code": "381" if tipo is TipoDocumento.TD04 else "380",
        "it": italian(document_type=tipo),
        "issue_date": draw(st.dates(min_value=datetime.date(1970, 1, 1), max_value=datetime.date(2099, 12, 31))),
    }
    buyer_: Buyer = draw(
        st.sampled_from([buyer(), buyer(vat_identifier=BUYER_VAT, legal_registration_identifier=None)])
    )
    if tipo is TipoDocumento.TD17:  # the buyer integrates a foreign supplier's invoice (SdI 00473, 00475)
        changes |= {
            "seller": _FOREIGN_SELLER,
            "it": italian(document_type=tipo, issuer=SoggettoEmittente.CC, tax_regime=RegimeFiscale.RF18),
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
    draft = it_draft(*draw(_lines()), buyer=buyer_, **changes)
    # BT-121 where App. 5.1 gives every Natura of the category one VATEX code (Natura carries it); none otherwise.
    codes: dict[str, set[str]] = {}
    for line in draft.lines:
        nature = None if line.it is None else line.it.nature
        if nature is not None and nature in VATEX_OF_NATURA:
            codes.setdefault(str(line.vat_information.category_code), set()).add(VATEX_OF_NATURA[nature])
    reasons = {cat: calc.ExemptionReason(code=next(iter(c))) for cat, c in codes.items() if len(c) == 1}
    return calc.complete(draft, exemption_reasons=reasons)
