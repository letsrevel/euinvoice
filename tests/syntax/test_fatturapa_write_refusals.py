"""Values the FPR12 writer refuses while serializing instead of altering them: they do not fit their XSD type (#119).

What FPR12 cannot carry at all is reported by the pre-flight: tests/syntax/test_fatturapa_preflight_refusals.py.
"""

import datetime
import typing as t

import pytest

from _fatturapa_write import TEST_IBAN, TRANSMISSION, buyer, it_invoice, it_line, italian, seller
from euinvoice.errors import ModelError
from euinvoice.model import (
    BuyerPostalAddress,
    CreditTransfer,
    Identifier,
    Invoice,
    InvoiceNote,
    PaymentInstructions,
    SellerContact,
    SellerPostalAddress,
)
from euinvoice.model.it import CondizioniPagamento, ItalianPayment
from euinvoice.report import Severity
from euinvoice.syntax.fatturapa import preflight, write


def _refused(invoice: Invoice, match: str) -> None:
    assert not [f for f in preflight(invoice) if f.severity is Severity.ERROR]
    with pytest.raises(ModelError, match=match):
        write(invoice, TRANSMISSION)


@pytest.mark.parametrize("identifier", ["01", "0", "10000", "A1", chr(0x661)])
def test_line_number_must_be_a_canonical_integer(identifier: str) -> None:
    _refused(it_invoice(it_line(identifier)), r"BT-126 \(lines\[0\]\.identifier\)")


def test_negative_quantity_is_refused() -> None:
    _refused(it_invoice(it_line(quantity="-1")), r"BT-129 .*Quantita \(QuantitaType\) is unsigned")


def test_unit_price_beyond_eight_decimals_is_refused() -> None:
    _refused(it_invoice(it_line(price="0.123456789")), r"BT-146 .*at most 8 decimals")


def test_rate_beyond_two_decimals_is_refused() -> None:
    _refused(it_invoice(it_line(rate="7.125")), r"BT-152 .*at most 2 decimals")


def _address(**changes: str) -> SellerPostalAddress:
    data = {"address_line_1": "A", "city": "Roma", "post_code": "00100", "country_code": "IT", **changes}
    return SellerPostalAddress(**data)


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        ({"seller": seller(vat_identifier="1T00000000001")}, r"BT-31 .*IdPaese"),
        ({"seller": seller(vat_identifier="IT" + "0" * 29)}, r"BT-31 .*1 to 28"),
        ({"seller": seller(vat_identifier="IT")}, r"BT-31 .*1 to 28"),
        ({"buyer": buyer(legal_registration_identifier=Identifier(value="abc", scheme_id="0210"))}, r"BT-47 .*CodiceF"),
        (
            {
                "buyer": buyer(
                    postal_address=BuyerPostalAddress(
                        address_line_1="A", city="London", post_code="SW1A 1AA", country_code="GB"
                    )
                )
            },
            r"BT-53 .*CAP",
        ),
        (
            {
                "buyer": buyer(
                    postal_address=BuyerPostalAddress(
                        address_line_1="A", city="Wien", post_code="10100", country_subdivision="W", country_code="AT"
                    )
                )
            },
            r"BT-54 .*only for an address in Italy \(BR-IT-220\)",
        ),
        (
            {"seller": seller(postal_address=_address(country_subdivision="B", country_code="DE", post_code="10115"))},
            r"BT-39 .*only for an address in Italy \(Allegato A 1\.9\.1, BR-IT-DC-150\)",
        ),
        ({"seller": seller(postal_address=_address(country_subdivision="Roma"))}, r"BT-39 .*ProvinciaType"),
        ({"seller": seller(postal_address=_address(address_line_2="123456789"))}, r"BT-36 .*1 to 8"),
        ({"seller": seller(postal_address=_address(country_code="1A"))}, r"BT-40 .*NazioneType"),
        ({"seller": seller(contact=SellerContact(telephone="123"))}, r"BT-42 .*5 to 12"),
        ({"seller": seller(contact=SellerContact(email="nobody"))}, r"BT-43 .*EmailContattiType"),
        ({"seller": seller(name="Caffè €uro")}, r"BT-27 .*'€' at position 6"),
        ({"notes": (InvoiceNote(note="a\nb"),)}, r"BT-22 .*without tab or line break"),
        ({"notes": (InvoiceNote(note="x" * 201),)}, r"BT-22 .*1 to 200 characters, got 201"),
        ({"number": "FT-è"}, r"BT-1 .*Basic Latin"),
        ({"number": "F" * 21}, r"BT-1 .*1 to 20"),
        ({"buyer_accounting_reference": "R" * 21}, r"BT-19 "),
        ({"issue_date": datetime.date(1969, 12, 31)}, r"BT-2 .*1970-01-01"),
    ],
)
def test_values_that_do_not_fit_their_xsd_type_are_refused(changes: dict[str, t.Any], match: str) -> None:
    _refused(it_invoice(**changes), match)


def test_amounts_beyond_eleven_integer_digits_are_refused() -> None:
    _refused(it_invoice(it_line(quantity="1", price="100000000000")), r"BT-112 .*at most 11 integer digits")


@pytest.mark.parametrize(
    ("instructions", "match"),
    [
        (
            PaymentInstructions(
                payment_means_type_code="58", credit_transfers=(CreditTransfer(payment_account_identifier="12345"),)
            ),
            r"BT-84 .*IBANType",
        ),
        (
            PaymentInstructions(
                payment_means_type_code="58",
                credit_transfers=(
                    CreditTransfer(payment_account_identifier=TEST_IBAN, payment_service_provider_identifier="BIC"),
                ),
            ),
            r"BT-86 .*BICType",
        ),
        (PaymentInstructions(payment_means_type_code="58", remittance_information="è"), r"BT-83 "),
    ],
)
def test_payment_values_that_do_not_fit(instructions: PaymentInstructions, match: str) -> None:
    payment = ItalianPayment(conditions=CondizioniPagamento.TP02)
    _refused(it_invoice(it=italian(payment=payment), payment_instructions=instructions), match)


def test_preflight_errors_block_write() -> None:
    with pytest.raises(ModelError, match=r"FatturaPA pre-flight: EUINVOICE-FATTURAPA-EXTENSION at it"):
        write(it_invoice(it=None), TRANSMISSION)


def test_every_preflight_error_is_named() -> None:
    with pytest.raises(ModelError, match=r"UNWRITTEN at buyer_reference: .*; .*UNWRITTEN at project_reference"):
        write(it_invoice(buyer_reference="R", project_reference="P"), TRANSMISSION)
