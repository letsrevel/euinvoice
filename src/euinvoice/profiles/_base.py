"""The :class:`Profile` type: what a specification (EN 16931 core or a CIUS/extension) declares (D5)."""

import dataclasses
import typing as t

from euinvoice.model import Invoice, ProcessControl

__all__ = ["SYNTAXES", "Profile"]

# ponytail: plain strings until ``euinvoice.syntax.Syntax`` (a StrEnum with these values) lands; switch the
# annotations to the enum then. StrEnum members compare equal to these strings, so callers keep working.
SYNTAXES: t.Final = frozenset({"ubl", "cii"})
"""The syntaxes a profile can support: UBL 2.1 (``"ubl"``) and UN/CEFACT CII D16B (``"cii"``)."""


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Profile:
    """A specification an invoice is written, read and validated under (IMPLEMENTATION_PLAN.md D5).

    A profile is data plus :meth:`prepare`. Pre-flight checks are a later addition of the CIUS
    profiles; the official Schematron stays the oracle (D8).

    Attributes:
        id: Short stable name, e.g. ``"en16931"``.
        title: Human-readable name.
        specification_identifier: The BT-24 value the profile writes and is looked up by.
        syntaxes: Supported syntaxes, a subset of :data:`SYNTAXES`.
        rule_sets: Names of the official Schematron rule sets to run after the XSD, in order. A name
            and a syntax select one ``euinvoice.validate.schematron`` constant: ``"cen"`` →
            ``CEN_UBL`` / ``CEN_CII``, ``"peppol"`` → ``PEPPOL_UBL`` / ``PEPPOL_CII``, ``"xrechnung"`` →
            ``XRECHNUNG_UBL`` / ``XRECHNUNG_CII``. Profiles do not import ``euinvoice.validate``
            (dependency direction, plan §4), so the validator owns that mapping.
        business_process_type: BT-23 default written when the invoice has none, or ``None``.
        facturx_filename: Name of the embedded XML in a Factur-X / ZUGFeRD PDF; ``None`` otherwise.
        facturx_conformance_level: XMP ``fx:ConformanceLevel`` of a Factur-X / ZUGFeRD profile;
            ``None`` otherwise.
    """

    id: str
    title: str
    specification_identifier: str
    syntaxes: frozenset[str]
    rule_sets: tuple[str, ...]
    business_process_type: str | None = None
    facturx_filename: str | None = None
    facturx_conformance_level: str | None = None

    def __post_init__(self) -> None:
        """Reject declarations no syntax module or validator could serve.

        Raises:
            ValueError: ``syntaxes`` is empty or holds an unknown syntax, or ``rule_sets`` is empty.
        """
        if not self.syntaxes:
            raise ValueError(f"profile {self.id!r} must support at least one syntax")
        if unknown := self.syntaxes - SYNTAXES:
            raise ValueError(f"profile {self.id!r} has unknown syntaxes {sorted(unknown)}; known: {sorted(SYNTAXES)}")
        if not self.rule_sets:
            raise ValueError(f"profile {self.id!r} must run at least one rule set")

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
