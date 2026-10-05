"""Report pins in ``manifest.toml`` that are behind their latest upstream release (plan §8, 5.3).

Run nightly by ``.github/workflows/nightly.yaml`` (job ``upstream``), which opens a tracker issue when
this exits non-zero. Usage::

    GH_TOKEN=$(gh auth token) uv run python scripts/check_upstream.py

Exit codes: 0 every pin is current, 1 at least one pin drifted (each is printed with the newer upstream
version), 2 an upstream could not be queried or a manifest source has no check (never a silent pass).

Only stdlib ``urllib`` + ``json``. ``GH_TOKEN`` (if set) is sent as a bearer token to api.github.com
only; redirects are not followed, so it can never leave that host.
"""

import json
import os
import re
import sys
import typing as t
import urllib.error
import urllib.request
from dataclasses import dataclass

from euinvoice.validate.artifacts import Source, load_manifest

GITHUB_API = "https://api.github.com"
CODEBERG_API = "https://codeberg.org/api/v1"
_TIMEOUT_S = 30

Strategy = t.Literal["release", "newer-tag", "head", "static"]


@dataclass(frozen=True, slots=True)
class Check:
    """How to find the latest upstream version of one manifest source.

    Attributes:
        strategy: ``release``: the latest non-draft, non-prerelease release's tag must equal
            ``tag_prefix + version``. ``newer-tag``: drift only if some tag parses as a version
            greater than the pinned one. ``head``: the default branch HEAD commit must start with
            the pinned (abbreviated) commit. ``static``: frozen upstream, not checked.
        api: API base URL (GitHub, or Codeberg's Gitea-compatible API).
        repo: ``owner/name`` on that host.
        tag_prefix: Prefix of the release tag before the pinned version.
    """

    strategy: Strategy
    api: str = GITHUB_API
    repo: str = ""
    tag_prefix: str = ""


# One entry per manifest source; a missing entry is an error (exit 2), so a new pin cannot go unchecked.
CHECKS: dict[str, Check] = {
    # GitHub's /releases/latest is the newest non-draft, non-prerelease release.
    "cen-ubl": Check("release", repo="ConnectingEurope/eInvoicing-EN16931", tag_prefix="validation-"),
    "cen-cii": Check("release", repo="ConnectingEurope/eInvoicing-EN16931", tag_prefix="validation-"),
    "xrechnung-schematron": Check("release", repo="itplr-kosit/xrechnung-schematron", tag_prefix="v"),
    "xrechnung-testsuite": Check("release", repo="itplr-kosit/xrechnung-testsuite", tag_prefix="v"),
    "xrechnung-validator-configuration": Check(
        "release", repo="itplr-kosit/validator-configuration-xrechnung", tag_prefix="v"
    ),
    # Peppol 3.0.21 is pinned to an untagged commit: upstream never tagged it and the newest tag is
    # v3.0.20 (see the manifest note). "Latest tag != pin" would therefore always report drift, so only
    # a tag whose version is strictly greater than the pinned version number (e.g. v3.0.22) counts.
    "peppol-bis": Check("newer-tag", repo="OpenPEPPOL/peppol-bis-invoice-3"),
    # Pinned to a master commit: any newer commit on the default branch is drift by definition.
    "zugferd-corpus": Check("head", repo="ZUGFeRD/corpus"),
    # Moved to Codeberg and archived there in favour of SchXslt2. Archived means no new 1.x releases are
    # expected, but the check is one cheap request and would catch an un-archive.
    "schxslt": Check("release", api=CODEBERG_API, repo="SchXslt/schxslt", tag_prefix="v"),
    # OASIS UBL 2.1 OS is a frozen standard; there is nothing newer to pin under that name.
    "ubl-2_1": Check("static"),
}

_VERSION = re.compile(r"v?(\d+(?:\.\d+)*)")


class UpstreamError(Exception):
    """An upstream API could not be queried or answered unexpectedly."""


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect (urllib then raises HTTPError), so the token stays on the API host."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: t.IO[bytes],
        code: int,
        msg: str,
        headers: t.Any,  # email.message.Message in typeshed
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirects())


