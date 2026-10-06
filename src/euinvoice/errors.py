"""Exception hierarchy of euinvoice.

Validation results are data, not exceptions (IMPLEMENTATION_PLAN.md D9): rule failures end up in a
``ValidationReport``. These exceptions are raised only for misuse, malformed input or missing
artifacts.
"""

from euinvoice.report import Finding, Severity


class EuInvoiceError(Exception):
    """Base class of every exception raised by euinvoice."""


class ModelError(EuInvoiceError, ValueError):
    """An invoice model was built with invalid or inconsistent values.

    Subclasses ``ValueError`` so that Pydantic validators raising it surface as validation errors.
    """


class ParseError(EuInvoiceError):
    """Input could not be parsed safely (malformed XML, forbidden DOCTYPE, unexpected structure).

    Attributes:
        location: Where the problem was found (an XPath or ``line:column``), if known.
    """

    def __init__(self, message: str, *, location: str | None = None) -> None:
        """Create the error.

        Args:
            message: Human-readable description.
            location: Where the problem was found (an XPath or ``line:column``), if known.
        """
        super().__init__(message if location is None else f"{message} (at {location})")
        self.location = location


class PreflightError(EuInvoiceError):
    """``to_xml`` refused an invoice: its pre-flight or calculation checks found ``fatal`` / ``error`` problems.

    The checks (the profile's ``preflight`` and ``calc.check`` for the target syntax) run on the invoice after
    ``Profile.prepare``; a blocking finding means the official rules would reject the written document, so nothing
    is written.

    Attributes:
        profile_id: The ``id`` of the profile the invoice was to be written under.
        syntax: The target syntax (``"ubl"`` or ``"cii"``).
        findings: Every finding of both checks (warnings included), each naming its rule id and model location.
    """

    def __init__(self, profile_id: str, syntax: str, findings: tuple[Finding, ...]) -> None:
        """Create the error.

        Args:
            profile_id: The profile's ``id``.
            syntax: The target syntax.
            findings: The pre-flight and calculation findings.

        Raises:
            ValueError: No finding is ``fatal`` or ``error``, so there is nothing to refuse.
        """
        blocking = [f for f in findings if f.severity in (Severity.FATAL, Severity.ERROR)]
        if not blocking:
            raise ValueError("PreflightError needs at least one fatal or error finding")
        details = "; ".join(f"{f.rule_id} ({f.severity}) at {f.location}: {f.message}" for f in blocking)
        super().__init__(f"invoice fails the {profile_id} pre-flight and calculation checks for {syntax}: {details}")
        self.profile_id = profile_id
        self.syntax = syntax
        self.findings = findings

    def __reduce__(self) -> tuple[type["PreflightError"], tuple[str, str, tuple[Finding, ...]]]:
        """Pickle by the constructor arguments (the default would call it with the message alone)."""
        return type(self), (self.profile_id, self.syntax, self.findings)


class UnsupportedDocumentError(EuInvoiceError):
    """The document's syntax, type or profile (BT-24) is not supported."""


class ArtifactsNotAvailableError(EuInvoiceError):
    """The official validation artifacts a run needs are not available.

    Either they are missing from the local cache, and the message names the command that fetches them
    (``python -m euinvoice artifacts fetch``), or the profile needs a rule set that is not pinned yet (the
    Factur-X / ZUGFeRD Schematron, issue #42), and the message says so; no fetch command can provide it.

    Attributes:
        reason: The message without the fallback hint.
        fallback_profile_id: The ``id`` of the profile that runs only the EN 16931 core rules on the same document
            (``"en16931"``) when the refusal is for an unpinned rule set, else ``None``. The message then ends with a
            hint naming it in Python spelling; the CLI builds its ``--profile`` hint from this attribute instead (#108).
    """

    def __init__(self, message: str, *, fallback_profile_id: str | None = None) -> None:
        """Create the error.

        Args:
            message: Human-readable description, without the fallback hint.
            fallback_profile_id: The ``id`` of the EN 16931 core profile to suggest instead, if any.
        """
        hint = (
            ""
            if fallback_profile_id is None
            else f". To run only the EN 16931 core rules, pass profile=euinvoice.profiles.{fallback_profile_id.upper()}"
        )
        super().__init__(message + hint)
        self.reason = message
        self.fallback_profile_id = fallback_profile_id


class ArtifactIntegrityError(EuInvoiceError):
    """An official artifact cannot be trusted or used.

    Raised when a download does not match the sha256 pinned in the manifest, a redirect leaves https,
    an archive member is unsafe (absolute path, ``..``, symlink), a manifest entry is malformed, or a
    rule file cannot be compiled.
    """


class PdfError(EuInvoiceError):
    """A PDF cannot be used for Factur-X / ZUGFeRD embedding or extraction."""
