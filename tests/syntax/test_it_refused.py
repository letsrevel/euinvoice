"""UBL and CII writers refuse a set ``Invoice.it`` instead of dropping it (D3 as amended, plan §1 "never silently
dropped", #118). The Italian extension has a FatturaPA home only (#119)."""

import re
import typing as t
from collections.abc import Callable

import pytest

import euinvoice
from _invoices import CEN, minimal_invoice
from euinvoice.errors import ModelError
from euinvoice.model import Invoice, ProcessControl
from euinvoice.model.it import ItalianExtension, ItalianLineExtension, Natura, RegimeFiscale, TipoDocumento
from euinvoice.profiles import EN16931
from euinvoice.syntax import cii, ubl

WRITERS: t.Final[dict[str, Callable[[Invoice], bytes]]] = {"UBL": ubl.write, "CII": cii.write}
_IT: t.Final = ItalianExtension(tax_regime=RegimeFiscale.RF01, document_type=TipoDocumento.TD01)


def _with_line_extension(invoice: Invoice) -> Invoice:
    line = invoice.lines[0].model_copy(update={"it": ItalianLineExtension(nature=Natura.N4)})
    return Invoice.model_validate({**dict(invoice), "lines": (line, *invoice.lines[1:])})


@pytest.mark.parametrize("syntax", WRITERS)
def test_document_extension_is_refused(syntax: str, invoice: Invoice) -> None:
    with pytest.raises(ModelError, match=rf"^it cannot be written in {syntax}: .*FatturaPA"):
        WRITERS[syntax](Invoice.model_validate({**dict(invoice), "it": _IT}))


@pytest.mark.parametrize("syntax", WRITERS)
def test_line_extension_is_refused(syntax: str, invoice: Invoice) -> None:
    with pytest.raises(ModelError, match=re.escape(f"lines[0].it cannot be written in {syntax}")):
        WRITERS[syntax](_with_line_extension(invoice))


@pytest.mark.parametrize("syntax", ["ubl", "cii"])
def test_to_xml_refuses_too(syntax: t.Literal["ubl", "cii"]) -> None:
    core = minimal_invoice(process_control=ProcessControl(specification_identifier=CEN))
    assert euinvoice.to_xml(core, profile=EN16931, syntax=syntax)  # passes pre-flight and calc.check
    with pytest.raises(ModelError, match=r"^it cannot be written"):
        euinvoice.to_xml(Invoice.model_validate({**dict(core), "it": _IT}), profile=EN16931, syntax=syntax)


@pytest.mark.parametrize("syntax", WRITERS)
def test_without_extension_the_writers_are_unchanged(syntax: str, invoice: Invoice) -> None:
    assert WRITERS[syntax](invoice).startswith(b"<?xml")
