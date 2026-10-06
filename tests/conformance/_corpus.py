"""The upstream samples of the corpus harness and their documented exceptions (plan §4, §8 9.1).

A :class:`Sample` is one XML file of a pinned corpus (``test_detect_corpora.py`` lists the few that are not
invoices), or the XML embedded in a Factur-X PDF of the ZUGFeRD corpus. :func:`samples` enumerates them from the
artifact cache without fetching (parametrization runs at collection time, also in unit runs without a cache);
``test_corpus_harness.py::test_every_corpus_is_complete`` fetches and fails if a cold cache made the harness
vacuous. :func:`expected_invalid` loads ``expected_invalid.toml``, the one list of samples that do not satisfy the
round-trip invariant, with the ids each must fail with.
"""

import dataclasses
import functools
import pathlib
import tomllib
import typing as t

import pypdf
from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ArtifactsNotAvailableError
from euinvoice.validate import artifacts

XML_DIRECTORIES: t.Final[dict[artifacts.SourceName, str]] = {
    "cen-ubl": "examples",
    "cen-cii": "examples",
    # The Peppol ``rules/unit-*`` directories hold vefa testSet files, not invoices (test_detect_corpora.py).
    "peppol-bis": "rules/examples",
    "xrechnung-testsuite": ".",
    "zugferd-corpus": ".",
}
"""Where each corpus keeps its XML, relative to the source directory."""

PDF_SCOPE: t.Final = ("ZUGFeRDv2/correct", "XML-Rechnung/FX")
"""ZUGFeRD corpus directories with Factur-X PDFs. ``fail`` directories are marked invalid upstream; ZUGFeRD 1.x and
2.0 PDFs (another XMP schema, extract-only, plan §8 7.2) are out of scope, see :func:`facturx_pdfs`."""

EXPECTED_INVALID: t.Final = pathlib.Path(__file__).with_name("expected_invalid.toml")

type Outcome = t.Literal["parse-error", "reads"]


@dataclasses.dataclass(frozen=True)
class FacturXPdf:
    """A Factur-X PDF of the ZUGFeRD corpus: its XMP level, the XMP file name and the embedded files."""

    name: str
    level: str
    xmp_filename: str
    attachments: dict[str, bytes]

    @property
    def xml(self) -> bytes:
        """The embedded invoice the XMP ``fx:DocumentFileName`` names."""
        return self.attachments[self.xmp_filename]


@dataclasses.dataclass(frozen=True)
class Sample:
    """One upstream invoice: ``file`` is relative to the source directory; ``level`` is set for a Factur-X PDF."""

    source: artifacts.SourceName
    file: str
    level: str | None = None

    @property
    def id(self) -> str:
        """The pytest id and the key of ``expected_invalid.toml``."""
        return f"{self.source}:{self.file}"

    def data(self) -> bytes:
        """The invoice XML (for a PDF, the embedded XML)."""
        if self.level is None:
            return (artifacts.source_dir(self.source) / self.file).read_bytes()
        return next(pdf for pdf in facturx_pdfs() if pdf.name == self.file).xml


@dataclasses.dataclass(frozen=True)
class ExpectedInvalid:
    """A sample that does not satisfy the round-trip invariant, and the ids that document how.

    Attributes:
        outcome: ``parse-error``: ``read(X)`` raises a ``ParseError`` whose message names exactly the ``rules``
            (rule, BT and BG ids). ``reads``: X reads and ``validate(write(read(X)))`` has exactly ``rules`` as
            its fatal or error rule ids.
        rules: See ``outcome``.
        upstream: The fatal or error rule ids of ``validate(X)`` on the upstream file itself, exactly.
        differs: For ``reads``: the BT/BG ids of the ``Invoice`` fields where ``read(write(read(X)))`` differs
            from ``read(X)``, exactly (a known reader/writer gap; ``reason`` names its issue).
        reason: Why, citing the rule texts and, where open, the issue.
        link: The upstream file at the pinned version.
    """

    outcome: Outcome
    rules: frozenset[str]
    upstream: frozenset[str]
    differs: frozenset[str]
    reason: str
    link: str


class _Entry(t.TypedDict):
    source: str
    file: str
    outcome: Outcome
    rules: list[str]
    upstream: list[str]
    differs: t.NotRequired[list[str]]
    reason: str
    link: str


def _cached(source: artifacts.SourceName) -> pathlib.Path | None:
    """The cache entry of ``source`` if present; never fetches."""
    try:
        return artifacts.source_dir(source)
    except ArtifactsNotAvailableError:
        return None


def _xml_samples(source: artifacts.SourceName) -> list[Sample]:
    """Every ``*.xml`` / ``*.XML`` file of ``source``; classifying them is left to the tests (``detect`` on the
    corpora's 25 MB and 61 MB Peppol samples is too slow for collection time)."""
    root = _cached(source)
    if root is None:
        return []
    paths = sorted(p for p in (root / XML_DIRECTORIES[source]).rglob("*") if p.is_file() and p.suffix.lower() == ".xml")
    return [Sample(source, p.relative_to(root).as_posix()) for p in paths]


def _fx(xmp: etree._Element, name: str) -> list[str]:
    """``fx:<name>`` of the Factur-X XMP schema, as element text or ``rdf:Description`` attribute."""
    qname = f"{{{_xml.FACTURX_XMP}}}{name}"
    return [element.text or "" for element in xmp.iter(qname)] + [
        str(element.get(qname)) for element in xmp.iter() if element.get(qname) is not None
    ]


