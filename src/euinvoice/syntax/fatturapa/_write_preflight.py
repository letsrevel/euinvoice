"""Pre-flight of the FPR12 writer: everything that keeps an invoice from being written as FatturaPA (#119).

:func:`preflight` reports, as findings located by model path (rule ids in :mod:`._write_rules`):

* data FatturaPA requires that the invoice does not give (``Invoice.it``, required elements, Natura, payment data);
* content FPR12 cannot carry (:func:`._write_refuse.structure`: business terms with no element, VAT categories
  O/L/M, document level allowances and charges other than a zero stamp duty, …);
* DatiRiepilogo that cannot be built from the lines and the VAT BREAKDOWN, and a BT-120 / BT-121 they cannot carry
  (:func:`._write_lines.summarize`);
* document totals that disagree with the summaries written (BR-CO-10/13/14/15/16 through App. 4.1), including
  the derived totals that are not written (BT-106..BT-110), so none of them is dropped while wrong.

An empty result means :func:`~euinvoice.syntax.fatturapa.write` succeeds unless a value does not
fit its XSD type (length, characters, decimals, CAP, …), which it refuses with :class:`~euinvoice.errors.ModelError`
while serializing. The SdI checks of Allegato A 1.9.1 are not repeated here (except 00400, whose missing Natura the
writer could only guess): ``to_xml`` runs them on the written document (D8).
"""

import typing as t
from decimal import Decimal

from euinvoice.model import Invoice
from euinvoice.model.codes import VatCategory
from euinvoice.model.it import ItalianExtension, SoggettoEmittente, TipoDocumento
from euinvoice.report import Finding
from euinvoice.syntax.fatturapa._write_codes import CATEGORY_OF_NATURA, DOCUMENT_TYPES, PAYMENT_METHOD_OF_MEANS
from euinvoice.syntax.fatturapa._write_lines import Block, summarize
from euinvoice.syntax.fatturapa._write_refuse import structure
from euinvoice.syntax.fatturapa._write_rules import (
    DOCUMENT_TYPE,
    EXTENSION,
    ISSUER,
    NATURA,
    PAYMENT,
    REQUIRED,
    TOTALS,
    UNSUPPORTED_CATEGORIES,
    finding,
)

__all__ = ["preflight"]

_NO_NATURA: t.Final = frozenset({VatCategory.STANDARD_RATED, VatCategory.SPLIT_PAYMENT})


def preflight(invoice: Invoice) -> tuple[Finding, ...]:
    """Report what keeps an invoice from being written as FPR12, before :func:`~euinvoice.syntax.fatturapa.write`.

    ``error`` findings block the write (``write`` raises :class:`~euinvoice.errors.ModelError`, ``to_xml``
    :class:`~euinvoice.errors.PreflightError`). Every set business term is either written or reported here: none
    is dropped.

    Args:
        invoice: The invoice.

    Returns:
        The findings, located by model path, with source ``"fatturapa-preflight"``.
    """
    it = invoice.it
    if it is None:
        return (
            finding(
                EXTENSION,
                "it",
                "Invoice.it is required: FatturaPA's RegimeFiscale (1.2.1.8) and TipoDocumento (2.1.1.1) have no "
                "EN 16931 business term (App. 4.1 of the Regole tecniche v2.6: EXT)",
            ),
        )
    blocks, summary_findings = summarize(invoice, it)
    findings = [
        *_document(invoice, it),
        *_required(invoice),
        *_natura(invoice),
        *_payment(invoice, it),
        *structure(invoice, it),
        *summary_findings,
    ]
    if not findings:  # the totals are compared with the summaries only once those can be built
        findings += _totals(invoice, blocks)
    return tuple(findings)


