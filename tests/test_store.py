import json

import httpx
import pytest

from meteoverdict import store
from meteoverdict.releases import GitHubReleaseStore


class FakeGitHub:
    """Enough of the GitHub releases API for the store: one repo, assets in memory."""

    def __init__(self):
        self.releases: dict[str, int] = {}
        self.assets: dict[int, dict] = {}  # id -> {name, label, content, release}
        self.calls: list[tuple[str, str]] = []
        self.storage_headers: list[httpx.Headers] = []
        self.client = httpx.Client(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        self.calls.append((request.method, url.path))
        if url.host == "objects.githubusercontent.com":
            self.storage_headers.append(request.headers)
            return httpx.Response(
                200, content=self.assets[int(url.path.rsplit("/", 1)[1])]["content"]
            )
        assert request.headers["Authorization"] == "Bearer t"
        path = url.path.removeprefix("/repos/o/r")
        if path.startswith("/releases/tags/"):
            tag = path.rsplit("/", 1)[1]
            if tag not in self.releases:
                return httpx.Response(404)
            return httpx.Response(200, json={"id": self.releases[tag]})
        if request.method == "POST" and path == "/releases":
            tag = json.loads(request.content)["tag_name"]
            self.releases[tag] = len(self.releases) + 1
            return httpx.Response(201, json={"id": self.releases[tag]})
        if path.endswith("/assets") and url.host == "api.github.com":
            release = int(path.split("/")[2])
            mine = [
                {"id": i, "name": a["name"], "label": a["label"], "size": len(a["content"])}
                for i, a in self.assets.items()
                if a["release"] == release
            ]
            page = int(url.params["page"])
            return httpx.Response(200, json=mine[(page - 1) * 100 : page * 100])
        if url.host == "uploads.github.com":
            release = int(path.split("/")[2])
            names = [a["name"] for a in self.assets.values() if a["release"] == release]
            if url.params["name"] in names:
                return httpx.Response(422, json={"message": "already_exists"})
            new_id = 100 + len(self.calls)
            self.assets[new_id] = {
                "name": url.params["name"],
                "label": url.params.get("label", ""),
                "content": request.content,
                "release": release,
            }
            return httpx.Response(201, json={"id": new_id})
        if path.startswith("/releases/assets/"):
            asset_id = int(path.rsplit("/", 1)[1])
            if request.method == "DELETE":
                del self.assets[asset_id]
                return httpx.Response(204)
            assert request.headers["Accept"] == "application/octet-stream"
            return httpx.Response(
                302, headers={"Location": f"https://objects.githubusercontent.com/x/{asset_id}"}
            )
        return httpx.Response(500)

    def store(self) -> GitHubReleaseStore:
        return GitHubReleaseStore(self.client, "o/r", "t", notes=store.RELEASE_NOTES)


def write(data_dir, kind, month, content: bytes):
    path = data_dir / kind / f"{month}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_names():
    assert store.release_tag("2026-09") == "data-2026-09"
    assert store.asset_name("fc", "2026-09") == "fc-2026-09.parquet"


def test_month_range():
    assert store.month_range("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]
    with pytest.raises(ValueError):
        store.month_range("2026-02", "2025-11")
    with pytest.raises(ValueError):
        store.month_range("2026-2", "2026-03")
    with pytest.raises(ValueError):
        store.month_range("2026-13", "2026-13")


def test_upload_only_changed_files_and_replace_them(tmp_path):
    gh = FakeGitHub()
    write(tmp_path, "obs", "2026-09", b"obs v1")
    write(tmp_path, "fc", "2026-09", b"fc v1")
    write(tmp_path, "obs", "notes", b"ignored: not a month")
    assert store.upload(gh.store(), tmp_path) == ["obs-2026-09.parquet", "fc-2026-09.parquet"]
    assert store.upload(gh.store(), tmp_path) == []  # labels hold the SHA-256

    write(tmp_path, "obs", "2026-09", b"obs v2")
    assert store.upload(gh.store(), tmp_path) == ["obs-2026-09.parquet"]
    contents = sorted(a["content"] for a in gh.assets.values())
    assert contents == [b"fc v1", b"obs v2"]  # replaced, not duplicated
    assert any(method == "DELETE" for method, _ in gh.calls)


def test_download_missing_or_changed_files_without_leaking_the_token(tmp_path):
    gh = FakeGitHub()
    source = tmp_path / "source"
    write(source, "obs", "2026-09", b"obs")
    write(source, "fc", "2026-10", b"fc")
    store.upload(gh.store(), source)

    target = tmp_path / "target"
    got = store.download(gh.store(), target, ["2026-09", "2026-10", "2026-11"])
    assert got == ["obs-2026-09.parquet", "fc-2026-10.parquet"]
    assert (target / "obs" / "2026-09.parquet").read_bytes() == b"obs"
    assert all("authorization" not in h for h in gh.storage_headers)
    assert store.download(gh.store(), target, ["2026-09", "2026-10"]) == []
