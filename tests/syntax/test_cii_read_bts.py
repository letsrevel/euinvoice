"""Per-term read tests of the CII reader: one row per EN 16931 business term and group.

Each row is ``(id, changes, expected)``. ``changes`` are model overrides applied to
``_cii_invoices.all_terms_invoice()`` (which sets every term CII can carry); the invoice is written with the CII
writer and read back. ``expected`` is the tuple of values found at the term's model path (``BT_INDEX``) in the read
invoice, or, for a group, the number of its instances. The BT id comes first so the BT coverage gate (#32) can read
the table; the XPath each term is read from is in ``test_cii_write_bts.py`` and ``docs/reference/bt-mapping.md``.

The rows are write→read: they prove the reader inverts the writer, not that both bind a term to the right XPath. A
symmetric bug (writer and reader agreeing on a wrong XPath) is caught by the writer's per-term XPath table and by the
conformance suite, which reads every upstream CII example and validates what is written back
(``tests/conformance/test_cii_read_conformance.py``).
"""

import datetime
import typing as t
from decimal import Decimal

import pytest
from _cii_invoices import all_terms_invoice

from _invoices import buyer, payment, rebuild
from euinvoice import _xml
from euinvoice.model import (
    BT_INDEX,
    BinaryObject,
    CreditTransfer,
    Identifier,
    ItemClassificationIdentifier,
    path_of,
)
from euinvoice.syntax import cii

Expected = tuple[t.Any, ...] | int
Row = tuple[str, dict[str, t.Any], Expected]
"""``(BT/BG id, model overrides of the all-terms base, expected)``; ``row[0]`` is the id (#32)."""