def _document(invoice: Invoice, it: ItalianExtension) -> t.Iterator[Finding]:
    tipo = it.document_type
    if tipo not in DOCUMENT_TYPES:
        yield finding(
            DOCUMENT_TYPE,
            "it.document_type",
            f"2.1.1.1 TipoDocumento {tipo} is not written by the v1 writer, which emits "
            f"{', '.join(DOCUMENT_TYPES)} (plan M11)",
        )
    elif invoice.type_code != DOCUMENT_TYPES[tipo]:
        yield finding(
            DOCUMENT_TYPE,
            "type_code",
            f"BT-3 is {invoice.type_code}, but TipoDocumento {tipo} is invoice type code {DOCUMENT_TYPES[tipo]} "
            "(App. 5.4 of the Regole tecniche v2.6)",
        )
    if tipo is TipoDocumento.TD17 and it.issuer is None:
        yield finding(
            ISSUER,
            "it.issuer",
            "TD17 is issued by the cessionario/committente (or a third party for it), so 1.6 SoggettoEmittente is "
            f'required: {SoggettoEmittente.CC} or {SoggettoEmittente.TZ} (Allegato A 1.9.1 §2.1.6: "Nei casi di '
            "documenti emessi da un soggetto diverso dal cedente/prestatore va valorizzato l'elemento seguente\")",
        )


def _required(invoice: Invoice) -> t.Iterator[Finding]:
    """Terms whose FatturaPA element the XSD requires (minOccurs 1)."""
    seller, buyer = invoice.seller, invoice.buyer
    needed: list[tuple[object, str, str]] = [
        (seller.vat_identifier, "seller.vat_identifier", "BT-31: 1.2.1.1 IdFiscaleIVA of the cedente/prestatore"),
        (seller.postal_address.address_line_1, "seller.postal_address.address_line_1", "BT-35: 1.2.2.1 Indirizzo"),
        (seller.postal_address.city, "seller.postal_address.city", "BT-37: 1.2.2.4 Comune"),
        (seller.postal_address.post_code, "seller.postal_address.post_code", "BT-38: 1.2.2.3 CAP"),
        (buyer.postal_address.address_line_1, "buyer.postal_address.address_line_1", "BT-50: 1.4.2.1 Indirizzo"),
        (buyer.postal_address.city, "buyer.postal_address.city", "BT-52: 1.4.2.4 Comune"),
        (buyer.postal_address.post_code, "buyer.postal_address.post_code", "BT-53: 1.4.2.3 CAP"),
    ]
    for index, line in enumerate(invoice.lines):
        if VatCategory(line.vat_information.category_code) in UNSUPPORTED_CATEGORIES:
            continue  # reported by structure()
        needed.append(
            (line.vat_information.rate, f"lines[{index}].vat_information.rate", "BT-152: 2.2.1.12 AliquotaIVA")
        )
    for value, location, what in needed:
        if value is None:
            yield finding(REQUIRED, location, f"{what} is required by the FatturaPA XSD 1.2.3 (minOccurs 1)")


def _natura(invoice: Invoice) -> t.Iterator[Finding]:
    """00400 and the App. 5.1 Natura ↔ category table, per line."""
    for index, line in enumerate(invoice.lines):
        category = VatCategory(line.vat_information.category_code)
        nature = None if line.it is None else line.it.nature
        location = f"lines[{index}].it.nature"
        if category in UNSUPPORTED_CATEGORIES:
            continue  # reported by structure()
        if nature is None:
            if line.vat_information.rate == 0:
                yield finding(
                    NATURA, location, "a line at AliquotaIVA 0 needs 2.2.1.14 Natura (SdI 00400, Allegato A 1.9.1)"
                )
            elif category not in _NO_NATURA:
                yield finding(
                    NATURA,
                    location,
                    f"VAT category {category} is expressed in FatturaPA only through a Natura (App. 5.1 of the "
                    "Regole tecniche v2.6); set lines[].it.nature",
                )
        elif CATEGORY_OF_NATURA.get(nature) != category:
            expected = CATEGORY_OF_NATURA.get(nature)
            reason = "is not in the App. 5.1 table" if expected is None else f"is VAT category {expected} in App. 5.1"
            yield finding(NATURA, location, f"Natura {nature} {reason}, but BT-151 is {category}")


