"""Exception hierarchy of euinvoice.

Validation results are data, not exceptions (IMPLEMENTATION_PLAN.md D9): rule failures end up in a
``ValidationReport``. These exceptions are raised only for misuse, malformed input or missing
artifacts.
"""


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


class UnsupportedDocumentError(EuInvoiceError):
    """The document's syntax, type or profile (BT-24) is not supported."""


class ArtifactsNotAvailableError(EuInvoiceError):
    """The official validation artifacts are missing from the local cache.

    The message names the command that fetches them (``python -m euinvoice artifacts fetch``).
    """


class ArtifactIntegrityError(EuInvoiceError):
    """A fetched or cached artifact does not match the sha256 pinned in the manifest."""


class PdfError(EuInvoiceError):
    """A PDF cannot be used for Factur-X / ZUGFeRD embedding or extraction."""
