"""Pre-flight of the FPR12 writer: what FatturaPA requires that the invoice does not give (#119).

:func:`preflight` reports model data the writer needs and cannot derive, as findings located by model path. It does
not repeat the SdI checks of :func:`euinvoice.validate` (D8), except 00400, whose missing ``Natura`` the writer
could only guess. Content FatturaPA has no place for is not reported here: :func:`~euinvoice.syntax.fatturapa.write`
refuses it with :class:`~euinvoice.errors.ModelError`.
"""

import typing as t

from euinvoice.model import Invoice
from euinvoice.model.codes import VatCategory
from euinvoice.model.it import ItalianExtension, SoggettoEmittente, TipoDocumento
from euinvoice.report import Finding, Severity
from euinvoice.syntax.fatturapa._write_codes import CATEGORY_OF_NATURA, DOCUMENT_TYPES, PAYMENT_METHOD_OF_MEANS

__all__ = [
    "DOCUMENT_TYPE",
    "EXTENSION",
    "ISSUER",
    "NATURA",
    "NOT_WRITTEN",
    "PAYMENT",
    "PREFLIGHT_SOURCE",
    "REQUIRED",
    "UNSUPPORTED_CATEGORIES",
    "preflight",
]

PREFLIGHT_SOURCE: t.Final = "fatturapa-preflight"
"""``source`` of every pre-flight finding."""
EXTENSION: t.Final = "EUINVOICE-FATTURAPA-EXTENSION"
"""``Invoice.it`` is missing: RegimeFiscale (1.2.1.8) and TipoDocumento (2.1.1.1) are required and have no BT."""
DOCUMENT_TYPE: t.Final = "EUINVOICE-FATTURAPA-DOCUMENT-TYPE"
"""TipoDocumento is not one the v1 writer emits (plan M11), or BT-3 is not its code in App. 5.4."""
ISSUER: t.Final = "EUINVOICE-FATTURAPA-ISSUER"
"""A TD17 without SoggettoEmittente (1.6)."""
REQUIRED: t.Final = "EUINVOICE-FATTURAPA-REQUIRED"
"""An element the XSD requires whose business term is missing."""
NATURA: t.Final = "EUINVOICE-FATTURAPA-NATURA"
"""A line's Natura (2.2.1.14) is missing at rate zero (SdI 00400) or does not match its VAT category (App. 5.1)."""
PAYMENT: t.Final = "EUINVOICE-FATTURAPA-PAYMENT"
"""DatiPagamento (2.4) cannot be filled: CondizioniPagamento or ModalitaPagamento has no source."""
NOT_WRITTEN: t.Final = "EUINVOICE-FATTURAPA-NOT-WRITTEN"
"""A ``warning``: a business term App. 4.1 builds from FatturaPA elements the writer fills from other data, so its
own text is not written (BT-20, BT-120, BT-121)."""

UNSUPPORTED_CATEGORIES: t.Final = frozenset({VatCategory.NOT_SUBJECT_TO_VAT, VatCategory.IGIC, VatCategory.IPSI})
"""O, L and M: App. 5.1 gives them no Natura, and the writer refuses them (#133)."""
_NO_NATURA: t.Final = frozenset({VatCategory.STANDARD_RATED, VatCategory.SPLIT_PAYMENT})


def _finding(rule_id: str, location: str, message: str, severity: Severity = Severity.ERROR) -> Finding:
    return Finding(rule_id=rule_id, severity=severity, location=location, message=message, source=PREFLIGHT_SOURCE)


def preflight(invoice: Invoice) -> tuple[Finding, ...]:
    """Report what the invoice lacks for an FPR12 document, before :func:`~euinvoice.syntax.fatturapa.write`.

    ``error`` findings block the write (``write`` raises :class:`~euinvoice.errors.ModelError`, ``to_xml``
    :class:`~euinvoice.errors.PreflightError`); ``warning`` findings name business terms that are not written
    because FatturaPA carries their content in other elements (App. 4.1 of the Regole tecniche v2.6).

    Args:
        invoice: The invoice.

    Returns:
        The findings, located by model path, with source :data:`PREFLIGHT_SOURCE`.
    """
    if invoice.it is None:
        return (
            _finding(
                EXTENSION,
                "it",
                "Invoice.it is required: FatturaPA's RegimeFiscale (1.2.1.8) and TipoDocumento (2.1.1.1) have no "
                "EN 16931 business term (App. 4.1 of the Regole tecniche v2.6: EXT)",
            ),
        )
    return (
        *_document(invoice, invoice.it),
        *_required(invoice),
        *_natura(invoice),
        *_payment(invoice, invoice.it),
        *_not_written(invoice),
    )


