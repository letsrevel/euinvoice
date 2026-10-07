"""Synthetic invoices for the FatturaPA writer tests (#119): fake parties, placeholder tax ids, the test IBAN.

:data:`SAMPLES` are the documents the conformance test writes and checks against the pinned XSD 1.2.3 and
``validate()``'s SdI checks (``tests/conformance/test_fatturapa_write_official.py``); the unit tests check the
mapping on the same builders.
"""

import dataclasses
import datetime
import typing as t
from decimal import Decimal

from lxml import etree

from euinvoice import _xml, calc
from euinvoice.model import (
    Buyer,
    BuyerPostalAddress,
    CreditTransfer,
    DocumentLevelAllowance,
    DocumentLevelCharge,
    Identifier,
    Invoice,
    InvoiceDraft,
    InvoiceLinePeriod,
    InvoiceNote,
    ItemInformation,
    LineDraft,
    LineVatInformation,
    Payee,
    PaymentInstructions,
    PrecedingInvoiceReference,
    PriceDetails,
    ProcessControl,
    Seller,
    SellerContact,
    SellerPostalAddress,
)
from euinvoice.model.it import (
    CondizioniPagamento,
    EsigibilitaIVA,
    ItalianExtension,
    ItalianLineExtension,
    ItalianPayment,
    ItalianVatSummary,
    ModalitaPagamento,
    Natura,
    RegimeFiscale,
    SoggettoEmittente,
    TipoCessionePrestazione,
    TipoDocumento,
)
from euinvoice.syntax.fatturapa import WriterOptions, write

TEST_IBAN: t.Final = "DE02120300000000202051"
SELLER_VAT: t.Final = "IT00000000001"
BUYER_VAT: t.Final = "IT00000000002"
BUYER_CF: t.Final = "AAAAAA00A00A000A"
OPTIONS: t.Final = WriterOptions(transmitter_country="IT", transmitter_code="00000000001", progressive="00001")
EXEMPT: t.Final = {code: calc.ExemptionReason(text="Synthetic exemption reason") for code in ("E", "G", "K", "AE")}


def it_line(
    identifier: str = "1",
    quantity: str = "2",
    price: str = "50",
    category: str = "S",
    rate: str | None = "22",
    *,
    nature: Natura | None = None,
    supply_type: TipoCessionePrestazione | None = None,
    **changes: t.Any,
) -> LineDraft:
    """A line draft; ``nature`` and ``supply_type`` fill ``LineDraft.it``."""
    extension = (
        None if nature is None and supply_type is None else ItalianLineExtension(nature=nature, supply_type=supply_type)
    )
    data: dict[str, t.Any] = {
        "identifier": identifier,
        "invoiced_quantity": Decimal(quantity),
        "invoiced_quantity_unit_code": "C62",
        "price_details": PriceDetails(item_net_price=Decimal(price)),
        "vat_information": LineVatInformation(category_code=category, rate=None if rate is None else Decimal(rate)),
        "item": ItemInformation(name="Biglietto evento"),
        "it": extension,
    }
    data.update(changes)
    return LineDraft(**data)


def italian(**changes: t.Any) -> ItalianExtension:
    """``Invoice.it`` of a TD01 from an ordinary-regime seller."""
    data: dict[str, t.Any] = {"tax_regime": RegimeFiscale.RF01, "document_type": TipoDocumento.TD01}
    data.update(changes)
    return ItalianExtension(**data)


def seller(**changes: t.Any) -> Seller:
    """An Italian seller (placeholder partita IVA)."""
    data: dict[str, t.Any] = {
        "name": "Esempio Eventi S.r.l.",
        "vat_identifier": SELLER_VAT,
        "postal_address": SellerPostalAddress(
            address_line_1="Via Esempio 1",
            city="Roma",
            post_code="00100",
            country_subdivision="RM",
            country_code="IT",
        ),
    }
    data.update(changes)
    return Seller(**data)


def buyer(**changes: t.Any) -> Buyer:
    """A consumer known by codice fiscale (placeholder)."""
    data: dict[str, t.Any] = {
        "name": "Mario Rossi",
        "legal_registration_identifier": Identifier(value=BUYER_CF, scheme_id="0210"),
        "postal_address": BuyerPostalAddress(
            address_line_1="Via Prova 2", city="Milano", post_code="20100", country_code="IT"
        ),
    }
    data.update(changes)
    return Buyer(**data)


