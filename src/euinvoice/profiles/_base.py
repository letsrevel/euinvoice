"""The :class:`Profile` type: what a specification (EN 16931 core or a CIUS/extension) declares (D5)."""

import dataclasses
import typing as t
from collections.abc import Callable
from decimal import Decimal

from euinvoice.model import Invoice, ProcessControl, VatBreakdown
from euinvoice.model.codes import VatCategory
from euinvoice.report import Finding
from euinvoice.syntax import Syntax

__all__ = ["FACTURX_RULE_SET", "RULE_SETS", "SYNTAXES", "Preflight", "Profile", "no_preflight"]

SYNTAXES: t.Final[frozenset[Syntax]] = frozenset(Syntax)
"""The syntaxes a profile can support: UBL 2.1 (``Syntax.UBL``) and UN/CEFACT CII D16B (``Syntax.CII``)."""

FACTURX_RULE_SET: t.Final = "facturx"
"""The rule-set name of the Factur-X / ZUGFeRD per-profile Schematron, not pinned yet (issue #42)."""

RULE_SETS: t.Final = frozenset({"cen", "peppol", "xrechnung", FACTURX_RULE_SET})
"""The official Schematron rule-set names a profile can declare (see :attr:`Profile.rule_sets`).

``"facturx"`` is the per-profile Schematron of the Factur-X / ZUGFeRD package (plan §3), which is not pinned yet
(issue #42): ``validate()`` raises ``ArtifactsNotAvailableError`` for a profile that declares it."""

# The XRechnung XSLT re-asserts 21 (UBL) / 22 (CII) PEPPOL-EN16931-R* rules, so running both double-counts
# (spec-auditor findings, https://github.com/letsrevel/euinvoice/issues/17#issuecomment-6004767546).
_EXCLUSIVE_RULE_SETS: t.Final = frozenset({"peppol", "xrechnung"})

type Preflight = Callable[[Invoice, Syntax], tuple[Finding, ...]]
"""A pre-flight check: ``(invoice, syntax) -> findings``, ``syntax`` being one of the profile's syntaxes."""


