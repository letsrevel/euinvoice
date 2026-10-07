"""Hypothesis strategies for the FatturaPA writer's v1 subset (#119): synthetic invoices the writer accepts."""

import datetime
import typing as t
from decimal import Decimal

from hypothesis import strategies as st

from _fatturapa_write import BUYER_VAT, buyer, it_draft, it_line, italian
from euinvoice import calc
from euinvoice.model import Buyer, Invoice, LineDraft, Seller, SellerPostalAddress
from euinvoice.model.it import Natura, RegimeFiscale, SoggettoEmittente, TipoDocumento
from euinvoice.syntax.fatturapa._write_codes import VATEX_OF_NATURA

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
        lines.append(it_line(str(number), str(draw(_QUANTITIES)), str(draw(_PRICES)), category, rate, nature=nature))
    return tuple(lines)


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
    draft = it_draft(*draw(_lines()), buyer=buyer_, **changes)
    # BT-121 where App. 5.1 gives every Natura of the category one VATEX code (Natura carries it); none otherwise.
    codes: dict[str, set[str]] = {}
    for line in draft.lines:
        nature = None if line.it is None else line.it.nature
        if nature is not None and nature in VATEX_OF_NATURA:
            codes.setdefault(str(line.vat_information.category_code), set()).add(VATEX_OF_NATURA[nature])
    reasons = {cat: calc.ExemptionReason(code=next(iter(c))) for cat, c in codes.items() if len(c) == 1}
    return calc.complete(draft, exemption_reasons=reasons)
