"""FatturaPA 2.4 ``DatiPagamento`` → BG-16, BG-10, BT-9, BT-20, BT-115 and ``Invoice.it.payment`` (#120).

App. 4.1 of the Regole tecniche v2.6 in reverse, rows 2.4.x; App. 5.6 reversed for BT-81 (see ``_read_codes``).
"""

import dataclasses
import datetime
from decimal import Decimal

from lxml import etree

from euinvoice.model.it import ItalianPayment, ModalitaPagamento
from euinvoice.syntax._read_errors import build
from euinvoice.syntax.fatturapa._read_codes import PAYMENT_MEANS, PAYMENT_MEANS_WITHOUT_ACCOUNT
from euinvoice.syntax.fatturapa._read_cursor import Cursor
from euinvoice.syntax.fatturapa._read_parties import CODICE_FISCALE

__all__ = ["Payment", "payment"]


@dataclasses.dataclass(frozen=True)
class Payment:
    """What 2.4 ``DatiPagamento`` gives the invoice; every attribute is ``None`` without one.

    Attributes:
        extension: ``Invoice.it.payment`` (2.4.1, 2.4.2.2).
        instructions: BG-16 as model input (2.4.2.2 → BT-81, 2.4.2.13 / .16 → BG-17, 2.4.2.21 → BT-83).
        payee: BG-10 as model input (2.4.2.1 → BT-59, 2.4.2.8-9 → BT-60, 2.4.2.10 → BT-61).
        due_date: BT-9 (2.4.2.5).
        terms: BT-20 (2.4.1 and 2.4.2.4).
        amount_due: BT-115 (2.4.2.6), only with a single ``DettaglioPagamento``.
    """

    extension: ItalianPayment | None = None
    instructions: dict[str, object] | None = None
    payee: dict[str, object] | None = None
    due_date: datetime.date | None = None
    terms: str | None = None
    amount_due: Decimal | None = None


def payment(cursor: Cursor, body: etree._Element, seller_name: str) -> Payment:
    """Read the first 2.4 ``DatiPagamento`` with its first ``DettaglioPagamento``.

    The model holds one of each (``ItalianPayment``); further ones are reported, and then ``ImportoPagamento`` (an
    instalment, not the amount due) is reported too. BT-20 is ``CondizioniPagamento`` and ``GiorniTerminiPagamento``
    joined by a space (rows 2.4.1, 2.4.2.4: "In BT-20 vengono concatenati"; the separator is #132's). A
    ``Beneficiario`` equal to the seller's name (BT-27) is no PAYEE: BG-10 is for a payee other than the seller
    (UBL-SR-19..21, BR-17), so no BG-10 is made and the element is reported, with the Quietanzante data.
    """
    blocks = cursor.children(body, "DatiPagamento")
    if not blocks:
        return Payment()
    block = cursor.use(blocks[0])
    details = cursor.children(block, "DettaglioPagamento")
    detail = cursor.use(details[0]) if details else None
    conditions = cursor.code(block, "CondizioniPagamento")
    extension = build(
        ItalianPayment, block, {"conditions": conditions, "method": cursor.code(detail, "ModalitaPagamento")}
    )
    days = cursor.code(detail, "GiorniTerminiPagamento")
    iban = cursor.text(detail, "IBAN")
    bic = cursor.text(detail, "BIC") if iban is not None else None
    single = len(blocks) == 1 and len(details) == 1
    instructions: dict[str, object] | None = None
    if extension.method is not None:
        instructions = {
            "payment_means_type_code": _means(extension.method, iban),
            "remittance_information": cursor.text(detail, "CodicePagamento"),
            "credit_transfers": ()
            if iban is None
            else ({"payment_account_identifier": iban, "payment_service_provider_identifier": bic},),
        }
    return Payment(
        extension=extension,
        instructions=instructions,
        payee=_payee(cursor, detail, seller_name),
        due_date=cursor.date(detail, "DataScadenzaPagamento", "2.4.2.5"),
        terms=str(extension.conditions) if days is None else f"{extension.conditions} {days}",
        amount_due=cursor.decimal(detail, "ImportoPagamento", "2.4.2.6") if single else None,
    )


def _means(method: ModalitaPagamento, iban: str | None) -> str:
    """BT-81 for ``method``: App. 5.6 reversed; without an IBAN, a row BR-61 does not tie to BT-84."""
    if iban is None and method in PAYMENT_MEANS_WITHOUT_ACCOUNT:
        return PAYMENT_MEANS_WITHOUT_ACCOUNT[method]
    return PAYMENT_MEANS.get(method, "1")


def _payee(cursor: Cursor, detail: etree._Element | None, seller_name: str) -> dict[str, object] | None:
    """BG-10 as model input, or ``None`` when there is no payee other than the seller.

    2.4.2.1 ``Beneficiario`` → BT-59, ``CognomeQuietanzante`` and ``NomeQuietanzante`` → BT-60 (rows 2.4.2.8-9,
    joined by a space, #132), ``CFQuietanzante`` → BT-61 with scheme 0210 (row 2.4.2.10).
    """
    names = cursor.children(detail, "Beneficiario")
    if not names or (names[0].text or "") == seller_name:
        return None  # no payee other than the seller: Beneficiario and the Quietanzante data stay reported
    name = cursor.text(detail, "Beneficiario")
    parts = [cursor.text(detail, field) for field in ("CognomeQuietanzante", "NomeQuietanzante")]
    known = [part for part in parts if part is not None]
    fiscal_code = cursor.text(detail, "CFQuietanzante")
    return {
        "name": name,
        "identifier": {"value": " ".join(known)} if known else None,
        "legal_registration_identifier": None
        if fiscal_code is None
        else {"value": fiscal_code, "scheme_id": CODICE_FISCALE},
    }
