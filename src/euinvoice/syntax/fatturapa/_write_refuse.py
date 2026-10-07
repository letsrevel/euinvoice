"""What FPR12 cannot express, as pre-flight findings (plan §1 "never silently dropped"; policies in #133).

:func:`structure` walks every business term the invoice sets and reports each one the writer does not map
(:data:`WRITTEN` is the complete list of terms it maps or derives), then the content it maps only in part: VAT
categories O/L/M, document level allowances and charges other than a zero stamp duty, a legal registration
identifier that is not a codice fiscale, several credit transfers and an item price discount without a gross price.
The terms App. 4.1 of the SdI "Regole tecniche fatture europee" v2.6 maps to a FatturaPA element the v1 writer does
not fill (e.g. BT-29 through "REA:" / "ALBO:" prefixes, BG-13 through DatiTrasporto, BG-24 through Allegati) are
reported like the ones it marks "Mappatura non considerabile" or does not list at all.
"""

import typing as t
from decimal import Decimal

import pydantic

from euinvoice.model import Identifier, Invoice
from euinvoice.model._base import bt_id, extension_of
from euinvoice.model.codes import VatCategory
from euinvoice.model.it import ItalianExtension, TipoDocumento
from euinvoice.report import Finding
from euinvoice.syntax.fatturapa._write_rules import (
    ALLOWANCE_CHARGE,
    CATEGORY,
    UNSUPPORTED_CATEGORIES,
    UNWRITTEN,
    finding,
)

__all__ = [
    "CODICE_FISCALE_PREFIX",
    "CODICE_FISCALE_SCHEME",
    "STAMP_DUTY_ALLOWANCE",
    "STAMP_DUTY_CHARGE",
    "STAMP_DUTY_REASON",
    "WRITTEN",
    "codice_fiscale",
    "is_stamp_duty_group",
    "stamp_duty",
    "structure",
]

CODICE_FISCALE_SCHEME: t.Final = "0210"
"""ICD scheme of the Italian codice fiscale (App. 4.1 rows 1.2.1.2 and 1.4.1.2: "schemeIdentifier ... 0210")."""
CODICE_FISCALE_PREFIX: t.Final = "CF:"
"""The prefix App. 4.1 rows 1.2.1.2 and 1.4.1.2 put before a codice fiscale in BT-30 / BT-47."""
STAMP_DUTY_CHARGE: t.Final = "SAE"
"""BT-105 of the document level charge that is the stamp duty of an invoice (App. 4.1 row 2.1.1.6)."""
STAMP_DUTY_ALLOWANCE: t.Final = "95"
"""BT-98 of the document level allowance that is the stamp duty of a credit note (App. 4.1 row 2.1.1.6)."""
STAMP_DUTY_REASON: t.Final = "BOLLO"
"""The reason text BR-IT-DC-480 of the Regole tecniche v2.6 (App. 2) gives the stamp duty charge."""

