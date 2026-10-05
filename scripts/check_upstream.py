"""Report pins in ``manifest.toml`` that are behind their upstream (plan §8, 5.3).

Run nightly by ``.github/workflows/nightly.yaml`` (job ``upstream``), which opens a tracker issue when
this exits non-zero. Usage::

    GH_TOKEN=$(gh auth token) uv run python scripts/check_upstream.py

Output: one line per finding. ``DRIFT`` names a newer upstream release, tag, commit or published file;
``PRERELEASE`` a release marked prerelease that was published after the pinned one; ``ERROR`` a source
that could not be checked.

Exit codes: 0 every pin is current, 1 at least one ``DRIFT`` / ``PRERELEASE``, 2 at least one ``ERROR``
(an upstream could not be queried, the pinned release is missing upstream, or a manifest source has no
check). Errors take precedence, and nothing ever passes silently.

Only stdlib ``urllib`` + ``json``. ``GH_TOKEN`` (if set) is sent as a bearer token to api.github.com
only; redirects are not followed, so it can never leave that host.
"""

import email.message
import hashlib
import json
import os
import re
import sys
import typing as t
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime

from euinvoice.validate.artifacts import Source, load_manifest

GITHUB_API = "https://api.github.com"
CODEBERG_API = "https://codeberg.org/api/v1"
PEPPOL_DOCS = "https://docs.peppol.eu/poacc/billing/3.0"
_TIMEOUT_S = 30
# ponytail: first page of releases / tags only (newest first; GitHub max 100, Gitea default max 50).
# A pinned release that falls off it is reported as ERROR ("not found"); paginate via Link if that happens.
_FIRST_PAGE = {GITHUB_API: "per_page=100", CODEBERG_API: "limit=50"}

Strategy = t.Literal["releases", "newer-tag", "head", "published-sha256", "release-notes", "static"]
Kind = t.Literal["DRIFT", "PRERELEASE"]
Get = t.Callable[[str], bytes]


@dataclass(frozen=True, slots=True)
class Check:
    """One way of detecting that a manifest source is behind upstream.

    Attributes:
        strategy: ``releases``: find the pinned release (tag ``tag_prefix + version``, drafts excluded)
            in the release list and report every release published after it; prereleases as
            ``PRERELEASE``. ``newer-tag``: report a tag that parses as a version greater than the pin.
            ``head``: the default-branch HEAD commit must start with the pinned (abbreviated) commit.
            ``published-sha256``: the file at ``url`` must have sha256 ``sha256``. ``release-notes``:
            the first ``<h2 id="_version_…">`` at ``url`` must be the pinned version. ``static``: frozen
            upstream, not checked.
        api: API base URL (GitHub, or Codeberg's Gitea API, which has the same release fields).
        repo: ``owner/name`` on that host.
        tag_prefix: Prefix of the release tag before the pinned version.
        url: Document URL for ``published-sha256`` and ``release-notes``.
        sha256: Expected sha256 for ``published-sha256``.
    """

    strategy: Strategy
    api: str = GITHUB_API
    repo: str = ""
    tag_prefix: str = ""
    url: str = ""
    sha256: str = ""


def _releases(repo: str, tag_prefix: str, api: str = GITHUB_API) -> tuple[Check, ...]:
    return (Check("releases", api=api, repo=repo, tag_prefix=tag_prefix),)