def it_draft(*lines: LineDraft, **changes: t.Any) -> InvoiceDraft:
    """A TD01 draft from :func:`seller` to :func:`buyer`; one 22 % line by default."""
    data: dict[str, t.Any] = {
        "number": "FT-1",
        "issue_date": datetime.date(2026, 1, 15),
        "type_code": "380",
        "currency_code": "EUR",
        "process_control": ProcessControl(specification_identifier="urn:cen.eu:en16931:2017"),
        "seller": seller(),
        "buyer": buyer(),
        "lines": lines or (it_line(),),
        "it": italian(),
    }
    data.update(changes)
    return InvoiceDraft(**data)


def it_invoice(*lines: LineDraft, **changes: t.Any) -> Invoice:
    """:func:`it_draft` completed by :func:`euinvoice.calc.complete` (exemption reasons for E/Z/G/K/AE)."""
    draft = it_draft(*lines, **changes)
    used = {
        str(c)
        for c in (
            *(line.vat_information.category_code for line in draft.lines),
            *(a.vat_category_code for a in draft.allowances),
            *(c.vat_category_code for c in draft.charges),
        )
    }
    return calc.complete(draft, exemption_reasons={k: v for k, v in EXEMPT.items() if k in used})


def written(invoice: Invoice, options: WriterOptions = OPTIONS) -> etree._Element:
    """The root of ``write(invoice, options)``."""
    return _xml.parse(write(invoice, options))


def body(root: etree._Element) -> etree._Element:
    """The only FatturaElettronicaBody."""
    (only,) = root.findall("FatturaElettronicaBody")
    return only


GENERAL: t.Final = "FatturaElettronicaBody/DatiGenerali/DatiGeneraliDocumento"
GOODS: t.Final = "FatturaElettronicaBody/DatiBeniServizi"
PAYMENT: t.Final = "FatturaElettronicaBody/DatiPagamento"
SELLER: t.Final = "FatturaElettronicaHeader/CedentePrestatore"
BUYER: t.Final = "FatturaElettronicaHeader/CessionarioCommittente"


def _stamp_duty() -> Invoice:
    return it_invoice(
        charges=(
            DocumentLevelCharge(
                amount=Decimal("0.00"), vat_category_code="Z", vat_rate=Decimal(0), reason="BOLLO", reason_code="SAE"
            ),
        ),
        lines=(it_line(rate="0", category="E", nature=Natura.N4),),
    )


def _credit_note() -> Invoice:
    return it_invoice(
        number="NC-1",
        type_code="381",
        it=italian(document_type=TipoDocumento.TD04),
        preceding_invoice_references=(
            PrecedingInvoiceReference(reference="FT-1", issue_date=datetime.date(2026, 1, 15)),
        ),
        allowances=(
            DocumentLevelAllowance(
                amount=Decimal("0.00"), vat_category_code="Z", vat_rate=Decimal(0), reason_code="95"
            ),
        ),
        issue_date=datetime.date(2026, 1, 20),
    )


def _deferred() -> Invoice:
    return it_invoice(
        it_line("1", "3", "20.5"),
        it_line(
            "2",
            "1",
            "8",
            rate="10",
            period=InvoiceLinePeriod(start_date=datetime.date(2025, 12, 1), end_date=datetime.date(2025, 12, 31)),
        ),
        it=italian(
            document_type=TipoDocumento.TD24,
            payment=ItalianPayment(conditions=CondizioniPagamento.TP02),
            vat_summaries=(
                ItalianVatSummary(rate=Decimal("22.00"), vat_chargeability=EsigibilitaIVA.D),
                ItalianVatSummary(rate=Decimal("10.00"), vat_chargeability=EsigibilitaIVA.D),
            ),
        ),
        buyer=buyer(vat_identifier=BUYER_VAT, legal_registration_identifier=None),
        payment_due_date=datetime.date(2026, 2, 15),
        payment_instructions=PaymentInstructions(
            payment_means_type_code="58",
            remittance_information="RF18000000000000000000001",
            credit_transfers=(CreditTransfer(payment_account_identifier=TEST_IBAN),),
        ),
        payee=Payee(name="Esempio Incassi S.p.A."),
    )