WRITTEN: t.Final = frozenset(
    {
        # Document (App. 4.1 rows 2.1.1.2-2.1.1.11, 2.1.2-2.1.6, 2.2.2.7, 2.4.2.5); BT-3 selects nothing, it is
        # checked against TipoDocumento (App. 5.4); BT-24 identifies an EN 16931 syntax and has no FatturaPA
        # counterpart. BT-20 is not here: its free text has no element (2.4.1 and 2.4.2.4 are codes; #133 item 11).
        *("BT-1", "BT-2", "BT-3", "BT-5", "BT-8", "BT-9", "BT-12", "BT-13", "BT-15", "BT-19"),
        *("BG-1", "BT-22", "BG-2", "BT-24", "BG-3", "BT-25", "BT-26"),
        # Seller and buyer (rows 1.2, 1.4)
        *("BG-4", "BT-27", "BT-30", "BT-31", "BG-5", "BT-35", "BT-36", "BT-37", "BT-38", "BT-39", "BT-40"),
        *("BG-6", "BT-42", "BT-43"),
        *("BG-7", "BT-44", "BT-47", "BT-48", "BG-8", "BT-50", "BT-51", "BT-52", "BT-53", "BT-54", "BT-55"),
        # Payment (rows 2.4.2.1, 2.4.2.2, 2.4.2.13, 2.4.2.16, 2.4.2.21)
        *("BG-10", "BT-59", "BG-16", "BT-81", "BT-83", "BG-17", "BT-84", "BT-86"),
        # Stamp duty only (row 2.1.1.6); every other allowance or charge is reported by _allowances_and_charges.
        *("BG-20", "BT-92", "BT-95", "BT-96", "BT-97", "BT-98", "BG-21", "BT-99", "BT-102", "BT-103"),
        *("BT-104", "BT-105"),
        # Totals: BT-112 (2.1.1.9), BT-114 (2.1.1.10), BT-115 (2.4.2.6); the other sums are checked against the
        # summaries written (preflight TOTALS).
        *("BG-22", "BT-106", "BT-107", "BT-108", "BT-109", "BT-110", "BT-112", "BT-114", "BT-115"),
        # VAT breakdown (2.2.2); BT-120 is RiferimentoNormativo and BT-121 must be the VATEX code of the group's
        # Natura (App. 5.1), both checked by summarize().
        *("BG-23", "BT-116", "BT-117", "BT-118", "BT-119", "BT-120", "BT-121"),
        # Lines (2.2.1); BT-151 is checked against Natura (App. 5.1) and becomes EsigibilitaIVA S for B.
        *("BG-25", "BT-126", "BT-129", "BT-130", "BT-131", "BT-133", "BG-26", "BT-134", "BT-135"),
        *("BG-29", "BT-146", "BT-147", "BT-148", "BG-30", "BT-151", "BT-152", "BG-31", "BT-153"),
    }
)
"""Every business term and group the writer maps or derives. A group listed here is entered; its own terms are
checked one by one."""

_REASONS: t.Final[t.Mapping[str, str]] = {
    "BT-6": "FatturaPA has one currency, Divisa (2.1.1.2); App. 4.1 maps no element to BT-6",
    "BT-20": "App. 4.1 builds it from 2.4.1 CondizioniPagamento and 2.4.2.4 GiorniTerminiPagamento, which are codes "
    "and a number with no place for its free text (#133 item 11); the CondizioniPagamento code comes from it.payment",
    "BT-23": "App. 4.1 maps no FatturaPA element to the business process (#133)",
    "BT-34": "App. 4.1 maps no FatturaPA element to the seller's electronic address (#133)",
    "BT-49": "the SdI routing (CodiceDestinatario, PECDestinatario) comes from Transmission, not from the model "
    "(plan M11.3); CIUS-IT BR-IT-190/200 make BT-49 the 6-character IPA code, which FPR12 refuses (SdI 00427)",
    "BT-154": "App. 4.1 concatenates BT-153 and BT-154 into 2.2.1.4 Descrizione without saying how (#133)",
    "BG-11": "1.3 RappresentanteFiscale has no address, so the tax representative's BG-12 would be lost",
    "BG-27": "2.2.1.10 ScontoMaggiorazione has no place for the reason (BT-139/BT-140, BR-42) or base amount (#133)",
    "BG-28": "2.2.1.10 ScontoMaggiorazione has no place for the reason (BT-144/BT-145, BR-44) or base amount (#133)",
    "BT-149": "2.2.1.9 PrezzoUnitario is the price of one unit (UnitaMisura); there is no base quantity",
    "BT-150": "2.2.1.9 PrezzoUnitario is the price of one unit (UnitaMisura); there is no base quantity unit",
}
_DEFAULT_REASON: t.Final = "no FatturaPA element the v1 writer fills (App. 4.1 of the Regole tecniche v2.6)"


def _is_set(value: object) -> bool:
    return value is not None and value != ()


