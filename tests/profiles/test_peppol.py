"""Tests for the Peppol BIS Billing 3.0 profile and its pre-flight checks (offline).

That each pre-flight rule agrees with the official Schematron is checked in
``tests/conformance/test_peppol_official.py``.
"""

import datetime
import typing as t
from decimal import Decimal

import pytest

from _calc_drafts import not_subject_to_vat
from _invoices import TEST_IBAN, minimal_invoice, peppol_invoice, rebuild, simple_line
from euinvoice import profiles
from euinvoice.model import (
    Buyer,
    BuyerPostalAddress,
    CreditTransfer,
    DeliveryInformation,
    DirectDebit,
    DocumentLevelAllowance,
    DocumentLevelCharge,
    DocumentTotals,
    Invoice,
    InvoiceLineAllowance,
    InvoiceLineCharge,
    InvoiceLinePeriod,
    InvoiceNote,
    InvoicingPeriod,
    PaymentInstructions,
    PriceDetails,
    ProcessControl,
    Seller,
    SellerPostalAddress,
)
from euinvoice.profiles import PEPPOL, peppol
from euinvoice.report import Severity
from euinvoice.syntax import Syntax

BT24 = "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
BT23 = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
SYNTAXES = pytest.mark.parametrize("syntax", [Syntax.UBL, Syntax.CII])
UBL, CII = Syntax.UBL, Syntax.CII


def ids(invoice: Invoice, syntax: Syntax) -> list[str]:
    return [f.rule_id.removeprefix("PEPPOL-EN16931-") for f in PEPPOL.preflight(invoice, syntax)]


def process(bt23: str | None, bt24: str = BT24) -> ProcessControl:
    return ProcessControl(business_process_type=bt23, specification_identifier=bt24)


def german(invoice: Invoice) -> Invoice:
    """``invoice`` with seller and buyer in Germany (the R002 exception in UBL)."""
    seller = Seller.model_validate({**dict(invoice.seller), "postal_address": SellerPostalAddress(country_code="DE")})
    buyer = Buyer.model_validate({**dict(invoice.buyer), "postal_address": BuyerPostalAddress(country_code="DE")})
    return rebuild(invoice, seller=seller, buyer=buyer)


class TestProfile:
    def test_declares_the_peppol_identifiers(self) -> None:
        assert PEPPOL.id == "peppol"
        assert PEPPOL.specification_identifier == BT24 == peppol.SPECIFICATION_IDENTIFIER
        assert PEPPOL.business_process_type == BT23 == peppol.BILLING_PROCESS

    def test_supports_ubl_and_cii_and_runs_cen_then_peppol(self) -> None:
        assert PEPPOL.syntaxes == frozenset({Syntax.UBL, Syntax.CII})
        assert PEPPOL.rule_sets == ("cen", "peppol")

    def test_is_registered_by_its_bt24(self) -> None:
        assert profiles.get(BT24) is PEPPOL

    def test_prepare_writes_the_peppol_bt24_and_the_billing_bt23(self) -> None:
        prepared = PEPPOL.prepare(minimal_invoice())
        assert prepared.process_control == process(BT23)

    # DE-R-014 (rules/sch/PEPPOL-EN16931-UBL.sch:799-800) asks for BT-119 on every VAT breakdown when the seller
    # and the buyer are both in Germany (issue #75).
    @pytest.mark.parametrize(
        ("seller_country", "buyer_country", "rate"),
        [("DE", "DE", Decimal("0")), ("DE", "AT", None), ("AT", "DE", None), ("AT", "AT", None)],
    )
    def test_prepare_writes_bt119_zero_on_an_o_breakdown_between_german_parties(
        self, seller_country: str, buyer_country: str, rate: Decimal | None
    ) -> None:
        invoice = not_subject_to_vat(seller_country, buyer_country)
        assert invoice.vat_breakdown[0].rate is None

        assert [g.rate for g in PEPPOL.prepare(invoice).vat_breakdown] == [rate]

    def test_covered_rules(self) -> None:
        rules = {f"PEPPOL-EN16931-R{n}" for n in ("001", "002", "003", "004", "005", "007", "008", "010", "020")}
        rules |= {f"PEPPOL-EN16931-R{n}" for n in ("041", "042", "061", "110", "111", "121")}
        assert rules == peppol._RULES

    def test_core_profile_has_no_preflight(self) -> None:
        assert profiles.EN16931.preflight is profiles.no_preflight
        assert profiles.EN16931.preflight(minimal_invoice(), UBL) == ()


