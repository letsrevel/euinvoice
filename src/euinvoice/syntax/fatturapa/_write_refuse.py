"""What the FPR12 writer refuses instead of dropping (plan §1; policies of #115 decision 5 in #133).

:func:`refuse_unwritten` walks every business term the invoice sets and refuses each one the writer does not map.
:data:`WRITTEN` is the complete list of terms it maps or derives; anything else would be lost. The terms App. 4.1 of
the SdI "Regole tecniche fatture europee" v2.6 maps to a FatturaPA element the v1 writer does not fill (e.g. BT-29
through "REA:" / "ALBO:" prefixes, BG-13 through DatiTrasporto, BG-24 through Allegati) are refused like the ones
it marks "Mappatura non considerabile" or does not list at all.
"""

import typing as t

import pydantic

from euinvoice.errors import ModelError
from euinvoice.model import Invoice
from euinvoice.model._base import bt_id, extension_of
from euinvoice.syntax.fatturapa._write_format import cannot_express

__all__ = ["WRITTEN", "refuse_unwritten"]

WRITTEN: t.Final = frozenset(
    {
        # Document (App. 4.1 rows 2.1.1.2-2.1.1.11, 2.1.2-2.1.6, 2.2.2.7, 2.4.2.5); BT-3 selects nothing, it is
        # checked against TipoDocumento (App. 5.4); BT-24 identifies an EN 16931 syntax and has no FatturaPA
        # counterpart; BT-20 is reported by preflight (NOT_WRITTEN).
        *("BT-1", "BT-2", "BT-3", "BT-5", "BT-8", "BT-9", "BT-12", "BT-13", "BT-15", "BT-19", "BT-20"),
        *("BG-1", "BT-22", "BG-2", "BT-24", "BG-3", "BT-25", "BT-26"),
        # Seller and buyer (rows 1.2, 1.4)
        *("BG-4", "BT-27", "BT-30", "BT-31", "BG-5", "BT-35", "BT-36", "BT-37", "BT-38", "BT-39", "BT-40"),
        *("BG-6", "BT-42", "BT-43"),
        *("BG-7", "BT-44", "BT-47", "BT-48", "BG-8", "BT-50", "BT-51", "BT-52", "BT-53", "BT-54", "BT-55"),
        # Payment (rows 2.4.2.1, 2.4.2.2, 2.4.2.13, 2.4.2.16, 2.4.2.21)
        *("BG-10", "BT-59", "BG-16", "BT-81", "BT-83", "BG-17", "BT-84", "BT-86"),
        # Stamp duty only (row 2.1.1.6); every other allowance or charge is refused in _stamp_duty.
        *("BG-20", "BT-92", "BT-95", "BT-96", "BT-97", "BT-98", "BG-21", "BT-99", "BT-102", "BT-103"),
        *("BT-104", "BT-105"),
        # Totals: BT-112 (2.1.1.9), BT-114 (2.1.1.10), BT-115 (2.4.2.6); the other sums follow from the lines and
        # summaries written.
        *("BG-22", "BT-106", "BT-107", "BT-108", "BT-109", "BT-110", "BT-112", "BT-114", "BT-115"),
        # VAT breakdown (2.2.2); BT-120 and BT-121 are reported by preflight (NOT_WRITTEN).
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
    "BT-23": "App. 4.1 maps no FatturaPA element to the business process",
    "BT-34": "App. 4.1 maps no FatturaPA element to the seller's electronic address",
    "BT-49": "the SdI routing (CodiceDestinatario, PECDestinatario) comes from WriterOptions, not from the model "
    "(plan M11.3)",
    "BT-154": "App. 4.1 concatenates BT-153 and BT-154 into 2.2.1.4 Descrizione without saying how (#133)",
    "BG-11": "1.3 RappresentanteFiscale has no address, so the tax representative's BG-12 would be lost",
    "BG-27": "2.2.1.10 ScontoMaggiorazione has no place for the reason (BT-139/BT-140) or base amount (BT-137)",
    "BG-28": "2.2.1.10 ScontoMaggiorazione has no place for the reason (BT-144/BT-145) or base amount (BT-142)",
    "BT-149": "2.2.1.9 PrezzoUnitario is the price of one unit (UnitaMisura); there is no base quantity",
    "BT-150": "2.2.1.9 PrezzoUnitario is the price of one unit (UnitaMisura); there is no base quantity unit",
}
_DEFAULT_REASON: t.Final = (
    "App. 4.1 of the Regole tecniche v2.6 maps it to no FatturaPA element, or to one the v1 writer does not fill; "
    "clear it to write the rest"
)


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


def refuse_unwritten(invoice: Invoice) -> None:
    """Refuse an invoice that sets a business term FPR12 cannot carry.

    Args:
        invoice: The invoice.

    Raises:
        ModelError: A term outside :data:`WRITTEN` is set; the message names each such term's id and model path.
    """
    errors = [
        str(cannot_express(f"{i} ({path})", _REASONS.get(i, _DEFAULT_REASON))) for i, path in _unwritten(invoice, "")
    ]
    if errors:
        raise ModelError("; ".join(errors))
