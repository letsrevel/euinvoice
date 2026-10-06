"""The :class:`Profile` type: what a specification (EN 16931 core or a CIUS/extension) declares (D5)."""

import dataclasses
import typing as t
from collections.abc import Callable

from euinvoice.model import Invoice, ProcessControl
from euinvoice.report import Finding
from euinvoice.syntax import Syntax

__all__ = ["RULE_SETS", "SYNTAXES", "Preflight", "Profile", "no_preflight"]

SYNTAXES: t.Final[frozenset[Syntax]] = frozenset(Syntax)
"""The syntaxes a profile can support: UBL 2.1 (``Syntax.UBL``) and UN/CEFACT CII D16B (``Syntax.CII``)."""

RULE_SETS: t.Final = frozenset({"cen", "peppol", "xrechnung"})
"""The official Schematron rule-set names a profile can declare (see :attr:`Profile.rule_sets`)."""

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
            ``XRECHNUNG_UBL`` / ``XRECHNUNG_CII``. Profiles do not import ``euinvoice.validate``
            (dependency direction, plan §4), so the validator owns that mapping. Names come from
            :data:`RULE_SETS`; ``"cen"`` is not required (Factur-X MINIMUM and BASIC WL are not EN 16931).
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
        :attr:`business_process_type` only when the invoice has none. The result is built through
        model validation (never ``model_copy(update=...)``, which skips it).

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
        # ``dict(invoice)`` holds the top-level field values; nested models are already validated.
        return Invoice.model_validate({**dict(invoice), "process_control": process_control})
