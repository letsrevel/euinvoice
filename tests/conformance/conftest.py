"""Shared helpers of the conformance tests."""

from euinvoice.validate.report import Finding, Severity


def line_of(data: bytes, needle: bytes) -> int:
    """Return the 1-based line on which ``needle`` first starts in ``data``."""
    return data[: data.index(needle)].count(b"\n") + 1


def assert_located_xsd_fatal(
    findings: tuple[Finding, ...], data: bytes, mutated: bytes, path: str, message: str, source: str
) -> None:
    """Assert that the first finding is a fatal XSD error located where ``mutated`` starts in ``data``.

    The first element of a mutation is where the schema stops accepting the document, so the first
    finding is located by that line and the given element path.
    """
    assert findings, "a mutated example must not be schema-valid"
    first = findings[0]
    assert (first.rule_id, first.severity, first.source) == ("XSD", Severity.FATAL, source)
    assert first.location == f"{line_of(data, mutated)} {path}"
    assert message in first.message
