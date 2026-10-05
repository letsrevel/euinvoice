"""Unit tests for the artifact fetcher. The network is always mocked (``_open_url``)."""

import hashlib
import io
import os
import re
import stat
import sys
import typing as t
import urllib.request
import zipfile
from pathlib import Path

import pytest

from euinvoice.errors import ArtifactIntegrityError, ArtifactsNotAvailableError
from euinvoice.validate import artifacts
from euinvoice.validate.artifacts import Source

# A stand-in for SchXslt's pipeline-for-svrl.xsl: "compiles" a schema by wrapping its title.
FAKE_PIPELINE = b"""<xsl:stylesheet version="2.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:sch="http://purl.oclc.org/dsdl/schematron" exclude-result-prefixes="sch">
  <xsl:template match="/"><compiled><xsl:value-of select="/sch:schema/sch:title"/></compiled></xsl:template>
</xsl:stylesheet>"""
FAKE_SCH = b"""<schema xmlns="http://purl.oclc.org/dsdl/schematron" queryBinding="xslt2"><title>T1</title></schema>"""


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

    def __init__(self, payloads: t.Mapping[str, bytes]) -> None:
        self.payloads = dict(payloads)
        self.calls: list[str] = []

    def __call__(self, url: str) -> t.BinaryIO:
        self.calls.append(url)
        return io.BytesIO(self.payloads[url])


@pytest.fixture
def net(monkeypatch: pytest.MonkeyPatch) -> FakeNet:
    fake = FakeNet({})
    monkeypatch.setattr(artifacts, "_open_url", fake)
    return fake


def offline(url: str) -> t.BinaryIO:
    raise AssertionError(f"network access in offline test: {url}")


ARCHIVE = make_zip({"top/a.xml": b"<a/>", "top/sub/b.sch": b"<b/>", "top/skip.txt": b"x", "top/dir/": b""})


def test_fetch_extracts_selected_members_into_versioned_cache(tmp_path: Path, net: FakeNet) -> None:
    src = make_source("demo", ARCHIVE, strip_components=1, members=("*.xml", "sub/*"))
    net.payloads[src.url] = ARCHIVE

    result = artifacts.fetch(root=tmp_path, sources={"demo": src})

    target = tmp_path / "demo" / "1.0"
    assert result == {"demo": target}
    files = sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file())
    assert files == [artifacts.MARKER, "a.xml", "sub/b.sch"]
    assert (target / "a.xml").read_bytes() == b"<a/>"
    assert artifacts.source_dir("demo", root=tmp_path, sources={"demo": src}) == target
    # nothing else left behind (no temp dirs, no archive)
    assert [p.name for p in (tmp_path / "demo").iterdir()] == ["1.0"]


