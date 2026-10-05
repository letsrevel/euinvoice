"""The BT/BG registry: every EN 16931 id exactly once, real paths, and docs/reference/bt-mapping.md in sync."""

import re
import typing as t
from pathlib import Path

import pydantic
import pytest

from euinvoice.model import BT_INDEX, Invoice, id_of, path_of
from euinvoice.model._base import EuInvoiceModel, bt, bt_id
from euinvoice.model.bt_index import PATH_INDEX, _unwrap, build_index

# Every EN 16931 business group and business term with its name, as listed in the XRechnung 3.0.2
# specification, chapter 11 "Detailbeschreibung" (xeinkauf.de, 302-XRechnung-2024-06-20.pdf): 32 groups
# BG-1..BG-32 and 164 terms BT-1..BT-165. BT-4 does not exist in EN 16931: no source has it (XRechnung
# spec, Peppol BIS 3.0.21 structure/syntax/ubl-invoice.xml, KoSIT xrechnung-visualization, CEN 1.3.16
# Schematron). Cross-checked: every id cited by the CEN Schematron is in this list, and the Peppol and
# KoSIT bindings cover all of them. BG-0 (the root) is a library convention, see bt-mapping.md.
EN16931_IDS: t.Final[dict[str, str]] = {
    "BG-1": "INVOICE NOTE",
    "BG-2": "PROCESS CONTROL",
    "BG-3": "PRECEDING INVOICE REFERENCE",
    "BG-4": "SELLER",
    "BG-5": "SELLER POSTAL ADDRESS",
    "BG-6": "SELLER CONTACT",
    "BG-7": "BUYER",
    "BG-8": "BUYER POSTAL ADDRESS",
    "BG-9": "BUYER CONTACT",
    "BG-10": "PAYEE",
    "BG-11": "SELLER TAX REPRESENTATIVE PARTY",
    "BG-12": "SELLER TAX REPRESENTATIVE POSTAL ADDRESS",
    "BG-13": "DELIVERY INFORMATION",
    "BG-14": "INVOICING PERIOD",
    "BG-15": "DELIVER TO ADDRESS",
    "BG-16": "PAYMENT INSTRUCTIONS",
    "BG-17": "CREDIT TRANSFER",
    "BG-18": "PAYMENT CARD INFORMATION",
    "BG-19": "DIRECT DEBIT",
    "BG-20": "DOCUMENT LEVEL ALLOWANCES",
    "BG-21": "DOCUMENT LEVEL CHARGES",
    "BG-22": "DOCUMENT TOTALS",
    "BG-23": "VAT BREAKDOWN",
    "BG-24": "ADDITIONAL SUPPORTING DOCUMENTS",
    "BG-25": "INVOICE LINE",
    "BG-26": "INVOICE LINE PERIOD",
    "BG-27": "INVOICE LINE ALLOWANCES",
    "BG-28": "INVOICE LINE CHARGES",
    "BG-29": "PRICE DETAILS",
    "BG-30": "LINE VAT INFORMATION",
    "BG-31": "ITEM INFORMATION",
    "BG-32": "ITEM ATTRIBUTES",
    "BT-1": "Invoice number",
    "BT-2": "Invoice issue date",
    "BT-3": "Invoice type code",
    "BT-5": "Invoice currency code",
    "BT-6": "VAT accounting currency code",
    "BT-7": "Value added tax point date",
    "BT-8": "Value added tax point date code",
    "BT-9": "Payment due date",
    "BT-10": "Buyer reference",
    "BT-11": "Project reference",
    "BT-12": "Contract reference",
    "BT-13": "Purchase order reference",
    "BT-14": "Sales order reference",
    "BT-15": "Receiving advice reference",
    "BT-16": "Despatch advice reference",
    "BT-17": "Tender or lot reference",
    "BT-18": "Invoiced object identifier",
    "BT-19": "Buyer accounting reference",
    "BT-20": "Payment terms",
    "BT-21": "Invoice note subject code",
    "BT-22": "Invoice note",
    "BT-23": "Business process type",
    "BT-24": "Specification identifier",
    "BT-25": "Preceding Invoice reference",
    "BT-26": "Preceding Invoice issue date",
    "BT-27": "Seller name",
    "BT-28": "Seller trading name",
    "BT-29": "Seller identifier",
    "BT-30": "Seller legal registration identifier",
    "BT-31": "Seller VAT identifier",
    "BT-32": "Seller tax registration identifier",
    "BT-33": "Seller additional legal information",
    "BT-34": "Seller electronic address",
    "BT-35": "Seller address line 1",
    "BT-36": "Seller address line 2",
    "BT-37": "Seller city",
    "BT-38": "Seller post code",
    "BT-39": "Seller country subdivision",
    "BT-40": "Seller country code",
    "BT-41": "Seller contact point",
    "BT-42": "Seller contact telephone number",
    "BT-43": "Seller contact email address",
    "BT-44": "Buyer name",
    "BT-45": "Buyer trading name",
    "BT-46": "Buyer identifier",
    "BT-47": "Buyer legal registration identifier",
    "BT-48": "Buyer VAT identifier",
    "BT-49": "Buyer electronic address",
    "BT-50": "Buyer address line 1",
    "BT-51": "Buyer address line 2",
    "BT-52": "Buyer city",
    "BT-53": "Buyer post code",
    "BT-54": "Buyer country subdivision",
    "BT-55": "Buyer country code",
    "BT-56": "Buyer contact point",
    "BT-57": "Buyer contact telephone number",
    "BT-58": "Buyer contact email address",
    "BT-59": "Payee name",
    "BT-60": "Payee identifier",
    "BT-61": "Payee legal registration identifier",
    "BT-62": "Seller tax representative name",
    "BT-63": "Seller tax representative VAT identifier",
    "BT-64": "Tax representative address line 1",
    "BT-65": "Tax representative address line 2",
    "BT-66": "Tax representative city",
    "BT-67": "Tax representative post code",
    "BT-68": "Tax representative country subdivision",
    "BT-69": "Tax representative country code",
    "BT-70": "Deliver to party name",
    "BT-71": "Deliver to location identifier",
    "BT-72": "Actual delivery date",
    "BT-73": "Invoicing period start date",
    "BT-74": "Invoicing period end date",
    "BT-75": "Deliver to address line 1",
    "BT-76": "Deliver to address line 2",
    "BT-77": "Deliver to city",
    "BT-78": "Deliver to post code",
    "BT-79": "Deliver to country subdivision",
    "BT-80": "Deliver to country code",
    "BT-81": "Payment means type code",
    "BT-82": "Payment means text",
    "BT-83": "Remittance information",
    "BT-84": "Payment account identifier",
    "BT-85": "Payment account name",
    "BT-86": "Payment service provider identifier",
    "BT-87": "Payment card primary account number",
    "BT-88": "Payment card holder name",
    "BT-89": "Mandate reference identifier",
    "BT-90": "Bank assigned creditor identifier",
    "BT-91": "Debited account identifier",
    "BT-92": "Document level allowance amount",
    "BT-93": "Document level allowance base amount",
    "BT-94": "Document level allowance percentage",
    "BT-95": "Document level allowance VAT category code",
    "BT-96": "Document level allowance VAT rate",
    "BT-97": "Document level allowance reason",
    "BT-98": "Document level allowance reason code",
    "BT-99": "Document level charge amount",
    "BT-100": "Document level charge base amount",
    "BT-101": "Document level charge percentage",
    "BT-102": "Document level charge VAT category code",
    "BT-103": "Document level charge VAT rate",
    "BT-104": "Document level charge reason",
    "BT-105": "Document level charge reason code",
    "BT-106": "Sum of Invoice line net amount",
    "BT-107": "Sum of allowances on document level",
    "BT-108": "Sum of charges on document level",
    "BT-109": "Invoice total amount without VAT",
    "BT-110": "Invoice total VAT amount",
    "BT-111": "Invoice total VAT amount in accounting currency",
    "BT-112": "Invoice total amount with VAT",
    "BT-113": "Paid amount",
    "BT-114": "Rounding amount",
    "BT-115": "Amount due for payment",
    "BT-116": "VAT category taxable amount",
    "BT-117": "VAT category tax amount",
    "BT-118": "VAT category code",
    "BT-119": "VAT category rate",
    "BT-120": "VAT exemption reason text",
    "BT-121": "VAT exemption reason code",
    "BT-122": "Supporting document reference",
    "BT-123": "Supporting document description",
    "BT-124": "External document location",
    "BT-125": "Attached document",
    "BT-126": "Invoice line identifier",
    "BT-127": "Invoice line note",
    "BT-128": "Invoice line object identifier",
    "BT-129": "Invoiced quantity",
    "BT-130": "Invoiced quantity unit of measure code",
    "BT-131": "Invoice line net amount",
    "BT-132": "Referenced purchase order line reference",
    "BT-133": "Invoice line Buyer accounting reference",
    "BT-134": "Invoice line period start date",
    "BT-135": "Invoice line period end date",
    "BT-136": "Invoice line allowance amount",
    "BT-137": "Invoice line allowance base amount",
    "BT-138": "Invoice line allowance percentage",
    "BT-139": "Invoice line allowance reason",
    "BT-140": "Invoice line allowance reason code",
    "BT-141": "Invoice line charge amount",
    "BT-142": "Invoice line charge base amount",
    "BT-143": "Invoice line charge percentage",
    "BT-144": "Invoice line charge reason",
    "BT-145": "Invoice line charge reason code",
    "BT-146": "Item net price",
    "BT-147": "Item price discount",
    "BT-148": "Item gross price",
    "BT-149": "Item price base quantity",
    "BT-150": "Item price base quantity unit of measure code",
    "BT-151": "Invoiced item VAT category code",
    "BT-152": "Invoiced item VAT rate",
    "BT-153": "Item name",
    "BT-154": "Item description",
    "BT-155": "Item Sellers identifier",
    "BT-156": "Item Buyers identifier",
    "BT-157": "Item standard identifier",
    "BT-158": "Item classification identifier",
    "BT-159": "Item country of origin",
    "BT-160": "Item attribute name",
    "BT-161": "Item attribute value",
    "BT-162": "Seller address line 3",
    "BT-163": "Buyer address line 3",
    "BT-164": "Tax representative address line 3",
    "BT-165": "Deliver to address line 3",
}

