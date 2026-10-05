"""Unit tests for the artifact fetcher. The network is always mocked (``_open_url`` / ``_OPENER``)."""

import dataclasses
import hashlib
import http.client
import io
import os
import re
import stat
import sys
import types
import typing as t
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from euinvoice.errors import ArtifactIntegrityError, ArtifactsNotAvailableError
from euinvoice.validate import artifacts
from euinvoice.validate.artifacts import Source

# A stand-in for SchXslt's pipeline-for-svrl.xsl: "compiles" a schema by wrapping its title.
FAKE_PIPELINE = b"""<xsl:stylesheet version="2.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:sch="http://purl.oclc.org/dsdl/schematron" exclude-result-prefixes="sch">
  <xsl:template match="/"><compiled><xsl:value-of select="/sch:schema/sch:title"/></compiled></xsl:template>
</xsl:stylesheet>"""
FAKE_SCH = b"""<schema xmlns="http://purl.oclc.org/dsdl/schematron" queryBinding="xslt2"><title>T1</title></schema>"""

DEMO: artifacts.SourceName = "cen-ubl"
RULES: artifacts.SourceName = "peppol-bis"
SCHX: artifacts.SourceName = artifacts.SCHXSLT_SOURCE


def make_zip(files: t.Mapping[str, bytes], *, symlinks: t.Collection[str] = ()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            info = zipfile.ZipInfo(name)
            if name in symlinks:
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, data)
    return buf.getvalue()


def make_source(name: str, payload: bytes, **kw: t.Any) -> Source:
    return Source(
        name=name,
        version=kw.pop("version", "1.0"),
        url=f"https://example.com/{name}.zip",
        sha256=hashlib.sha256(payload).hexdigest(),
        license="MIT",
        members=kw.pop("members", ("*",)),
        **kw,
    )


class FakeNet:
    """Serves archives by URL and records every request."""

    def __init__(self) -> None:
        self.payloads: dict[str, bytes] = {}
        self.calls: list[str] = []

    def __call__(self, url: str) -> t.BinaryIO:
        self.calls.append(url)
        return io.BytesIO(self.payloads[url])

    def serve(self, *pairs: tuple[Source, bytes]) -> dict[str, Source]:
        for src, payload in pairs:
            self.payloads[src.url] = payload
        return {src.name: src for src, _ in pairs}


@pytest.fixture
def net(monkeypatch: pytest.MonkeyPatch) -> FakeNet:
    fake = FakeNet()
    monkeypatch.setattr(artifacts, "_open_url", fake)
    return fake


def offline(url: str) -> t.BinaryIO:
    raise AssertionError(f"network access in offline test: {url}")


def precompile_sources(net: FakeNet, sch: bytes = FAKE_SCH, pipeline: bytes = FAKE_PIPELINE) -> dict[str, Source]:
    schx_zip = make_zip({"schxslt-9/2.0/pipeline-for-svrl.xsl": pipeline})
    rules_zip = make_zip({"rules/sch/R.sch": sch})
    return net.serve(
        (make_source(RULES, rules_zip, precompile=("rules/sch/R.sch",)), rules_zip),
        (make_source(SCHX, schx_zip, strip_components=1), schx_zip),
    )


ARCHIVE = make_zip({"top/a.xml": b"<a/>", "top/sub/b.sch": b"<b/>", "top/skip.txt": b"x", "top/dir/": b""})


def test_fetch_extracts_selected_members_into_versioned_cache(tmp_path: Path, net: FakeNet) -> None:
    sources = net.serve((make_source(DEMO, ARCHIVE, strip_components=1, members=("*.xml", "sub/*")), ARCHIVE))

    result = artifacts.fetch(root=tmp_path, sources=sources)

    target = tmp_path / DEMO / "1.0"
    assert result == {DEMO: target}
    files = sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file())
    assert files == [artifacts.MARKER, "a.xml", "sub/b.sch"]
    assert (target / "a.xml").read_bytes() == b"<a/>"
    assert artifacts.source_dir(DEMO, root=tmp_path, sources=sources) == target
    assert [p.name for p in (tmp_path / DEMO).iterdir()] == ["1.0"]  # no temp dirs, no archive


