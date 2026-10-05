"""Fetch, verify and look up the pinned official validation artifacts (IMPLEMENTATION_PLAN.md D7).

The sources are pinned in ``manifest.toml`` next to this module. :func:`fetch` is the only code in
euinvoice that touches the network: it downloads each archive with :mod:`urllib`, checks its sha256,
extracts the selected members safely into ``<cache>/<source>/<version>/`` and, for rule sets that ship
as Schematron only (Peppol), compiles them to XSLT with SchXslt. Everything else, :func:`source_dir`
in particular, only reads the cache and raises :class:`ArtifactsNotAvailableError` when it is cold.

Layout of a complete entry::

    <cache>/<source>/<version>/...            extracted members (minus ``strip_components``)
    <cache>/<source>/<version>/.euinvoice-sha256   marker: the archive sha256, written last

The marker is written into a temporary directory that is renamed into place, so an entry is either
complete or absent. A warm cache therefore needs no network at all.
"""

import fnmatch
import hashlib
import os
import shutil
import stat
import tempfile
import tomllib
import typing as t
import urllib.request
import zipfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath

from euinvoice import __version__
from euinvoice.errors import ArtifactIntegrityError, ArtifactsNotAvailableError

ENV_VAR = "EUINVOICE_ARTIFACTS_DIR"
DEFAULT_CACHE_DIR = "~/.cache/euinvoice"
FETCH_COMMAND = "python -m euinvoice artifacts fetch"
MARKER = ".euinvoice-sha256"

# The Schematron → XSLT compiler source and its entry point for queryBinding="xslt2" schemas
# (SchXslt 1.10.1 README, "XSLT only": transform the schema with pipeline-for-svrl.xsl).
SCHXSLT_SOURCE = "schxslt"
SCHXSLT_PIPELINE = "2.0/pipeline-for-svrl.xsl"

_CHUNK = 1 << 20
_TIMEOUT_S = 120


@dataclass(frozen=True, slots=True)
class Source:
    """One pinned upstream archive from ``manifest.toml``.

    Attributes:
        name: Manifest key, also the cache sub-directory.
        version: Upstream version; the cache directory below ``name``.
        url: HTTPS URL of the zip archive.
        sha256: Expected sha256 of the archive bytes (lowercase hex).
        license: Licence of the upstream content.
        members: fnmatch globs selecting archive members (after stripping); ``*`` matches ``/``.
        strip_components: Number of leading path components dropped from every member.
        precompile: ``.sch`` paths (relative to the extracted directory) compiled to sibling ``.xslt``.
        note: Free-text provenance note.
    """

    name: str
    version: str
    url: str
    sha256: str
    license: str
    members: tuple[str, ...]
    strip_components: int = 0
    precompile: tuple[str, ...] = ()
    note: str = ""


def load_manifest(text: str | None = None) -> dict[str, Source]:
    """Parse the artifact manifest.

    Args:
        text: TOML text to parse; defaults to the packaged ``manifest.toml``.

    Returns:
        The sources keyed by name, in manifest order.
    """
    if text is None:
        text = resources.files(__package__).joinpath("manifest.toml").read_text(encoding="utf-8")
    raw = tomllib.loads(text)
    return {
        name: Source(
            name=name,
            version=entry["version"],
            url=entry["url"],
            sha256=entry["sha256"].lower(),
            license=entry["license"],
            members=tuple(entry["members"]),
            strip_components=entry.get("strip_components", 0),
            precompile=tuple(entry.get("precompile", ())),
            note=entry.get("note", ""),
        )
        for name, entry in raw["sources"].items()
    }


def cache_dir() -> Path:
    """Return the artifact cache root: ``$EUINVOICE_ARTIFACTS_DIR``, else ``~/.cache/euinvoice``."""
    return Path(os.environ.get(ENV_VAR) or DEFAULT_CACHE_DIR).expanduser()


def source_dir(name: str, *, root: Path | None = None, sources: t.Mapping[str, Source] | None = None) -> Path:
    """Return the extracted directory of a fetched source, without touching the network.

    Args:
        name: Manifest key, e.g. ``"cen-ubl"``.
        root: Cache root; defaults to :func:`cache_dir`.
        sources: Manifest to resolve ``name`` in; defaults to :func:`load_manifest`.

    Returns:
        ``<root>/<name>/<version>``.

    Raises:
        KeyError: ``name`` is not in the manifest.
        ArtifactsNotAvailableError: The source has not been fetched (or not completely).
    """
    source = (load_manifest() if sources is None else sources)[name]
    target = _target(source, cache_dir() if root is None else root)
    if not _is_complete(source, target):
        raise ArtifactsNotAvailableError(
            f"Validation artifact {name!r} {source.version} is not in the cache at {target}. "
            f"Run `{FETCH_COMMAND}` (set ${ENV_VAR} to use another cache directory)."
        )
    return target


