"""Fetch, verify and look up the pinned official validation artifacts (IMPLEMENTATION_PLAN.md D7).

The sources are pinned in ``manifest.toml`` next to this module. :func:`fetch` is the only code in
euinvoice that touches the network: it downloads each source with :mod:`urllib` (https only, also
across redirects), checks its sha256, extracts the selected members of a zip archive safely into
``<cache>/<source>/<version>/`` (or stores a single-file source there under its ``file`` name) and, for
rule sets that ship as Schematron only (Peppol), compiles them to XSLT with SchXslt. Everything else,
:func:`source_dir` in particular, only reads the cache and raises :class:`ArtifactsNotAvailableError` when
it is cold.

Layout of a complete entry::

    <cache>/<source>/<version>/...                       extracted members (minus ``strip_components``)
    <cache>/<source>/<version>/<file>                    or the one downloaded file of a ``file`` source
    <cache>/<source>/<version>/.euinvoice-fingerprint    marker, written last

The marker holds a fingerprint of the whole recipe (download sha256, member globs or file name,
stripping, precompile list and, when precompiling, the SchXslt pin), so changing any of them rebuilds the entry.
It is written into a temporary directory that is renamed into place, so an entry is either complete
or absent. A warm cache therefore needs no network at all.
"""

import contextlib
import fnmatch
import functools
import hashlib
import http.client
import json
import os
import re
import shutil
import stat
import tempfile
import tomllib
import typing as t
import urllib.request
import zipfile
from dataclasses import dataclass
from importlib import metadata, resources
from pathlib import Path, PurePosixPath

from lxml import etree

from euinvoice import _xml
from euinvoice.errors import ArtifactIntegrityError, ArtifactsNotAvailableError, ParseError

ENV_VAR = "EUINVOICE_ARTIFACTS_DIR"
DEFAULT_CACHE_DIR = "~/.cache/euinvoice"
FETCH_COMMAND = "python -m euinvoice artifacts fetch"
MARKER = ".euinvoice-fingerprint"

# Keys of manifest.toml; a unit test keeps this in sync with the packaged manifest.
SourceName = t.Literal[
    "cen-ubl",
    "cen-cii",
    "peppol-bis",
    "xrechnung-schematron",
    "xrechnung-testsuite",
    "xrechnung-validator-configuration",
    "ubl-2_1",
    "zugferd-corpus",
    "schxslt",
    "fatturapa-xsd",
]

# The Schematron → XSLT compiler source and its entry point for queryBinding="xslt2" schemas
# (SchXslt 1.10.1 README, "XSLT only": transform the schema with pipeline-for-svrl.xsl).
SCHXSLT_SOURCE: SourceName = "schxslt"
SCHXSLT_PIPELINE = "2.0/pipeline-for-svrl.xsl"

_CHUNK = 1 << 20
_TIMEOUT_S = 120
_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class Source:
    """One pinned upstream download from ``manifest.toml``: a zip archive (``members``) or a single file (``file``).

    Attributes:
        name: Manifest key, also the cache sub-directory.
        version: Upstream version; the cache directory below ``name``.
        url: HTTPS URL of the zip archive or the single file.
        sha256: Expected sha256 of the downloaded bytes (lowercase hex).
        license: Licence of the upstream content.
        members: fnmatch globs selecting archive members (after stripping); ``*`` matches ``/``. Empty for
            a single-file source.
        file: For a single-file source, the name the download is stored under in the version directory;
            empty for a zip archive. Exactly one of ``members`` and ``file`` is set.
        strip_components: Number of leading path components dropped from every member.
        precompile: ``.sch`` paths (relative to the extracted directory) compiled to sibling ``.xslt``.
        note: Free-text provenance note.
    """

    name: str
    version: str
    url: str
    sha256: str
    license: str
    members: tuple[str, ...] = ()
    strip_components: int = 0
    precompile: tuple[str, ...] = ()
    note: str = ""
    file: str = ""


def _check_source(source: Source) -> Source:
    """Reject manifest entries that could escape the cache or bypass https / sha256 pinning."""
    problems = [
        f"{field} {value!r} must match [A-Za-z0-9._-]+ and not be '.' or '..'"
        for field, value in (("name", source.name), ("version", source.version))
        if not _SAFE_SEGMENT.fullmatch(value) or value in {".", ".."}
    ]
    if not source.url.startswith("https://"):
        problems.append(f"url {source.url!r} must use https")
    if not _SHA256.fullmatch(source.sha256):
        problems.append(f"sha256 {source.sha256!r} must be 64 hex characters")
    if source.strip_components < 0:
        problems.append("strip_components must be >= 0")
    problems += _layout_problems(source)
    for rel in source.precompile:
        path = PurePosixPath(rel)
        if path.is_absolute() or ".." in path.parts or path.suffix != ".sch":
            problems.append(f"precompile entry {rel!r} must be a relative .sch path without '..'")
    if problems:
        raise ArtifactIntegrityError(f"manifest source {source.name!r}: " + "; ".join(problems))
    return source


