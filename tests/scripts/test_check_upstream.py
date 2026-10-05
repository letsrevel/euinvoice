"""scripts/check_upstream.py against a mocked upstream API (no network)."""

import io
import json
import typing as t
import urllib.error
import urllib.request

import check_upstream as cu
import pytest

from euinvoice.validate.artifacts import Source, load_manifest

GH = "https://api.github.com/repos"
CB = "https://codeberg.org/api/v1/repos"

# What every upstream answers when all pins in the packaged manifest are current.
CURRENT: dict[str, t.Any] = {
    f"{GH}/ConnectingEurope/eInvoicing-EN16931/releases/latest": {"tag_name": "validation-1.3.16"},
    f"{GH}/itplr-kosit/xrechnung-schematron/releases/latest": {"tag_name": "v2.6.0"},
    f"{GH}/itplr-kosit/xrechnung-testsuite/releases/latest": {"tag_name": "v2026-08-31"},
    f"{GH}/itplr-kosit/validator-configuration-xrechnung/releases/latest": {"tag_name": "v2026-08-31"},
    # Real situation: 3.0.21 is pinned to an untagged commit, the newest tag is v3.0.20.
    f"{GH}/OpenPEPPOL/peppol-bis-invoice-3/tags?per_page=100": [
        {"name": "v3.0.20"},
        {"name": "v3.0.19"},
        {"name": "3.0.18"},
        {"name": "not-a-version"},
    ],
    f"{GH}/ZUGFeRD/corpus": {"default_branch": "master"},
    f"{GH}/ZUGFeRD/corpus/commits/master": {"sha": "d891458e9822e34271a5438497bf924e89955979"},
    f"{CB}/SchXslt/schxslt/releases/latest": {"tag_name": "v1.10.1"},
}


def fake(responses: dict[str, t.Any]) -> t.Callable[[str], t.Any]:
    def get(url: str) -> t.Any:
        if url not in responses:
            raise cu.UpstreamError(f"GET {url} failed: HTTP Error 404: Not Found")
        return responses[url]

    return get


def test_every_manifest_source_has_a_check() -> None:
    assert set(cu.CHECKS) == set(load_manifest())


def test_up_to_date_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    assert cu.run(fake(CURRENT)) == 0
    out = capsys.readouterr().out
    assert "DRIFT" not in out
    assert "ERROR" not in out
    assert "static  ubl-2_1 2.1" in out
    assert "0 pin(s) behind upstream, 0 source(s) could not be checked." in out


def test_newer_release_exits_1_and_names_the_version(capsys: pytest.CaptureFixture[str]) -> None:
    responses = {**CURRENT, f"{GH}/itplr-kosit/xrechnung-schematron/releases/latest": {"tag_name": "v2.7.0"}}
    assert cu.run(fake(responses)) == 1
    out = capsys.readouterr().out
    assert "DRIFT   xrechnung-schematron: pinned 2.6.0, upstream has v2.7.0" in out
    assert "1 pin(s) behind upstream" in out


def test_cen_release_drifts_both_syntaxes(capsys: pytest.CaptureFixture[str]) -> None:
    responses = {
        **CURRENT,
        f"{GH}/ConnectingEurope/eInvoicing-EN16931/releases/latest": {"tag_name": "validation-1.3.17"},
    }
    assert cu.run(fake(responses)) == 1
    out = capsys.readouterr().out
    assert "DRIFT   cen-ubl: pinned 1.3.16, upstream has validation-1.3.17" in out
    assert "DRIFT   cen-cii: pinned 1.3.16, upstream has validation-1.3.17" in out


def test_peppol_untagged_pin_is_not_drift_when_newest_tag_is_older() -> None:
    peppol = load_manifest()["peppol-bis"]
    assert cu.latest(peppol, cu.CHECKS["peppol-bis"], fake(CURRENT)) is None


@pytest.mark.parametrize("tag", ["v3.0.22", "3.1", "v4.0.0"])
def test_peppol_tag_above_pinned_version_is_drift(tag: str, capsys: pytest.CaptureFixture[str]) -> None:
    url = f"{GH}/OpenPEPPOL/peppol-bis-invoice-3/tags?per_page=100"
    responses = {**CURRENT, url: [{"name": "v3.0.20"}, {"name": tag}]}
    assert cu.run(fake(responses)) == 1
    assert f"DRIFT   peppol-bis: pinned 3.0.21, upstream has {tag}" in capsys.readouterr().out


def test_peppol_tag_equal_to_pin_is_not_drift() -> None:
    url = f"{GH}/OpenPEPPOL/peppol-bis-invoice-3/tags?per_page=100"
    responses = {**CURRENT, url: [{"name": "v3.0.21"}]}
    assert cu.run(fake(responses)) == 0