def get_json(url: str) -> t.Any:
    """GET ``url`` and decode its JSON body.

    Args:
        url: https URL of an API endpoint.

    Returns:
        The decoded JSON value.

    Raises:
        UpstreamError: Non-https URL, network or HTTP error, or a non-JSON body.
    """
    if not url.startswith("https://"):
        raise UpstreamError(f"refusing non-https URL {url}")
    headers = {"Accept": "application/json", "User-Agent": "euinvoice-check-upstream"}
    token = os.environ.get("GH_TOKEN")
    if token and url.startswith(GITHUB_API + "/"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)  # ruff: ignore[suspicious-url-open-usage] - https enforced above
    try:
        with _OPENER.open(request, timeout=_TIMEOUT_S) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpstreamError(f"GET {url} failed: {exc}") from exc


def _field(data: t.Any, key: str, url: str) -> str:
    """Return ``data[key]`` as a string or raise UpstreamError for an unexpected payload."""
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, str):
        raise UpstreamError(f"unexpected response from {url}: no string {key!r}")
    return value


def _version_tuple(text: str) -> tuple[int, ...] | None:
    match = _VERSION.fullmatch(text)
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def latest(source: Source, check: Check, get: t.Callable[[str], t.Any]) -> str | None:
    """Return the newer upstream version of ``source``, or ``None`` if the pin is current.

    Args:
        source: The pinned manifest source.
        check: How to query its upstream.
        get: JSON GET function (``get_json``; replaced in tests).

    Raises:
        UpstreamError: The upstream could not be queried or answered unexpectedly.
    """
    base = f"{check.api}/repos/{check.repo}"
    if check.strategy == "release":
        url = f"{base}/releases/latest"
        tag = _field(get(url), "tag_name", url)
        return None if tag == check.tag_prefix + source.version else tag
    if check.strategy == "newer-tag":
        # ponytail: first page of 100 tags only (Peppol has ~20); paginate via the Link header if it grows.
        url = f"{base}/tags?per_page=100"
        tags = get(url)
        if not isinstance(tags, list):
            raise UpstreamError(f"unexpected response from {url}: not a list")
        pinned = _version_tuple(source.version)
        if pinned is None:
            raise UpstreamError(f"pinned version {source.version!r} is not numeric")
        newer = [(v, name) for name in (_field(tag, "name", url) for tag in tags) if (v := _version_tuple(name))]
        newest = max(newer, default=None)
        return newest[1] if newest and newest[0] > pinned else None
    if check.strategy == "head":
        branch = _field(get(base), "default_branch", base)
        url = f"{base}/commits/{branch}"
        sha = _field(get(url), "sha", url)
        return None if sha.startswith(source.version) else f"{branch}@{sha[:12]}"
    return None  # static


def run(get: t.Callable[[str], t.Any] = get_json, sources: t.Mapping[str, Source] | None = None) -> int:
    """Check every manifest source, print one line each, and return the exit code.

    Args:
        get: JSON GET function.
        sources: Manifest to check; defaults to the packaged ``manifest.toml``.

    Returns:
        0 when every pin is current, 1 on drift, 2 when any upstream could not be checked.
    """
    sources = load_manifest() if sources is None else sources
    drift = errors = 0
    for name, source in sources.items():
        check = CHECKS.get(name)
        if check is None:
            print(f"ERROR {name}: no upstream check defined; add it to CHECKS in {__file__}")
            errors += 1
            continue
        if check.strategy == "static":
            print(f"static  {name} {source.version}: frozen upstream, not checked")
            continue
        try:
            newer = latest(source, check, get)
        except UpstreamError as exc:
            print(f"ERROR {name}: could not check upstream: {exc}")
            errors += 1
            continue
        if newer is None:
            print(f"ok      {name} {source.version}")
        else:
            print(f"DRIFT   {name}: pinned {source.version}, upstream has {newer} ({check.api}/repos/{check.repo})")
            drift += 1
    print(f"\n{drift} pin(s) behind upstream, {errors} source(s) could not be checked.")
    return 2 if errors else (1 if drift else 0)


if __name__ == "__main__":
    sys.exit(run())