def test_fetch_is_idempotent_and_warm_cache_works_offline(
    tmp_path: Path, net: FakeNet, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = make_source("demo", ARCHIVE)
    net.payloads[src.url] = ARCHIVE
    artifacts.fetch(root=tmp_path, sources={"demo": src})
    assert net.calls == [src.url]

    monkeypatch.setattr(artifacts, "_open_url", offline)
    assert artifacts.fetch(["demo"], root=tmp_path, sources={"demo": src}) == {"demo": tmp_path / "demo" / "1.0"}


def test_corrupted_download_is_rejected_and_leaves_no_cache_entry(tmp_path: Path, net: FakeNet) -> None:
    src = make_source("demo", ARCHIVE)
    net.payloads[src.url] = ARCHIVE[:-1] + b"!"

    with pytest.raises(ArtifactIntegrityError, match=f"expected {src.sha256}"):
        artifacts.fetch(root=tmp_path, sources={"demo": src})

    assert list((tmp_path / "demo").iterdir()) == []
    with pytest.raises(ArtifactsNotAvailableError):
        artifacts.source_dir("demo", root=tmp_path, sources={"demo": src})


def test_entry_with_stale_marker_is_refetched(tmp_path: Path, net: FakeNet) -> None:
    src = make_source("demo", ARCHIVE)
    net.payloads[src.url] = ARCHIVE
    target = tmp_path / "demo" / "1.0"
    target.mkdir(parents=True)
    (target / "leftover").write_text("old")
    (target / artifacts.MARKER).write_text("0" * 64)

    artifacts.fetch(root=tmp_path, sources={"demo": src})

    assert net.calls == [src.url]
    assert not (target / "leftover").exists()
    assert (target / artifacts.MARKER).read_text().strip() == src.sha256


@pytest.mark.parametrize(
    "member",
    ["../evil.txt", "top/../../evil.txt", "/etc/evil.txt", "C:/evil.txt", "top\\..\\evil.txt", "\\evil.txt"],
)
def test_zip_slip_member_is_rejected(tmp_path: Path, net: FakeNet, member: str) -> None:
    payload = make_zip({"ok.txt": b"ok", member: b"pwned"})
    src = make_source("demo", payload)
    net.payloads[src.url] = payload

    with pytest.raises(ArtifactIntegrityError, match="unsafe archive member"):
        artifacts.fetch(root=tmp_path, sources={"demo": src})

    assert not list(tmp_path.rglob("evil.txt"))
    assert not (tmp_path / "demo" / "1.0").exists()


def test_symlink_member_is_rejected(tmp_path: Path, net: FakeNet) -> None:
    payload = make_zip({"link": b"/etc/passwd"}, symlinks={"link"})
    src = make_source("demo", payload)
    net.payloads[src.url] = payload

    with pytest.raises(ArtifactIntegrityError, match="symlink"):
        artifacts.fetch(root=tmp_path, sources={"demo": src})


def test_source_dir_on_cold_cache_names_the_fetch_command(tmp_path: Path) -> None:
    src = make_source("demo", ARCHIVE)
    with pytest.raises(ArtifactsNotAvailableError, match=re.escape("python -m euinvoice artifacts fetch")):
        artifacts.source_dir("demo", root=tmp_path, sources={"demo": src})


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


def test_precompile_compiles_schematron_with_schxslt(tmp_path: Path, net: FakeNet) -> None:
    schx_zip = make_zip({"schxslt-9/2.0/pipeline-for-svrl.xsl": FAKE_PIPELINE})
    rules_zip = make_zip({"rules/sch/R.sch": FAKE_SCH})
    schx = make_source(artifacts.SCHXSLT_SOURCE, schx_zip, strip_components=1)
    rules = make_source("rules", rules_zip, precompile=("rules/sch/R.sch",))
    net.payloads |= {schx.url: schx_zip, rules.url: rules_zip}

    result = artifacts.fetch(["rules"], root=tmp_path, sources={"rules": rules, schx.name: schx})

    assert list(result) == [artifacts.SCHXSLT_SOURCE, "rules"]
    xslt = (result["rules"] / "rules" / "sch" / "R.xslt").read_text(encoding="utf-8")
    assert "<compiled>T1</compiled>" in xslt
    assert (result["rules"] / "rules" / "sch" / "R.sch").read_bytes() == FAKE_SCH


def test_precompile_entry_missing_from_archive_is_an_integrity_error(tmp_path: Path, net: FakeNet) -> None:
    schx_zip = make_zip({"2.0/pipeline-for-svrl.xsl": FAKE_PIPELINE})
    rules_zip = make_zip({"other.sch": FAKE_SCH})
    schx = make_source(artifacts.SCHXSLT_SOURCE, schx_zip)
    rules = make_source("rules", rules_zip, precompile=("R.sch",))
    net.payloads |= {schx.url: schx_zip, rules.url: rules_zip}

    with pytest.raises(ArtifactIntegrityError, match=re.escape("'R.sch' is not in the archive")):
        artifacts.fetch(root=tmp_path, sources={"rules": rules, schx.name: schx})


def test_precompile_without_saxonche_explains_the_extra(
    tmp_path: Path, net: FakeNet, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "saxonche", None)  # makes `import saxonche` raise ImportError
    schx_zip = make_zip({"2.0/pipeline-for-svrl.xsl": FAKE_PIPELINE})
    rules_zip = make_zip({"R.sch": FAKE_SCH})
    schx = make_source(artifacts.SCHXSLT_SOURCE, schx_zip)
    rules = make_source("rules", rules_zip, precompile=("R.sch",))
    net.payloads |= {schx.url: schx_zip, rules.url: rules_zip}

    with pytest.raises(ArtifactsNotAvailableError, match=re.escape("euinvoice[validate]")):
        artifacts.fetch(root=tmp_path, sources={schx.name: schx, "rules": rules})
    assert not (tmp_path / "rules" / "1.0").exists()


def test_unknown_source_name_raises_key_error(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        artifacts.fetch(["nope"], root=tmp_path, sources={})


def test_open_url_rejects_non_https() -> None:
    with pytest.raises(ValueError, match="https"):
        artifacts._open_url("file:///etc/passwd")


def test_open_url_sends_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, t.Any] = {}

    def fake_urlopen(request: t.Any, timeout: float) -> io.BytesIO:
        seen["ua"] = request.get_header("User-agent")
        seen["timeout"] = timeout
        return io.BytesIO(b"x")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert artifacts._open_url("https://example.com/a.zip").read() == b"x"
    assert seen["ua"].startswith("euinvoice/")
    assert seen["timeout"] > 0


def test_concurrent_fetcher_that_finished_first_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = make_source("demo", ARCHIVE)
    target = tmp_path / "demo" / "1.0"

    def racing_open(url: str) -> t.BinaryIO:
        target.mkdir(parents=True)  # another process completes the entry while we download
        (target / "theirs").write_text("x")
        (target / artifacts.MARKER).write_text(src.sha256)
        return io.BytesIO(ARCHIVE)

    monkeypatch.setattr(artifacts, "_open_url", racing_open)
    assert artifacts.fetch(root=tmp_path, sources={"demo": src}) == {"demo": target}
    assert sorted(p.name for p in target.iterdir()) == [artifacts.MARKER, "theirs"]
    assert [p.name for p in (tmp_path / "demo").iterdir()] == ["1.0"]


@pytest.mark.parametrize("other_completed", [True, False])
def test_rename_failure_is_tolerated_only_if_another_fetcher_completed(
    tmp_path: Path, net: FakeNet, monkeypatch: pytest.MonkeyPatch, other_completed: bool
) -> None:
    src = make_source("demo", ARCHIVE)
    net.payloads[src.url] = ARCHIVE
    target = tmp_path / "demo" / "1.0"
    real_replace = os.replace

    def flaky_replace(a: t.Any, b: t.Any) -> None:
        if Path(b) == target:
            if other_completed:
                target.mkdir(parents=True)
                (target / artifacts.MARKER).write_text(src.sha256)
            raise OSError("Directory not empty")
        real_replace(a, b)

    monkeypatch.setattr(os, "replace", flaky_replace)
    if other_completed:
        assert artifacts.fetch(root=tmp_path, sources={"demo": src}) == {"demo": target}
    else:
        with pytest.raises(OSError, match="not empty"):
            artifacts.fetch(root=tmp_path, sources={"demo": src})


# --- the packaged manifest ------------------------------------------------------------------------


def test_packaged_manifest_is_well_formed() -> None:
    sources = artifacts.load_manifest()
    for src in sources.values():
        assert src.url.startswith("https://"), src.name
        assert re.fullmatch(r"[0-9a-f]{64}", src.sha256), src.name
        assert src.members, src.name
        assert src.license, src.name
        assert src.note, src.name
        assert "/" not in src.version, src.name
        assert all(p.endswith(".sch") for p in src.precompile), src.name
    assert artifacts.SCHXSLT_SOURCE in sources


def test_packaged_manifest_pins_every_plan_source() -> None:
    # IMPLEMENTATION_PLAN.md §3. Factur-X/ZUGFeRD spec package: no official direct URL (needs-human).
    assert set(artifacts.load_manifest()) >= {
        "cen-ubl",
        "cen-cii",
        "peppol-bis",
        "xrechnung-schematron",
        "xrechnung-testsuite",
        "xrechnung-validator-configuration",
        "zugferd-corpus",
        "ubl-2_1",
        "schxslt",
    }


def test_load_manifest_applies_defaults() -> None:
    text = """
schema_version = 1
[sources.x]
version = "1"
url = "https://example.com/x.zip"
sha256 = "ABC"
license = "MIT"
members = ["*"]
"""
    assert artifacts.load_manifest(text)["x"] == Source(
        name="x", version="1", url="https://example.com/x.zip", sha256="abc", license="MIT", members=("*",)
    )