def _read_pdf(path: pathlib.Path, name: str) -> FacturXPdf | None:
    """The Factur-X view of a PDF, or ``None`` when its XMP does not declare the Factur-X schema."""
    reader = pypdf.PdfReader(path)
    root = t.cast(pypdf.generic.DictionaryObject, reader.trailer["/Root"])
    metadata = root.get("/Metadata")
    if metadata is None:
        return None
    xmp = _xml.parse(t.cast(pypdf.generic.StreamObject, metadata.get_object()).get_data())
    levels, filenames = _fx(xmp, "ConformanceLevel"), _fx(xmp, "DocumentFileName")
    if not levels:
        return None
    assert len(levels) == 1, name
    assert len(filenames) == 1, name
    attachments = {key: value[0] for key, value in reader.attachments.items()}
    return FacturXPdf(name, levels[0], filenames[0], attachments)


@functools.cache
def facturx_pdfs() -> tuple[FacturXPdf, ...]:
    """Every PDF under :data:`PDF_SCOPE` whose XMP declares the Factur-X 1.0 / ZUGFeRD 2.1+ schema.

    The PDFs are read with pypdf (the ``[pdf]`` extra) only to get at the XMP and the attachments; every XML goes
    through :func:`euinvoice._xml.parse`.
    """
    corpus = _cached("zugferd-corpus")
    if corpus is None:
        return ()
    found = []
    for scope in PDF_SCOPE:
        for path in sorted((corpus / scope).rglob("*.pdf")):
            pdf = _read_pdf(path, path.relative_to(corpus).as_posix())
            if pdf is not None:
                found.append(pdf)
    return tuple(found)


def samples() -> list[Sample]:
    """Every cached upstream sample: the XML files of the corpora, then the Factur-X PDFs."""
    found = [sample for source in XML_DIRECTORIES for sample in _xml_samples(source)]
    return found + [Sample("zugferd-corpus", pdf.name, pdf.level) for pdf in facturx_pdfs()]


@dataclasses.dataclass(frozen=True)
class CrossSyntax:
    """A sample whose cross-syntax round trip (``test_cross_syntax.py``) is a documented exception.

    Attributes:
        outcome: ``refuses``: the other syntax's writer raises a ``ModelError`` naming exactly ``rules`` (a
            documented gap of that syntax). ``reads``: ``validate`` of the other syntax's output has exactly
            ``rules`` as its fatal or error rule ids.
        rules: See ``outcome``.
        differs: For ``reads``: the BT/BG ids where the round trip differs beyond the documented writer
            normalizations, exactly (a tracked gap; ``reason`` names its issue).
        reason: Why, citing ``docs/reference/bt-mapping.md`` or the rule texts.
    """

    outcome: t.Literal["refuses", "reads"]
    rules: frozenset[str]
    differs: frozenset[str]
    reason: str


@functools.cache
def cross_syntax() -> dict[str, CrossSyntax]:
    """The ``[[cross_syntax]]`` section of ``expected_invalid.toml`` keyed by :attr:`Sample.id`."""
    with EXPECTED_INVALID.open("rb") as file:
        entries = t.cast(list[dict[str, t.Any]], tomllib.load(file)["cross_syntax"])
    found: dict[str, CrossSyntax] = {}
    for entry in entries:
        assert {"source", "file", "outcome", "rules", "reason"} <= set(entry), entry
        assert set(entry) <= {"source", "file", "outcome", "rules", "differs", "reason"}, entry
        assert entry["outcome"] in ("refuses", "reads"), entry
        differs = entry.get("differs", [])
        for ids in (entry["rules"], differs):
            assert isinstance(ids, list), entry  # a bare string would become a set of characters
            assert all(isinstance(value, str) for value in ids), entry
        assert entry["rules"] or differs, f"{entry} documents no exception"
        assert entry["outcome"] == "reads" or not differs, entry
        assert isinstance(entry["reason"], str), entry
        assert entry["reason"], entry
        key = f"{entry['source']}:{entry['file']}"
        assert key not in found, f"duplicate entry {key}"
        found[key] = CrossSyntax(entry["outcome"], frozenset(entry["rules"]), frozenset(differs), entry["reason"])
    return found


@functools.cache
def expected_invalid() -> dict[str, ExpectedInvalid]:
    """``expected_invalid.toml`` keyed by :attr:`Sample.id`; a malformed or duplicate entry fails loudly."""
    with EXPECTED_INVALID.open("rb") as file:
        entries = t.cast(list[_Entry], tomllib.load(file)["sample"])
    found: dict[str, ExpectedInvalid] = {}
    for entry in entries:
        assert _Entry.__required_keys__ <= set(entry) <= _Entry.__required_keys__ | _Entry.__optional_keys__, entry
        assert entry["outcome"] in t.get_args(Outcome.__value__), entry
        differs = entry.get("differs", [])
        for ids in (entry["rules"], entry["upstream"], differs):
            # A bare string (rules = "X") would become a set of characters: refuse it at load time.
            assert isinstance(ids, list), entry
            assert all(isinstance(value, str) for value in ids), entry
        assert entry["rules"] or entry["upstream"] or differs, f"{entry} documents no exception"
        assert entry["outcome"] == "reads" or not differs, entry
        assert isinstance(entry["reason"], str), entry
        assert entry["reason"], entry
        assert isinstance(entry["link"], str), entry
        assert entry["link"].startswith("https://"), entry
        key = f"{entry['source']}:{entry['file']}"
        assert key not in found, f"duplicate entry {key}"
        found[key] = ExpectedInvalid(
            entry["outcome"],
            frozenset(entry["rules"]),
            frozenset(entry["upstream"]),
            frozenset(differs),
            entry["reason"],
            entry["link"],
        )
    return found