def _payment(invoice: Invoice, it: ItalianExtension) -> t.Iterator[Finding]:
    """CondizioniPagamento (2.4.1) and ModalitaPagamento (2.4.2.2), both required in DatiPagamento."""
    instructions = invoice.payment_instructions
    if it.payment is None:
        sources = [
            name
            for name, value in (("BG-16", instructions), ("BT-9", invoice.payment_due_date), ("BG-10", invoice.payee))
            if value is not None
        ]
        if sources:
            yield finding(
                PAYMENT,
                "it.payment",
                f"{', '.join(sources)} can be written only in 2.4 DatiPagamento, whose 2.4.1 CondizioniPagamento has "
                "no EN 16931 source (App. 4.1 folds it into BT-20 as text); set it.payment (#133)",
            )
        return
    means = None if instructions is None else instructions.payment_means_type_code
    mapped = None if means is None else PAYMENT_METHOD_OF_MEANS.get(means)
    method = it.payment.method
    if method is None and mapped is None:
        found = "no BG-16" if means is None else f"BT-81 {means}, which App. 5.6 does not map"
        yield finding(
            PAYMENT,
            "it.payment.method",
            f"2.4.2.2 ModalitaPagamento is required: set it.payment.method, or give a BT-81 that App. 5.6 of the "
            f"Regole tecniche v2.6 maps (found {found})",
        )
    elif method is not None and means is not None and mapped is not method:
        found = "no ModalitaPagamento" if mapped is None else f"ModalitaPagamento {mapped}"
        yield finding(
            PAYMENT,
            "payment_instructions.payment_means_type_code",
            f"BT-81 cannot be written in FatturaPA: App. 5.6 gives BT-81 {means} {found}, but it.payment.method is "
            f"{method}; 2.4.2.2 holds one code",
        )


def _totals(invoice: Invoice, blocks: list[Block]) -> t.Iterator[Finding]:
    """The totals against the summaries written: ImportoTotaleDocumento, ImportoPagamento and the derived sums.

    App. 4.1 maps 2.1.1.9 ↔ BT-112, 2.1.1.10 ↔ BT-114, 2.4.2.6 ↔ BT-115 and 2.2.2.5 / 2.2.2.6 ↔ BT-116 / BT-117; the
    equalities are the EN rules on those terms: BR-CO-10 (BT-106 = Σ BT-131), BR-CO-13 (BT-109 = BT-106 - BT-107 +
    BT-108), BR-CO-14 (BT-110 = Σ BT-117), BR-CO-15 (BT-112 = BT-109 + BT-110) and BR-CO-16 (BT-115 = BT-112 -
    BT-113 + BT-114). With BT-113 refused, BG-20/21 limited to a zero stamp duty and ImponibileImporto = Σ BT-131
    per block, they read ImportoTotaleDocumento = Σ ImponibileImporto + Σ Imposta and ImportoPagamento =
    ImportoTotaleDocumento + Arrotondamento. The sums that are not written (BT-106..BT-110) must agree too, or they
    would be dropped while wrong. No SdI check covers these totals.
    """
    totals = invoice.totals
    taxable = sum((block.taxable for block in blocks), Decimal("0.00"))
    tax = sum((block.tax for block in blocks), Decimal("0.00"))
    lines = sum((line.net_amount for line in invoice.lines), Decimal("0.00"))
    expected: list[tuple[str, str, Decimal | None, Decimal, str]] = [
        ("BT-106", "sum_of_line_net_amounts", totals.sum_of_line_net_amounts, lines, "Σ PrezzoTotale"),
        ("BT-107", "sum_of_allowances", totals.sum_of_allowances or Decimal(0), Decimal(0), "0 (no allowance written)"),
        ("BT-108", "sum_of_charges", totals.sum_of_charges or Decimal(0), Decimal(0), "0 (no charge written)"),
        ("BT-109", "total_without_vat", totals.total_without_vat, taxable, "Σ ImponibileImporto"),
        ("BT-110", "total_vat", totals.total_vat or Decimal(0), tax, "Σ Imposta"),
        (
            "BT-112",
            "total_with_vat",
            totals.total_with_vat,
            taxable + tax,
            "Σ ImponibileImporto + Σ Imposta (2.1.1.9 ImportoTotaleDocumento, App. 4.1)",
        ),
        (
            "BT-115",
            "amount_due",
            totals.amount_due,
            totals.total_with_vat + (totals.rounding_amount or 0),
            "ImportoTotaleDocumento + Arrotondamento (2.4.2.6 ImportoPagamento, 2.1.1.10, App. 4.1)",
        ),
    ]
    for term, name, value, computed, what in expected:
        if value != computed:
            yield finding(
                TOTALS, f"totals.{name}", f"{term} is {value}, but the FatturaPA document gives {what} = {computed}"
            )