def no_preflight(invoice: Invoice, syntax: Syntax) -> tuple[Finding, ...]:
    """The pre-flight of a profile without one (EN 16931 core): no findings.

    Args:
        invoice: The invoice (unused).
        syntax: The target syntax (unused).

    Returns:
        An empty tuple.
    """
    return ()


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Profile:
    """A specification an invoice is written, read and validated under (IMPLEMENTATION_PLAN.md D5).

    A profile is data plus :meth:`prepare` and an optional :attr:`preflight`. Pre-flight checks give
    early, model-level messages for a CIUS's rules; the official Schematron stays the oracle (D8).

    Attributes:
        id: Short stable name, e.g. ``"en16931"``.
        title: Human-readable name.
        specification_identifier: The BT-24 value the profile writes and is looked up by.
        syntaxes: Supported syntaxes, a subset of :data:`SYNTAXES`.
        rule_sets: Names of the official Schematron rule sets to run after the XSD, in order. A name
            and a syntax select one ``euinvoice.validate.schematron`` constant: ``"cen"`` →
            ``CEN_UBL`` / ``CEN_CII``, ``"peppol"`` → ``PEPPOL_UBL`` / ``PEPPOL_CII``, ``"xrechnung"`` →
            ``XRECHNUNG_UBL`` / ``XRECHNUNG_CII``; ``"facturx"`` has no pinned artifact yet (#42). Profiles do
            not import ``euinvoice.validate`` (dependency direction, plan §4), so the validator owns that
            mapping. Names come from :data:`RULE_SETS`; ``"cen"`` is not required (Factur-X MINIMUM and BASIC WL
            are not EN 16931).
        business_process_type: BT-23 default written when the invoice has none, or ``None``.
        facturx_filename: Name of the embedded XML in a Factur-X / ZUGFeRD PDF; ``None`` otherwise.
        facturx_conformance_level: XMP ``fx:ConformanceLevel`` of a Factur-X / ZUGFeRD profile;
            ``None`` otherwise.
        preflight: Checks an invoice for the profile's rules before it is written in a syntax, e.g.
            ``PEPPOL.preflight(PEPPOL.prepare(invoice), Syntax.UBL)``. Call contract: it runs on the
            invoice **after** :meth:`prepare`, right before writing; ``to_xml`` (#27) calls it.
            ``validate()`` never does, because there the official Schematron is the oracle (D8). A
            pre-flight never reports a ``fatal`` official rule id that the oracle would not raise for
            the written document; extra semantic checks use ``EUINV-*`` ids at ``warning`` severity.
            Defaults to :func:`no_preflight`.
        vat_breakdown_rate_required: Whether the profile's rules require the VAT category rate (BT-119) on
            every VAT breakdown of the given invoice, e.g. XRechnung BR-DE-14 or Peppol DE-R-014. When it
            returns ``True``, :meth:`prepare` writes BT-119 = 0 on each "Not subject to VAT" (O) breakdown
            that has none. ``None`` (EN 16931 core: BR-48 exempts category O) never asks.
    """

    id: str
    title: str
    specification_identifier: str
    syntaxes: frozenset[Syntax]
    rule_sets: tuple[str, ...]
    business_process_type: str | None = None
    facturx_filename: str | None = None
    facturx_conformance_level: str | None = None
    preflight: Preflight = no_preflight
    vat_breakdown_rate_required: Callable[[Invoice], bool] | None = None

    def __post_init__(self) -> None:
        """Reject declarations no syntax module or validator could serve.

        Raises:
            ValueError: ``syntaxes`` is empty or holds an unknown syntax, or ``rule_sets`` is empty, holds
                an unknown or repeated name, or holds both ``"peppol"`` and ``"xrechnung"``.
        """
        if not self.syntaxes:
            raise ValueError(f"profile {self.id!r} must support at least one syntax")
        if unknown := self.syntaxes - SYNTAXES:
            raise ValueError(
                f"profile {self.id!r} has unknown syntaxes {sorted(map(str, unknown))}; "
                f"known: {sorted(map(str, SYNTAXES))}"
            )
        if not self.rule_sets:
            raise ValueError(f"profile {self.id!r} must run at least one rule set")
        if unknown_sets := set(self.rule_sets) - RULE_SETS:
            raise ValueError(
                f"profile {self.id!r} has unknown rule sets {sorted(unknown_sets)}; known: {sorted(RULE_SETS)}"
            )
        if len(set(self.rule_sets)) != len(self.rule_sets):
            raise ValueError(f"profile {self.id!r} repeats a rule set: {self.rule_sets}")
        if set(self.rule_sets) >= _EXCLUSIVE_RULE_SETS:
            raise ValueError(
                f"profile {self.id!r} runs both 'peppol' and 'xrechnung'; the XRechnung rules re-assert "
                "PEPPOL-EN16931-R* rules, so findings would be counted twice"
            )

    def prepare(self, invoice: Invoice) -> Invoice:
        """Return ``invoice`` set up for this profile, ready to be written.

        Sets PROCESS CONTROL (BG-2): BT-24 always becomes :attr:`specification_identifier`, because
        the profile the caller writes under decides what the document claims; BT-23 gets
        :attr:`business_process_type` only when the invoice has none. When
        :attr:`vat_breakdown_rate_required` says so, a "Not subject to VAT" (O) VAT breakdown without
        BT-119 gets BT-119 = 0, the value of the official XRechnung instance ``standard/01.04a-INVOICE_ubl.xml``
        (``cbc:Percent`` 0) and ``01.04a-INVOICE_uncefact.xml`` (``ram:RateApplicablePercent`` 0). The CEN rules
        accept it: BR-O-05/06/07 forbid a rate on O lines, allowances and charges only, and BR-CO-17 holds with
        BT-117 = 0 (BR-O-09). A breakdown of another category keeps a missing rate, which has no default. The
        result is built through model validation (never ``model_copy(update=...)``, which skips it).

        Args:
            invoice: The invoice to prepare.

        Returns:
            A new, validated invoice (equal to ``invoice`` when nothing changes).

        Raises:
            pydantic.ValidationError: The profile's values are invalid for the model.
        """
        bt23 = invoice.process_control.business_process_type
        process_control = ProcessControl(
            business_process_type=self.business_process_type if bt23 is None else bt23,
            specification_identifier=self.specification_identifier,
        )
        breakdown = invoice.vat_breakdown
        if self.vat_breakdown_rate_required is not None and self.vat_breakdown_rate_required(invoice):
            breakdown = tuple(
                VatBreakdown.model_validate({**dict(group), "rate": Decimal(0)})
                if group.category_code == VatCategory.NOT_SUBJECT_TO_VAT and group.rate is None
                else group
                for group in breakdown
            )
        # ``dict(invoice)`` holds the top-level field values; nested models are already validated.
        return Invoice.model_validate({**dict(invoice), "process_control": process_control, "vat_breakdown": breakdown})
