"""Store data files as GitHub Release assets (one release per tag)."""

from __future__ import annotations

from pathlib import Path

import httpx

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"


class GitHubReleaseStore:
    """Assets of releases in ``repo`` ("owner/name"); releases are created on demand."""

    def __init__(self, client: httpx.Client, repo: str, token: str, notes: str = "") -> None:
        self.client = client
        self.repo = repo
        self.notes = notes
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._ids: dict[str, int] = {}

    def _release_id(self, tag: str, create: bool) -> int | None:
        if tag in self._ids:
            return self._ids[tag]
        response = self.client.get(
            f"{API}/repos/{self.repo}/releases/tags/{tag}", headers=self.headers
        )
        if response.status_code == 404:
            if not create:
                return None
            response = self.client.post(
                f"{API}/repos/{self.repo}/releases",
                headers=self.headers,
                json={"tag_name": tag, "name": tag, "body": self.notes, "make_latest": "false"},
            )
        response.raise_for_status()
        self._ids[tag] = response.json()["id"]
        return self._ids[tag]

    def names(self, tag: str) -> set[str]:
        release = self._release_id(tag, create=False)
        if release is None:
            return set()
        names: set[str] = set()
        page = 1
        while True:
            response = self.client.get(
                f"{API}/repos/{self.repo}/releases/{release}/assets",
                headers=self.headers,
                params={"per_page": 100, "page": page},
            )
            response.raise_for_status()
            batch = response.json()
            names |= {asset["name"] for asset in batch}
            if len(batch) < 100:
                return names
            page += 1

    def put(self, tag: str, name: str, path: Path) -> None:
        release = self._release_id(tag, create=True)
        response = self.client.post(
            f"{UPLOADS}/repos/{self.repo}/releases/{release}/assets",
            headers={**self.headers, "Content-Type": "application/octet-stream"},
            params={"name": name},
            content=path.read_bytes(),
        )
        response.raise_for_status()
