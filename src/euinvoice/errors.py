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
    """``to_xml`` refused to write an invoice: its profile's pre-flight checks found ``fatal`` / ``error`` problems.

    The checks run on the invoice after ``Profile.prepare``; a blocking finding means the profile's official rules
    would reject the written document, so nothing is written.

    Attributes:
        findings: Every pre-flight finding (warnings included), each naming its rule id and model location.
    """

    def __init__(self, profile_id: str, syntax: str, findings: tuple[Finding, ...]) -> None:
        """Create the error.

        Args:
            profile_id: The profile's ``id``.
            syntax: The target syntax.
            findings: The pre-flight findings; at least one is ``fatal`` or ``error``.
        """
        blocking = [f for f in findings if f.severity in (Severity.FATAL, Severity.ERROR)]
        details = "; ".join(f"{f.rule_id} ({f.severity}) at {f.location}: {f.message}" for f in blocking)
        super().__init__(f"invoice fails the {profile_id} pre-flight checks for {syntax}: {details}")
        self.findings = findings


class UnsupportedDocumentError(EuInvoiceError):
    """The document's syntax, type or profile (BT-24) is not supported."""


class ArtifactsNotAvailableError(EuInvoiceError):
    """The official validation artifacts a run needs are not available.

    Either they are missing from the local cache, and the message names the command that fetches them
    (``python -m euinvoice artifacts fetch``), or the profile needs a rule set that is not pinned yet (the
    Factur-X / ZUGFeRD Schematron, issue #42), and the message says so; no fetch command can provide it.
    """


class ArtifactIntegrityError(EuInvoiceError):
    """An official artifact cannot be trusted or used.

    Raised when a download does not match the sha256 pinned in the manifest, a redirect leaves https,
    an archive member is unsafe (absolute path, ``..``, symlink), a manifest entry is malformed, or a
    rule file cannot be compiled.
    """


class PdfError(EuInvoiceError):
    """A PDF cannot be used for Factur-X / ZUGFeRD embedding or extraction."""