def _document(invoice: Invoice, it: ItalianExtension) -> t.Iterator[Finding]:
    tipo = it.document_type
    if tipo not in DOCUMENT_TYPES:
        yield _finding(
            DOCUMENT_TYPE,
            "it.document_type",
            f"2.1.1.1 TipoDocumento {tipo} is not written by the v1 writer, which emits "
            f"{', '.join(DOCUMENT_TYPES)} (plan M11)",
        )
    elif invoice.type_code != DOCUMENT_TYPES[tipo]:
        yield _finding(
            DOCUMENT_TYPE,
            "type_code",
            f"BT-3 is {invoice.type_code}, but TipoDocumento {tipo} is invoice type code {DOCUMENT_TYPES[tipo]} "
            "(App. 5.4 of the Regole tecniche v2.6)",
        )
    if tipo is TipoDocumento.TD17 and it.issuer is None:
        yield _finding(
            ISSUER,
            "it.issuer",
            "TD17 is issued by the cessionario/committente (or a third party for it), so 1.6 SoggettoEmittente is "
            f"required: {SoggettoEmittente.CC} or {SoggettoEmittente.TZ} (Rappresentazione tabellare, row 1.6: "
            '"da valorizzare in tutti i casi in cui la fattura è emessa da un soggetto diverso dal '
            'cedente/prestatore")',
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
            continue  # refused by write()
        needed.append(
            (line.vat_information.rate, f"lines[{index}].vat_information.rate", "BT-152: 2.2.1.12 AliquotaIVA")
        )
    for value, location, what in needed:
        if value is None:
            yield _finding(REQUIRED, location, f"{what} is required by the FatturaPA XSD 1.2.3 (minOccurs 1)")


def _natura(invoice: Invoice) -> t.Iterator[Finding]:
    """00400 and the App. 5.1 Natura ↔ category table, per line."""
    for index, line in enumerate(invoice.lines):
        category = VatCategory(line.vat_information.category_code)
        nature = None if line.it is None else line.it.nature
        location = f"lines[{index}].it.nature"
        if category in UNSUPPORTED_CATEGORIES:
            continue  # refused by write()
        if nature is None:
            if line.vat_information.rate == 0:
                yield _finding(
                    NATURA, location, "a line at AliquotaIVA 0 needs 2.2.1.14 Natura (SdI 00400, Allegato A 1.9.1)"
                )
            elif category not in _NO_NATURA:
                yield _finding(
                    NATURA,
                    location,
                    f"VAT category {category} is expressed in FatturaPA only through a Natura (App. 5.1 of the "
                    "Regole tecniche v2.6); set lines[].it.nature",
                )
        elif CATEGORY_OF_NATURA.get(nature) != category:
            expected = CATEGORY_OF_NATURA.get(nature)
            reason = "is not in the App. 5.1 table" if expected is None else f"is VAT category {expected} in App. 5.1"
            yield _finding(NATURA, location, f"Natura {nature} {reason}, but BT-151 is {category}")


def _payment(invoice: Invoice, it: ItalianExtension) -> t.Iterator[Finding]:
    """CondizioniPagamento (2.4.1) and ModalitaPagamento (2.4.2.2), both required in DatiPagamento."""
    instructions = invoice.payment_instructions
    if it.payment is None:
        sources = [
            name
            for name, value in (
                ("BG-16", instructions),
                ("BT-9", invoice.payment_due_date),
                ("BG-10", invoice.payee),
            )
            if value is not None
        ]
        if sources:
            yield _finding(
                PAYMENT,
                "it.payment",
                f"{', '.join(sources)} can be written only in 2.4 DatiPagamento, whose 2.4.1 CondizioniPagamento has "
                "no EN 16931 source (App. 4.1 folds it into BT-20 as text); set it.payment",
            )
        return
    if it.payment.method is None:
        means = None if instructions is None else instructions.payment_means_type_code
        if means is None or means not in PAYMENT_METHOD_OF_MEANS:
            found = "no BG-16" if means is None else f"BT-81 {means}, which App. 5.6 does not map"
            yield _finding(
                PAYMENT,
                "it.payment.method",
                f"2.4.2.2 ModalitaPagamento is required: set it.payment.method, or give a BT-81 that App. 5.6 of the "
                f"Regole tecniche v2.6 maps (found {found})",
            )


def _not_written(invoice: Invoice) -> t.Iterator[Finding]:
    if invoice.payment_terms is not None:
        yield _finding(
            NOT_WRITTEN,
            "payment_terms",
            "BT-20 is not written: App. 4.1 builds it from 2.4.1 CondizioniPagamento and 2.4.2.4 "
            "GiorniTerminiPagamento, which come from it.payment",
            Severity.WARNING,
        )
    for index, group in enumerate(invoice.vat_breakdown):
        for name, term in (("exemption_reason", "BT-120"), ("exemption_reason_code", "BT-121")):
            if getattr(group, name) is not None:
                yield _finding(
                    NOT_WRITTEN,
                    f"vat_breakdown[{index}].{name}",
                    f"{term} is not written: App. 4.1 builds the exemption reason from 2.2.2.2 Natura and 2.2.2.8 "
                    "RiferimentoNormativo, which come from lines[].it.nature and it.vat_summaries",
                    Severity.WARNING,
                )
