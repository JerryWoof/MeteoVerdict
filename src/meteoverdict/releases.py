"""Store data files as GitHub Release assets (one release per tag).

The client is frugal with the REST API, whose budget for a workflow's ``GITHUB_TOKEN``
is 1,000 requests an hour per repository (shared by all workflows of the repository):

* the asset list of a release is read once (paginated, 100 a page) and kept up to date
  by ``put``, so ``names``/``assets``/``download`` after the first call cost nothing;
* downloads go to the asset's ``browser_download_url`` (plain HTTPS from GitHub's
  storage, not counted against the API budget; it works without a token for a public
  repository), with the API's asset URL as the fallback (private repositories);
* a response saying the budget is used up (403 or 429 with ``x-ratelimit-remaining:
  0``, ``retry-after`` or "rate limit" in the message) is retried after the wait
  GitHub asks for (``retry-after``, or until ``x-ratelimit-reset``), with backoff for
  the secondary limits.

GitHub allows at most ``MAX_ASSETS`` assets per release. When a release is full, new
assets go to overflow releases ``<tag>.2``, ``<tag>.3``, …, which this client treats
as part of ``<tag>``: ``assets(tag)`` lists them together (each asset says in ``_tag``
which release holds it), ``put`` replaces an asset where it is, and ``tags`` leaves the
overflow releases out.
"""

from __future__ import annotations

import re
import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
#: GitHub's limit of assets per release
MAX_ASSETS = 1000
#: retries of one request held up by a rate limit, and the longest wait accepted
RATE_LIMIT_RETRIES = 6
MAX_WAIT = 3700.0  # the primary limit resets within an hour
#: first wait for a secondary rate limit without a retry-after (doubles each time)
SECONDARY_WAIT = 60.0
#: retries of a download that failed with a server error
DOWNLOAD_RETRIES = 3
_OVERFLOW_RE = re.compile(r"\.(\d+)$")


class RateLimitError(httpx.HTTPStatusError):
    """The API budget is used up and the wait for it is longer than allowed."""


def overflow_tag(tag: str, part: int) -> str:
    """Tag of the ``part``-th release of ``tag`` (1 is ``tag`` itself)."""
    return tag if part == 1 else f"{tag}.{part}"


def is_overflow(tag: str) -> bool:
    match = _OVERFLOW_RE.search(tag)
    return match is not None and int(match.group(1)) >= 2


def rate_limit_wait(response: httpx.Response, now: float, attempt: int) -> float | None:
    """Seconds to wait before retrying ``response`` when it is a rate-limit answer
    (None when it is not one)."""
    if response.status_code not in (403, 429):
        return None
    headers = response.headers
    remaining = headers.get("x-ratelimit-remaining")
    text = response.text.lower() if response.status_code == 403 else ""
    limited = remaining == "0" or "rate limit" in text or "retry-after" in headers
    if response.status_code == 403 and not limited:
        return None  # a real "forbidden"
    if "retry-after" in headers:
        try:
            return max(float(headers["retry-after"]), 1.0)
        except ValueError:
            pass
    if remaining == "0" and "x-ratelimit-reset" in headers:
        try:
            return max(float(headers["x-ratelimit-reset"]) - now, 0.0) + 1.0
        except ValueError:
            pass
    return SECONDARY_WAIT * 2**attempt


def _stderr(message: str) -> None:
    print(message, file=sys.stderr)


