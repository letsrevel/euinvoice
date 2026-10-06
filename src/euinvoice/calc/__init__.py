r"""EN 16931 calculation: derive line net amounts, document totals and the VAT breakdown (D11).

:func:`complete` turns an :class:`~euinvoice.model.InvoiceDraft` into an :class:`~euinvoice.model.Invoice`
by deriving BT-131 per line, the DOCUMENT TOTALS (BG-22) and the VAT BREAKDOWN (BG-23).
:func:`check` reports where a complete invoice, for example one whose totals the consumer supplied,
breaks the CEN arithmetic, VAT category and period date rules. Both are pure: no I/O.

Sources: the pinned CEN validation artifacts ``validation-1.3.16``. Rule ids and texts come from the
abstract patterns (``schematron/abstract/EN16931-model.sch`` of the UBL package and
``schematron/abstract/EN16931-CII-model.sch`` of the CII package; every rule used here is
``flag="fatal"`` in both), the tests from the bindings ``schematron/UBL/EN16931-UBL-model.sch`` and
``schematron/CII/EN16931-CII-model.sch``.

Rounding (D11): amounts are rounded to two decimals half up, ties away from zero (``ROUND_HALF_UP``),
at the two places a product is rounded: the line net amount and the VAT category tax amount
(BR-CO-17). Every other total is a sum or difference of two-decimal amounts and needs no rounding.
The Schematron's XPath ``round()`` breaks ties towards positive infinity instead; the two differ only
on negative ties, and BR-CO-17 compares absolute values, so the difference never changes an outcome.

Severity policy (D8): :func:`check` evaluates every rule as **both** bindings test it. Given a
target ``syntax`` (:class:`euinvoice.syntax.Syntax`), it reports each rule that binding rejects as
``fatal`` under the official id and ignores the other binding. Without one, a rule is ``fatal`` only
when its test fails in both bindings; when only one binding rejects it, the invoice is valid in one
syntax and not in the other, and :func:`check` reports a ``warning`` with rule id
:data:`PORTABILITY` (``EUINV-CALC-PORTABILITY``) whose message names the official rule and the
rejecting binding. Either way a ``fatal`` id is one the official Schematron of that syntax (or of
both) reports too. The output of :func:`complete` passes both bindings. The asymmetric cases, with ``n`` lines, ``a``
document level allowances and charges and ``b`` VAT breakdowns of one category:

* BR-CO-15. UBL: exactly one VAT total in BT-5 and BT-112 = BT-109 + BT-110. CII: the same, *or*
  BT-112 = BT-109 (which accepts an absent or ignored BT-110). BT-6 = BT-5 with BT-111 puts two VAT
  totals in BT-5, so only CII's second disjunct can pass.
* BR-CO-17. Both: \|BT-117\| within 1 of the rounded product; UBL with strict ``<`` / ``>``, CII with
  ``<=`` / ``>=``.
* BR-48, BR-CO-17 on an L, M or O breakdown. UBL: tested. CII: never run. Its single pattern binds
  ``$VATAF``, ``$VATAG`` and ``$VATO`` to the same ``ram:ApplicableTradeTax`` node as
  ``$VAT_breakdown`` and lists them first, and Schematron fires only the first matching rule per node.
* BR-AF-09, BR-AG-09. UBL: within 1, strict. CII: ``true()`` (not tested).
* BR-AF-05/06/07. UBL: rate ``>= 0``. CII: rate ``> 0``.
* BR-S-08. UBL, by XPath precedence: (the rate occurs on a line, allowance or charge and within 1 of
  the full sum) *or* (a document level allowance or charge has the rate and within 1 of charges -
  allowances; the credit-note branch on an invoice, and vice versa). CII: exact.
* BR-AF-08, BR-AG-08. UBL: within 1. CII: exact.
* BR-Z/E/AE/IC/G-08. UBL: exact. CII: within 1.
* BR-S/AF/AG-01. UBL: ``(n + a > 0) = (b > 0)``. CII: ``(n = 0 or n + b >= 2) and (a = 0 or a + b >= 2)``.
* BR-Z/E/AE/IC/G-01. UBL: ``b = 1 or n + a + b = 0`` (its ``//cac:TaxCategory`` also matches the
  breakdown itself). CII: ``n + a + b = 0 or (b = 1 and n + a > 0)``.
* BR-O-01. UBL: as BR-Z-01. CII: ``b = 0 or (b = 1 and n + a > 0)``.
* BR-53. UBL: a ``cbc:TaxAmount`` in BT-6 (BT-110 is one when BT-6 = BT-5). CII: BT-111 in BT-6 and
  BT-6 != BT-5.
* BR-CO-19. CII: BT-73 or BT-74 in BG-14. UBL: the same, or ``cbc:DescriptionCode`` in the same
  ``cac:InvoicePeriod``, which holds BT-8; so UBL accepts an undated BG-14 when BT-8 is present.
* BR-O-11 … 14 (with an O breakdown). UBL: other breakdowns (11), non-O lines (12), allowances (13)
  and charges (14), each apart. CII: 11 and 12 both test breakdowns and lines, 13 and 14 both
  allowances and charges; each offending item is fatal under its own rule and fails its partner rule
  in CII only.

Every other rule :func:`check` reports tests the same in both bindings (BR-CO-10 … 14, BR-CO-16,
BR-48, ``-05``/``-06``/``-07`` except IGIC, BR-O-08, ``-09`` except IGIC/IPSI, ``-10``, BR-B-02,
BR-29, BR-30 and BR-CO-20).

Line net amount (BT-131): EN 16931 has no rule that computes BT-131 (the CEN Schematron only requires
it, BR-24, and limits its decimals, BR-DEC-23). :func:`line_net_amount` uses the formula of Peppol
BIS 3.0.21 rule PEPPOL-EN16931-R120 (``rules/sch/PEPPOL-EN16931-UBL.sch``): invoiced quantity *
(item net price / item price base quantity) + line charges - line allowances, rounded half up per
D11 (R120 itself allows a slack of 0.02). :func:`check` does not test it, since no CEN rule does.
"""

from euinvoice.calc._check import check
from euinvoice.calc._common import PORTABILITY, SOURCE
from euinvoice.calc._complete import ExemptionReason, complete, line_net_amount

__all__ = ["PORTABILITY", "SOURCE", "ExemptionReason", "check", "complete", "line_net_amount"]
