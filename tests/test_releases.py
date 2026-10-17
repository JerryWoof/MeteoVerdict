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


# --- rate limits, caching, downloads and the asset cap -------------------------------
import pytest  # noqa: E402

from meteoverdict import releases as rel  # noqa: E402


class FakeGitHub:
    """Releases by tag with assets; counts API requests; can answer rate limits first."""

    def __init__(self, releases: dict[str, list[str]], public: bool = True) -> None:
        self.releases = {
            tag: {"id": i + 1, "assets": list(names)}
            for i, (tag, names) in enumerate(releases.items())
        }
        self.public = public
        self.api: list[tuple[str, str]] = []
        self.storage: list[str] = []
        self.limited: list[httpx.Response] = []  # answered before the real answer
        self.next_asset = 1000

    def _by_id(self, release_id: int) -> str:
        return next(t for t, r in self.releases.items() if r["id"] == release_id)

    def asset(self, tag: str, name: str) -> dict:
        n = self.releases[tag]["assets"].index(name)
        aid = self.releases[tag]["id"] * 100000 + n
        return {
            "id": aid,
            "name": name,
            "size": 4,
            "label": None,
            "browser_download_url": f"https://github.com/o/r/releases/download/{tag}/{name}",
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.host == "github.com":
            self.storage.append(url.path)
            assert "Authorization" not in request.headers
            if not self.public:
                return httpx.Response(404)
            return httpx.Response(200, content=b"file")
        self.api.append((request.method, url.path))
        if self.limited:
            return self.limited.pop(0)
        path = url.path.removeprefix("/repos/o/r")
        if path.startswith("/releases/tags/"):
            tag = path.rsplit("/", 1)[1]
            if tag not in self.releases:
                return httpx.Response(404)
            return httpx.Response(200, json={"id": self.releases[tag]["id"], "body": ""})
        if path == "/releases" and request.method == "GET":
            return httpx.Response(200, json=[{"tag_name": t} for t in self.releases])
        if path == "/releases" and request.method == "POST":
            tag = json.loads(request.content)["tag_name"]
            self.releases[tag] = {"id": len(self.releases) + 1, "assets": []}
            return httpx.Response(201, json={"id": self.releases[tag]["id"]})
        if path.startswith("/releases/assets/") and request.method == "DELETE":
            aid = int(path.rsplit("/", 1)[1])
            tag = self._by_id(aid // 100000)
            self.releases[tag]["assets"][aid % 100000] = None
            return httpx.Response(204)
        if path.startswith("/releases/assets/"):
            return httpx.Response(200, content=b"via api")
        if path.endswith("/assets") and url.host == "uploads.github.com":
            tag = self._by_id(int(path.split("/")[2]))
            names = self.releases[tag]["assets"]
            if sum(n is not None for n in names) >= rel.MAX_ASSETS:
                return httpx.Response(422, json={"message": "too many assets"})
            names.append(url.params["name"])
            return httpx.Response(201, json=self.asset(tag, url.params["name"]))
        if path.endswith("/assets"):
            tag = self._by_id(int(path.split("/")[2]))
            page = int(url.params["page"])
            live = [n for n in self.releases[tag]["assets"] if n is not None]
            batch = live[(page - 1) * 100 :][:100]
            return httpx.Response(200, json=[self.asset(tag, n) for n in batch])
        return httpx.Response(500)

    def store(self, **kwargs) -> rel.GitHubReleaseStore:
        client = httpx.Client(transport=httpx.MockTransport(self.handler))
        self.waits: list[float] = []
        return rel.GitHubReleaseStore(
            client,
            "o/r",
            "t0ken",
            sleep=self.waits.append,
            clock=lambda: 1000.0,
            log=lambda _: None,
            **kwargs,
        )


def test_rate_limit_is_waited_out_until_the_reset():
    gh = FakeGitHub({"chmi-2026": ["a"]})
    gh.limited = [
        httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1120"},
            json={"message": "API rate limit exceeded"},
        ),
        httpx.Response(429, headers={"retry-after": "30"}),
        httpx.Response(403, json={"message": "You have exceeded a secondary rate limit"}),
    ]
    store = gh.store()
    assert store.names("chmi-2026") == {"a"}
    assert gh.waits == [121.0, 30.0, 240.0]  # reset - now + 1; retry-after; backoff


def test_a_wait_longer_than_allowed_raises():
    gh = FakeGitHub({"chmi-2026": ["a"]})
    gh.limited = [
        httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999"})
    ]
    with pytest.raises(rel.RateLimitError):
        gh.store(max_wait=600).names("chmi-2026")


def test_a_plain_forbidden_is_not_retried():
    gh = FakeGitHub({"chmi-2026": ["a"]})
    gh.limited = [httpx.Response(403, json={"message": "Resource not accessible"})]
    with pytest.raises(httpx.HTTPStatusError):
        gh.store().names("chmi-2026")
    assert gh.waits == []


def test_listing_paginates_once_and_downloads_cost_no_api_requests(tmp_path):
    names = [f"h{i:04d}.parquet" for i in range(250)]
    gh = FakeGitHub({"chmi-history-1": names})
    store = gh.store()
    assert len(store.assets("chmi-history-1")) == 250
    for name in names[:50]:
        store.download("chmi-history-1", name, tmp_path / name)
    # the release by tag, then 3 pages; no listing per download, no API download
    assert len(gh.api) == 4
    assert len(gh.storage) == 50
    assert (tmp_path / names[0]).read_bytes() == b"file"
    assert store.api_calls == 4


def test_download_falls_back_to_the_api_for_a_private_repository(tmp_path):
    gh = FakeGitHub({"data-latest": ["x.json"]}, public=False)
    store = gh.store()
    store.download("data-latest", "x.json", tmp_path / "x.json")
    assert (tmp_path / "x.json").read_bytes() == b"via api"


def test_a_full_release_overflows_into_the_next(tmp_path):
    full = [f"h{i:04d}.parquet" for i in range(rel.MAX_ASSETS)]
    gh = FakeGitHub({"chmi-history-1": full})
    store = gh.store()
    path = tmp_path / "new.parquet"
    path.write_bytes(b"data")
    store.put("chmi-history-1", "new.parquet", path)
    assert gh.releases["chmi-history-1.2"]["assets"] == ["new.parquet"]
    assets = store.assets("chmi-history-1")
    assert len(assets) == rel.MAX_ASSETS + 1
    assert assets["new.parquet"]["_tag"] == "chmi-history-1.2"
    # replacing an asset keeps it where it is
    store.put("chmi-history-1", "h0001.parquet", path)
    assert "h0001.parquet" in gh.releases["chmi-history-1"]["assets"]
    assert "h0001.parquet" not in gh.releases["chmi-history-1.2"]["assets"]
    # a new store finds both releases as one; tags() hides the overflow
    fresh = gh.store()
    assert len(fresh.names("chmi-history-1")) == rel.MAX_ASSETS + 1
    assert fresh.tags("chmi-history") == ["chmi-history-1"]
    fresh.download("chmi-history-1", "new.parquet", tmp_path / "got")
    assert gh.storage[-1] == "/o/r/releases/download/chmi-history-1.2/new.parquet"


def test_put_never_exceeds_the_cap(tmp_path):
    gh = FakeGitHub({"t": [f"a{i}" for i in range(rel.MAX_ASSETS - 1)]})
    store = gh.store()
    path = tmp_path / "f"
    path.write_bytes(b"x")
    for i in range(3):
        store.put("t", f"b{i}", path)
    assert len(gh.releases["t"]["assets"]) == rel.MAX_ASSETS
    assert gh.releases["t.2"]["assets"] == ["b1", "b2"]


def test_rate_limit_wait_reads_the_headers():
    def resp(status, **headers):
        return httpx.Response(status, headers=headers)

    assert rel.rate_limit_wait(resp(200), 0, 0) is None
    assert rel.rate_limit_wait(resp(404), 0, 0) is None
    assert rel.rate_limit_wait(resp(429), 0, 2) == rel.SECONDARY_WAIT * 4
    assert rel.rate_limit_wait(resp(403, **{"retry-after": "5"}), 0, 0) == 5
    reset = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "50"}
    assert rel.rate_limit_wait(resp(403, **reset), 100, 0) == 1  # already reset