def _layout_problems(source: Source) -> list[str]:
    """A source is a zip archive (``members``) or a single file (``file``) stored as one path segment."""
    if bool(source.members) == bool(source.file):
        return ["set exactly one of members or file"]
    problems: list[str] = []
    # A leading dot is refused: it covers '.', '..' and the cache marker MARKER, which would overwrite the file (#128).
    if source.file and (not _SAFE_SEGMENT.fullmatch(source.file) or source.file.startswith(".")):
        problems.append(f"file {source.file!r} must match [A-Za-z0-9._-]+ and not start with '.'")
    if source.file and (source.strip_components or source.precompile):
        problems.append("a single-file source takes neither strip_components nor precompile")
    return problems


def load_manifest(text: str | None = None) -> dict[str, Source]:
    """Parse and validate the artifact manifest.

    Args:
        text: TOML text to parse; defaults to the packaged ``manifest.toml``.

    Returns:
        The sources keyed by name, in manifest order.

    Raises:
        ArtifactIntegrityError: An entry has an unsafe name/version, a non-https URL or a malformed
            sha256.
    """
    if text is None:
        return dict(_packaged_manifest())
    raw = tomllib.loads(text)
    return {
        name: _check_source(
            Source(
                name=name,
                version=entry["version"],
                url=entry["url"],
                sha256=entry["sha256"].lower(),
                license=entry["license"],
                members=tuple(entry.get("members", ())),
                strip_components=entry.get("strip_components", 0),
                precompile=tuple(entry.get("precompile", ())),
                note=entry.get("note", ""),
                file=entry.get("file", ""),
            )
        )
        for name, entry in raw["sources"].items()
    }


@functools.cache
def _packaged_manifest() -> t.Mapping[str, Source]:
    text = resources.files(__package__).joinpath("manifest.toml").read_text(encoding="utf-8")
    return load_manifest(text)


def cache_dir() -> Path:
    """Return the artifact cache root: ``$EUINVOICE_ARTIFACTS_DIR``, else ``~/.cache/euinvoice``."""
    return Path(os.environ.get(ENV_VAR) or DEFAULT_CACHE_DIR).expanduser()


def source_dir(name: SourceName, *, root: Path | None = None, sources: t.Mapping[str, Source] | None = None) -> Path:
    """Return the extracted directory of a fetched source, without touching the network.

    Args:
        name: Manifest key, e.g. ``"cen-ubl"``.
        root: Cache root; defaults to :func:`cache_dir`.
        sources: Manifest to resolve ``name`` in; defaults to the packaged manifest.

    Returns:
        ``<root>/<name>/<version>``.

    Raises:
        KeyError: ``name`` is not in the manifest.
        ArtifactsNotAvailableError: The source has not been fetched (or not with the current recipe).
    """
    sources = _packaged_manifest() if sources is None else sources
    source = sources[name]
    target = _target(source, cache_dir() if root is None else root)
    if not _is_complete(target, _fingerprint(source, sources)):
        raise ArtifactsNotAvailableError(
            f"Validation artifact {name!r} {source.version} is not in the cache at {target}. "
            f"Run `{FETCH_COMMAND}` (set ${ENV_VAR} to use another cache directory)."
        )
    return target


def fetch(
    names: t.Iterable[SourceName] | None = None,
    *,
    root: Path | None = None,
    sources: t.Mapping[str, Source] | None = None,
) -> dict[str, Path]:
    """Download, verify and extract sources that are not in the cache yet.

    Idempotent: sources whose cache entry is complete are skipped without any network access.
    A source with ``precompile`` entries pulls in the SchXslt source first.

    Args:
        names: Manifest keys to fetch; all sources when ``None``.
        root: Cache root; defaults to :func:`cache_dir`.
        sources: Manifest; defaults to the packaged manifest.

    Returns:
        The extracted directory per fetched (or already cached) source name.

    Raises:
        TypeError: ``names`` is a single string instead of an iterable of names.
        KeyError: An unknown source name was requested.
        ArtifactIntegrityError: A download does not match its pinned sha256, a redirect leaves https,
            an archive member is unsafe (absolute path, ``..`` component, symlink) or a Schematron
            cannot be compiled.
        ArtifactsNotAvailableError: A download failed (network / HTTP error), or precompiling needs
            ``saxonche`` (the ``[validate]`` extra).
    """
    if isinstance(names, str):
        raise TypeError(f"fetch() takes an iterable of source names, not the string {names!r}")
    sources = _packaged_manifest() if sources is None else sources
    root = cache_dir() if root is None else root
    wanted: list[str] = list(dict.fromkeys(sources if names is None else [sources[n].name for n in names]))
    if any(sources[n].precompile for n in wanted):  # the compiler must be in place first
        wanted = [SCHXSLT_SOURCE, *(n for n in wanted if n != SCHXSLT_SOURCE)]
    result: dict[str, Path] = {}
    for name in wanted:
        source = sources[name]
        target = _target(source, root)
        fingerprint = _fingerprint(source, sources)
        if not _is_complete(target, fingerprint):
            compiler = _target(sources[SCHXSLT_SOURCE], root) if source.precompile else None
            _install(source, target, fingerprint, compiler)
        result[name] = target
    return result