def _unwritten(model: pydantic.BaseModel, prefix: str) -> t.Iterator[tuple[str, str]]:
    """``(id, path)`` of every set term below ``model`` that is not in :data:`WRITTEN`."""
    cls = type(model)
    for name in cls.model_fields:
        value = getattr(model, name)
        ident = bt_id(cls, name)
        if ident is None or extension_of(cls, name) is not None or not _is_set(value):
            continue  # extension hooks and the untagged parts of a data type (an Identifier's scheme_id)
        path = f"{prefix}{name}"
        if ident not in WRITTEN:
            yield ident, path
        elif ident.startswith("BG-"):
            items = value if isinstance(value, tuple) else (value,)
            for index, item in enumerate(items):
                inner = f"{path}[{index}]." if isinstance(value, tuple) else f"{path}."
                yield from _unwritten(t.cast(pydantic.BaseModel, item), inner)


def _unwritable(term: str, path: str, reason: str) -> Finding:
    return finding(UNWRITTEN, path, f"{term} cannot be written in FatturaPA: {reason}")


def structure(invoice: Invoice, it: ItalianExtension) -> t.Iterator[Finding]:
    """Report every part of the invoice that FPR12 cannot carry, one ``error`` finding each.

    Args:
        invoice: The invoice.
        it: Its ``Invoice.it``.

    Yields:
        ``UNWRITTEN``, ``CATEGORY`` and ``ALLOWANCE_CHARGE`` findings, located by model path.
    """
    for ident, path in _unwritten(invoice, ""):
        yield _unwritable(ident, path, _REASONS.get(ident, _DEFAULT_REASON))
    for term, path, identifier in (
        ("BT-30", "seller.legal_registration_identifier", invoice.seller.legal_registration_identifier),
        ("BT-47", "buyer.legal_registration_identifier", invoice.buyer.legal_registration_identifier),
    ):
        if identifier is not None and _codice_fiscale(identifier) is None:
            yield _unwritable(
                term,
                path,
                f"only a codice fiscale is written (CodiceFiscale, rows 1.2.1.2 / 1.4.1.2): scheme "
                f"{CODICE_FISCALE_SCHEME} or the prefix {CODICE_FISCALE_PREFIX!r}; got scheme {identifier.scheme_id!r}",
            )
    instructions = invoice.payment_instructions
    if instructions is not None and len(instructions.credit_transfers) > 1:
        yield _unwritable(
            "BG-17", "payment_instructions.credit_transfers", "the v1 writer writes one DettaglioPagamento, one IBAN"
        )
    yield from _lines(invoice)
    for index, group in enumerate(invoice.vat_breakdown):
        if VatCategory(group.category_code) in UNSUPPORTED_CATEGORIES:
            yield finding(
                CATEGORY,
                f"vat_breakdown[{index}].category_code",
                f"BT-118 VAT category {group.category_code} has no Natura in App. 5.1 of the Regole tecniche v2.6 "
                "(#133)",
            )
    yield from _allowances_and_charges(invoice, it)


def _lines(invoice: Invoice) -> t.Iterator[Finding]:
    for index, line in enumerate(invoice.lines):
        category = VatCategory(line.vat_information.category_code)
        if category in UNSUPPORTED_CATEGORIES:
            yield finding(
                CATEGORY,
                f"lines[{index}].vat_information.category_code",
                f"BT-151 VAT category {category} has no Natura in App. 5.1 of the Regole tecniche v2.6 (#133)",
            )
        price = line.price_details
        if price.item_price_discount is not None and price.item_price_discount != 0 and price.item_gross_price is None:
            yield _unwritable(
                "BT-147",
                f"lines[{index}].price_details.item_price_discount",
                "2.2.1.9 PrezzoUnitario is the net price BT-146 without a gross price BT-148, so a discount on it "
                "would be applied twice",
            )


def _codice_fiscale(identifier: Identifier) -> str | None:
    """The codice fiscale a legal registration identifier holds (rows 1.2.1.2, 1.4.1.2), or ``None``."""
    if identifier.scheme_id is None and identifier.value.startswith(CODICE_FISCALE_PREFIX):
        return identifier.value.removeprefix(CODICE_FISCALE_PREFIX)
    return identifier.value if identifier.scheme_id == CODICE_FISCALE_SCHEME else None


