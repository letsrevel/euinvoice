"""Every document the FPR12 writer produces passes the pinned XSD 1.2.3 and the offline SdI checks (#119, D8).

``validate()`` runs the FatturaPA 1.2.3 schema and then the Allegato A 1.9.1 checks of ``euinvoice.validation.sdi``;
a written document must get no finding at all. Needs ``make artifacts``.
"""

import datetime
import typing as t
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from _fatturapa_write import BUYER_VAT, TRANSMISSION, Sample, buyer, it_draft, it_line, italian, samples
from euinvoice import calc, detect, validate
from euinvoice.model import Buyer, Invoice, LineDraft, Seller, SellerPostalAddress
from euinvoice.model.it import Natura, RegimeFiscale, SoggettoEmittente, TipoDocumento
from euinvoice.syntax import Syntax
from euinvoice.syntax.fatturapa import write

pytestmark = pytest.mark.conformance

SAMPLES: t.Final = samples()


@pytest.mark.parametrize("sample", SAMPLES.values(), ids=SAMPLES.keys())
def test_written_samples_pass_the_xsd_and_the_sdi_checks(sample: Sample) -> None:
    data = write(sample.invoice, sample.options)

    assert validate(data).findings == ()
    detection = detect(data)
    assert (detection.syntax, detection.fatturapa_version) == (Syntax.FATTURAPA, "FPR12")


# (VAT category, rate, Natura): App. 5.1 pairs and the Italian rates, the v1 subset the writer accepts.
_VAT: t.Final[list[tuple[str, str, Natura | None]]] = [
    ("S", "22", None),
    ("S", "10", None),
    ("S", "5", None),
    ("S", "4", None),
    ("B", "22", None),
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
def _invoices(draw: st.DrawFn) -> Invoice:
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
    used = {str(line.vat_information.category_code) for line in draft.lines} - {"S", "B"}
    reasons = {code: calc.ExemptionReason(text="Synthetic exemption reason") for code in used - {"Z"}}
    return calc.complete(draft, exemption_reasons=reasons)


@settings(max_examples=60)
@given(_invoices())
def test_random_v1_invoices_pass_the_xsd_and_the_sdi_checks(invoice: Invoice) -> None:
    assert validate(write(invoice, TRANSMISSION)).findings == ()