class GitHubReleaseStore:
    """Assets of releases in ``repo`` ("owner/name"); releases are created on demand.

    ``notes`` is the release body: a text, or a function of the tag. A release this
    store writes to (``put``) gets its body set to the notes when they differ, so a
    correction of the notes in the code reaches the releases that already exist."""

    def __init__(
        self,
        client: httpx.Client,
        repo: str,
        token: str,
        notes: str | Callable[[str], str] = "",
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        log: Callable[[str], None] = _stderr,
        max_wait: float = MAX_WAIT,
    ) -> None:
        self.client = client
        self.repo = repo
        self.notes = notes
        self.sleep, self.clock, self.log, self.max_wait = sleep, clock, log, max_wait
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._ids: dict[str, int] = {}  # physical tag -> release id
        self._bodies: dict[str, str] = {}  # physical tag -> release body as GitHub has it
        self._missing: set[str] = set()  # physical tags known not to exist
        # tag -> (physical tags in order, their asset counts, assets by name)
        self._listing: dict[str, tuple[list[str], dict[str, int], dict[str, dict]]] = {}
        self.api_calls = 0

    # --- requests -------------------------------------------------------------------
    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """One API request, retried while GitHub answers that a rate limit is reached."""
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            self.api_calls += 1
            response = self.client.request(method, url, **kwargs)
            wait = rate_limit_wait(response, self.clock(), attempt)
            if wait is None:
                return response
            if attempt == RATE_LIMIT_RETRIES or wait > self.max_wait:
                raise RateLimitError(
                    f"GitHub rate limit for {method} {url} (status {response.status_code}, "
                    f"wait {wait:.0f} s): {response.text[:200]}",
                    request=response.request,
                    response=response,
                )
            self.log(f"GitHub rate limit ({response.status_code}); waiting {wait:.0f} s")
            self.sleep(wait)
        raise AssertionError("unreachable")

    def notes_for(self, tag: str) -> str:
        return self.notes(tag) if callable(self.notes) else self.notes

    def _release_id(self, tag: str, create: bool, notes_tag: str | None = None) -> int | None:
        if tag in self._ids:
            return self._ids[tag]
        response = None
        if tag not in self._missing:
            response = self._request(
                "GET", f"{API}/repos/{self.repo}/releases/tags/{tag}", headers=self.headers
            )
        body = None
        if response is None or response.status_code == 404:
            self._missing.add(tag)
            if not create:
                return None
            body = self.notes_for(notes_tag or tag)
            response = self._request(
                "POST",
                f"{API}/repos/{self.repo}/releases",
                headers=self.headers,
                json={"tag_name": tag, "name": tag, "body": body, "make_latest": "false"},
            )
            self._missing.discard(tag)
        response.raise_for_status()
        release = response.json()
        self._ids[tag] = release["id"]
        self._bodies[tag] = body if body is not None else release.get("body") or ""
        return self._ids[tag]

    def _update_notes(self, tag: str, release: int, notes_tag: str) -> None:
        """Set the body of ``tag`` to the notes if it differs (only stores with notes)."""
        notes = self.notes_for(notes_tag)
        if not notes or self._bodies.get(tag) == notes:
            return
        response = self._request(
            "PATCH",
            f"{API}/repos/{self.repo}/releases/{release}",
            headers=self.headers,
            json={"body": notes},
        )
        response.raise_for_status()
        self._bodies[tag] = notes

    def tags(self, prefix: str = "") -> list[str]:
        """Tags of all releases starting with ``prefix`` (not the overflow releases)."""
        found: list[str] = []
        page = 1
        while True:
            response = self._request(
                "GET",
                f"{API}/repos/{self.repo}/releases",
                headers=self.headers,
                params={"per_page": 100, "page": page},
            )
            response.raise_for_status()
            batch = response.json()
            found += [
                r["tag_name"]
                for r in batch
                if r["tag_name"].startswith(prefix) and not is_overflow(r["tag_name"])
            ]
            if len(batch) < 100:
                return sorted(found)
            page += 1

    def _list_release(self, release: int) -> list[dict]:
        found: list[dict] = []
        page = 1
        while True:
            response = self._request(
                "GET",
                f"{API}/repos/{self.repo}/releases/{release}/assets",
                headers=self.headers,
                params={"per_page": 100, "page": page},
            )
            response.raise_for_status()
            batch = response.json()
            found += batch
            if len(batch) < 100:
                return found
            page += 1

    def _load(self, tag: str) -> tuple[list[str], dict[str, int], dict[str, dict]]:
        """The releases of ``tag`` (itself and its overflow releases) and their assets,
        read once and then kept up to date by ``put``."""
        if tag in self._listing:
            return self._listing[tag]
        parts: list[str] = []
        counts: dict[str, int] = {}
        assets: dict[str, dict] = {}
        part = 1
        while True:
            physical = overflow_tag(tag, part)
            release = self._release_id(physical, create=False)
            if release is None:
                break
            batch = self._list_release(release)
            parts.append(physical)
            counts[physical] = len(batch)
            for asset in batch:
                assets.setdefault(asset["name"], {**asset, "_tag": physical})
            if len(batch) < MAX_ASSETS:  # only a full release has a next one
                break
            part += 1
        self._listing[tag] = (parts, counts, assets)
        return self._listing[tag]

    def assets(self, tag: str) -> dict[str, dict]:
        """Assets of the release ``tag`` (with its overflow releases) by name: ``id``,
        ``size``, ``label``, ``browser_download_url``, … and ``_tag``, the release that
        holds it. Read from GitHub once per store."""
        return dict(self._load(tag)[2])

    def names(self, tag: str) -> set[str]:
        return set(self._load(tag)[2])

    def forget(self, tag: str | None = None) -> None:
        """Read the asset list of ``tag`` (or of all) from GitHub again next time."""
        if tag is None:
            self._listing.clear()
        else:
            self._listing.pop(tag, None)

    def put(self, tag: str, name: str, path: Path, label: str = "") -> None:
        """Upload ``path`` as ``name``, replacing an existing asset of that name; a new
        asset goes to the first release of ``tag`` with room (``MAX_ASSETS``), a new
        overflow release when all are full."""
        parts, counts, assets = self._load(tag)
        old = assets.get(name)
        if old is not None:
            physical = old["_tag"]
        else:
            physical = next((p for p in parts if counts[p] < MAX_ASSETS), None)
            if physical is None:
                physical = overflow_tag(tag, len(parts) + 1)
                if parts:
                    self.log(f"release {parts[-1]} is full; new assets go to {physical}")
        release = self._release_id(physical, create=True, notes_tag=tag)
        if physical not in counts:
            parts.append(physical)
            counts[physical] = 0
        self._update_notes(physical, release, tag)
        if old is not None:  # GitHub cannot overwrite an asset
            response = self._request(
                "DELETE",
                f"{API}/repos/{self.repo}/releases/assets/{old['id']}",
                headers=self.headers,
            )
            if response.status_code != 404:  # already gone is fine
                response.raise_for_status()
            del assets[name]
            counts[physical] -= 1
        params = {"name": name, **({"label": label} if label else {})}
        response = self._request(
            "POST",
            f"{UPLOADS}/repos/{self.repo}/releases/{release}/assets",
            headers={**self.headers, "Content-Type": "application/octet-stream"},
            params=params,
            content=path.read_bytes(),
        )
        response.raise_for_status()
        try:
            uploaded = response.json()
        except ValueError:
            uploaded = {}
        if not isinstance(uploaded, dict):
            uploaded = {}
        assets[name] = {"name": name, "label": label or None, **uploaded, "_tag": physical}
        counts[physical] += 1

    def download(self, tag: str, name: str, dest: Path) -> Path:
        """Download the asset ``name`` of ``tag`` to ``dest``: from its
        ``browser_download_url`` (no API request), else through the API."""
        asset = self._load(tag)[2][name]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if asset.get("browser_download_url") and self._fetch(
            asset["browser_download_url"], {}, dest
        ):
            return dest
        if "id" not in asset:
            raise KeyError(f"{tag}/{name} has no asset id")
        headers = {**self.headers, "Accept": "application/octet-stream"}
        url = f"{API}/repos/{self.repo}/releases/assets/{asset['id']}"
        self.api_calls += 1
        if not self._fetch(url, headers, dest, api=True):
            raise httpx.HTTPError(f"could not download {tag}/{name}")
        return dest

    def _fetch(self, url: str, headers: dict, dest: Path, api: bool = False) -> bool:
        """Stream ``url`` to ``dest``; False when the URL does not serve the file
        (401/403/404 of a browser URL), raising for other errors after retries.
        GitHub redirects to its storage host; httpx drops the token on that redirect."""
        part = dest.with_name(dest.name + ".part")
        for attempt in range(DOWNLOAD_RETRIES + 1):
            with self.client.stream("GET", url, headers=headers, follow_redirects=True) as r:
                if not api and r.status_code in (401, 403, 404):
                    return False
                wait = rate_limit_wait(r, self.clock(), attempt) if api else None
                if wait is None and r.status_code >= 500:
                    wait = 2.0 * 2**attempt
                if wait is not None and attempt < DOWNLOAD_RETRIES and wait <= self.max_wait:
                    r.read()
                else:
                    r.raise_for_status()
                    with part.open("wb") as out:
                        for chunk in r.iter_bytes(1 << 20):
                            out.write(chunk)
                    part.replace(dest)
                    return True
            self.log(f"download of {url} answered {r.status_code}; retrying in {wait:.0f} s")
            self.sleep(wait)
        raise AssertionError("unreachable")
