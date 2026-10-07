"""Unit tests for single-file artifact sources (``file`` instead of ``members``). The network is mocked."""

import hashlib
import io
import json
import typing as t
from pathlib import Path

import pytest

from euinvoice.errors import ArtifactIntegrityError, ArtifactsNotAvailableError
from euinvoice.validation import artifacts
from euinvoice.validation.artifacts import Source

NAME: artifacts.SourceName = "fatturapa-xsd"
PAYLOAD = b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>'


def file_source(payload: bytes = PAYLOAD, **kw: t.Any) -> Source:
    return Source(
        name=NAME,
        version="1.2.3",
        url="https://example.com/download/schema_v1-2-3",
        sha256=hashlib.sha256(payload).hexdigest(),
        license="all rights reserved",
        file=kw.pop("file", "Schema.xsd"),
        **kw,
    )


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """URL → payload map behind a mocked ``_open_url``."""
    payloads: dict[str, bytes] = {}

    def fake(url: str) -> t.BinaryIO:
        return io.BytesIO(payloads[url])

    monkeypatch.setattr(artifacts, "_open_url", fake)
    return payloads


def test_single_file_is_stored_under_its_name_in_the_versioned_cache(tmp_path: Path, served: dict[str, bytes]) -> None:
    src = file_source()
    served[src.url] = PAYLOAD

    result = artifacts.fetch(root=tmp_path, sources={NAME: src})

    target = tmp_path / NAME / "1.2.3"
    assert result == {NAME: target}
    assert sorted(p.name for p in target.iterdir()) == [artifacts.MARKER, "Schema.xsd"]
    assert (target / "Schema.xsd").read_bytes() == PAYLOAD
    assert artifacts.source_dir(NAME, root=tmp_path, sources={NAME: src}) == target
    assert [p.name for p in (tmp_path / NAME).iterdir()] == ["1.2.3"]  # no temp dirs left behind


def test_single_file_with_wrong_sha256_is_rejected(tmp_path: Path, served: dict[str, bytes]) -> None:
    src = file_source()
    served[src.url] = PAYLOAD + b" "

    with pytest.raises(ArtifactIntegrityError, match=f"expected {src.sha256}"):
        artifacts.fetch(root=tmp_path, sources={NAME: src})

    with pytest.raises(ArtifactsNotAvailableError, match="artifacts fetch"):
        artifacts.source_dir(NAME, root=tmp_path, sources={NAME: src})


def test_renaming_the_file_triggers_a_refetch(tmp_path: Path, served: dict[str, bytes]) -> None:
    src = file_source()
    served[src.url] = PAYLOAD
    artifacts.fetch(root=tmp_path, sources={NAME: src})
    renamed = file_source(file="Other.xsd")

    with pytest.raises(ArtifactsNotAvailableError):
        artifacts.source_dir(NAME, root=tmp_path, sources={NAME: renamed})
    artifacts.fetch(root=tmp_path, sources={NAME: renamed})

    assert sorted(p.name for p in (tmp_path / NAME / "1.2.3").iterdir()) == [artifacts.MARKER, "Other.xsd"]


def test_zip_source_fingerprints_are_unchanged_by_single_file_support() -> None:
    # Existing caches must stay warm: a zip source's recipe has no "file" key.
    src = Source(name="z", version="1", url="https://example.com/z.zip", sha256="0" * 64, license="", members=("*",))
    recipe = {"sha256": "0" * 64, "members": ["*"], "strip_components": 0, "precompile": []}
    expected = hashlib.sha256(json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert artifacts._fingerprint(src, {}) == expected


FILE_MANIFEST = """
schema_version = 1
[sources.f]
version = "1"
url = "https://example.com/download"
sha256 = "{sha}"
license = "x"
{extra}
"""


def test_load_manifest_reads_a_single_file_source() -> None:
    text = FILE_MANIFEST.format(sha="ab" * 32, extra='file = "Schema.xsd"')
    assert artifacts.load_manifest(text)["f"] == Source(
        name="f", version="1", url="https://example.com/download", sha256="ab" * 32, license="x", file="Schema.xsd"
    )


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("", "exactly one of members or file"),
        ('file = "a.xsd"\nmembers = ["*"]', "exactly one of members or file"),
        ('file = "../a.xsd"', "file"),
        ('file = "sub/a.xsd"', "file"),
        ('file = ".."', "file"),
        ('file = "a.xsd"\nstrip_components = 1', "strip_components"),
        ('file = "a.xsd"\nprecompile = ["a.sch"]', "precompile"),
    ],
)
def test_load_manifest_rejects_bad_single_file_sources(extra: str, message: str) -> None:
    with pytest.raises(ArtifactIntegrityError, match=message):
        artifacts.load_manifest(FILE_MANIFEST.format(sha="ab" * 32, extra=extra))