READ_ROWS: t.Final[tuple[Row, ...]] = (
    ("BG-0", {}, 1),
    ("BT-1", {}, ("INV-2026-0001",)),
    ("BT-2", {}, (datetime.date(2026, 1, 15),)),
    ("BT-3", {}, ("380",)),
    ("BT-5", {}, ("EUR",)),
    ("BT-6", {}, ("SEK",)),
    ("BT-7", {}, (datetime.date(2026, 1, 10),)),
    ("BT-8", {}, ("35",)),
    ("BT-9", {}, (datetime.date(2026, 2, 14),)),
    ("BT-10", {}, ("BUYER-REF-1",)),
    ("BT-11", {}, ("PROJ-1",)),
    ("BT-12", {}, ("CONTRACT-1",)),
    ("BT-13", {}, ("PO-1",)),
    ("BT-14", {}, ("SO-1",)),
    ("BT-15", {}, ("RA-1",)),
    ("BT-16", {}, ("DA-1",)),
    ("BT-17", {}, ("LOT-1",)),
    ("BT-18", {}, (Identifier(value="OBJ-1", scheme_id="AAA"),)),
    ("BT-19", {}, ("ACC-1",)),
    ("BT-20", {}, ("30 days net",)),
    ("BG-1", {}, 1),
    ("BT-21", {}, ("AAI",)),
    ("BT-22", {}, ("Synthetic test invoice.",)),
    ("BG-2", {}, 1),
    ("BT-23", {}, ("urn:example.com:process:01",)),
    ("BT-24", {}, ("urn:cen.eu:en16931:2017",)),
    ("BG-3", {}, 1),
    ("BT-25", {}, ("INV-2025-0099",)),
    ("BT-26", {}, (datetime.date(2025, 12, 1),)),
    ("BG-4", {}, 1),
    ("BT-27", {}, ("Seller Example GmbH",)),
    ("BT-28", {}, ("Seller Example",)),
    ("BT-29", {}, (Identifier(value="SELLER-1", scheme_id=None), Identifier(value="4000001000005", scheme_id="0088"))),
    ("BT-30", {}, (Identifier(value="HRB 00000", scheme_id="0002"),)),
    ("BT-31", {}, ("DE000000000",)),
    ("BT-32", {}, ("000/000/00000",)),
    ("BT-33", {}, ("Share capital 25 000 EUR",)),
    ("BT-34", {}, (Identifier(value="seller@example.com", scheme_id="EM"),)),
    ("BG-5", {}, 1),
    ("BT-35", {}, ("Example Street 1",)),
    ("BT-36", {}, ("Building A",)),
    ("BT-162", {}, ("Floor 2",)),
    ("BT-37", {}, ("Example City",)),
    ("BT-38", {}, ("10000",)),
    ("BT-39", {}, ("Example State",)),
    ("BT-40", {}, ("DE",)),
    ("BG-6", {}, 1),
    ("BT-41", {}, ("Sales",)),
    ("BT-42", {}, ("+49 000 000000",)),
    ("BT-43", {}, ("sales@example.com",)),
    ("BG-7", {}, 1),
    ("BT-44", {}, ("Buyer Example AG",)),
    ("BT-45", {}, ("Buyer Example",)),
    ("BT-46", {}, (Identifier(value="4000001000036", scheme_id="0088"),)),
    ("BT-47", {}, (Identifier(value="CHE-000.000.000", scheme_id="0183"),)),
    ("BT-48", {}, ("ATU00000000",)),
    ("BT-49", {}, (Identifier(value="buyer@example.com", scheme_id="EM"),)),
    ("BG-8", {}, 1),
    ("BT-50", {}, ("Sample Road 2",)),
    ("BT-51", {}, ("Unit 3",)),
    ("BT-163", {}, ("Back office",)),
    ("BT-52", {}, ("Sample Town",)),
    ("BT-53", {}, ("1010",)),
    ("BT-54", {}, ("Sample Region",)),
    ("BT-55", {}, ("AT",)),
    ("BG-9", {}, 1),
    ("BT-56", {}, ("Accounts payable",)),
    ("BT-57", {}, ("+43 0 000000",)),
    ("BT-58", {}, ("ap@example.com",)),
    ("BG-10", {}, 1),
    ("BT-59", {}, ("Payee Example Ltd",)),
    ("BT-60", {}, (Identifier(value="PAYEE-1", scheme_id=None),)),
    ("BT-61", {}, (Identifier(value="00000000", scheme_id="0002"),)),
    ("BG-11", {}, 1),
    ("BT-62", {}, ("Tax Rep Example SARL",)),
    ("BT-63", {}, ("FR00000000000",)),
    ("BG-12", {}, 1),
    ("BT-64", {}, ("Rue Exemple 3",)),
    ("BT-65", {}, ("Batiment B",)),
    ("BT-164", {}, ("Etage 1",)),
    ("BT-66", {}, ("Exempleville",)),
    ("BT-67", {}, ("75000",)),
    ("BT-68", {}, ("Exemple",)),
    ("BT-69", {}, ("FR",)),
    ("BG-13", {}, 1),
    ("BT-70", {}, ("Warehouse Example",)),
    ("BT-71", {}, (Identifier(value="4000001000012", scheme_id="0088"),)),
    ("BT-72", {}, (datetime.date(2026, 1, 10),)),
    ("BG-14", {}, 1),
    ("BT-73", {}, (datetime.date(2026, 1, 1),)),
    ("BT-74", {}, (datetime.date(2026, 1, 31),)),
    ("BG-15", {}, 1),
    ("BT-75", {}, ("Dock Lane 4",)),
    ("BT-76", {}, ("Gate 5",)),
    ("BT-165", {}, ("Bay 6",)),
    ("BT-77", {}, ("Harbour Town",)),
    ("BT-78", {}, ("20000",)),
    ("BT-79", {}, ("Harbour State",)),
    ("BT-80", {}, ("DE",)),
    ("BG-16", {}, 1),
    ("BT-81", {}, ("58",)),
    ("BT-82", {}, ("SEPA credit transfer",)),
    ("BT-83", {}, ("INV-2026-0001",)),
    ("BG-17", {}, 1),
    ("BT-84", {}, ("DE02120300000000202051",)),
    ("BT-85", {}, ("Seller Example GmbH",)),
    ("BT-86", {}, ("EXAMPLEXXXX",)),
    ("BG-18", {}, 1),
    ("BT-87", {}, ("0000000000",)),
    ("BT-88", {}, ("A. Holder",)),
    ("BG-19", {}, 1),
    ("BT-89", {}, ("MANDATE-1",)),
    ("BT-90", {}, ("DE98ZZZ09999999999",)),
    ("BT-91", {}, ("DE02120300000000202051",)),
    ("BG-20", {}, 1),
    ("BT-92", {}, (Decimal("10.00"),)),
    ("BT-93", {}, (Decimal("100.00"),)),
    ("BT-94", {}, (Decimal("10"),)),
    ("BT-95", {}, ("S",)),
    ("BT-96", {}, (Decimal("19"),)),
    ("BT-97", {}, ("Loyalty discount",)),
    ("BT-98", {}, ("95",)),
    ("BG-21", {}, 1),
    ("BT-99", {}, (Decimal("10.00"),)),
    ("BT-100", {}, (Decimal("100.00"),)),
    ("BT-101", {}, (Decimal("10"),)),
    ("BT-102", {}, ("S",)),
    ("BT-103", {}, (Decimal("19"),)),
    ("BT-104", {}, ("Freight",)),
    ("BT-105", {}, ("FC",)),
    ("BG-24", {}, 1),
    ("BT-122", {}, ("TIMESHEET-1",)),
    ("BT-123", {}, ("Timesheet",)),
    ("BT-124", {}, ("https://example.com/timesheet.pdf",)),
    (
        "BT-125",
        {},
        (BinaryObject(content=b"%PDF-1.7\n\x00\xff", mime_code="application/pdf", filename="timesheet.pdf"),),
    ),
    ("BG-22", {}, 1),
    ("BT-106", {}, (Decimal("150.00"),)),
    ("BT-107", {}, (Decimal("10.00"),)),
    ("BT-108", {}, (Decimal("10.00"),)),
    ("BT-109", {}, (Decimal("150.00"),)),
    ("BT-110", {}, (Decimal("19.00"),)),
    ("BT-111", {}, (Decimal("210.00"),)),
    ("BT-112", {}, (Decimal("169.00"),)),
    ("BT-113", {}, (Decimal("0.00"),)),
    ("BT-114", {}, (Decimal("0.00"),)),
    ("BT-115", {}, (Decimal("169.00"),)),
    ("BG-23", {}, 2),
    ("BT-116", {}, (Decimal("100.00"), Decimal("50.00"))),
    ("BT-117", {}, (Decimal("19.00"), Decimal("0.00"))),
    ("BT-118", {}, ("S", "E")),
    ("BT-119", {}, (Decimal("19"), Decimal("0"))),
    ("BT-120", {}, ("Exempt",)),
    ("BT-121", {}, ("VATEX-EU-132",)),
    ("BG-25", {}, 2),
    ("BT-126", {}, ("1", "2")),
    ("BT-127", {}, ("Line note",)),
    ("BT-128", {}, (Identifier(value="LINE-OBJ-1", scheme_id="AAA"),)),
    ("BT-129", {}, (Decimal("2"), Decimal("1"))),
    ("BT-130", {}, ("C62", "C62")),
    ("BT-132", {}, ("PO-1-10",)),
    ("BT-133", {}, ("ACC-LINE-1",)),
    ("BG-26", {}, 1),
    ("BT-134", {}, (datetime.date(2026, 1, 1),)),
    ("BT-135", {}, (datetime.date(2026, 1, 31),)),
    ("BG-27", {}, 1),
    ("BT-136", {}, (Decimal("5.00"),)),
    ("BT-137", {}, (Decimal("100.00"),)),
    ("BT-138", {}, (Decimal("5"),)),
    ("BT-139", {}, ("Line discount",)),
    ("BT-140", {}, ("95",)),
    ("BG-28", {}, 1),
    ("BT-141", {}, (Decimal("5.00"),)),
    ("BT-142", {}, (Decimal("100.00"),)),
    ("BT-143", {}, (Decimal("5"),)),
    ("BT-144", {}, ("Packing",)),
    ("BT-145", {}, ("ABL",)),
    ("BG-29", {}, 2),
    ("BT-146", {}, (Decimal("50.0000"), Decimal("50"))),
    ("BT-147", {}, (Decimal("0.5"),)),
    ("BT-148", {}, (Decimal("50.5"),)),
    ("BT-149", {}, (Decimal("1"),)),
    ("BT-150", {}, ("C62",)),
    ("BG-30", {}, 2),
    ("BT-151", {}, ("S", "E")),
    ("BT-152", {}, (Decimal("19"), Decimal("0"))),
    ("BG-31", {}, 2),
    ("BT-153", {}, ("Widget", "Exempt service")),
    ("BT-154", {}, ("A synthetic widget",)),
    ("BT-155", {}, ("SKU-1",)),
    ("BT-156", {}, ("BUY-SKU-1",)),
    ("BT-157", {}, (Identifier(value="4000001000029", scheme_id="0160"),)),
    ("BT-158", {}, (ItemClassificationIdentifier(value="43211503", scheme_id="STI", scheme_version_id="19.0501"),)),
    ("BT-159", {}, ("DE",)),
    ("BG-32", {}, 1),
    ("BT-160", {}, ("Colour",)),
    ("BT-161", {}, ("Blue",)),
    ("BT-131", {}, (Decimal("100.00"), Decimal("50.00"))),
    # Alternatives that need a different base value.
    ("BT-8", {"vat_point_date_code": "3"}, ("3",)),
    ("BT-8", {"vat_point_date_code": "432"}, ("432",)),
    ("BT-46", {"buyer": buyer(identifier=Identifier(value="BUYER-1"))}, (Identifier(value="BUYER-1"),)),
    (
        "BT-84",
        {"payment_instructions": payment(credit_transfers=(CreditTransfer(payment_account_identifier="ACCOUNT-1"),))},
        ("ACCOUNT-1",),
    ),
)
"""Every business term and group of the model, with the value(s) the reader must return for it."""