DOC = Path(__file__).parents[2] / "docs" / "reference" / "bt-mapping.md"


def test_the_official_list_has_32_groups_and_164_terms() -> None:
    assert sum(ident.startswith("BG-") for ident in EN16931_IDS) == 32
    assert sum(ident.startswith("BT-") for ident in EN16931_IDS) == 164
    assert "BT-4" not in EN16931_IDS


def test_every_en16931_id_appears_exactly_once_in_the_index() -> None:
    # build_index() raises on an id declared twice, so equal key sets mean "exactly once".
    assert set(BT_INDEX) == set(EN16931_IDS) | {"BG-0"}
    assert len(set(BT_INDEX.values())) == len(BT_INDEX)


def test_a_duplicated_id_is_refused() -> None:
    class _Twice(EuInvoiceModel):
        a: t.Annotated[str, bt("BT-1")]
        b: t.Annotated[str, bt("BT-1")]

    with pytest.raises(ValueError, match="BT-1 is declared twice"):
        build_index(_Twice)


def test_lookups_are_inverse() -> None:
    assert path_of("BT-153") == "lines[].item.name"
    assert id_of("lines[].item.name") == "BT-153"
    assert path_of("BG-0") == ""
    assert all(id_of(path_of(ident)) == ident for ident in BT_INDEX)
    assert PATH_INDEX["seller.postal_address.country_code"] == "BT-40"
    with pytest.raises(KeyError):
        path_of("BT-4")


