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