# Every manifest source needs an entry; a missing one is an ERROR, so a new pin cannot go unchecked.
# GitHub's /releases/latest is not used: it is picked by date or a manual flag and skips prereleases
# (CEN 1.2.2 only ever existed as a prerelease; 1.3.15 was cut from a branch).
CHECKS: dict[str, tuple[Check, ...]] = {
    "cen-ubl": _releases("ConnectingEurope/eInvoicing-EN16931", "validation-"),
    "cen-cii": _releases("ConnectingEurope/eInvoicing-EN16931", "validation-"),
    "xrechnung-schematron": _releases("itplr-kosit/xrechnung-schematron", "v"),
    "xrechnung-testsuite": _releases("itplr-kosit/xrechnung-testsuite", "v"),
    "xrechnung-validator-configuration": _releases("itplr-kosit/validator-configuration-xrechnung", "v"),
    # Peppol releases are neither tagged nor merged to master reliably: 3.0.21 is an untagged commit on
    # branch 2026-Q2-QA2 (manifest note; newest tag is v3.0.20), 3.0.22 is prepared the same way, and
    # hotfixes keep the version number. So the authoritative signal is the rule file published on
    # docs.peppol.eu: its sha256 must equal the pinned one. The newest release-notes heading and a tag
    # above the pinned version number are secondary signals ("latest tag != pin" would always fire).
    "peppol-bis": (
        Check(
            "published-sha256",
            url=f"{PEPPOL_DOCS}/files/PEPPOL-EN16931-UBL.sch",
            # sha256 of rules/sch/PEPPOL-EN16931-UBL.sch at the pinned commit 806866bd, which equals
            # the file published at the URL above (verified 2026-10-06). Bump together with manifest.toml.
            sha256="62e5b67892f12755352d78b06f63229a02cc2eccc748677c56efbc8dbcb336e3",
        ),
        Check("release-notes", url=f"{PEPPOL_DOCS}/release-notes/"),
        Check("newer-tag", repo="OpenPEPPOL/peppol-bis-invoice-3"),
    ),
    # Pinned to a master commit: any newer commit on the default branch is drift by definition.
    "zugferd-corpus": (Check("head", repo="ZUGFeRD/corpus"),),
    # Moved to Codeberg and archived there in favour of SchXslt2. Archived means no new 1.x releases are
    # expected, but the check is one cheap request and would catch an un-archive.
    "schxslt": _releases("SchXslt/schxslt", "v", api=CODEBERG_API),
    # OASIS UBL 2.1 OS is a frozen standard; there is nothing newer to pin under that name.
    "ubl-2_1": (Check("static"),),
}

_VERSION = re.compile(r"v?(\d+(?:\.\d+)*)")
_RELEASE_NOTES_H2 = re.compile(r'<h2 id="(_version_[^"]*)"')


class UpstreamError(Exception):
    """An upstream could not be queried or answered unexpectedly."""


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect (urllib then raises HTTPError), so the token stays on the API host."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: t.IO[bytes],
        code: int,
        msg: str,
        headers: email.message.Message,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirects())


def get(url: str) -> bytes:
    """GET ``url`` (https only, no redirects) and return the body.

    Args:
        url: https URL of an API endpoint or a published document.

    Returns:
        The response body.

    Raises:
        UpstreamError: Non-https URL, network or HTTP error (including any redirect).
    """
    if not url.startswith("https://"):
        raise UpstreamError(f"refusing non-https URL {url}")
    headers = {"User-Agent": "euinvoice-check-upstream"}
    token = os.environ.get("GH_TOKEN")
    if token and url.startswith(GITHUB_API + "/"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)  # ruff: ignore[suspicious-url-open-usage] - https enforced above
    try:
        with _OPENER.open(request, timeout=_TIMEOUT_S) as response:
            return t.cast(bytes, response.read())
    except urllib.error.HTTPError as exc:
        exc.close()  # an HTTPError holds the response body; release it (ResourceWarning otherwise)
        raise UpstreamError(f"GET {url} failed: {exc}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise UpstreamError(f"GET {url} failed: {exc}") from exc


def _json(fetch: Get, url: str) -> t.Any:
    try:
        return json.loads(fetch(url))
    except ValueError as exc:
        raise UpstreamError(f"GET {url}: not JSON: {exc}") from exc


def _list(data: t.Any, url: str) -> list[t.Any]:
    if not isinstance(data, list):
        raise UpstreamError(f"unexpected response from {url}: not a list")
    return data


def _field(data: t.Any, key: str, url: str) -> str:
    """Return ``data[key]`` as a string or raise UpstreamError for an unexpected payload."""
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, str):
        raise UpstreamError(f"unexpected response from {url}: no string {key!r}")
    return value


def _published(release: t.Any, url: str) -> datetime:
    text = _field(release, "published_at", url)
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise UpstreamError(f"unexpected response from {url}: published_at {text!r}") from exc


def _version_tuple(text: str) -> tuple[int, ...] | None:
    match = _VERSION.fullmatch(text)
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def _check_releases(source: Source, check: Check, fetch: Get) -> list[tuple[Kind, str]]:
    url = f"{check.api}/repos/{check.repo}/releases?{_FIRST_PAGE[check.api]}"
    releases = [r for r in _list(_json(fetch, url), url) if not (isinstance(r, dict) and r.get("draft") is True)]
    pinned_tag = check.tag_prefix + source.version
    pinned = next((r for r in releases if _field(r, "tag_name", url) == pinned_tag), None)
    if pinned is None:
        raise UpstreamError(f"pinned release {pinned_tag!r} not found in {url}")
    pinned_at = _published(pinned, url)
    newer = [r for r in releases if r is not pinned and _published(r, url) > pinned_at]
    return [
        (
            "PRERELEASE" if r.get("prerelease") is True else "DRIFT",
            f"{_field(r, 'tag_name', url)} (published {_field(r, 'published_at', url)})",
        )
        for r in sorted(newer, key=lambda r: _published(r, url))
    ]


