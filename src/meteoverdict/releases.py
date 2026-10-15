"""Store data files as GitHub Release assets (one release per tag)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"


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
    ) -> None:
        self.client = client
        self.repo = repo
        self.notes = notes
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._ids: dict[str, int] = {}
        self._bodies: dict[str, str] = {}  # tag -> release body as GitHub has it

    def notes_for(self, tag: str) -> str:
        return self.notes(tag) if callable(self.notes) else self.notes

    def _release_id(self, tag: str, create: bool) -> int | None:
        if tag in self._ids:
            return self._ids[tag]
        response = self.client.get(
            f"{API}/repos/{self.repo}/releases/tags/{tag}", headers=self.headers
        )
        body = None
        if response.status_code == 404:
            if not create:
                return None
            body = self.notes_for(tag)
            response = self.client.post(
                f"{API}/repos/{self.repo}/releases",
                headers=self.headers,
                json={
                    "tag_name": tag,
                    "name": tag,
                    "body": body,
                    "make_latest": "false",
                },
            )
        response.raise_for_status()
        release = response.json()
        self._ids[tag] = release["id"]
        self._bodies[tag] = body if body is not None else release.get("body") or ""
        return self._ids[tag]

    def _update_notes(self, tag: str, release: int) -> None:
        """Set the body of ``tag`` to the notes if it differs (only stores with notes)."""
        notes = self.notes_for(tag)
        if not notes or self._bodies.get(tag) == notes:
            return
        response = self.client.patch(
            f"{API}/repos/{self.repo}/releases/{release}",
            headers=self.headers,
            json={"body": notes},
        )
        response.raise_for_status()
        self._bodies[tag] = notes

    def tags(self, prefix: str = "") -> list[str]:
        """Tags of all releases starting with ``prefix``."""
        found: list[str] = []
        page = 1
        while True:
            response = self.client.get(
                f"{API}/repos/{self.repo}/releases",
                headers=self.headers,
                params={"per_page": 100, "page": page},
            )
            response.raise_for_status()
            batch = response.json()
            found += [r["tag_name"] for r in batch if r["tag_name"].startswith(prefix)]
            if len(batch) < 100:
                return sorted(found)
            page += 1

    def assets(self, tag: str) -> dict[str, dict]:
        """Assets of the release ``tag`` by name (``id``, ``size``, ``label``, …)."""
        release = self._release_id(tag, create=False)
        if release is None:
            return {}
        found: dict[str, dict] = {}
        page = 1
        while True:
            response = self.client.get(
                f"{API}/repos/{self.repo}/releases/{release}/assets",
                headers=self.headers,
                params={"per_page": 100, "page": page},
            )
            response.raise_for_status()
            batch = response.json()
            found |= {asset["name"]: asset for asset in batch}
            if len(batch) < 100:
                return found
            page += 1

    def names(self, tag: str) -> set[str]:
        return set(self.assets(tag))

    def put(self, tag: str, name: str, path: Path, label: str = "") -> None:
        """Upload ``path`` as ``name``, replacing an existing asset of that name."""
        release = self._release_id(tag, create=True)
        self._update_notes(tag, release)
        old = self.assets(tag).get(name)
        if old is not None:  # GitHub cannot overwrite an asset
            response = self.client.delete(
                f"{API}/repos/{self.repo}/releases/assets/{old['id']}", headers=self.headers
            )
            response.raise_for_status()
        params = {"name": name, **({"label": label} if label else {})}
        response = self.client.post(
            f"{UPLOADS}/repos/{self.repo}/releases/{release}/assets",
            headers={**self.headers, "Content-Type": "application/octet-stream"},
            params=params,
            content=path.read_bytes(),
        )
        response.raise_for_status()

    def download(self, tag: str, name: str, dest: Path) -> Path:
        asset = self.assets(tag)[name]
        dest.parent.mkdir(parents=True, exist_ok=True)
        headers = {**self.headers, "Accept": "application/octet-stream"}
        url = f"{API}/repos/{self.repo}/releases/assets/{asset['id']}"
        # GitHub redirects to its storage host; httpx drops the token on that redirect
        with self.client.stream("GET", url, headers=headers, follow_redirects=True) as response:
            response.raise_for_status()
            with dest.open("wb") as out:
                for chunk in response.iter_bytes(1 << 20):
                    out.write(chunk)
        return dest