def test_fetch_is_idempotent_and_warm_cache_works_offline(
    tmp_path: Path, net: FakeNet, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = net.serve((make_source(DEMO, ARCHIVE), ARCHIVE))
    artifacts.fetch(root=tmp_path, sources=sources)
    assert net.calls == [sources[DEMO].url]

    monkeypatch.setattr(artifacts, "_open_url", offline)
    assert artifacts.fetch([DEMO], root=tmp_path, sources=sources) == {DEMO: tmp_path / DEMO / "1.0"}


def test_changed_recipe_triggers_refetch(tmp_path: Path, net: FakeNet) -> None:
    narrow = make_source(DEMO, ARCHIVE, strip_components=1, members=("*.xml",))
    artifacts.fetch(root=tmp_path, sources=net.serve((narrow, ARCHIVE)))
    wide = dataclasses.replace(narrow, members=("*",))

    with pytest.raises(ArtifactsNotAvailableError):
        artifacts.source_dir(DEMO, root=tmp_path, sources={DEMO: wide})
    artifacts.fetch(root=tmp_path, sources={DEMO: wide})

    assert len(net.calls) == 2
    assert (tmp_path / DEMO / "1.0" / "skip.txt").is_file()


def test_schxslt_pin_change_triggers_recompile(tmp_path: Path, net: FakeNet) -> None:
    sources = precompile_sources(net)
    artifacts.fetch([RULES], root=tmp_path, sources=sources)
    new_zip = make_zip({"x/2.0/pipeline-for-svrl.xsl": FAKE_PIPELINE, "x/extra": b""})
    bumped = make_source(SCHX, new_zip, strip_components=1)
    sources = {**sources, **net.serve((bumped, new_zip))}

    with pytest.raises(ArtifactsNotAvailableError):
        artifacts.source_dir(RULES, root=tmp_path, sources=sources)
    artifacts.fetch([RULES], root=tmp_path, sources=sources)

    assert net.calls.count(sources[RULES].url) == 2


def test_corrupted_download_is_rejected_and_leaves_no_cache_entry(tmp_path: Path, net: FakeNet) -> None:
    src = make_source(DEMO, ARCHIVE)
    net.payloads[src.url] = ARCHIVE[:-1] + b"!"

    with pytest.raises(ArtifactIntegrityError, match=f"expected {src.sha256}"):
        artifacts.fetch(root=tmp_path, sources={DEMO: src})

    assert list((tmp_path / DEMO).iterdir()) == []
    with pytest.raises(ArtifactsNotAvailableError):
        artifacts.source_dir(DEMO, root=tmp_path, sources={DEMO: src})


@pytest.mark.parametrize(
    "exc",
    [urllib.error.URLError("no route"), TimeoutError("timed out"), ConnectionResetError("reset")],
)
def test_download_failure_becomes_not_available_with_retry_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc: OSError
) -> None:
    def failing(url: str) -> t.BinaryIO:
        raise exc

    monkeypatch.setattr(artifacts, "_open_url", failing)
    src = make_source(DEMO, ARCHIVE)
    with pytest.raises(ArtifactsNotAvailableError, match=re.escape(f"could not download {src.url}")) as info:
        artifacts.fetch(root=tmp_path, sources={DEMO: src})
    assert artifacts.FETCH_COMMAND in str(info.value)
    assert info.value.__cause__ is exc


def test_entry_with_stale_marker_is_refetched(tmp_path: Path, net: FakeNet) -> None:
    sources = net.serve((make_source(DEMO, ARCHIVE), ARCHIVE))
    target = tmp_path / DEMO / "1.0"
    target.mkdir(parents=True)
    (target / "leftover").write_text("old")
    (target / artifacts.MARKER).write_text("0" * 64)

    artifacts.fetch(root=tmp_path, sources=sources)

    assert len(net.calls) == 1
    assert not (target / "leftover").exists()
    assert artifacts.source_dir(DEMO, root=tmp_path, sources=sources) == target


