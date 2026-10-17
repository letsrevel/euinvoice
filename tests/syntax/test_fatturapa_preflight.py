"""The FPR12 writer's pre-flight (#119): what the invoice lacks for FatturaPA, located by model path."""

import datetime
import typing as t

import pytest

from _fatturapa_write import buyer, it_invoice, it_line, italian, samples, seller
from euinvoice.model import (
    BuyerPostalAddress,
    Payee,
    PaymentInstructions,
    SellerPostalAddress,
)
from euinvoice.model.it import (
    CondizioniPagamento,
    ItalianPayment,
    ModalitaPagamento,
    Natura,
    SoggettoEmittente,
    TipoDocumento,
)
from euinvoice.report import Severity
from euinvoice.syntax.fatturapa import preflight
from euinvoice.syntax.fatturapa._write_codes import METHODS_WITHOUT_MEANS
from euinvoice.syntax.fatturapa._write_rules import (
    CATEGORY,
    DOCUMENT_TYPE,
    EXTENSION,
    ISSUER,
    NAME,
    NATURA,
    PAYMENT,
    POST_CODE,
    PREFLIGHT_SOURCE,
    REQUIRED,
)


def _found(**changes: t.Any) -> list[tuple[str, str | None, Severity]]:
    return [(f.rule_id, f.location, f.severity) for f in preflight(it_invoice(**changes))]


@pytest.mark.parametrize("name", list(samples()))
def test_samples_have_no_finding(name: str) -> None:
    # The one exempt sample whose N2.1 summary has no RiferimentoNormativo has only that warning (#149).
    expected = ["vat_breakdown[1]"] if name == "TD01 exempt and split payment" else []
    sample = samples()[name]
    findings = preflight(sample.invoice, sample.options)
    assert [f.location for f in findings if f.severity is not Severity.WARNING] == []
    assert [f.location for f in findings if f.severity is Severity.WARNING] == expected


def test_findings_come_from_the_preflight() -> None:
    assert {f.source for f in preflight(it_invoice(it=italian(document_type=TipoDocumento.TD17)))} == {PREFLIGHT_SOURCE}


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

    assert {(rule, location) for rule, location, _ in found if rule == REQUIRED} == {
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


def test_o_lines_are_reported_as_a_category_only() -> None:
    assert _found(lines=(it_line(category="O", rate=None),)) == [
        (CATEGORY, "lines[0].vat_information.category_code", Severity.ERROR),
        (CATEGORY, "vat_breakdown[0].category_code", Severity.ERROR),
    ]


@pytest.mark.parametrize(
    ("changes", "location"),
    [
        (
            {"seller": seller(name="Anna Verdi"), "it": italian(seller_first_name="Anna", seller_last_name="Bianchi")},
            "seller.name",
        ),
        (
            {"buyer": buyer(name="Mario"), "it": italian(buyer_first_name="Mario", buyer_last_name="Rossi")},
            "buyer.name",
        ),
    ],
)
def test_a_name_split_must_agree_with_the_bt_name(changes: dict[str, t.Any], location: str) -> None:
    findings = preflight(it_invoice(**changes))

    assert [(f.rule_id, f.location, f.severity) for f in findings] == [(NAME, location, Severity.ERROR)]
    assert "'Nome Cognome'" in findings[0].message


def test_a_name_split_equal_to_nome_cognome_is_accepted() -> None:
    it = italian(buyer_first_name="Mario", buyer_last_name="De Rossi")

    assert preflight(it_invoice(buyer=buyer(name="Mario De Rossi"), it=it)) == ()


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


UNMAPPED_METHODS: t.Final = ("MP07", "MP09", "MP10", "MP11", "MP14", "MP16", "MP20", "MP21")


def test_the_methods_without_an_app_5_6_row_are_the_eight_of_136() -> None:
    assert sorted(METHODS_WITHOUT_MEANS) == sorted(ModalitaPagamento(m) for m in UNMAPPED_METHODS)


@pytest.mark.parametrize("method", UNMAPPED_METHODS)
def test_bt_81_1_carries_a_method_app_5_6_has_no_row_for(method: str) -> None:
    """#136 option b: App. 5.6 gives no BT-81 for these 8 codes, so "1" (instrument not defined) accompanies them."""
    it = italian(payment=ItalianPayment(conditions=CondizioniPagamento.TP02, method=ModalitaPagamento(method)))

    assert preflight(it_invoice(it=it, payment_instructions=PaymentInstructions(payment_means_type_code="1"))) == ()


@pytest.mark.parametrize("method", ["MP02", "MP05", "MP19"])
def test_bt_81_1_stays_refused_with_a_method_app_5_6_maps_elsewhere(method: str) -> None:
    """App. 5.6 maps "1" to MP01, so "1" next to another method that has a row is inconsistent."""
    it = italian(payment=ItalianPayment(conditions=CondizioniPagamento.TP02, method=ModalitaPagamento(method)))
    findings = preflight(it_invoice(it=it, payment_instructions=PaymentInstructions(payment_means_type_code="1")))

    assert [(f.rule_id, f.location) for f in findings] == [(PAYMENT, "payment_instructions.payment_means_type_code")]


@pytest.mark.parametrize("means", ["10", "30", "ZZZ"])
def test_other_bt_81_stays_refused_with_a_method_app_5_6_has_no_row_for(means: str) -> None:
    it = italian(payment=ItalianPayment(conditions=CondizioniPagamento.TP02, method=ModalitaPagamento.MP07))
    findings = preflight(it_invoice(it=it, payment_instructions=PaymentInstructions(payment_means_type_code=means)))

    assert [(f.rule_id, f.location) for f in findings] == [(PAYMENT, "payment_instructions.payment_means_type_code")]


def test_an_absent_post_code_is_required_only_in_italy() -> None:
    abroad = SellerPostalAddress(address_line_1="A", city="Berlin", country_code="DE")

    assert _found(seller=seller(postal_address=abroad)) == []


def test_a_replaced_foreign_post_code_is_a_warning() -> None:
    abroad = BuyerPostalAddress(address_line_1="A", city="London", post_code="SW1A 1AA", country_code="GB")
    kept = BuyerPostalAddress(address_line_1="A", city="Paris", post_code="75001", country_code="FR")

    assert _found(buyer=buyer(postal_address=abroad)) == [
        (POST_CODE, "buyer.postal_address.post_code", Severity.WARNING)
    ]
    assert _found(buyer=buyer(postal_address=kept)) == []
    assert "00000" in preflight(it_invoice(buyer=buyer(postal_address=abroad)))[0].message