def _target(source: Source, root: Path) -> Path:
    return root / source.name / source.version


def _fingerprint(source: Source, sources: t.Mapping[str, Source]) -> str:
    """sha256 of the canonical recipe that produced an entry (see the module docstring)."""
    recipe: dict[str, object] = {
        "sha256": source.sha256,
        "members": list(source.members),
        "strip_components": source.strip_components,
        "precompile": list(source.precompile),
    }
    if source.file:  # only when set, so the fingerprints of existing zip entries stay the same
        recipe["file"] = source.file
    if source.precompile:
        recipe["schxslt"] = [sources[SCHXSLT_SOURCE].sha256, SCHXSLT_PIPELINE]
    return hashlib.sha256(json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _is_complete(target: Path, fingerprint: str) -> bool:
    marker = target / MARKER
    return marker.is_file() and marker.read_text(encoding="ascii").strip() == fingerprint


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to https URLs (urllib would also follow http:// and ftp://)."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: t.IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        """Refuse a redirect that leaves https, otherwise defer to urllib."""
        if not newurl.startswith("https://"):
            raise ArtifactIntegrityError(f"refusing redirect from {req.full_url} to non-https {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_REDIRECTS = _HttpsOnlyRedirects()
_OPENER = urllib.request.build_opener(_REDIRECTS)


def _open_url(url: str) -> t.BinaryIO:
    """Open ``url`` for reading. The single network entry point (patched in unit tests)."""
    if not url.startswith("https://"):
        raise ValueError(f"artifact URLs must use https: {url}")
    # The scheme is checked above and on every redirect, so S310 (file:// or custom schemes) does not apply.
    request = urllib.request.Request(  # ruff: ignore[suspicious-url-open-usage]
        url, headers={"User-Agent": f"euinvoice/{metadata.version('euinvoice')}"}
    )
    return t.cast(t.BinaryIO, _OPENER.open(request, timeout=_TIMEOUT_S))


def _download(source: Source, dest: Path) -> None:
    """Stream ``source.url`` into ``dest`` and verify its sha256."""
    digest = hashlib.sha256()
    try:
        with _open_url(source.url) as response, dest.open("wb") as out:
            while chunk := response.read(_CHUNK):
                digest.update(chunk)
                out.write(chunk)
    except OSError as exc:  # URLError, HTTPError and TimeoutError are OSErrors
        raise ArtifactsNotAvailableError(
            f"{source.name} {source.version}: could not download {source.url}: {exc}. "
            f"Check the network and run `{FETCH_COMMAND}` again."
        ) from exc
    if digest.hexdigest() != source.sha256:
        raise ArtifactIntegrityError(
            f"{source.name} {source.version}: sha256 of {source.url} is {digest.hexdigest()}, "
            f"expected {source.sha256} (pinned in manifest.toml). Refusing to use it."
        )


def _install(source: Source, target: Path, fingerprint: str, compiler: Path | None) -> None:
    """Download, extract (or place the single file) and precompile into a temp dir, then rename it atomically."""
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{source.version}-", dir=parent))
    try:
        download = staging / ".download"
        _download(source, download)
        content = staging / "content"
        content.mkdir()
        if source.file:
            download.rename(content / source.file)
        else:
            _extract(source, download, content)
            download.unlink()
        if source.precompile:
            _precompile(source, content, compiler)
        (content / MARKER).write_text(fingerprint + "\n", encoding="ascii")
        # ponytail: no file lock. Concurrent fetchers (e.g. pytest-xdist workers) may both download;
        # the first rename wins and the loser discards its copy. Add a lock file if that ever hurts.
        if _is_complete(target, fingerprint):
            return
        with contextlib.suppress(FileNotFoundError):  # stale entry: move aside, deleted with staging
            os.replace(target, staging / "stale")
        try:
            os.replace(content, target)
        except OSError:
            if not _is_complete(target, fingerprint):
                raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _safe_member(source: Source, info: zipfile.ZipInfo) -> PurePosixPath | None:
    """Return the stripped relative path of a member, ``None`` to skip it, or raise if unsafe."""
    raw = info.filename
    path = PurePosixPath(raw)
    if (
        not path.parts
        or path.is_absolute()
        or raw.startswith("\\")
        or ":" in path.parts[0]
        or ".." in path.parts
        or "\\" in raw
        or stat.S_ISLNK(info.external_attr >> 16)
    ):
        raise ArtifactIntegrityError(f"{source.name}: unsafe archive member {raw!r} (zip slip / symlink)")
    if info.is_dir() or len(path.parts) <= source.strip_components:
        return None
    rel = PurePosixPath(*path.parts[source.strip_components :])
    if not any(fnmatch.fnmatchcase(str(rel), glob) for glob in source.members):
        return None
    return rel


def _extract(source: Source, archive: Path, dest: Path) -> None:
    """Extract the selected members of ``archive`` into ``dest`` (zip-slip safe)."""
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            rel = _safe_member(source, info)
            if rel is None:
                continue
            # Safe by construction: rel is relative, has no "..", and no symlink is ever extracted.
            out = dest.joinpath(*rel.parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst, _CHUNK)


def _precompile(source: Source, content: Path, compiler: Path | None) -> None:
    """Compile each ``precompile`` Schematron to a sibling ``.xslt`` with SchXslt on Saxon.

    Only the pinned SchXslt pipeline is loaded by path (it includes its sibling stylesheets). Each
    ``.sch`` reaches Saxon through :func:`euinvoice._xml.to_xdm` (D10), so it has no base URI and a
    schema with ``sch:include`` or ``sch:extends[@href]`` is refused. For the Peppol ``.sch`` files, which
    use neither, the output differs from a by-path compile only in SchXslt's ``dct:created`` timestamp
    and generated ids (checked on Peppol 3.0.21).
    """
    if compiler is None or not (compiler / SCHXSLT_PIPELINE).is_file():
        raise ArtifactsNotAvailableError(
            f"{source.name} needs the {SCHXSLT_SOURCE!r} source to compile its Schematron; run `{FETCH_COMMAND}`."
        )
    try:
        import saxonche
    except ImportError as exc:
        raise ArtifactsNotAvailableError(
            f"{source.name} ships Schematron only and must be compiled to XSLT, which needs saxonche. "
            "Install the extra (`pip install 'euinvoice[validate]'`) and run "
            f"`{FETCH_COMMAND}` again."
        ) from exc
    with saxonche.PySaxonProcessor(license=False) as proc:
        pipeline = compiler / SCHXSLT_PIPELINE
        try:
            executable = proc.new_xslt30_processor().compile_stylesheet(stylesheet_file=str(pipeline))
        except saxonche.PySaxonApiError as exc:
            raise ArtifactIntegrityError(f"{source.name}: cannot compile SchXslt {pipeline}: {exc}") from exc
        for rel in source.precompile:
            sch = content / rel
            if not sch.is_file():
                raise ArtifactIntegrityError(f"{source.name}: precompile entry {rel!r} is not in the archive")
            try:
                node = _xml.to_xdm(proc, _standalone_schematron(source, rel, sch.read_bytes()))
                xslt = executable.transform_to_string(xdm_node=node)
            except (ParseError, saxonche.PySaxonApiError) as exc:
                raise ArtifactIntegrityError(f"{source.name}: SchXslt failed on {rel}: {exc}") from exc
            if xslt is None:
                raise ArtifactIntegrityError(f"{source.name}: SchXslt produced no output for {rel}")
            sch.with_suffix(".xslt").write_text(xslt, encoding="utf-8")


def _standalone_schematron(source: Source, rel: str, data: bytes) -> etree._Element:
    """Parse a ``.sch`` and refuse it if it pulls in other files.

    The schema reaches SchXslt as text without a base URI, so a reference to another file would be
    resolved against the current directory instead of the artifact. SchXslt 1.10.1 follows three:

    * ``sch:include`` and ``sch:extends[@href]``, loaded at compile time (``2.0/include.xsl``, template
      ``match="sch:include | sch:extends[@href]"``); ``sch:extends[@rule]`` is an in-schema reference.
    * ``sch:pattern[@documents]``, loaded at validation time: the generated XSLT runs
      ``source-document href="{resolve-uri(., $base-uri)}"`` (``2.0/compile/compile-2.0.xsl``,
      ``xsl:when test="@documents"``). Abstract patterns pass ``@documents`` on to their instances
      (``2.0/expand.xsl``), so every pattern is checked.
    """
    root = _xml.parse(data)
    sch = f"{{{_xml.SCHEMATRON}}}"
    for element in root.iter(f"{sch}include", f"{sch}extends", f"{sch}pattern"):
        name = etree.QName(element).localname
        target = element.get("documents") if name == "pattern" else element.get("href")
        if name == "include" or target is not None:
            raise ArtifactIntegrityError(
                f"{source.name}: {rel} pulls in another file (sch:{name} {target!r}), "
                "which cannot be resolved without a base URI"
            )
    return root
