"""XML Schema (XSD) validation of e-invoice documents against the pinned official schemas.

The schema is picked by the namespace of the document's root element; the root element's local name is
then checked by the schema itself (a wrong one is a ``No matching global declaration`` finding):

* UBL 2.1 ``Invoice`` and ``CreditNote`` are validated against the OASIS UBL 2.1 ``maindoc`` schemas of
  the ``ubl-2_1`` artifact source (the same schemas the KoSIT validator configuration uses in its UBL
  scenarios: ``resources/ubl/2.1/xsd/maindoc/UBL-{Invoice,CreditNote}-2.1.xsd`` in ``scenarios.xml``).
* UN/CEFACT CII D16B ``CrossIndustryInvoice`` is validated against
  ``resources/cii/16b/xsd/CrossIndustryInvoice_100pD16B.xsd`` of the
  ``xrechnung-validator-configuration`` source: the D16B SCRDM Subset ("uncoupled clm") schema the CEN
  EN 16931 CII artifacts are written for, and the schema every CII scenario of the KoSIT
  ``scenarios.xml`` (XRechnung, XRechnung extension, CVD and plain EN 16931) validates against.

Every schema-validity error becomes a :class:`~euinvoice.validate.report.Finding` with rule id ``XSD``
and severity ``fatal``, located by line number and element path: a document that is not schema-valid
cannot be processed further, and the official validators reject it. The KoSIT validator's report
stylesheet (``resources/default-report.xsl`` of ``xrechnung-validator-configuration``, template
``in:xmlSyntaxError``) reports every non-warning XSD message at level ``error``, the level it also gives Schematron
``fatal`` flags, and any such message makes the XSD step, and so the whole report, invalid. The same
template keeps ``SEVERITY_WARNING`` messages as ``warning``, so libxml2 warnings stay warnings here.

Thread safety: compiled schemas are cached per process and shared between threads. An lxml
``XMLSchema`` keeps its error log on the object, so concurrent ``validate()`` calls on one schema mix
their errors (observed with lxml 6.1: 8 threads sharing one unlocked schema got the wrong error log
about half the time). Each schema therefore carries a lock that is held while validating and reading the
log, which serialises validations against the *same* schema (validations against different schemas
still run in parallel).
"""

import dataclasses
import pathlib
import threading
import typing as t

from lxml import etree

from euinvoice import _xml
from euinvoice.errors import UnsupportedDocumentError
from euinvoice.validate import artifacts
from euinvoice.validate.report import Finding, Severity

RULE_ID: t.Final = "XSD"
"""The ``rule_id`` of every XSD finding."""


@dataclasses.dataclass(frozen=True, slots=True)
class _SchemaSpec:
    """Where the schema for one root namespace lives.

    Attributes:
        source: The artifact source (manifest key) that ships the schema.
        path: The root ``.xsd``, relative to the source directory.
        root: The directory every file the schema loads must be inside (``load_trusted_schema(root=)``),
            relative to the source directory.
    """

    source: artifacts.SourceName
    path: str
    root: str


# Root namespace → schema. UBL 2.1 maindoc schemas import ``../common/*.xsd``, so the confinement root
# is the whole ``xsd`` directory of the OASIS UBL 2.1 package.
_SCHEMAS: t.Final[t.Mapping[str, _SchemaSpec]] = {
    _xml.UBL_INVOICE: _SchemaSpec("ubl-2_1", "xsd/maindoc/UBL-Invoice-2.1.xsd", "xsd"),
    _xml.UBL_CREDIT_NOTE: _SchemaSpec("ubl-2_1", "xsd/maindoc/UBL-CreditNote-2.1.xsd", "xsd"),
    # The CII D16B schema imports only its three siblings (qdt, ram, udt), so its own directory is the
    # confinement root.
    # ponytail: keyed by namespace alone, so every rsm document gets this D16B schema. Factur-X / ZUGFeRD
    # profiles (MINIMUM, BASIC WL, BASIC, EN16931, EXTENDED) share the rsm namespace but the Factur-X
    # package ships its own per-profile XSDs, which may be stricter; that package is not pinned yet
    # (needs-human #42). Once it is, schema selection needs the profile (BT-24) as an extra argument
    # (#17 / #22).
    _xml.CII_RSM: _SchemaSpec(
        "xrechnung-validator-configuration",
        "resources/cii/16b/xsd/CrossIndustryInvoice_100pD16B.xsd",
        "resources/cii/16b/xsd",
    ),
}


@dataclasses.dataclass(frozen=True, slots=True)
class _Compiled:
    schema: etree._Validator  # an XMLSchema from _xml.load_trusted_schema
    lock: threading.Lock


class _LogEntry(t.Protocol):
    """The fields of an lxml ``_LogEntry`` used here (lxml-stubs leave ``_ErrorLog`` untyped)."""

    line: int
    path: str | None
    message: str
    level_name: str


_cache: dict[pathlib.Path, _Compiled] = {}
_cache_lock = threading.Lock()


def validate(element: etree._Element) -> tuple[Finding, ...]:
    """Validate a parsed document against the official XML Schema for its root namespace.

    Args:
        element: The document's root element, as returned by ``euinvoice._xml.parse``.

    Returns:
        One ``XSD`` finding per schema-validity error (severity ``fatal``, or ``warning`` for a libxml2
        warning), in document order; empty when the document is schema-valid.

    Raises:
        UnsupportedDocumentError: No schema is known for the root element's namespace.
        ArtifactsNotAvailableError: The schema's artifact source has not been fetched.
    """
    namespace = etree.QName(element).namespace
    spec = _SCHEMAS.get(namespace or "")
    if spec is None:
        raise UnsupportedDocumentError(
            f"no XML Schema for root element {element.tag!r}; supported namespaces: {', '.join(_SCHEMAS)}"
        )
    directory = artifacts.source_dir(spec.source)
    compiled = _compiled(directory / spec.path, directory / spec.root)
    with compiled.lock:
        compiled.schema.validate(element)
        # lxml-stubs declare _ErrorLog as an empty class; at runtime it iterates _LogEntry objects.
        errors = list(t.cast(t.Iterable[_LogEntry], compiled.schema.error_log))
    return tuple(_finding(error, f"xsd:{spec.source}") for error in errors)


def _compiled(path: pathlib.Path, root: pathlib.Path) -> _Compiled:
    """Return the compiled schema for ``path``, compiling it on first use.

    Keyed by path alone: the path contains the pinned version, and ``artifacts.source_dir`` rejects an
    entry fetched with another recipe, so the file behind a path cannot change within a process.
    """
    with _cache_lock:  # held while compiling, so concurrent first calls compile only once
        compiled = _cache.get(path)
        if compiled is None:
            compiled = _Compiled(_xml.load_trusted_schema(path, root=root), threading.Lock())
            _cache[path] = compiled
    return compiled


def _finding(error: _LogEntry, source: str) -> Finding:
    """Turn one libxml2 schema-validity message into an ``XSD`` finding.

    Warnings stay ``warning`` and everything else is ``fatal`` (KoSIT ``default-report.xsl``, template
    ``in:xmlSyntaxError``). The location is the line number followed by the element path when libxml2
    gives one. There is no column: libxml2 does not track columns while validating a parsed tree.
    """
    severity = Severity.WARNING if error.level_name == "WARNING" else Severity.FATAL
    location = f"{error.line} {error.path}" if error.path else str(error.line)
    return Finding(rule_id=RULE_ID, severity=severity, location=location, message=error.message, source=source)