def values_at(model: t.Any, path: str) -> tuple[t.Any, ...]:
    """The values at a ``BT_INDEX`` path (``[]`` flattens a repeated field, ``None`` is skipped)."""
    items = [model]
    for part in filter(None, path.split(".")):
        name = part.removesuffix("[]")
        found: list[t.Any] = []
        for item in items:
            value = getattr(item, name)
            if part.endswith("[]"):
                found.extend(value)
            elif value is not None:
                found.append(value)
        items = found
    return tuple(items)


@pytest.mark.parametrize(
    ("term", "changes", "expected"), READ_ROWS, ids=[f"{r[0]}-{i}" for i, r in enumerate(READ_ROWS)]
)
def test_term_is_read(term: str, changes: dict[str, t.Any], expected: Expected) -> None:
    result = cii.read(_xml.parse(cii.write(rebuild(all_terms_invoice(), **changes))))
    found = values_at(result.invoice, path_of(term))
    assert (len(found) if isinstance(expected, int) else found) == expected, term
    assert result.unmapped == (), term


def test_every_model_term_has_a_row() -> None:
    assert {row[0] for row in READ_ROWS} == set(BT_INDEX)


def test_all_terms_invoice_reads_back_equal() -> None:
    invoice = all_terms_invoice()
    assert cii.read(_xml.parse(cii.write(invoice))).invoice == invoice