@pytest.mark.parametrize(
    "member",
    ["../evil.txt", "top/../../evil.txt", "/etc/evil.txt", "C:/evil.txt", "top\\..\\evil.txt", "\\evil.txt", ""],
)
def test_zip_slip_member_is_rejected(tmp_path: Path, net: FakeNet, member: str) -> None:
    payload = make_zip({"ok.txt": b"ok", member: b"pwned"})
    sources = net.serve((make_source(DEMO, payload), payload))

    with pytest.raises(ArtifactIntegrityError, match="unsafe archive member"):
        artifacts.fetch(root=tmp_path, sources=sources)

    assert not list(tmp_path.rglob("evil.txt"))
    assert not (tmp_path / DEMO / "1.0").exists()


def test_symlink_member_is_rejected(tmp_path: Path, net: FakeNet) -> None:
    payload = make_zip({"link": b"/etc/passwd"}, symlinks={"link"})
    sources = net.serve((make_source(DEMO, payload), payload))

    with pytest.raises(ArtifactIntegrityError, match="symlink"):
        artifacts.fetch(root=tmp_path, sources=sources)


@given(
    name=st.lists(st.sampled_from(["a", "b", ".", "..", "", "C:", "\\", "x\\..", "~"]), max_size=5).map("/".join),
    leading_slash=st.booleans(),
    strip=st.integers(min_value=0, max_value=2),
)
def test_every_accepted_member_resolves_inside_dest(name: str, leading_slash: bool, strip: int) -> None:
    info = zipfile.ZipInfo("/" * leading_slash + name)
    source = Source(name="p", version="1", url="https://example.com", sha256="0" * 64, license="", members=("*",))
    source = dataclasses.replace(source, strip_components=strip)
    dest = Path("/srv/cache/p/1")
    try:
        rel = artifacts._safe_member(source, info)
    except ArtifactIntegrityError:
        return
    if rel is not None:
        assert Path(os.path.normpath(dest.joinpath(*rel.parts))).is_relative_to(dest)
        assert rel.parts
        assert ".." not in rel.parts


def test_source_dir_on_cold_cache_names_the_fetch_command(tmp_path: Path) -> None:
    src = make_source(DEMO, ARCHIVE)
    with pytest.raises(ArtifactsNotAvailableError, match=re.escape("python -m euinvoice artifacts fetch")):
        artifacts.source_dir(DEMO, root=tmp_path, sources={DEMO: src})


def test_cache_dir_honours_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(artifacts.ENV_VAR, str(tmp_path))
    assert artifacts.cache_dir() == tmp_path
    monkeypatch.setenv(artifacts.ENV_VAR, "")
    assert artifacts.cache_dir() == Path("~/.cache/euinvoice").expanduser()
    monkeypatch.delenv(artifacts.ENV_VAR)
    assert artifacts.cache_dir() == Path("~/.cache/euinvoice").expanduser()


