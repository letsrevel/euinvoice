"""Meta-test of :data:`_strategies.invoices`: every model field is drawn both set and, if optional, unset (#89).

A term the strategy never sets can be dropped by a mapper without any round-trip property noticing (in #30 a UBL
writer without BT-10 passed them all). The check is deterministic: a fixed number of derandomized draws, so it
fails the same way on every run and on every machine. 150 draws reach every path today; 300 leave a margin for
changes to the strategy.
"""

import typing as t

import pydantic
from hypothesis import Phase, given, settings

from _strategies import invoices
from euinvoice.model import Invoice
from euinvoice.model._base import EuInvoiceModel
from euinvoice.model.bt_index import BT_INDEX, _unwrap

_DRAWS: t.Final = 300
_REQUIRED_BY_A_VALIDATOR: t.Final = {
    # Identifier.scheme_id is optional in the type, but these fields' validators require it.
    "seller.electronic_address.scheme_id",  # BR-62
    "buyer.electronic_address.scheme_id",  # BR-63
    "lines[].item.standard_identifier.scheme_id",  # BR-64
}


def _field_paths(model: type[pydantic.BaseModel], prefix: str = "") -> dict[str, bool]:
    """Every field path below ``model`` in :data:`BT_INDEX` notation, mapped to whether the field is optional."""
    paths: dict[str, bool] = {}
    for name, field in model.model_fields.items():
        inner, repeated = _unwrap(field.annotation)
        path = f"{prefix}{name}{'[]' if repeated else ''}"
        paths[path] = not field.is_required()
        if isinstance(inner, type) and issubclass(inner, EuInvoiceModel):
            paths.update(_field_paths(inner, f"{path}."))
    return paths


def _observe(model: pydantic.BaseModel, present: set[str], absent: set[str], prefix: str = "") -> None:
    for name in type(model).model_fields:
        value = getattr(model, name)
        repeated = isinstance(value, tuple)
        path = f"{prefix}{name}{'[]' if repeated else ''}"
        (absent if value is None or value == () else present).add(path)
        for item in value if repeated else (value,):
            if isinstance(item, pydantic.BaseModel):
                _observe(item, present, absent, f"{path}.")


def test_every_model_field_is_drawn_set_and_unset() -> None:
    present: set[str] = set()
    absent: set[str] = set()

    @settings(max_examples=_DRAWS, derandomize=True, database=None, phases=[Phase.generate])
    @given(invoices)
    def draw(invoice: Invoice) -> None:
        _observe(invoice, present, absent)

    draw()
    fields = _field_paths(Invoice)
    assert set(BT_INDEX.values()) - {""} <= fields.keys()
    assert sorted(fields.keys() - present) == []
    assert (
        sorted(path for path, optional in fields.items() if optional and path not in absent | _REQUIRED_BY_A_VALIDATOR)
        == []
    )
