"""FatturaPA 2.1.1.7 ``DatiCassaPrevidenziale`` → DOCUMENT LEVEL CHARGES (BG-21) (#120).

App. 4.1 of the Regole tecniche v2.6 maps each social-security fund contribution to a document level charge: rows
2.1.1.7.3 ``ImportoContributoCassa`` → BT-99, 2.1.1.7.4 ``ImponibileCassa`` → BT-100, 2.1.1.7.2 ``AlCassa`` →
BT-101, 2.1.1.7.5 ``AliquotaIVA`` → BT-103, and 2.1.1.7.1 ``TipoCassa``, 2.1.1.7.6 ``Ritenuta`` and 2.1.1.7.7
``Natura`` "concatenati" in BT-104 (joined by a space here; the separator is #132's). The contribution is part of the
VAT summaries' taxable amount (SdI checks 00443/00422), so the charge keeps the declared summaries consistent with
BR-S-08 and its siblings. Its VAT category BT-102 follows the ``Natura`` by App. 5.1, as a line's does; row 2.1.1.7.8
``RiferimentoAmministrazione`` is "Mappatura non considerabile" and reported.
"""

from lxml import etree

from euinvoice.model import DocumentLevelCharge
from euinvoice.syntax._read_errors import build
from euinvoice.syntax.fatturapa._read_cursor import Cursor
from euinvoice.syntax.fatturapa._read_lines import Summaries, read_nature, vat_category

__all__ = ["funds"]


def funds(cursor: Cursor, document: etree._Element | None, vat: Summaries) -> tuple[DocumentLevelCharge, ...]:
    """Every 2.1.1.7 ``DatiCassaPrevidenziale`` as a BG-21, in document order."""
    return tuple(_fund(cursor, cursor.use(e), vat) for e in cursor.children(document, "DatiCassaPrevidenziale"))


def _fund(cursor: Cursor, element: etree._Element, vat: Summaries) -> DocumentLevelCharge:
    kind = cursor.code(element, "TipoCassa")
    rate = cursor.decimal(element, "AliquotaIVA", "2.1.1.7.5")
    withholding = cursor.code(element, "Ritenuta")
    nature = read_nature(cursor, element, "2.1.1.7.7")
    reason = " ".join(str(part) for part in (kind, withholding, nature) if part is not None)
    values = {
        "amount": cursor.decimal(element, "ImportoContributoCassa", "2.1.1.7.3"),  # → BT-99
        "base_amount": cursor.decimal(element, "ImponibileCassa", "2.1.1.7.4"),  # → BT-100
        "percentage": cursor.decimal(element, "AlCassa", "2.1.1.7.2"),  # → BT-101
        "vat_category_code": vat_category(cursor, element, nature, rate, vat, "2.1.1.7.7"),  # → BT-102 (App. 5.1)
        "vat_rate": rate,  # → BT-103
        "reason": reason or None,  # → BT-104
    }
    return build(DocumentLevelCharge, element, values)