def test_new_corpus_commit_is_drift(capsys: pytest.CaptureFixture[str]) -> None:
    responses = {**CURRENT, f"{GH}/ZUGFeRD/corpus/commits/master": {"sha": "0123456789abcdef" * 2}}
    assert cu.run(fake(responses)) == 1
    assert "DRIFT   zugferd-corpus: pinned d891458e9822, upstream has master@0123456789ab" in capsys.readouterr().out


def test_api_error_exits_2_with_distinct_message(capsys: pytest.CaptureFixture[str]) -> None:
    responses = dict(CURRENT)
    del responses[f"{CB}/SchXslt/schxslt/releases/latest"]
    assert cu.run(fake(responses)) == 2
    out = capsys.readouterr().out
    assert "ERROR schxslt: could not check upstream: GET" in out
    assert "404" in out
    assert "1 source(s) could not be checked" in out


def test_api_error_wins_over_drift() -> None:
    responses = {**CURRENT, f"{GH}/itplr-kosit/xrechnung-testsuite/releases/latest": {"message": "rate limited"}}
    responses[f"{GH}/itplr-kosit/xrechnung-schematron/releases/latest"] = {"tag_name": "v9"}
    assert cu.run(fake(responses)) == 2


@pytest.mark.parametrize(
    "payload",
    [{"not": "a list"}, [{"name": 3}]],
)
def test_unexpected_tags_payload_is_an_error(payload: t.Any) -> None:
    responses = {**CURRENT, f"{GH}/OpenPEPPOL/peppol-bis-invoice-3/tags?per_page=100": payload}
    assert cu.run(fake(responses)) == 2


def test_source_without_check_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    sources = {"new-thing": Source("new-thing", "1", "https://example.com/x.zip", "0" * 64, "MIT", ("*",))}
    assert cu.run(fake(CURRENT), sources) == 2
    assert "ERROR new-thing: no upstream check defined" in capsys.readouterr().out


def test_non_numeric_peppol_pin_is_an_error() -> None:
    source = Source("peppol-bis", "next", "https://example.com/x.zip", "0" * 64, "MIT", ("*",))
    with pytest.raises(cu.UpstreamError, match="not numeric"):
        cu.latest(source, cu.CHECKS["peppol-bis"], fake(CURRENT))


class _Response(io.BytesIO):
    def __enter__(self) -> "_Response":
        return self


def _capture(monkeypatch: pytest.MonkeyPatch, body: bytes = b"{}") -> list[urllib.request.Request]:
    seen: list[urllib.request.Request] = []

    def open_(request: urllib.request.Request, timeout: float) -> _Response:
        seen.append(request)
        return _Response(body)

    monkeypatch.setattr(cu._OPENER, "open", open_)
    return seen


def test_get_json_sends_token_to_github_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "secret")
    seen = _capture(monkeypatch, json.dumps({"tag_name": "v1"}).encode())
    assert cu.get_json(f"{GH}/a/b/releases/latest") == {"tag_name": "v1"}
    cu.get_json(f"{CB}/a/b/releases/latest")
    assert seen[0].get_header("Authorization") == "Bearer secret"
    assert seen[1].get_header("Authorization") is None


def test_get_json_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    seen = _capture(monkeypatch)
    cu.get_json(f"{GH}/a/b")
    assert seen[0].get_header("Authorization") is None


def test_get_json_rejects_http(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch)
    with pytest.raises(cu.UpstreamError, match="non-https"):
        cu.get_json("http://api.github.com/repos/a/b")
    assert seen == []


def test_get_json_wraps_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture(monkeypatch, b"<html>")
    with pytest.raises(cu.UpstreamError, match="failed"):
        cu.get_json(f"{GH}/a/b")


def test_get_json_wraps_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def open_(request: urllib.request.Request, timeout: float) -> _Response:
        raise urllib.error.HTTPError(request.full_url, 403, "rate limit exceeded", t.cast(t.Any, {}), None)

    monkeypatch.setattr(cu._OPENER, "open", open_)
    with pytest.raises(cu.UpstreamError, match="403"):
        cu.get_json(f"{GH}/a/b")


def test_redirects_are_refused() -> None:
    request = urllib.request.Request(f"{GH}/a/b")  # ruff: ignore[suspicious-url-open-usage] - constant https URL, never opened
    handler = cu._NoRedirects()
    assert handler.redirect_request(request, io.BytesIO(), 301, "Moved", {}, "https://example.com/") is None
