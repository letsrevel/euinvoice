"""scripts/check_upstream.py against a mocked upstream (no network)."""

import email.message
import hashlib
import io
import json
import typing as t
import urllib.error
import urllib.request

import pytest

import check_upstream as cu
from euinvoice.validation.artifacts import Source, load_manifest

GH = "https://api.github.com/repos"
CB = "https://codeberg.org/api/v1/repos"
PEPPOL_SCH = "https://docs.peppol.eu/poacc/billing/3.0/files/PEPPOL-EN16931-UBL.sch"
PEPPOL_NOTES = "https://docs.peppol.eu/poacc/billing/3.0/release-notes/"
PEPPOL_TAGS = f"{GH}/OpenPEPPOL/peppol-bis-invoice-3/tags?per_page=100"
CEN = f"{GH}/ConnectingEurope/eInvoicing-EN16931/releases?per_page=100"
XR_SCH = f"{GH}/itplr-kosit/xrechnung-schematron/releases?per_page=100"
SCHXSLT = f"{CB}/SchXslt/schxslt/releases?limit=50"

SCH_BYTES = b"<schema>pinned peppol rules</schema>"
FATTURAPA_AE = "https://www.agenziaentrate.gov.it/portale/documents/d/guest/schema_vfpr12_v1-2-3"
FATTURAPA_SDI = "https://www.fatturapa.gov.it/export/documenti/fatturapa/v1.4/Schema_VFPR12_v1.2.3.xsd"
XSD_BYTES = b"<xs:schema>pinned fatturapa</xs:schema>"
REAL_FATTURAPA_CHECKS = cu.CHECKS["fatturapa-xsd"]  # before the autouse fixture swaps the hashes


def rel(tag: str, published: str, *, prerelease: bool = False, draft: bool = False) -> dict[str, t.Any]:
    return {"tag_name": tag, "published_at": published, "prerelease": prerelease, "draft": draft}


# What every upstream answers when all pins in the packaged manifest are current.
CURRENT: dict[str, t.Any] = {
    CEN: [rel("validation-1.3.16", "2026-04-13T12:58:43Z"), rel("validation-1.3.15", "2025-10-20T14:36:27Z")],
    XR_SCH: [rel("v2.6.0", "2026-08-31T10:00:00Z")],
    f"{GH}/itplr-kosit/xrechnung-testsuite/releases?per_page=100": [rel("v2026-08-31", "2026-08-31T10:00:00Z")],
    f"{GH}/itplr-kosit/validator-configuration-xrechnung/releases?per_page=100": [
        rel("v2026-08-31", "2026-08-31T10:00:00Z")
    ],
    PEPPOL_SCH: SCH_BYTES,
    PEPPOL_NOTES: b'<h1>Notes</h1><h2 id="_version_3_0_21">Version 3.0.21</h2><h2 id="_version_3_0_20_hotfix">',
    # Real situation: 3.0.21 is pinned to an untagged commit, the newest tag is v3.0.20.
    PEPPOL_TAGS: [{"name": "v3.0.20"}, {"name": "v3.0.19"}, {"name": "3.0.18"}, {"name": "not-a-version"}],
    f"{GH}/ZUGFeRD/corpus": {"default_branch": "master"},
    f"{GH}/ZUGFeRD/corpus/commits/master": {"sha": "d891458e9822e34271a5438497bf924e89955979"},
    SCHXSLT: [rel("v1.10.1", "2024-10-18T16:51:57+02:00"), rel("v1.10", "2024-07-24T20:01:57+02:00")],
    FATTURAPA_AE: XSD_BYTES,
    FATTURAPA_SDI: XSD_BYTES,
}