def codice_fiscale(identifier: Identifier) -> str:
    """The codice fiscale of an identifier :func:`structure` accepted."""
    return t.cast(str, _codice_fiscale(identifier))


type _Entry = tuple[str, str, Decimal, str | None, bool]


def _entries(invoice: Invoice, it: ItalianExtension) -> list[_Entry]:
    """``(path, reason term, amount, reason, is stamp duty)`` of every BG-20 and BG-21."""
    credit_note = it.document_type is TipoDocumento.TD04
    allowances: list[_Entry] = [
        (f"allowances[{i}]", "BT-97", e.amount, e.reason, credit_note and e.reason_code == STAMP_DUTY_ALLOWANCE)
        for i, e in enumerate(invoice.allowances)
    ]
    charges: list[_Entry] = [
        (f"charges[{i}]", "BT-104", e.amount, e.reason, not credit_note and e.reason_code == STAMP_DUTY_CHARGE)
        for i, e in enumerate(invoice.charges)
    ]
    return allowances + charges


def _allowances_and_charges(invoice: Invoice, it: ItalianExtension) -> t.Iterator[Finding]:
    """Only a zero stamp duty is written (2.1.1.6 DatiBollo, App. 4.1); everything else is refused (#133).

    FatturaPA's 2.1.1.8 ScontoMaggiorazione does not reduce the DatiRiepilogo taxable amount that SdI 00422 compares
    with the lines, so it cannot carry BG-20 / BG-21.
    """
    seen = False
    for path, reason_term, amount, reason, is_stamp_duty in _entries(invoice, it):
        group = "BG-20" if path.startswith("allowances") else "BG-21"
        if not is_stamp_duty:
            yield finding(
                ALLOWANCE_CHARGE,
                path,
                f"{group} cannot be written in FatturaPA: only the stamp duty is (2.1.1.6 DatiBollo: BT-105 = SAE on "
                "an invoice, BT-98 = 95 on a credit note, App. 4.1); 2.1.1.8 ScontoMaggiorazione does not reduce the "
                "DatiRiepilogo taxable amount (SdI 00422), so other document level allowances and charges are "
                "refused (#133)",
            )
            continue
        if seen:
            yield finding(ALLOWANCE_CHARGE, path, f"{group}: 2.1.1.6 DatiBollo occurs at most once")
        seen = True
        if amount != 0:
            yield finding(
                ALLOWANCE_CHARGE,
                f"{path}.amount",
                f"{group}: a stamp duty charged to the buyer is not written; its amount would be in the VAT "
                "BREAKDOWN, which DatiRiepilogo cannot carry (SdI 00422), and BR-IT-DC-480 sets it to 0 (#133)",
            )
        if reason is not None and reason != STAMP_DUTY_REASON:
            yield finding(
                ALLOWANCE_CHARGE,
                f"{path}.reason",
                f"{reason_term}: 2.1.1.6 DatiBollo has no reason; only {STAMP_DUTY_REASON!r} (BR-IT-DC-480) is implied",
            )


def stamp_duty(invoice: Invoice, it: ItalianExtension) -> Decimal | None:
    """ImportoBollo: the amount of the stamp duty allowance or charge, or ``None`` (after :func:`structure`)."""
    return next((entry[2] for entry in _entries(invoice, it) if entry[4]), None)


def is_stamp_duty_group(invoice: Invoice, it: ItalianExtension, category: str, rate: Decimal | None) -> bool:
    """Whether a VAT BREAKDOWN with no lines is the stamp duty's own (BR-IT-DC-480 puts it in category Z).

    Only a zero stamp duty is written, so such a breakdown carries nothing but its category: DatiBollo stands for it.
    """
    if it.document_type is TipoDocumento.TD04:
        sources = [
            (a.vat_category_code, a.vat_rate) for a in invoice.allowances if a.reason_code == STAMP_DUTY_ALLOWANCE
        ]
    else:
        sources = [(c.vat_category_code, c.vat_rate) for c in invoice.charges if c.reason_code == STAMP_DUTY_CHARGE]
    return (category, rate) in sources
