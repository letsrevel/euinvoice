"""The FPR12 writer's pre-flight (#119): what the invoice lacks for FatturaPA, located by model path."""

import datetime
import typing as t
from decimal import Decimal

import pytest

from _fatturapa_write import buyer, it_invoice, it_line, italian, samples, seller
from euinvoice.model import (
    BuyerPostalAddress,
    Payee,
    PaymentInstructions,
    SellerPostalAddress,
)
from euinvoice.model.it import CondizioniPagamento, ItalianPayment, Natura, SoggettoEmittente, TipoDocumento
from euinvoice.report import Severity
from euinvoice.syntax.fatturapa import preflight
from euinvoice.syntax.fatturapa._write_preflight import (
    DOCUMENT_TYPE,
    EXTENSION,
    ISSUER,
    NATURA,
    NOT_WRITTEN,
    PAYMENT,
    PREFLIGHT_SOURCE,
    REQUIRED,
)


def _found(**changes: t.Any) -> list[tuple[str, str | None, Severity]]:
    return [(f.rule_id, f.location, f.severity) for f in preflight(it_invoice(**changes))]


@pytest.mark.parametrize("name", list(samples()))
def test_samples_have_no_blocking_finding(name: str) -> None:
    findings = preflight(samples()[name].invoice)

    assert all(f.severity is Severity.WARNING for f in findings)
    assert all(f.source == PREFLIGHT_SOURCE for f in findings)


def test_missing_extension_is_the_only_finding() -> None:
    assert _found(it=None) == [(EXTENSION, "it", Severity.ERROR)]


@pytest.mark.parametrize("tipo", [TipoDocumento.TD02, TipoDocumento.TD16, TipoDocumento.TD27])
def test_document_types_outside_v1(tipo: TipoDocumento) -> None:
    assert _found(it=italian(document_type=tipo)) == [(DOCUMENT_TYPE, "it.document_type", Severity.ERROR)]


@pytest.mark.parametrize(
    ("tipo", "type_code"),
    [(TipoDocumento.TD01, "381"), (TipoDocumento.TD04, "380"), (TipoDocumento.TD24, "389")],
)
def test_bt_3_must_be_the_app_5_4_code(tipo: TipoDocumento, type_code: str) -> None:
    assert _found(it=italian(document_type=tipo), type_code=type_code) == [(DOCUMENT_TYPE, "type_code", Severity.ERROR)]


def test_td17_needs_soggetto_emittente() -> None:
    assert _found(it=italian(document_type=TipoDocumento.TD17)) == [(ISSUER, "it.issuer", Severity.ERROR)]
    assert _found(it=italian(document_type=TipoDocumento.TD17, issuer=SoggettoEmittente.TZ)) == []


def test_required_elements_without_their_business_term() -> None:
    found = _found(
        seller=seller(vat_identifier=None, postal_address=SellerPostalAddress(country_code="IT")),
        buyer=buyer(postal_address=BuyerPostalAddress(country_code="IT")),
        lines=(it_line(rate=None),),
    )

    assert {(rule, location) for rule, location, _ in found} == {
        (REQUIRED, "seller.vat_identifier"),
        (REQUIRED, "seller.postal_address.address_line_1"),
        (REQUIRED, "seller.postal_address.city"),
        (REQUIRED, "seller.postal_address.post_code"),
        (REQUIRED, "buyer.postal_address.address_line_1"),
        (REQUIRED, "buyer.postal_address.city"),
        (REQUIRED, "buyer.postal_address.post_code"),
        (REQUIRED, "lines[0].vat_information.rate"),
    }


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (it_line(category="E", rate="0"), "AliquotaIVA 0 needs 2.2.1.14 Natura"),
        (it_line(category="E", rate="5"), "VAT category E is expressed in FatturaPA only through a Natura"),
        (
            it_line(category="E", rate="0", nature=Natura.N3_1),
            "Natura N3.1 is VAT category G in App. 5.1, but BT-151 is E",
        ),
        (it_line(category="E", rate="0", nature=Natura.N2), "Natura N2 is not in the App. 5.1 table"),
        (it_line(nature=Natura.N4), "Natura N4 is VAT category E in App. 5.1, but BT-151 is S"),
    ],
    ids=["00400", "category needs Natura", "wrong category", "generic Natura", "Natura on S"],
)
def test_natura_against_rate_and_category(line: t.Any, message: str) -> None:
    findings = [f for f in preflight(it_invoice(line)) if f.severity is Severity.ERROR]

    assert [(f.rule_id, f.location) for f in findings] == [(NATURA, "lines[0].it.nature")]
    assert message in findings[0].message


def test_o_lines_are_left_to_write() -> None:
    assert _found(lines=(it_line(category="O", rate=None),)) == []


@pytest.mark.parametrize(
    ("changes", "named"),
    [
        ({"payment_instructions": PaymentInstructions(payment_means_type_code="58")}, "BG-16"),
        ({"payment_due_date": datetime.date(2026, 2, 1)}, "BT-9"),
        ({"payee": Payee(name="P")}, "BG-10"),
    ],
)
def test_payment_data_needs_it_payment(changes: dict[str, t.Any], named: str) -> None:
    findings = preflight(it_invoice(**changes))

    assert [(f.rule_id, f.location) for f in findings] == [(PAYMENT, "it.payment")]
    assert findings[0].message.startswith(f"{named} can be written only in 2.4 DatiPagamento")


@pytest.mark.parametrize(
    ("instructions", "found"),
    [(None, "no BG-16"), (PaymentInstructions(payment_means_type_code="98"), "BT-81 98, which App. 5.6")],
)
def test_modalita_pagamento_needs_a_source(instructions: PaymentInstructions | None, found: str) -> None:
    it = italian(payment=ItalianPayment(conditions=CondizioniPagamento.TP02))
    findings = preflight(it_invoice(it=it, payment_instructions=instructions))

    assert [(f.rule_id, f.location) for f in findings] == [(PAYMENT, "it.payment.method")]
    assert found in findings[0].message


def test_terms_folded_into_other_elements_are_warnings() -> None:
    found = _found(payment_terms="30 days", lines=(it_line(category="E", rate="0", nature=Natura.N4),))

    assert found == [
        (NOT_WRITTEN, "payment_terms", Severity.WARNING),
        (NOT_WRITTEN, "vat_breakdown[0].exemption_reason", Severity.WARNING),
    ]


def test_exemption_reason_code_is_a_warning() -> None:
    invoice = it_invoice(it_line(category="E", rate="0", nature=Natura.N4))
    group = invoice.vat_breakdown[0].model_copy(
        update={"exemption_reason": None, "exemption_reason_code": "VATEX-EU-132"}
    )
    findings = preflight(invoice.model_copy(update={"vat_breakdown": (group,)}))

    assert [(f.rule_id, f.location) for f in findings] == [(NOT_WRITTEN, "vat_breakdown[0].exemption_reason_code")]
    assert Decimal(0) == invoice.vat_breakdown[0].tax_amount
