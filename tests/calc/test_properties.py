"""Hypothesis invariants of ``calc.complete``: the BR-CO-10 … BR-CO-17 equivalents hold for any draft.

Quantities, prices and allowances may be negative (credit notes, corrections), and prices carry up to
four decimals, so ties at the rounding points, negative ones included, occur often.
"""

from decimal import Decimal, localcontext

from _calc_drafts import allowance, charge, draft, line
from hypothesis import given
from hypothesis import strategies as st

from euinvoice import calc
from euinvoice.calc._common import CATEGORY_RULES
from euinvoice.model import DocumentLevelAllowance, DocumentLevelCharge, Invoice, InvoiceDraft, LineDraft

# (category, rate) pairs that satisfy BR-<x>-05/06/07; the exemption reason is added where -10 needs one.
VALID: list[tuple[str, str | None]] = [
    ("S", "20"),
    ("S", "10"),
    ("S", "13"),
    ("S", "7.7"),
    ("S", "1"),
    ("Z", "0"),
    ("E", "0"),
    ("AE", "0"),
]
VALID += [("K", "0"), ("G", "0"), ("O", None), ("L", "7"), ("M", "0"), ("M", "4"), ("B", "22")]


def decimals(places: int, bound: int = 10_000) -> st.SearchStrategy[str]:
    """Decimal strings with up to ``places`` fraction digits in [-bound, bound]."""
    return st.decimals(-bound, bound, places=places, allow_nan=False, allow_infinity=False).map(
        lambda d: format(d, "f")
    )


category_rates = st.sampled_from(VALID)


@st.composite
def lines(draw: st.DrawFn) -> LineDraft:
    category, rate = draw(category_rates)
    return line(
        draw(decimals(3, 1_000)),
        draw(decimals(4).filter(lambda p: Decimal(p) >= 0)),  # BR-27: net price not negative
        category,
        rate,
        base_quantity=draw(st.none() | st.sampled_from(["1", "3", "12", "0.5"])),
        allowances=draw(st.lists(decimals(2, 100), max_size=2)),
        charges=draw(st.lists(decimals(2, 100), max_size=2)),
    )


@st.composite
def drafts(draw: st.DrawFn) -> InvoiceDraft:
    drawn = draw(st.lists(lines(), min_size=1, max_size=6))
    used = [(ln.vat_information.category_code, ln.vat_information.rate) for ln in drawn]

    def rate_text(rate: Decimal | None) -> str | None:
        return None if rate is None else format(rate, "f")

    allowances: list[DocumentLevelAllowance] = []
    charges: list[DocumentLevelCharge] = []
    for _ in range(draw(st.integers(0, 2))):
        category, rate = draw(st.sampled_from(used))
        allowances.append(allowance(draw(decimals(2, 500)), category, rate_text(rate)))
    for _ in range(draw(st.integers(0, 2))):
        category, rate = draw(st.sampled_from(used))
        charges.append(charge(draw(decimals(2, 500)), category, rate_text(rate)))
    numbered = (LineDraft.model_validate({**dict(ln), "identifier": str(i)}) for i, ln in enumerate(drawn))
    return draft(*numbered, allowances=allowances, charges=charges)


def complete(d: InvoiceDraft, paid: str | None = None, rounding: str | None = None) -> Invoice:
    used = {ln.vat_information.category_code for ln in d.lines}
    used |= {a.vat_category_code for a in d.allowances} | {c.vat_category_code for c in d.charges}
    reasons = {
        c: calc.ExemptionReason(text="Exemption text")
        for c in used
        if c in CATEGORY_RULES and CATEGORY_RULES[c].needs_reason
    }
    return calc.complete(
        d,
        paid_amount=None if paid is None else Decimal(paid),
        rounding_amount=None if rounding is None else Decimal(rounding),
        exemption_reasons=reasons,
    )


def two_places(value: Decimal) -> bool:
    return value == value.quantize(Decimal("0.01"))


@given(drafts(), st.none() | decimals(2), st.none() | decimals(2, 1))
def test_completed_drafts_pass_check(d: InvoiceDraft, paid: str | None, rounding: str | None) -> None:
    assert calc.check(complete(d, paid, rounding)) == ()


@given(drafts(), st.none() | decimals(2), st.none() | decimals(2, 1))
def test_br_co_equivalents(d: InvoiceDraft, paid: str | None, rounding: str | None) -> None:
    invoice = complete(d, paid, rounding)
    totals = invoice.totals
    zero = Decimal(0)

    assert totals.sum_of_line_net_amounts == sum(ln.net_amount for ln in invoice.lines)  # BR-CO-10
    assert (totals.sum_of_allowances or zero) == sum(a.amount for a in d.allowances)  # BR-CO-11
    assert (totals.sum_of_charges or zero) == sum(c.amount for c in d.charges)  # BR-CO-12
    assert totals.total_without_vat == (
        totals.sum_of_line_net_amounts - (totals.sum_of_allowances or zero) + (totals.sum_of_charges or zero)
    )  # BR-CO-13
    assert totals.total_vat == sum(g.tax_amount for g in invoice.vat_breakdown)  # BR-CO-14
    assert totals.total_with_vat == totals.total_without_vat + (totals.total_vat or zero)  # BR-CO-15
    assert totals.amount_due == (
        totals.total_with_vat - (totals.paid_amount or zero) + (totals.rounding_amount or zero)
    )  # BR-CO-16
    for group in invoice.vat_breakdown:  # BR-CO-17: exact half-up rounding, no tolerance needed
        if group.rate is None:
            assert group.tax_amount == 0
        else:
            with localcontext(prec=60):
                exact = group.taxable_amount * group.rate / 100
            assert abs(group.tax_amount - exact) <= Decimal("0.005")
            assert abs(group.tax_amount) == abs(exact).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
    # the VAT breakdown covers every taxable amount exactly once
    assert sum(g.taxable_amount for g in invoice.vat_breakdown) == totals.total_without_vat
    assert all(two_places(v) for v in dict(totals).values() if v is not None)


@given(decimals(2, 1_000), st.sampled_from(["1", "5", "10", "15", "25"]))
def test_negative_ties_round_away_from_zero(taxable: str, rate: str) -> None:
    """D11: half up = ties away from zero, so a credit note mirrors its invoice to the cent."""
    invoice = complete(draft(line("1", taxable.lstrip("-") or "0", "S", rate)))
    credit = complete(draft(line("-1", taxable.lstrip("-") or "0", "S", rate), type_code="381"))

    assert credit.vat_breakdown[0].tax_amount == -invoice.vat_breakdown[0].tax_amount
    assert calc.check(credit) == ()


def test_negative_tie_examples() -> None:
    """-0.50 x 1 % = -0.005, -1.25 x 2 % and -0.10 x 25 % = -0.025: ties, rounded away from zero."""
    for taxable, rate, expected in [("0.50", "1", "-0.01"), ("1.25", "2", "-0.03"), ("0.10", "25", "-0.03")]:
        credit = complete(draft(line("-1", taxable, "S", rate), type_code="381"))
        assert credit.vat_breakdown[0].tax_amount == Decimal(expected)
        assert calc.check(credit) == ()