def _self_billing() -> Invoice:
    """TD17: a German supplier's service, integrated by the Italian buyer (SoggettoEmittente CC)."""
    return it_invoice(
        it=italian(document_type=TipoDocumento.TD17, issuer=SoggettoEmittente.CC, tax_regime=RegimeFiscale.RF18),
        seller=Seller(
            name="Example Hosting GmbH",
            vat_identifier="DE000000000",
            postal_address=SellerPostalAddress(
                address_line_1="Beispielstrasse 1", city="Berlin", post_code="10115", country_code="DE"
            ),
        ),
        buyer=buyer(vat_identifier=BUYER_VAT, legal_registration_identifier=None, name="Esempio Eventi S.r.l."),
    )


def _exempt_and_split() -> Invoice:
    """N2.1 and N4 at rate 0 (two summaries of one E breakdown), plus split payment (B) at 22 %."""
    return it_invoice(
        it_line("1", category="B"),
        it_line("2", "1", "30", "E", "0", nature=Natura.N2_1),
        it_line("3", "1", "20", "E", "0", nature=Natura.N4),
        it=italian(
            vat_summaries=(
                ItalianVatSummary(rate=Decimal(0), nature=Natura.N4, legal_reference="Art. 10 DPR 633/72"),
                ItalianVatSummary(rate=Decimal(22), vat_chargeability=EsigibilitaIVA.S),
            ),
            payment=ItalianPayment(conditions=CondizioniPagamento.TP02, method=ModalitaPagamento.MP05),
        ),
        buyer=buyer(vat_identifier=BUYER_VAT, legal_registration_identifier=None, name="Comune di Esempio"),
    )


def _rich_line() -> Invoice:
    """Gross price with a discount, an accessory charge line, notes, references, rounding and contacts."""
    discounted = it_line(
        "1",
        "4",
        "9.5",
        price_details=PriceDetails(
            item_net_price=Decimal("9.5"), item_gross_price=Decimal("10"), item_price_discount=Decimal("0.5")
        ),
        buyer_accounting_reference="CDC-1",
    )
    return it_invoice(
        discounted,
        it_line("2", "1", "5", supply_type=TipoCessionePrestazione.AC),
        notes=(InvoiceNote(note="Evento del 15 gennaio, ingresso unico."),),
        purchase_order_reference="PO-1",
        contract_reference="CT-1",
        receiving_advice_reference="RA-1",
        buyer_accounting_reference="RIF-AMM",
        seller=seller(
            contact=SellerContact(telephone="0600000000", email="fatture@example.com"),
            legal_registration_identifier=Identifier(value="CF:00000000001"),
        ),
    )


@dataclasses.dataclass(frozen=True)
class Sample:
    """A named invoice and the options it is written with."""

    invoice: Invoice
    options: WriterOptions = OPTIONS


def samples() -> dict[str, Sample]:
    """Every document the conformance test writes, by name."""
    return {
        "TD01 B2C": Sample(it_invoice()),
        "TD01 B2B with PEC": Sample(
            it_invoice(buyer=buyer(vat_identifier=BUYER_VAT, legal_registration_identifier=None)),
            OPTIONS.model_copy(update={"recipient_pec": "fatture@example.com"}),
        ),
        "TD01 B2B with SdI code": Sample(
            it_invoice(buyer=buyer(vat_identifier=BUYER_VAT, legal_registration_identifier=None)),
            WriterOptions(
                transmitter_country="IT", transmitter_code="00000000001", progressive="A1", recipient_code="ABCDEF1"
            ),
        ),
        "TD01 stamp duty": Sample(_stamp_duty()),
        "TD01 exempt and split payment": Sample(_exempt_and_split()),
        "TD01 rich line": Sample(_rich_line()),
        "TD04 credit note": Sample(_credit_note()),
        "TD24 deferred": Sample(_deferred()),
        "TD17 self-billing": Sample(_self_billing()),
    }