def fetch(
    names: t.Iterable[str] | None = None,
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
        sources: Manifest; defaults to :func:`load_manifest`.

    Returns:
        The extracted directory per fetched (or already cached) source name.

    Raises:
        KeyError: An unknown source name was requested.
        ArtifactIntegrityError: A download does not match its pinned sha256, or an archive member
            is unsafe (absolute path, ``..`` component, symlink).
        ArtifactsNotAvailableError: Precompiling needs ``saxonche`` (the ``[validate]`` extra).
    """
    sources = load_manifest() if sources is None else sources
    root = cache_dir() if root is None else root
    wanted = list(dict.fromkeys(sources if names is None else [sources[n].name for n in names]))
    if any(sources[n].precompile for n in wanted):  # the compiler must be in place first
        wanted = [SCHXSLT_SOURCE, *(n for n in wanted if n != SCHXSLT_SOURCE)]
    result: dict[str, Path] = {}
    for name in wanted:
        source = sources[name]
        target = _target(source, root)
        if not _is_complete(source, target):
            _install(source, target, result.get(SCHXSLT_SOURCE))
        result[name] = target
    return result


def _target(source: Source, root: Path) -> Path:
    return root / source.name / source.version


def _is_complete(source: Source, target: Path) -> bool:
    marker = target / MARKER
    return marker.is_file() and marker.read_text(encoding="ascii").strip() == source.sha256


def _open_url(url: str) -> t.BinaryIO:
    """Open ``url`` for reading. The single network entry point (patched in unit tests)."""
    if not url.startswith("https://"):
        raise ValueError(f"artifact URLs must use https: {url}")
    # The scheme is checked above, so S310 (file:// or custom schemes) does not apply.
    headers = {"User-Agent": f"euinvoice/{__version__}"}
    request = urllib.request.Request(url, headers=headers)  # ruff: ignore[suspicious-url-open-usage]
    response = urllib.request.urlopen(request, timeout=_TIMEOUT_S)  # ruff: ignore[suspicious-url-open-usage]
    return t.cast(t.BinaryIO, response)


def _download(source: Source, dest: Path) -> None:
    """Stream ``source.url`` into ``dest`` and verify its sha256."""
    digest = hashlib.sha256()
    with _open_url(source.url) as response, dest.open("wb") as out:
        while chunk := response.read(_CHUNK):
            digest.update(chunk)
            out.write(chunk)
    if digest.hexdigest() != source.sha256:
        raise ArtifactIntegrityError(
            f"{source.name} {source.version}: sha256 of {source.url} is {digest.hexdigest()}, "
            f"expected {source.sha256} (pinned in manifest.toml). Refusing to use it."
        )


def _install(source: Source, target: Path, schxslt: Path | None) -> None:
    """Download, extract and precompile into a temp dir, then rename it to ``target`` atomically."""
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{source.version}-", dir=parent))
    try:
        archive = staging / ".archive.zip"
        _download(source, archive)
        content = staging / "content"
        content.mkdir()
        _extract(source, archive, content)
        archive.unlink()
        if source.precompile:
            assert schxslt is not None  # ruff: ignore[assert] - guaranteed by fetch()
            _precompile(source, content, schxslt)
        (content / MARKER).write_text(source.sha256 + "\n", encoding="ascii")
        # ponytail: no file lock. Concurrent fetchers (e.g. pytest-xdist workers) may both download;
        # the first rename wins and the loser discards its copy. Add a lock file if that ever hurts.
        if _is_complete(source, target):
            return
        if target.exists():  # stale or incomplete entry: move it aside, it is deleted with staging
            os.replace(target, staging / "stale")
        try:
            os.replace(content, target)
        except OSError:
            if not _is_complete(source, target):
                raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _safe_member(source: Source, info: zipfile.ZipInfo) -> PurePosixPath | None:
    """Return the stripped relative path of a member, ``None`` to skip it, or raise if unsafe."""
    raw = info.filename
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
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


def _precompile(source: Source, content: Path, schxslt: Path) -> None:
    """Compile each ``precompile`` Schematron to a sibling ``.xslt`` with SchXslt on Saxon.

    The inputs are sha256-pinned official artifacts, not user documents, so they are handed to Saxon
    by file path; D10 (hardened parsing) governs invoice input.
    """
    try:
        import saxonche
    except ImportError as exc:
        raise ArtifactsNotAvailableError(
            f"{source.name} ships Schematron only and must be compiled to XSLT, which needs saxonche. "
            "Install the extra (`pip install 'euinvoice[validate]'`) and run "
            f"`{FETCH_COMMAND}` again."
        ) from exc
    with saxonche.PySaxonProcessor(license=False) as proc:
        compiler = proc.new_xslt30_processor().compile_stylesheet(stylesheet_file=str(schxslt / SCHXSLT_PIPELINE))
        for rel in source.precompile:
            sch = content / rel
            if not sch.is_file():
                raise ArtifactIntegrityError(f"{source.name}: precompile entry {rel!r} is not in the archive")
            xslt = compiler.transform_to_string(source_file=str(sch))
            sch.with_suffix(".xslt").write_text(xslt, encoding="utf-8")
