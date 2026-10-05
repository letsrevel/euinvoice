"""EN 16931 calculation: derive line net amounts, document totals and the VAT breakdown (D11).

:func:`complete` turns an :class:`~euinvoice.model.InvoiceDraft` into an :class:`~euinvoice.model.Invoice`
by deriving BT-131 per line, the DOCUMENT TOTALS (BG-22) and the VAT BREAKDOWN (BG-23).
:func:`check` reports where the amounts of a complete invoice, for example one whose totals the
consumer supplied, break the CEN arithmetic and VAT category rules. Both are pure: no I/O.

Every rule was read from the pinned CEN validation artifacts ``validation-1.3.16``:
``schematron/abstract/EN16931-model.sch`` (rule ids and texts; every rule used here is
``flag="fatal"``) and the bindings ``schematron/UBL/EN16931-UBL-model.sch`` and
``schematron/CII/EN16931-CII-model.sch`` (the tests).

Rounding (D11): amounts are rounded to two decimals half up, ties away from zero (``ROUND_HALF_UP``),
at the two places a product is rounded: the line net amount and the VAT category tax amount
(BR-CO-17). Every other total is a sum or difference of two-decimal amounts and needs no rounding.
The Schematron's XPath ``round()`` breaks ties towards positive infinity instead; the two differ only
on negative ties, and BR-CO-17 compares absolute values, so the difference never changes an outcome.

Where the two bindings test one rule with different tolerances, :func:`check` applies the stricter
test, so an invoice it accepts passes that rule in either syntax:

* BR-CO-17 and BR-S/AF/AG-09 accept a VAT amount within 1 of the rounded product; UBL compares with
  strict ``<`` / ``>`` (CII's BR-CO-17 uses ``<=`` / ``>=``), so a difference of exactly 1 is flagged.
* The ``-08`` taxable amount rules: UBL tests BR-Z/E/AE/IC/G/O-08 with exact equality and CII tests
  BR-S/AF/AG/O-08 with exact equality (the other binding tolerates a difference below 1), so every
  ``-08`` rule is checked exactly.
* BR-AF-05/06/07 (IGIC rate): UBL accepts ``>= 0`` and CII ``> 0``; the rate must be greater than zero.

Line net amount (BT-131): EN 16931 has no rule that computes BT-131 (the CEN Schematron only requires
it, BR-24, and limits its decimals, BR-DEC-23). :func:`line_net_amount` follows Peppol BIS 3.0.21 rule
PEPPOL-EN16931-R120 (``rules/sch/PEPPOL-EN16931-UBL.sch``) as the convention: invoiced quantity *
(item net price / item price base quantity) + Σ line charges - Σ line allowances. :func:`check` does
not test it, since no CEN rule does.
"""

from euinvoice.calc._check import SOURCE, check
from euinvoice.calc._complete import ExemptionReason, complete, line_net_amount

__all__ = ["SOURCE", "ExemptionReason", "check", "complete", "line_net_amount"]