@pytest.fixture(autouse=True)
def _pinned_peppol_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the published-sha256 checks at synthetic bytes instead of the real published files."""
    for name, payload in (("peppol-bis", SCH_BYTES), ("fatturapa-xsd", XSD_BYTES)):
        checks = tuple(
            cu.Check("published-sha256", url=c.url, sha256=hashlib.sha256(payload).hexdigest())
            if c.strategy == "published-sha256"
            else c
            for c in cu.CHECKS[name]
        )
        monkeypatch.setitem(cu.CHECKS, name, checks)


def fake(responses: dict[str, t.Any]) -> cu.Get:
    def get(url: str) -> bytes:
        if url not in responses:
            raise cu.UpstreamError(f"GET {url} failed: HTTP Error 404: Not Found")
        body = responses[url]
        return body if isinstance(body, bytes) else json.dumps(body).encode()

    return get


def run(responses: dict[str, t.Any], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = cu.run(fake(responses))
    return code, capsys.readouterr().out


def test_every_manifest_source_has_a_check() -> None:
    assert set(cu.CHECKS) == set(load_manifest())


def test_peppol_hash_is_pinned_next_to_the_manifest_version() -> None:
    # sha256 of rules/sch/PEPPOL-EN16931-UBL.sch at commit 806866bd (manifest peppol-bis 3.0.21).
    assert load_manifest()["peppol-bis"].version == "3.0.21"
    (check,) = (c for c in cu.CHECKS["peppol-bis"] if c.strategy == "published-sha256")
    assert check.url == PEPPOL_SCH


def test_fatturapa_checks_expect_the_pinned_sha256_at_the_pinned_url_and_its_mirror() -> None:
    pin = load_manifest()["fatturapa-xsd"]
    assert [(c.strategy, c.url, c.sha256) for c in REAL_FATTURAPA_CHECKS] == [
        ("published-sha256", pin.url, pin.sha256),
        ("published-sha256", FATTURAPA_SDI, pin.sha256),
    ]


def test_changed_fatturapa_mirror_is_drift(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run({**CURRENT, FATTURAPA_SDI: XSD_BYTES + b" "}, capsys)
    assert code == 1
    assert f"{FATTURAPA_SDI} changed" in out


def test_up_to_date_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(CURRENT, capsys)
    assert code == 0, out
    assert "DRIFT" not in out
    assert "ERROR" not in out
    assert "static     ubl-2_1 2.1" in out
    assert "ok         peppol-bis 3.0.21" in out
    assert "0 source(s) behind upstream, 0 source(s) could not be checked." in out


def test_newer_release_exits_1_and_names_the_version(capsys: pytest.CaptureFixture[str]) -> None:
    responses = {**CURRENT, XR_SCH: [rel("v2.7.0", "2026-12-01T00:00:00Z"), *CURRENT[XR_SCH]]}
    code, out = run(responses, capsys)
    assert code == 1
    assert "DRIFT      xrechnung-schematron: pinned 2.6.0, upstream has v2.7.0 (published 2026-12-01" in out
    assert "1 source(s) behind upstream" in out


def test_release_from_a_branch_is_found_regardless_of_list_order(capsys: pytest.CaptureFixture[str]) -> None:
    # e.g. a later release listed after the pinned one: order does not matter, published_at does.
    responses = {**CURRENT, CEN: [*CURRENT[CEN], rel("validation-1.3.17", "2026-11-01T00:00:00Z")]}
    code, out = run(responses, capsys)
    assert code == 1
    assert "DRIFT      cen-ubl: pinned 1.3.16, upstream has validation-1.3.17" in out
    assert "DRIFT      cen-cii: pinned 1.3.16, upstream has validation-1.3.17" in out


def test_newer_prerelease_is_reported_distinctly(capsys: pytest.CaptureFixture[str]) -> None:
    newer = rel("validation-1.4.0-rc1", "2026-11-01T00:00:00Z", prerelease=True)
    code, out = run({**CURRENT, CEN: [newer, *CURRENT[CEN]]}, capsys)
    assert code == 1
    assert "PRERELEASE cen-ubl: pinned 1.3.16, upstream has validation-1.4.0-rc1" in out
    assert "DRIFT" not in out


def test_drafts_are_ignored(capsys: pytest.CaptureFixture[str]) -> None:
    draft = rel("validation-1.4.0", "2026-11-01T00:00:00Z", draft=True)
    assert run({**CURRENT, CEN: [draft, *CURRENT[CEN]]}, capsys)[0] == 0


def test_codeberg_release_drift(capsys: pytest.CaptureFixture[str]) -> None:
    responses = {**CURRENT, SCHXSLT: [rel("v1.11", "2027-01-01T00:00:00+01:00"), *CURRENT[SCHXSLT]]}
    code, out = run(responses, capsys)
    assert code == 1
    assert "DRIFT      schxslt: pinned 1.10.1, upstream has v1.11" in out


def test_missing_pinned_release_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run({**CURRENT, XR_SCH: [rel("v2.5.0", "2026-01-01T00:00:00Z")]}, capsys)
    assert code == 2
    assert "ERROR      xrechnung-schematron: could not check upstream (releases): " in out
    assert "pinned release 'v2.6.0' not found" in out


@pytest.mark.parametrize(
    "payload",
    [{"not": "a list"}, [{"tag_name": "v2.6.0"}], [{"tag_name": "v2.6.0", "published_at": "yesterday"}]],
)
def test_unexpected_release_payload_is_an_error(payload: t.Any, capsys: pytest.CaptureFixture[str]) -> None:
    assert run({**CURRENT, XR_SCH: payload}, capsys)[0] == 2


def test_changed_peppol_rules_are_drift(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run({**CURRENT, PEPPOL_SCH: b"<schema>3.0.22</schema>"}, capsys)
    assert code == 1
    assert f"DRIFT      peppol-bis: pinned 3.0.21, upstream has {PEPPOL_SCH} changed (sha256 " in out


@pytest.mark.parametrize("missing", [PEPPOL_SCH, PEPPOL_NOTES])
def test_peppol_docs_unreachable_is_an_error(missing: str, capsys: pytest.CaptureFixture[str]) -> None:
    responses = dict(CURRENT)
    del responses[missing]
    code, out = run(responses, capsys)
    assert code == 2
    assert "ERROR      peppol-bis: could not check upstream" in out
    assert "404" in out


def test_new_peppol_release_notes_entry_is_drift(capsys: pytest.CaptureFixture[str]) -> None:
    notes = b'<h2 id="_version_3_0_22">Version 3.0.22</h2><h2 id="_version_3_0_21">'
    code, out = run({**CURRENT, PEPPOL_NOTES: notes}, capsys)
    assert code == 1
    assert "DRIFT      peppol-bis: pinned 3.0.21, upstream has release notes now start with _version_3_0_22" in out


def test_release_notes_without_version_headings_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert run({**CURRENT, PEPPOL_NOTES: b"<html>maintenance</html>"}, capsys)[0] == 2


def test_peppol_untagged_pin_is_not_drift_when_newest_tag_is_older() -> None:
    peppol = load_manifest()["peppol-bis"]
    newer_tag = cu.Check("newer-tag", repo="OpenPEPPOL/peppol-bis-invoice-3")
    assert cu.findings(peppol, newer_tag, fake(CURRENT)) == []
    assert cu.findings(peppol, newer_tag, fake({PEPPOL_TAGS: [{"name": "v3.0.21"}]})) == []


@pytest.mark.parametrize("tag", ["v3.0.22", "3.1", "v4.0.0"])
def test_peppol_tag_above_pinned_version_is_drift(tag: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run({**CURRENT, PEPPOL_TAGS: [{"name": "v3.0.20"}, {"name": tag}]}, capsys)
    assert code == 1
    assert f"DRIFT      peppol-bis: pinned 3.0.21, upstream has tag {tag}" in out


@pytest.mark.parametrize("payload", [{"not": "a list"}, [{"name": 3}]])
def test_unexpected_tags_payload_is_an_error(payload: t.Any, capsys: pytest.CaptureFixture[str]) -> None:
    assert run({**CURRENT, PEPPOL_TAGS: payload}, capsys)[0] == 2


def test_non_numeric_peppol_pin_is_an_error() -> None:
    source = Source("peppol-bis", "next", "https://example.com/x.zip", "0" * 64, "MIT", ("*",))
    with pytest.raises(cu.UpstreamError, match="not numeric"):
        cu.findings(source, cu.Check("newer-tag", repo="OpenPEPPOL/peppol-bis-invoice-3"), fake(CURRENT))


def test_new_corpus_commit_is_drift(capsys: pytest.CaptureFixture[str]) -> None:
    responses = {**CURRENT, f"{GH}/ZUGFeRD/corpus/commits/master": {"sha": "0123456789abcdef" * 2}}
    code, out = run(responses, capsys)
    assert code == 1
    assert "DRIFT      zugferd-corpus: pinned d891458e9822, upstream has master@0123456789ab" in out


def test_api_error_exits_2_with_distinct_message(capsys: pytest.CaptureFixture[str]) -> None:
    responses = dict(CURRENT)
    del responses[SCHXSLT]
    code, out = run(responses, capsys)
    assert code == 2
    assert "ERROR      schxslt: could not check upstream (releases): GET" in out
    assert "1 source(s) could not be checked" in out


def test_non_json_api_answer_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run({**CURRENT, SCHXSLT: b"<html>"}, capsys)
    assert code == 2
    assert "not JSON" in out


def test_api_error_wins_over_drift(capsys: pytest.CaptureFixture[str]) -> None:
    responses = {**CURRENT, XR_SCH: [rel("v9", "2027-01-01T00:00:00Z"), *CURRENT[XR_SCH]]}
    del responses[SCHXSLT]
    assert run(responses, capsys)[0] == 2


def test_source_without_check_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    sources = {"new-thing": Source("new-thing", "1", "https://example.com/x.zip", "0" * 64, "MIT", ("*",))}
    assert cu.run(fake(CURRENT), sources) == 2
    assert "ERROR      new-thing: no upstream check defined" in capsys.readouterr().out


def test_crash_exits_2_not_drift(capsys: pytest.CaptureFixture[str]) -> None:
    # Exit 1 means drift to the nightly workflow; a bug in the script must not look like drift.
    def boom(url: str) -> bytes:
        raise RuntimeError("bug")

    assert cu.main(boom) == 2
    captured = capsys.readouterr()
    assert "ERROR      check_upstream crashed: RuntimeError: bug" in captured.out
    assert "Traceback" in captured.err


def test_main_passes_through_the_run_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    assert cu.main(fake(CURRENT)) == 0
    assert "0 source(s) behind upstream, 0 source(s) could not be checked." in capsys.readouterr().out


def test_findings_for_static_is_empty() -> None:
    source = load_manifest()["ubl-2_1"]
    assert cu.findings(source, cu.Check("static"), fake({})) == []


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


def test_get_sends_token_to_github_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "secret")
    seen = _capture(monkeypatch, b'{"tag_name": "v1"}')
    assert cu.get(f"{GH}/a/b/releases") == b'{"tag_name": "v1"}'
    cu.get(f"{CB}/a/b/releases")
    cu.get(PEPPOL_SCH)
    assert seen[0].get_header("Authorization") == "Bearer secret"
    assert seen[1].get_header("Authorization") is None
    assert seen[2].get_header("Authorization") is None


def test_get_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    seen = _capture(monkeypatch)
    cu.get(f"{GH}/a/b")
    assert seen[0].get_header("Authorization") is None


def test_get_rejects_http(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture(monkeypatch)
    with pytest.raises(cu.UpstreamError, match="non-https"):
        cu.get("http://api.github.com/repos/a/b")
    assert seen == []


def test_get_wraps_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def open_(request: urllib.request.Request, timeout: float) -> _Response:
        raise urllib.error.HTTPError(request.full_url, 403, "rate limit exceeded", email.message.Message(), None)

    monkeypatch.setattr(cu._OPENER, "open", open_)
    with pytest.raises(cu.UpstreamError, match="403"):
        cu.get(f"{GH}/a/b")


def test_get_wraps_network_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def open_(request: urllib.request.Request, timeout: float) -> _Response:
        raise urllib.error.URLError("Name or service not known")

    monkeypatch.setattr(cu._OPENER, "open", open_)
    with pytest.raises(cu.UpstreamError, match="Name or service not known"):
        cu.get(PEPPOL_SCH)


def test_opener_refuses_redirects() -> None:
    request = urllib.request.Request(f"{GH}/a/b")  # ruff: ignore[suspicious-url-open-usage] - constant https URL, never opened
    headers = email.message.Message()
    headers["Location"] = "https://example.com/elsewhere"
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        cu._OPENER.error("https", request, io.BytesIO(), 301, "Moved", headers)
    excinfo.value.close()
    assert excinfo.value.code == 301
