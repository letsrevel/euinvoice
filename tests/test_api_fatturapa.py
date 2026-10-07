"""``to_xml(..., syntax=Syntax.FATTURAPA)``: the FatturaPA branch of the top-level API (#119)."""

import pickle  # ruff: ignore[suspicious-pickle-import] - round-trips our own exception
import typing as t
from decimal import Decimal

import pytest

from _fatturapa_write import TRANSMISSION, it_invoice, it_line, italian
from _invoices import minimal_invoice
from euinvoice import profiles, to_xml
from euinvoice.errors import PreflightError, UnsupportedDocumentError
from euinvoice.model import Invoice
from euinvoice.model.it import Natura, TipoDocumento
from euinvoice.report import Severity
from euinvoice.syntax import Syntax
from euinvoice.syntax.fatturapa import RECIPIENT_FOREIGN, Transmission, preflight, write


@pytest.mark.parametrize("syntax", [Syntax.FATTURAPA, "fatturapa"])
def test_to_xml_writes_fatturapa_with_the_transmission(syntax: Syntax | t.Literal["fatturapa"]) -> None:
    invoice = it_invoice()

    assert to_xml(invoice, syntax=syntax, fatturapa_transmission=TRANSMISSION) == write(invoice, TRANSMISSION)


def _amounts(invoice: Invoice, *, net: str | None = None, tax: str) -> Invoice:
    """``invoice`` (one line, one breakdown) with BT-131 and BT-117 replaced and every total made consistent."""
    line = invoice.lines[0]
    if net is not None:
        line = line.model_copy(update={"net_amount": Decimal(net)})
    taxable = line.net_amount
    group = invoice.vat_breakdown[0].model_copy(update={"taxable_amount": taxable, "tax_amount": Decimal(tax)})
    total = taxable + Decimal(tax)
    totals = invoice.totals.model_copy(
        update={
            "sum_of_line_net_amounts": taxable,
            "total_without_vat": taxable,
            "total_vat": Decimal(tax),
            "total_with_vat": total,
            "amount_due": total,
        }
    )
    return invoice.model_copy(update={"lines": (line,), "vat_breakdown": (group,), "totals": totals})


@pytest.mark.parametrize(
    ("invoice", "transmission", "code"),
    [
        (_amounts(it_invoice(), tax="22.05"), TRANSMISSION, "00421"),
        (_amounts(it_invoice(), net="80.00", tax="17.60"), TRANSMISSION, "00423"),
        (
            it_invoice(it_line(category="E", rate="10", nature=Natura.N4)),
            TRANSMISSION,
            "00401",
        ),
        (it_invoice(), TRANSMISSION.model_copy(update={"recipient_code": RECIPIENT_FOREIGN}), "00313"),
    ],
    ids=["Imposta", "PrezzoTotale", "Natura at a non-zero rate", "XXXXXXX to an Italian buyer"],
)
def test_to_xml_refuses_what_the_sdi_checks_reject(invoice: Invoice, transmission: Transmission, code: str) -> None:
    assert not [f for f in preflight(invoice) if f.severity is Severity.ERROR]
    write(invoice, transmission)  # the writer alone does not run the SdI checks

    with pytest.raises(PreflightError) as raised:
        to_xml(invoice, syntax=Syntax.FATTURAPA, fatturapa_transmission=transmission)

    assert code in {f.rule_id for f in raised.value.findings}
    assert all(f.source == "sdi" for f in raised.value.findings if f.severity is Severity.ERROR)


def test_to_xml_needs_the_options_for_fatturapa() -> None:
    with pytest.raises(ValueError, match="writing FatturaPA needs fatturapa_transmission"):
        to_xml(it_invoice(), syntax=Syntax.FATTURAPA)


def test_to_xml_refuses_the_options_for_another_syntax() -> None:
    with pytest.raises(ValueError, match=r"fatturapa_transmission applies only to syntax=Syntax\.FATTURAPA"):
        to_xml(minimal_invoice(), syntax=Syntax.UBL, fatturapa_transmission=TRANSMISSION)


def test_to_xml_refuses_a_profile_with_fatturapa() -> None:
    with pytest.raises(UnsupportedDocumentError, match=r"FatturaPA is written without a profile .* 'en16931'"):
        to_xml(it_invoice(), profile=profiles.EN16931, syntax=Syntax.FATTURAPA, fatturapa_transmission=TRANSMISSION)


def test_to_xml_raises_preflight_error_for_fatturapa() -> None:
    invoice = it_invoice(it=italian(document_type=TipoDocumento.TD02))

    with pytest.raises(PreflightError) as raised:
        to_xml(invoice, syntax=Syntax.FATTURAPA, fatturapa_transmission=TRANSMISSION)

    error = raised.value
    assert (error.profile_id, error.syntax) == ("fatturapa", "fatturapa")
    assert [(f.rule_id, f.severity) for f in error.findings] == [("EUINVOICE-FATTURAPA-DOCUMENT-TYPE", Severity.ERROR)]
    assert "fatturapa pre-flight" in str(error)
    assert pickle.loads(pickle.dumps(error)).findings == error.findings  # ruff: ignore[suspicious-pickle-usage] - our own exception


def test_to_xml_ignores_fatturapa_warnings() -> None:
    invoice = it_invoice(payment_terms="Pagamento a 30 giorni")

    assert to_xml(invoice, syntax=Syntax.FATTURAPA, fatturapa_transmission=TRANSMISSION) == write(invoice, TRANSMISSION)