class TestPreflight:
    @SYNTAXES
    def test_a_peppol_invoice_has_no_findings(self, syntax: Syntax) -> None:
        assert PEPPOL.preflight(peppol_invoice(), syntax) == ()

    def test_findings_are_fatal_with_the_official_id_and_a_model_location(self) -> None:
        (finding,) = PEPPOL.preflight(peppol_invoice(buyer_reference=None), CII)
        assert finding.rule_id == "PEPPOL-EN16931-R003"
        assert finding.severity is Severity.FATAL
        assert finding.source == "peppol-preflight"
        assert finding.location == "buyer_reference"
        assert finding.message.startswith(
            "[PEPPOL-EN16931-R003]-A buyer reference or purchase order reference MUST be provided. "
        )
        assert "BT-10" in finding.message
        assert "BT-13" in finding.message

    def test_rejects_an_unknown_syntax(self) -> None:
        with pytest.raises(ValueError, match="'xml'"):
            PEPPOL.preflight(peppol_invoice(), "xml")  # type: ignore[arg-type]  # the runtime check is the point

    @SYNTAXES
    def test_r001_and_r007_without_bt23(self, syntax: Syntax) -> None:
        # No BT-23 also makes $profile 'Unknown', so R007 fires with R001 in both bindings.
        assert ids(peppol_invoice(process_control=process(None)), syntax) == ["R001", "R007"]

    @SYNTAXES
    def test_r007_for_an_unapproved_bt23(self, syntax: Syntax) -> None:
        assert ids(peppol_invoice(process_control=process("urn:example.com:process")), syntax) == ["R007"]

    @pytest.mark.parametrize(
        ("bt23", "ubl", CII),
        [
            (f"  {BT23}\n", [], []),
            ("urn:peppol:bis:billing_with_response", [], []),
            ("urn:peppol:france:billing:regulated", [], ["R007"]),
            ("urn:peppol:france:billing:non-regulated", [], ["R007"]),
        ],
    )
    def test_r007_approved_processes_per_binding(self, bt23: str, ubl: list[str], cii: list[str]) -> None:
        invoice = peppol_invoice(process_control=process(bt23))
        assert (ids(invoice, UBL), ids(invoice, CII)) == (ubl, cii)

    @SYNTAXES
    @pytest.mark.parametrize("bt24", ["urn:cen.eu:en16931:2017", f"{BT24}::x", "urn:example.com:" + BT24])
    def test_r004_bt24(self, syntax: Syntax, bt24: str) -> None:
        assert ids(peppol_invoice(process_control=process(BT23, bt24)), syntax) == ["R004"]

    @SYNTAXES
    def test_r004_accepts_an_extension_of_the_peppol_bt24(self, syntax: Syntax) -> None:
        bt24 = f" {BT24}#conformant#urn:example.com:extension "
        assert ids(peppol_invoice(process_control=process(BT23, bt24)), syntax) == []

    @SYNTAXES
    def test_r002_two_notes(self, syntax: Syntax) -> None:
        notes = (InvoiceNote(note="One"), InvoiceNote(note="Two"))
        assert ids(peppol_invoice(notes=notes), syntax) == ["R002"]

    def test_r002_ubl_allows_several_notes_between_german_parties_cii_does_not(self) -> None:
        invoice = german(peppol_invoice(notes=(InvoiceNote(note="One"), InvoiceNote(note="Two"))))
        assert (ids(invoice, UBL), ids(invoice, CII)) == ([], ["R002"])

    def test_r002_cii_forbids_a_subject_code(self) -> None:
        invoice = peppol_invoice(notes=(InvoiceNote(subject_code="AAI", note="One"),))
        assert (ids(invoice, UBL), ids(invoice, CII)) == ([], ["R002"])

    def test_r002_counts_only_the_notes_the_writers_emit(self) -> None:
        # UBL drops a note without BT-21 and without BT-22 text; CII drops one with neither set.
        invoice = peppol_invoice(notes=(InvoiceNote(note="One"), InvoiceNote(), InvoiceNote(note="")))
        assert (ids(invoice, UBL), ids(invoice, CII)) == ([], ["R002"])

    @SYNTAXES
    def test_r003_needs_bt10_or_bt13(self, syntax: Syntax) -> None:
        assert ids(peppol_invoice(buyer_reference=None), syntax) == ["R003"]
        assert ids(peppol_invoice(buyer_reference=None, purchase_order_reference="PO-1"), syntax) == []

    def test_r003_only_bt14_is_a_warning_in_ubl_and_fatal_in_cii(self) -> None:
        # UBL writes cac:OrderReference/cbc:ID "NA", which passes R003 officially: no fatal R003 there (D8).
        invoice = peppol_invoice(buyer_reference=None, sales_order_reference="SO-1")
        (warning,) = PEPPOL.preflight(invoice, UBL)
        assert (warning.rule_id, warning.severity, warning.location, warning.source) == (
            "EUINV-PEPPOL-R003-NA",
            Severity.WARNING,
            "purchase_order_reference",
            "peppol-preflight",
        )
        assert "PEPPOL-EN16931-R003" in warning.message
        assert "'NA'" in warning.message
        assert "CII" in warning.message
        assert ids(invoice, CII) == ["R003"]

    @SYNTAXES
    def test_r005_bt6_equal_to_bt5(self, syntax: Syntax) -> None:
        assert ids(peppol_invoice(vat_accounting_currency_code="EUR"), syntax) == ["R005"]
        assert ids(peppol_invoice(vat_accounting_currency_code="SEK"), syntax) == []

    @SYNTAXES
    def test_r010_and_r020_electronic_addresses(self, syntax: Syntax) -> None:
        invoice = peppol_invoice()
        seller = Seller.model_validate({**dict(invoice.seller), "electronic_address": None})
        buyer = Buyer.model_validate({**dict(invoice.buyer), "electronic_address": None})
        assert ids(rebuild(invoice, seller=seller, buyer=buyer), syntax) == ["R010", "R020"]

    @SYNTAXES
    def test_r041_and_r042_document_and_line_allowances_and_charges(self, syntax: Syntax) -> None:
        common: dict[str, t.Any] = {"amount": Decimal("1.00"), "reason": "Reason"}
        line = simple_line(
            allowances=(InvoiceLineAllowance(**common, base_amount=Decimal("10.00")),),
            charges=(InvoiceLineCharge(**common, percentage=Decimal("10")),),
        )
        invoice = peppol_invoice(
            allowances=(DocumentLevelAllowance(**common, percentage=Decimal("10"), vat_category_code="S"),),
            charges=(DocumentLevelCharge(**common, base_amount=Decimal("10.00"), vat_category_code="S"),),
            lines=(line,),
        )
        findings = PEPPOL.preflight(invoice, syntax)
        assert [(f.rule_id.removeprefix("PEPPOL-EN16931-"), f.location) for f in findings] == [
            ("R041", "allowances[0]"),
            ("R042", "charges[0]"),
            ("R042", "lines[0].allowances[0]"),
            ("R041", "lines[0].charges[0]"),
        ]

    @SYNTAXES
    @pytest.mark.parametrize("code", ["49", "59"])
    def test_r061_direct_debit_needs_a_mandate(self, syntax: Syntax, code: str) -> None:
        without = PaymentInstructions(payment_means_type_code=code)
        no_mandate = PaymentInstructions(payment_means_type_code=code, direct_debit=DirectDebit())
        with_mandate = PaymentInstructions(
            payment_means_type_code=code, direct_debit=DirectDebit(mandate_reference_identifier="M-1")
        )
        assert ids(peppol_invoice(payment_instructions=without), syntax) == ["R061"]
        assert ids(peppol_invoice(payment_instructions=no_mandate), syntax) == ["R061"]
        assert ids(peppol_invoice(payment_instructions=with_mandate), syntax) == []

    def test_r061_ubl_writes_the_mandate_in_the_first_of_several_payment_means_only(self) -> None:
        transfers = (
            CreditTransfer(payment_account_identifier=TEST_IBAN),
            CreditTransfer(payment_account_identifier="X"),
        )
        payment = PaymentInstructions(
            payment_means_type_code="59",
            credit_transfers=transfers,
            direct_debit=DirectDebit(mandate_reference_identifier="M-1"),
        )
        invoice = peppol_invoice(payment_instructions=payment)
        assert (ids(invoice, UBL), ids(invoice, CII)) == (["R061"], [])

    @SYNTAXES
    def test_r061_ignores_other_payment_means(self, syntax: Syntax) -> None:
        assert ids(peppol_invoice(payment_instructions=PaymentInstructions(payment_means_type_code="58")), syntax) == []

    @SYNTAXES
    def test_r110_and_r111_line_period_within_the_invoicing_period(self, syntax: Syntax) -> None:
        jan = [datetime.date(2026, 1, day) for day in (1, 10, 20, 31)]
        delivery = DeliveryInformation(invoicing_period=InvoicingPeriod(start_date=jan[1], end_date=jan[2]))
        outside = simple_line(period=InvoiceLinePeriod(start_date=jan[0], end_date=jan[3]))
        inside = simple_line(period=InvoiceLinePeriod(start_date=jan[1], end_date=jan[2]))
        assert ids(peppol_invoice(delivery=delivery, lines=(outside,)), syntax) == ["R110", "R111"]
        assert ids(peppol_invoice(delivery=delivery, lines=(inside,)), syntax) == []
        # Either period open on a side: nothing to compare.
        open_period = DeliveryInformation(invoicing_period=InvoicingPeriod(start_date=jan[1]))
        assert ids(peppol_invoice(delivery=open_period, lines=(outside,)), syntax) == ["R110"]
        assert ids(peppol_invoice(lines=(outside,)), syntax) == []
        bare = simple_line(period=InvoiceLinePeriod(end_date=jan[3]))
        assert ids(peppol_invoice(delivery=open_period, lines=(bare,)), syntax) == []

    @SYNTAXES
    @pytest.mark.parametrize(("base", "fires"), [("0", True), ("-1", True), ("0.5", False)])
    def test_r121_base_quantity_above_zero(self, syntax: Syntax, base: str, fires: bool) -> None:
        price = PriceDetails(item_net_price=Decimal("50"), base_quantity=Decimal(base))
        assert ids(peppol_invoice(lines=(simple_line(price_details=price),)), syntax) == (["R121"] if fires else [])

    def test_r008_empty_elements_in_ubl_only(self) -> None:
        invoice = peppol_invoice(buyer_reference=" \t", notes=(InvoiceNote(note="\n"),))
        findings = PEPPOL.preflight(invoice, UBL)
        assert [(f.rule_id, f.location) for f in findings] == [
            ("PEPPOL-EN16931-R008", "/*/cbc:Note"),
            ("PEPPOL-EN16931-R008", "/*/cbc:BuyerReference"),
        ]
        # The CII rules have no R008.
        assert ids(invoice, CII) == []

    def test_r008_on_an_empty_purchase_order_reference(self) -> None:
        # Issue #79: the "NA" placeholder stands in for a missing BT-13 only, so an empty BT-13 is an empty element.
        invoice = peppol_invoice(purchase_order_reference="", sales_order_reference="SO-1")
        findings = PEPPOL.preflight(invoice, UBL)
        assert [(f.rule_id, f.location) for f in findings] == [("PEPPOL-EN16931-R008", "/*/cac:OrderReference/cbc:ID")]

    def test_r008_keeps_non_xml_whitespace(self) -> None:
        # normalize-space() strips only space, tab, CR and LF: a no-break space is content.
        assert ids(peppol_invoice(buyer_reference="\N{NO-BREAK SPACE}"), UBL) == []

    def test_a_blank_bt23_fails_r007_and_r008_in_ubl(self) -> None:
        # cbc:ProfileID exists (R001 holds) but is empty.
        assert ids(peppol_invoice(process_control=process("")), UBL) == ["R007", "R008"]

    def test_totals_are_not_checked(self) -> None:
        # Arithmetic belongs to calc and the Schematron (module docstring).
        totals = DocumentTotals(
            sum_of_line_net_amounts=Decimal("1.00"),
            total_without_vat=Decimal("1.00"),
            total_vat=Decimal("0.00"),
            total_with_vat=Decimal("1.00"),
            amount_due=Decimal("1.00"),
        )
        assert PEPPOL.preflight(peppol_invoice(totals=totals), UBL) == ()