def _check_newer_tag(source: Source, check: Check, fetch: Get) -> list[tuple[Kind, str]]:
    url = f"{check.api}/repos/{check.repo}/tags?{_FIRST_PAGE[check.api]}"
    pinned = _version_tuple(source.version)
    if pinned is None:
        raise UpstreamError(f"pinned version {source.version!r} is not numeric")
    names = [_field(tag, "name", url) for tag in _list(_json(fetch, url), url)]
    newest = max(((v, name) for name in names if (v := _version_tuple(name))), default=None)
    return [("DRIFT", f"tag {newest[1]}")] if newest and newest[0] > pinned else []


def _check_head(source: Source, check: Check, fetch: Get) -> list[tuple[Kind, str]]:
    base = f"{check.api}/repos/{check.repo}"
    branch = _field(_json(fetch, base), "default_branch", base)
    url = f"{base}/commits/{branch}"
    sha = _field(_json(fetch, url), "sha", url)
    return [] if sha.startswith(source.version) else [("DRIFT", f"{branch}@{sha[:12]}")]


def _check_published_sha256(source: Source, check: Check, fetch: Get) -> list[tuple[Kind, str]]:
    digest = hashlib.sha256(fetch(check.url)).hexdigest()
    return [] if digest == check.sha256 else [("DRIFT", f"{check.url} changed (sha256 {digest})")]


def _check_release_notes(source: Source, check: Check, fetch: Get) -> list[tuple[Kind, str]]:
    match = _RELEASE_NOTES_H2.search(fetch(check.url).decode("utf-8", "replace"))
    if match is None:
        raise UpstreamError(f'no <h2 id="_version_..."> heading in {check.url}')
    expected = "_version_" + source.version.replace(".", "_")
    return [] if match.group(1) == expected else [("DRIFT", f"release notes now start with {match.group(1)}")]


_STRATEGIES: dict[Strategy, t.Callable[[Source, Check, Get], list[tuple[Kind, str]]]] = {
    "releases": _check_releases,
    "newer-tag": _check_newer_tag,
    "head": _check_head,
    "published-sha256": _check_published_sha256,
    "release-notes": _check_release_notes,
}


def findings(source: Source, check: Check, fetch: Get = get) -> list[tuple[Kind, str]]:
    """Return what is newer upstream than ``source`` according to ``check`` (empty when current).

    Args:
        source: The pinned manifest source.
        check: How to query its upstream; must not be ``static``.
        fetch: Body GET function (:func:`get`; replaced in tests).

    Raises:
        UpstreamError: The upstream could not be queried, answered unexpectedly, or lacks the pin.
    """
    return _STRATEGIES[check.strategy](source, check, fetch)


def run(fetch: Get = get, sources: t.Mapping[str, Source] | None = None) -> int:
    """Check every manifest source, print one line per finding, and return the exit code.

    Args:
        fetch: Body GET function.
        sources: Manifest to check; defaults to the packaged ``manifest.toml``.

    Returns:
        0 when every pin is current, 1 on DRIFT / PRERELEASE, 2 when any source could not be checked.
    """
    sources = load_manifest() if sources is None else sources
    behind = errors = 0
    for name, source in sources.items():
        checks = CHECKS.get(name)
        if checks is None:
            print(f"ERROR      {name}: no upstream check defined; add it to CHECKS in {__file__}")
            errors += 1
            continue
        if all(check.strategy == "static" for check in checks):
            print(f"static     {name} {source.version}: frozen upstream, not checked")
            continue
        found: list[tuple[Kind, str]] = []
        failed = False
        for check in checks:
            try:
                found += findings(source, check, fetch)
            except UpstreamError as exc:
                print(f"ERROR      {name}: could not check upstream ({check.strategy}): {exc}")
                failed = True
        for kind, what in found:
            print(f"{kind:<10} {name}: pinned {source.version}, upstream has {what}")
        if not found and not failed:
            print(f"ok         {name} {source.version}")
        behind += bool(found)
        errors += failed
    print(f"\n{behind} source(s) behind upstream, {errors} source(s) could not be checked.")
    return 2 if errors else (1 if behind else 0)


if __name__ == "__main__":
    sys.exit(run())