def test_defaults_use_packaged_manifest_and_env_cache(
    tmp_path: Path, net: FakeNet, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(artifacts.ENV_VAR, str(tmp_path))
    real = artifacts.load_manifest()["xrechnung-schematron"]
    with pytest.raises(ArtifactsNotAvailableError, match=str(tmp_path)):
        artifacts.source_dir("xrechnung-schematron")
    net.payloads[real.url] = b"not the pinned archive"
    with pytest.raises(ArtifactIntegrityError):
        artifacts.fetch(["xrechnung-schematron"])


def test_fetch_rejects_a_bare_string(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="iterable of source names"):
        artifacts.fetch(t.cast(t.Any, "cen-ubl"), root=tmp_path, sources={})


def test_unknown_source_name_raises_key_error(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        artifacts.fetch(t.cast(t.Any, ["nope"]), root=tmp_path, sources={})


# --- SchXslt precompile ----------------------------------------------------------------------------


def test_precompile_compiles_schematron_with_schxslt(tmp_path: Path, net: FakeNet) -> None:
    sources = precompile_sources(net)

    result = artifacts.fetch([RULES], root=tmp_path, sources=sources)

    assert list(result) == [SCHX, RULES]
    xslt = (result[RULES] / "rules" / "sch" / "R.xslt").read_text(encoding="utf-8")
    assert "<compiled>T1</compiled>" in xslt
    assert (result[RULES] / "rules" / "sch" / "R.sch").read_bytes() == FAKE_SCH


def test_precompile_entry_missing_from_archive_is_an_integrity_error(tmp_path: Path, net: FakeNet) -> None:
    sources = precompile_sources(net)
    sources[RULES] = dataclasses.replace(sources[RULES], precompile=("R.sch",))

    with pytest.raises(ArtifactIntegrityError, match=re.escape("'R.sch' is not in the archive")):
        artifacts.fetch(root=tmp_path, sources=sources)


def test_broken_schxslt_pipeline_is_an_integrity_error(tmp_path: Path, net: FakeNet) -> None:
    sources = precompile_sources(net, pipeline=b"<not-xslt/>")
    with pytest.raises(ArtifactIntegrityError, match="cannot compile SchXslt"):
        artifacts.fetch([RULES], root=tmp_path, sources=sources)
    assert not (tmp_path / RULES / "1.0").exists()


def test_schematron_that_fails_to_compile_names_the_sch(tmp_path: Path, net: FakeNet) -> None:
    sources = precompile_sources(net, sch=b"this is not XML")
    with pytest.raises(ArtifactIntegrityError, match=re.escape("SchXslt failed on rules/sch/R.sch")):
        artifacts.fetch([RULES], root=tmp_path, sources=sources)


def test_schematron_with_a_doctype_is_refused_before_saxon(tmp_path: Path, net: FakeNet) -> None:
    sch = b'<!DOCTYPE schema [<!ENTITY t "T1">]>' + FAKE_SCH.replace(b"T1", b"&t;")
    sources = precompile_sources(net, sch=sch)
    with pytest.raises(ArtifactIntegrityError, match="DOCTYPE"):
        artifacts.fetch([RULES], root=tmp_path, sources=sources)


@pytest.mark.parametrize(
    "element",
    [
        '<include href="other.sch"/>',
        '<pattern><rule context="/"><extends href="rules.sch"/></rule></pattern>',
        '<pattern documents="\'codes.xml\'"><rule context="/"/></pattern>',
        '<pattern abstract="true" id="p" documents="\'codes.xml\'"/>',
    ],
)
def test_schematron_that_pulls_in_other_files_is_refused(tmp_path: Path, net: FakeNet, element: str) -> None:
    # Without a base URI SchXslt would resolve the href against the current directory.
    sch = FAKE_SCH.replace(b"</schema>", element.encode() + b"</schema>")
    sources = precompile_sources(net, sch=sch)
    with pytest.raises(ArtifactIntegrityError, match=r"rules/sch/R\.sch pulls in another file"):
        artifacts.fetch([RULES], root=tmp_path, sources=sources)


def test_schematron_extends_of_an_abstract_rule_is_fine(tmp_path: Path, net: FakeNet) -> None:
    body = b'<pattern><rule abstract="true" id="a"/><rule context="/"><extends rule="a"/></rule></pattern>'
    sources = precompile_sources(net, sch=FAKE_SCH.replace(b"</schema>", body + b"</schema>"))
    result = artifacts.fetch([RULES], root=tmp_path, sources=sources)
    assert "<compiled>T1</compiled>" in (result[RULES] / "rules" / "sch" / "R.xslt").read_text(encoding="utf-8")


def test_schxslt_without_output_is_an_integrity_error(
    tmp_path: Path, net: FakeNet, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Executable:
        def transform_to_string(self, xdm_node: object) -> None:
            return None

    class Proc:
        def __enter__(self) -> "Proc":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def new_xslt30_processor(self) -> "Proc":
            return self

        def compile_stylesheet(self, stylesheet_file: str) -> Executable:
            return Executable()

        def parse_xml(self, xml_text: str, encoding: str) -> object:
            return object()

    fake = types.SimpleNamespace(PySaxonProcessor=lambda license: Proc(), PySaxonApiError=RuntimeError)
    monkeypatch.setitem(sys.modules, "saxonche", fake)
    with pytest.raises(ArtifactIntegrityError, match=re.escape("produced no output for rules/sch/R.sch")):
        artifacts.fetch([RULES], root=tmp_path, sources=precompile_sources(net))


def test_precompile_without_compiler_source_is_not_available(tmp_path: Path) -> None:
    src = make_source(RULES, b"", precompile=("R.sch",))
    with pytest.raises(ArtifactsNotAvailableError, match="needs the 'schxslt' source"):
        artifacts._precompile(src, tmp_path, None)
    with pytest.raises(ArtifactsNotAvailableError, match="needs the 'schxslt' source"):
        artifacts._precompile(src, tmp_path, tmp_path / "missing")


def test_precompile_without_saxonche_explains_the_extra(
    tmp_path: Path, net: FakeNet, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "saxonche", None)  # makes `import saxonche` raise ImportError
    sources = precompile_sources(net)

    with pytest.raises(ArtifactsNotAvailableError, match=re.escape("euinvoice[validate]")):
        artifacts.fetch(root=tmp_path, sources=sources)
    assert not (tmp_path / RULES / "1.0").exists()


# --- concurrency -----------------------------------------------------------------------------------


def test_concurrent_fetcher_that_finished_first_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = make_source(DEMO, ARCHIVE)
    target = tmp_path / DEMO / "1.0"
    fingerprint = artifacts._fingerprint(src, {DEMO: src})

    def racing_open(url: str) -> t.BinaryIO:
        target.mkdir(parents=True)  # another process completes the entry while we download
        (target / "theirs").write_text("x")
        (target / artifacts.MARKER).write_text(fingerprint)
        return io.BytesIO(ARCHIVE)

    monkeypatch.setattr(artifacts, "_open_url", racing_open)
    assert artifacts.fetch(root=tmp_path, sources={DEMO: src}) == {DEMO: target}
    assert sorted(p.name for p in target.iterdir()) == [artifacts.MARKER, "theirs"]
    assert [p.name for p in (tmp_path / DEMO).iterdir()] == ["1.0"]


@pytest.mark.parametrize("other_completed", [True, False])
def test_rename_failure_is_tolerated_only_if_another_fetcher_completed(
    tmp_path: Path, net: FakeNet, monkeypatch: pytest.MonkeyPatch, other_completed: bool
) -> None:
    sources = net.serve((make_source(DEMO, ARCHIVE), ARCHIVE))
    target = tmp_path / DEMO / "1.0"
    real_replace = os.replace

    def flaky_replace(a: t.Any, b: t.Any) -> None:
        if Path(b) == target:
            if other_completed:
                target.mkdir(parents=True)
                (target / artifacts.MARKER).write_text(artifacts._fingerprint(sources[DEMO], sources))
            raise OSError("Directory not empty")
        real_replace(a, b)

    monkeypatch.setattr(os, "replace", flaky_replace)
    if other_completed:
        assert artifacts.fetch(root=tmp_path, sources=sources) == {DEMO: target}
    else:
        with pytest.raises(OSError, match="not empty"):
            artifacts.fetch(root=tmp_path, sources=sources)


# --- network entry point ---------------------------------------------------------------------------


def test_open_url_rejects_non_https() -> None:
    with pytest.raises(ValueError, match="https"):
        artifacts._open_url("file:///etc/passwd")


def test_open_url_uses_the_https_only_opener(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, t.Any] = {}

    class Opener:
        def open(self, request: urllib.request.Request, timeout: float) -> io.BytesIO:
            seen["ua"] = request.get_header("User-agent")
            seen["timeout"] = timeout
            return io.BytesIO(b"x")

    monkeypatch.setattr(artifacts, "_OPENER", Opener())
    assert artifacts._open_url("https://example.com/a.zip").read() == b"x"
    assert seen["ua"].startswith("euinvoice/")
    assert seen["timeout"] > 0


def test_real_opener_installs_the_https_only_redirect_handler() -> None:
    assert artifacts._REDIRECTS.parent is artifacts._OPENER


@pytest.mark.parametrize("newurl", ["http://example.com/a.zip", "ftp://example.com/a.zip", "file:///etc/passwd"])
def test_redirect_away_from_https_is_refused(newurl: str) -> None:
    handler = artifacts._HttpsOnlyRedirects()
    request = urllib.request.Request("https://example.com/a.zip")
    with pytest.raises(ArtifactIntegrityError, match="non-https"):
        handler.redirect_request(request, io.BytesIO(), 302, "Found", http.client.HTTPMessage(), newurl)


def test_redirect_to_https_is_followed() -> None:
    handler = artifacts._HttpsOnlyRedirects()
    request = urllib.request.Request("https://example.com/a.zip")
    new = handler.redirect_request(
        request, io.BytesIO(), 302, "Found", http.client.HTTPMessage(), "https://cdn.example.com/a.zip"
    )
    assert new is not None
    assert new.full_url == "https://cdn.example.com/a.zip"


# --- the manifest ----------------------------------------------------------------------------------


def test_packaged_manifest_is_well_formed() -> None:
    sources = artifacts.load_manifest()
    for src in sources.values():
        assert src.members, src.name
        assert src.license, src.name
        assert src.note, src.name
    assert artifacts.SCHXSLT_SOURCE in sources


def test_source_name_literal_matches_the_manifest() -> None:
    assert set(t.get_args(artifacts.SourceName)) == set(artifacts.load_manifest())


def test_packaged_manifest_is_parsed_once() -> None:
    assert artifacts._packaged_manifest() is artifacts._packaged_manifest()
    assert artifacts.load_manifest() == artifacts._packaged_manifest()
    assert artifacts.load_manifest() is not artifacts._packaged_manifest()  # callers get a copy


MINIMAL = """
schema_version = 1
[sources.{name}]
version = "{version}"
url = "{url}"
sha256 = "{sha256}"
license = "MIT"
members = ["*"]
precompile = [{precompile}]
"""
GOOD: dict[str, str] = {
    "name": "x",
    "version": "1",
    "url": "https://example.com/x.zip",
    "sha256": "AB" * 32,
    "precompile": "",
}


def test_load_manifest_applies_defaults() -> None:
    assert artifacts.load_manifest(MINIMAL.format(**GOOD))["x"] == Source(
        name="x", version="1", url="https://example.com/x.zip", sha256="ab" * 32, license="MIT", members=("*",)
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("version", "../../escape", "version"),
        ("version", "..", "version"),
        ("version", ".", "version"),
        ("version", "a/b", "version"),
        ("name", '"..', "name"),
        ("name", '"a b', "name"),
        ("url", "http://example.com/x.zip", "https"),
        ("sha256", "abc", "64 hex"),
        ("sha256", "g" * 64, "64 hex"),
        ("precompile", '"../x.sch"', "precompile"),
        ("precompile", '"/x.sch"', "precompile"),
        ("precompile", '"x.xml"', "precompile"),
    ],
)
def test_load_manifest_rejects_unsafe_entries(field: str, value: str, message: str) -> None:
    text = MINIMAL.format(**{**GOOD, field: value})
    if field == "name":  # quoted TOML key
        text = text.replace(f"[sources.{value}]", f'[sources.{value}"]')
    with pytest.raises(ArtifactIntegrityError, match=message):
        artifacts.load_manifest(text)


def test_negative_strip_components_is_rejected() -> None:
    text = MINIMAL.format(**GOOD) + "strip_components = -1\n"
    with pytest.raises(ArtifactIntegrityError, match="strip_components"):
        artifacts.load_manifest(text)
