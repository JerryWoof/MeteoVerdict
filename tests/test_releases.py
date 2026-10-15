import json

import httpx

from meteoverdict.releases import GitHubReleaseStore


def fake_github(existing_assets: int = 0):
    calls: list[tuple[str, str]] = []
    releases: dict[str, int] = {}
    assets: list[str] = [f"a{i}.parquet" for i in range(existing_assets)]

    def handler(request: httpx.Request) -> httpx.Response:
        url = request.url
        calls.append((request.method, f"{url.host}{url.path}"))
        assert request.headers["Authorization"] == "Bearer t0ken"
        if url.path.startswith("/repos/o/r/releases/tags/"):
            tag = url.path.rsplit("/", 1)[1]
            if tag in releases or existing_assets:
                return httpx.Response(200, json={"id": 7})
            return httpx.Response(404)
        if request.method == "POST" and url.path == "/repos/o/r/releases":
            body = json.loads(request.content)
            releases[body["tag_name"]] = 7
            assert body["make_latest"] == "false" and body["body"] == "notes"
            return httpx.Response(201, json={"id": 7})
        if url.path == "/repos/o/r/releases/7/assets" and url.host == "api.github.com":
            page = int(url.params["page"])
            return httpx.Response(200, json=[{"name": n} for n in assets[(page - 1) * 100 :][:100]])
        if url.host == "uploads.github.com":
            assets.append(url.params["name"])
            assert request.headers["Content-Type"] == "application/octet-stream"
            return httpx.Response(201, json={})
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GitHubReleaseStore(client, "o/r", "t0ken", notes="notes"), calls, assets


def test_missing_release_has_no_names_and_is_not_created():
    store, calls, _ = fake_github()
    assert store.names("aladin-2026-10") == set()
    assert [m for m, _ in calls] == ["GET"]


def test_put_creates_the_release_and_uploads(tmp_path):
    store, calls, assets = fake_github()
    path = tmp_path / "x.parquet"
    path.write_bytes(b"data")
    store.put("aladin-2026-10", "x.parquet", path)
    assert assets == ["x.parquet"]
    assert ("POST", "api.github.com/repos/o/r/releases") in calls
    assert store.names("aladin-2026-10") == {"x.parquet"}


def test_names_follow_pagination():
    store, _, _ = fake_github(existing_assets=230)
    assert len(store.names("aladin-2026-10")) == 230


def notes_github(body: str):
    """One existing release (id 7) whose body is ``body``; records the PATCHes."""
    patches: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/o/r/releases/tags/satellite-2025-12":
            return httpx.Response(200, json={"id": 7, "body": body})
        if request.method == "PATCH" and path == "/repos/o/r/releases/7":
            patches.append(json.loads(request.content))
            return httpx.Response(200, json={"id": 7})
        if path == "/repos/o/r/releases/7/assets":
            return httpx.Response(200, json=[])
        if request.url.host == "uploads.github.com":
            return httpx.Response(201, json={})
        return httpx.Response(500)

    return httpx.Client(transport=httpx.MockTransport(handler)), patches


def test_put_corrects_the_notes_of_an_existing_release(tmp_path):
    client, patches = notes_github("old notes")
    store = GitHubReleaseStore(client, "o/r", "t0ken", notes=lambda tag: f"notes of {tag}")
    path = tmp_path / "x.tar"
    path.write_bytes(b"data")
    store.put("satellite-2025-12", "x.tar", path)
    store.put("satellite-2025-12", "y.tar", path)
    assert patches == [{"body": "notes of satellite-2025-12"}]  # once


def test_notes_already_right_or_none_are_left_alone(tmp_path):
    path = tmp_path / "x.tar"
    path.write_bytes(b"data")
    client, patches = notes_github("notes")
    GitHubReleaseStore(client, "o/r", "t0ken", notes="notes").put("satellite-2025-12", "x", path)
    client, patches_without = notes_github("old notes")
    GitHubReleaseStore(client, "o/r", "t0ken").put("satellite-2025-12", "x", path)
    assert patches == patches_without == []


def test_reading_does_not_touch_the_notes():
    client, patches = notes_github("old notes")
    store = GitHubReleaseStore(client, "o/r", "t0ken", notes="notes")
    assert store.names("satellite-2025-12") == set()
    assert patches == []
