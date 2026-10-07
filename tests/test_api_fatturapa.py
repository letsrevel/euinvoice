"""``to_xml(..., syntax=Syntax.FATTURAPA)``: the FatturaPA branch of the top-level API (#119)."""

import pickle  # ruff: ignore[suspicious-pickle-import] - round-trips our own exception

import pytest

from _fatturapa_write import OPTIONS, it_invoice, italian
from _invoices import minimal_invoice
from euinvoice import profiles, to_xml
from euinvoice.errors import PreflightError, UnsupportedDocumentError
from euinvoice.model.it import TipoDocumento
from euinvoice.report import Severity
from euinvoice.syntax import Syntax
from euinvoice.syntax.fatturapa import write


@pytest.mark.parametrize("syntax", [Syntax.FATTURAPA, "fatturapa"])
def test_to_xml_writes_fatturapa_with_the_options(syntax: Syntax | str) -> None:
    invoice = it_invoice()

    assert to_xml(invoice, syntax=syntax, fatturapa_options=OPTIONS) == write(invoice, OPTIONS)  # type: ignore[arg-type]


def test_to_xml_needs_the_options_for_fatturapa() -> None:
    with pytest.raises(ValueError, match="writing FatturaPA needs fatturapa_options"):
        to_xml(it_invoice(), syntax=Syntax.FATTURAPA)


def test_to_xml_refuses_the_options_for_another_syntax() -> None:
    with pytest.raises(ValueError, match=r"fatturapa_options apply only to syntax=Syntax\.FATTURAPA"):
        to_xml(minimal_invoice(), syntax=Syntax.UBL, fatturapa_options=OPTIONS)


def test_to_xml_refuses_a_profile_with_fatturapa() -> None:
    with pytest.raises(UnsupportedDocumentError, match=r"FatturaPA is written without a profile .* 'en16931'"):
        to_xml(it_invoice(), profile=profiles.EN16931, syntax=Syntax.FATTURAPA, fatturapa_options=OPTIONS)


def test_to_xml_raises_preflight_error_for_fatturapa() -> None:
    invoice = it_invoice(it=italian(document_type=TipoDocumento.TD02))

    with pytest.raises(PreflightError) as raised:
        to_xml(invoice, syntax=Syntax.FATTURAPA, fatturapa_options=OPTIONS)

    error = raised.value
    assert (error.profile_id, error.syntax) == ("fatturapa", "fatturapa")
    assert [(f.rule_id, f.severity) for f in error.findings] == [("EUINVOICE-FATTURAPA-DOCUMENT-TYPE", Severity.ERROR)]
    assert "fatturapa pre-flight" in str(error)
    assert pickle.loads(pickle.dumps(error)).findings == error.findings  # ruff: ignore[suspicious-pickle-usage] - our own exception


def test_to_xml_ignores_fatturapa_warnings() -> None:
    invoice = it_invoice(payment_terms="Pagamento a 30 giorni")

    assert to_xml(invoice, syntax=Syntax.FATTURAPA, fatturapa_options=OPTIONS) == write(invoice, OPTIONS)