def _group_models(model: type[pydantic.BaseModel]) -> t.Iterator[type[pydantic.BaseModel]]:
    yield model
    for name, field in model.model_fields.items():
        inner, _ = _unwrap(field.annotation)
        if bt_id(model, name) is not None and bt_id(model, name).startswith("BG-"):  # type: ignore[union-attr]  # checked just before
            yield from _group_models(inner)


def test_every_field_of_every_group_carries_an_id() -> None:
    for model in _group_models(Invoice):
        untagged = [name for name in model.model_fields if bt_id(model, name) is None]
        assert not untagged, (model.__name__, untagged)


def _resolve(node: t.Any, path: str) -> list[t.Any]:
    values = [node]
    for part in filter(None, path.split(".")):
        name, repeated = part.removesuffix("[]"), part.endswith("[]")
        values = [getattr(value, name) for value in values]
        if repeated:
            values = [item for value in values for item in value]
    return values


def test_every_path_resolves_on_the_full_invoice(invoice: Invoice) -> None:
    for ident, path in BT_INDEX.items():
        values = _resolve(invoice, path)
        assert values, ident
        assert any(value not in (None, ()) for value in values), ident  # the fixture sets every term


def _model_cardinalities() -> dict[str, str]:
    cards = {"BG-0": "1"}
    for model in _group_models(Invoice):
        for name, field in model.model_fields.items():
            _, repeated = _unwrap(field.annotation)
            ident = bt_id(model, name)
            assert ident is not None
            required = field.is_required()
            cards[ident] = ("1..n" if required else "0..n") if repeated else ("1" if required else "0..1")
    return cards


_ROW = re.compile(r"^\| (B[GT]-\d+) \| ([^|]+) \| `([^`]*)` \| (1|0\.\.1|0\.\.n|1\.\.n) \|")


def test_bt_mapping_doc_matches_the_model() -> None:
    rows = {m[1]: (m[2].strip(), m[3], m[4]) for m in map(_ROW.match, DOC.read_text().splitlines()) if m}
    assert set(rows) == set(BT_INDEX)
    cards = _model_cardinalities()
    for ident, (name, path, card) in rows.items():
        assert path == (BT_INDEX[ident] or "(root)"), ident
        assert card == cards[ident], ident
        assert name == EN16931_IDS.get(ident, "INVOICE (root)"), ident
