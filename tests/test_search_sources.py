"""Searching each source: what is asked for, and what comes back.

Both halves live in one file on purpose. The two sources disagree about almost
everything — paging, filters, and the shape of a poster — and the pins that
matter are the ones that read side by side.
"""

import html
import json

import pytest
import requests

from app.core import page


# ── StreamingCommunity ────────────────────────────────────────────────────────

def _page_html(payload: dict) -> str:
    """A server-rendered page carrying *payload*, escaped the way the site does."""
    return (
        '<html><body><div id="app" data-page="'
        + html.escape(json.dumps(payload), quote=True)
        + '"></div></body></html>'
    )


def _title(n, kind="tv", poster="p.jpg"):
    return {
        "id": n, "name": f"Title {n}", "slug": f"title-{n}", "type": kind,
        "score": "8.1", "last_air_date": "2024-05-01", "age": 14,
        "seasons_count": 2,
        "images": [{"type": "background", "filename": "b.jpg"},
                   {"type": "poster", "filename": poster}],
    }


class _Response:
    def __init__(self, text="", status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture
def sc(monkeypatch):
    """Serve one page payload, and record every request made to get it."""
    state = {"payload": {"props": {"titles": []}}, "calls": []}

    def fake_get(url, *args, **kwargs):
        state["calls"].append((url, kwargs))
        return _Response(_page_html(state["payload"]))

    monkeypatch.setattr(page.requests, "get", fake_get)
    return state


def test_the_search_reads_the_server_rendered_props(sc):
    sc["payload"] = {"props": {"titles": [_title(1), _title(2)]}}

    results = page.search("x", "source.test")

    assert [r["name"] for r in results] == ["Title 1", "Title 2"]
    assert results[0]["id"] == 1 and results[0]["slug"] == "title-1"


def test_it_costs_one_request_and_carries_no_inertia_headers(sc):
    """The payload is in the HTML any visitor gets: no handshake, no session."""
    page.search("x", "source.test")

    assert len(sc["calls"]) == 1
    url, kwargs = sc["calls"][0]
    assert url == "https://source.test/it/search"
    assert kwargs["params"] == {"q": "x"}
    assert not any(h.lower().startswith("x-inertia") for h in kwargs["headers"])


def test_the_request_carries_a_timeout(sc):
    page.search("x", "source.test")

    assert sc["calls"][0][1]["timeout"]


def test_the_page_number_is_passed_through(sc):
    page.search("x", "source.test", page=3)

    assert sc["calls"][0][1]["params"]["page"] == 3


def test_the_kind_filter_runs_before_the_cap(sc):
    """Filtering the cap's output answers "no films" for a search whose films
    were all sitting at position 22."""
    sc["payload"] = {"props": {"titles": [_title(n, "tv") for n in range(65)]
                                         + [_title(100 + n, "movie") for n in range(5)]}}

    results = page.search("x", "source.test", media_type="movie")

    assert len(results) == 5
    assert {r["type"] for r in results} == {"movie"}


def test_at_most_sixty_results_come_back(sc):
    sc["payload"] = {"props": {"titles": [_title(n) for n in range(100)]}}

    assert len(page.search("x", "source.test")) == 60


def test_the_poster_is_a_bare_filename(sc):
    """The frontend routes it through /api/image, where the host is ours."""
    sc["payload"] = {"props": {"titles": [_title(1, poster="poster-1.jpg")]}}

    assert page.search("x", "source.test")[0]["poster"] == "poster-1.jpg"


def test_a_page_with_no_titles_is_an_empty_list(sc):
    sc["payload"] = {"props": {}}

    assert page.search("nothing", "source.test") == []


def test_a_row_without_an_id_is_dropped_not_rendered(sc):
    """One malformed row must not take the shelf, or the search, with it."""
    broken = _title(2)
    del broken["id"]
    sc["payload"] = {"props": {"titles": [_title(1), broken]}}

    assert [r["id"] for r in page.search("x", "source.test")] == [1]


def test_entities_are_unescaped_exactly_once(sc):
    """BeautifulSoup already decodes the attribute. A second pass would turn a
    plot's "&amp;amp;" into "&"."""
    titled = _title(1)
    titled["name"] = 'Tom &amp; Jerry "1940"'
    sc["payload"] = {"props": {"titles": [titled]}}

    assert page.search("x", "source.test")[0]["name"] == 'Tom &amp; Jerry "1940"'


# ── A host without the /it segment (#34) ─────────────────────────────────────

@pytest.fixture
def unprefixed(monkeypatch):
    """A clone that serves /search and answers 404 to /it/search."""
    monkeypatch.setattr(page, "_locale_by_host", {})
    calls = []

    def fake_get(url, *args, **kwargs):
        calls.append(url)
        if "/it/" in url or url.endswith("/it"):
            return _Response("not found", status_code=404)
        return _Response(_page_html({"props": {"titles": [_title(1)]}}))

    monkeypatch.setattr(page.requests, "get", fake_get)
    return calls


def test_a_host_without_the_locale_segment_is_searched_without_it(unprefixed):
    assert [r["name"] for r in page.search("x", "clone.test")] == ["Title 1"]
    assert unprefixed == ["https://clone.test/it/search", "https://clone.test/search"]


def test_the_form_that_worked_is_remembered_per_host(unprefixed):
    page.search("x", "clone.test")
    unprefixed.clear()

    page.search("y", "clone.test")

    assert unprefixed == ["https://clone.test/search"]
    assert page.site_url("clone.test", "/titles/1-a") == "https://clone.test/titles/1-a"
    assert page.site_url("other.test", "/titles/1-a") == "https://other.test/it/titles/1-a"


def test_a_page_missing_both_ways_does_not_flip_the_host(monkeypatch):
    """A title that does not exist is a 404 with or without /it."""
    monkeypatch.setattr(page, "_locale_by_host", {})
    monkeypatch.setattr(page.requests, "get",
                        lambda url, *a, **kw: _Response("nope", status_code=404))

    response = page.get_localized("source.test", "/titles/9-gone")

    assert response.status_code == 404
    assert page.locale("source.test") == "/it"


def test_a_host_that_regains_the_segment_is_followed_back(monkeypatch):
    monkeypatch.setattr(page, "_locale_by_host", {"source.test": ""})

    def fake_get(url, *args, **kwargs):
        if "/it/" in url:
            return _Response(_page_html({"props": {"titles": [_title(2)]}}))
        return _Response("not found", status_code=404)

    monkeypatch.setattr(page.requests, "get", fake_get)

    assert [r["name"] for r in page.search("x", "source.test")] == ["Title 2"]
    assert page.locale("source.test") == "/it"


# ── get_domain_version keeps its three answers ────────────────────────────────

def test_an_unreachable_domain_raises(monkeypatch):
    def boom(*a, **kw):
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(page.requests, "get", boom)

    with pytest.raises(RuntimeError, match="Cannot reach"):
        page.get_domain_version("gone.test")


def test_a_page_without_a_payload_has_no_version(monkeypatch):
    """Reachable, but nothing that says it is the source: "" , not None."""
    monkeypatch.setattr(page.requests, "get",
                        lambda *a, **kw: _Response("<html><body>hi</body></html>"))

    assert page.get_domain_version("other.test") == ""


def test_an_unparseable_payload_is_none(monkeypatch):
    monkeypatch.setattr(page.requests, "get", lambda *a, **kw: _Response(
        '<html><div id="app" data-page="{not json"></div></html>'))

    assert page.get_domain_version("broken.test") is None


def test_a_good_page_reports_its_version(monkeypatch, sc):
    sc["payload"] = {"version": "abc123", "props": {}}

    assert page.get_domain_version("source.test") == "abc123"
    assert sc["calls"][0][0] == "https://source.test", "not /it: domain_recovery reads this page"


# ── AnimeUnity ────────────────────────────────────────────────────────────────

from app.core import animeunity  # noqa: E402


class _Resp:
    def __init__(self, text="", status_code=200, payload=None):
        self.text, self.status_code, self._payload = text, status_code, payload
        self.ok = status_code < 400

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def _page(props):
    """An Inertia page: the props in a data-page attribute, as the site serves it."""
    payload = html.escape(json.dumps({"component": "Archive", "props": props}), quote=True)
    return _Resp(text=f'<html><body><div id="app" data-page="{payload}"></div></body></html>')


class _Site:
    """Answers the archive page and the episodes API from canned data."""

    def __init__(self, rows=(), genres=(), episodes=()):
        self.rows, self.genres, self.episodes = list(rows), list(genres), list(episodes)
        self.gets = []

    def get(self, url, params=None, **kwargs):
        self.gets.append((url, dict(params or {})))
        if url.endswith("/archive"):
            return _page({"animes": {"data": self.rows}, "animeGenres": self.genres})
        if "/api/anime/" in url:
            start = int((params or {}).get("start", 1))
            batch = [e for e in self.episodes if int(e["number"]) >= start][:120]
            return _Resp(payload={"episodes": batch, "total": len(self.episodes),
                                  "start": start, "tab_size": 120})
        raise AssertionError(f"unexpected GET {url}")


def _row(n, variants=(("jpn", "completed"),), **extra):
    row = {
        "id": n, "slug": f"anime-{n}", "title": f"Anime {n}", "title_ja": f"アニメ{n}",
        "title_it": None, "type": "tv", "year": 2002, "season": "fall",
        "default_status": "completed", "total_episodes": 12, "score": "8.5",
        "plot": "Una trama.", "genres": [{"id": 1, "name": "Action"}],
        "studios": [{"id": 8, "name": "Studio Pierrot"}],
        "images": {"poster": f"https://img.test/{n}.jpg", "cover": None,
                   "banner": f"https://img.test/b{n}.jpg"},
        "variants": [{"language": lang, "status": status} for lang, status in variants],
    }
    row.update(extra)
    return row


def _video(vid, lang, hidden=False):
    return {"id": vid, "language": lang, "is_hidden": hidden, "runtime": 24}


@pytest.fixture
def site(monkeypatch):
    fake = _Site()
    monkeypatch.setattr(animeunity, "_get_scraper", lambda: fake)
    return fake


def test_search_asks_the_archive_page_with_the_query_and_page(site):
    site.rows = [_row(1)]
    animeunity.search("naruto", page=2)
    url, params = site.gets[-1]
    assert url.endswith("/archive")
    assert params == {"query": "naruto", "page": 2}


def test_filters_become_the_sources_own_parameters(site):
    site.rows = [_row(1)]
    animeunity.search("", media_type="OVA", dubbed=True, genre=37, year=2020,
                      order="latest", status="completed")
    assert site.gets[-1][1] == {"query": "", "page": 1, "language": "ita", "type": "ova",
                                "genres[]": 37, "year": 2020, "sort_by": "latest",
                                "status": "completed"}


def test_a_record_becomes_a_card(site):
    site.rows = [_row(7, variants=(("jpn", "completed"), ("ita", "ongoing")))]
    card = animeunity.search("x")[0]
    assert card["id"] == "7-anime-7"
    assert card["name"] == "Anime 7"
    assert card["media_type"] == "tv"
    assert card["dubbed"] is True
    assert card["poster"] == "https://img.test/7.jpg"
    assert card["backdrop"] == "https://img.test/b7.jpg"
    assert card["episodes_count"] == 12
    assert card["release_date"] == "2002"
    assert card["studio"] == "Studio Pierrot"
    assert card["genres"] == ["Action"]
    assert card["status"] == "completed"
    assert card["original_name"] == "アニメ7"


def test_no_italian_variant_means_not_dubbed(site):
    site.rows = [_row(1, variants=(("jpn", "completed"),))]
    assert animeunity.search("x")[0]["dubbed"] is False


def test_an_empty_page_is_an_empty_list_not_an_error(site):
    assert animeunity.search("nothing at all") == []


def test_the_same_record_twice_is_one_card(site):
    site.rows = [_row(1), _row(1)]
    assert len(animeunity.search("x")) == 1


def test_a_refused_page_is_reported(site, monkeypatch):
    monkeypatch.setattr(site, "get", lambda url, **kw: _Resp(status_code=503))
    with pytest.raises(RuntimeError, match="HTTP 503"):
        animeunity.search("x")


def test_browse_options_reads_the_genres_from_the_archive_page(site):
    site.genres = [{"id": 1, "name": "Action"}, {"id": 2, "name": "Adventure"}]
    assert animeunity.browse_options() == {"genres": [
        {"id": 1, "name": "Action"}, {"id": 2, "name": "Adventure"}]}


def test_episodes_are_read_in_batches_of_120_by_first_number(site):
    site.episodes = [{"id": n, "number": str(n), "videos": []} for n in range(1, 171)]
    episodes = animeunity.get_episodes("112-black-clover")
    assert [e["number"] for e in episodes][:1] == ["1"]
    assert len(episodes) == 170
    episode_calls = [(u, p["start"]) for u, p in site.gets if "/api/anime/" in u]
    assert episode_calls == [("https://animeunity.cx/api/anime/112/episodes", 1),
                             ("https://animeunity.cx/api/anime/112/episodes", 121)]


def test_no_episodes_is_an_empty_list(site):
    assert animeunity.get_episodes("112-black-clover") == []


def test_the_italian_video_is_picked_unless_another_language_is_asked():
    ep = {"number": "1", "videos": [_video(10, "jpn"), _video(20, "ita")]}
    assert animeunity._pick_video(ep)["id"] == 20
    assert animeunity._pick_video(ep, ("jpn",))["id"] == 10


def test_without_the_language_asked_the_first_video_is_used():
    ep = {"number": "1", "videos": [_video(10, "jpn")]}
    assert animeunity._pick_video(ep, ("ita",))["id"] == 10


def test_a_visible_video_beats_a_hidden_one():
    ep = {"number": "1", "videos": [_video(10, "ita", hidden=True), _video(20, "jpn")]}
    assert animeunity._pick_video(ep)["id"] == 20
    assert animeunity.get_episode_languages(ep) == {"audio": ["jpn"], "subtitles": []}


def test_hidden_videos_are_the_fallback_when_nothing_is_visible():
    ep = {"number": "5", "videos": [_video(10, "ita", hidden=True), _video(11, "jpn", hidden=True)]}
    assert animeunity._pick_video(ep, ("ita",))["id"] == 10
    assert animeunity.get_episode_languages(ep) == {"audio": ["ita", "jpn"], "subtitles": []}


def test_an_episode_with_no_video_is_an_error():
    with pytest.raises(animeunity.NoPlayableVideoError, match="non ha video disponibili"):
        animeunity._pick_video({"number": "3", "videos": []})


def test_the_languages_of_an_episode_are_its_videos_languages():
    ep = {"number": "1", "videos": [_video(10, "jpn"), _video(20, "ita")]}
    assert animeunity.get_episode_languages(ep) == {"audio": ["jpn", "ita"], "subtitles": []}



# ── /api/search ───────────────────────────────────────────────────────────────

from app.auth.permissions import ALL_PERMISSIONS  # noqa: E402
from tests.conftest import do_setup, make_user, session_for  # noqa: E402


@pytest.fixture
def signed_in(client, admin_credentials):
    do_setup(client, admin_credentials)
    user = make_user("boss", "jf-boss-id", int(ALL_PERMISSIONS))
    client.cookies.clear()
    return session_for(client, user.id)


@pytest.fixture
def asked(monkeypatch):
    """Record what each source was asked for, without reaching either."""
    seen = {}
    from app.core import animeunity as au
    from app.routers import search as router

    monkeypatch.setattr(router, "configured_domain", lambda: "source.test")
    monkeypatch.setattr(router, "core_search",
                        lambda q, domain, **kw: seen.update(sc=(q, domain, kw)) or [])
    monkeypatch.setattr(au, "search", lambda q, **kw: seen.update(au=(q, kw)) or [])
    return seen


def test_the_page_and_kind_reach_streamingcommunity(client, signed_in, asked):
    response = client.get("/api/search?q=abc&page=4&media_type=movie")

    assert response.status_code == 200
    q, domain, kwargs = asked["sc"]
    assert (q, domain) == ("abc", "source.test")
    assert kwargs["page"] == 4 and kwargs["media_type"] == "movie"


def test_the_anime_filters_reach_animeunity(client, signed_in, asked):
    response = client.get(
        "/api/search?q=abc&source=animeunity&page=2&media_type=ova&dubbed=true")

    assert response.status_code == 200
    q, kwargs = asked["au"]
    assert q == "abc"
    assert (kwargs["page"], kwargs["media_type"], kwargs["dubbed"]) == (2, "ova", True)


def test_an_unknown_source_is_refused(client, signed_in, asked):
    """It used to fall through to StreamingCommunity in silence."""
    assert client.get("/api/search?q=abc&source=nowhere").status_code == 422


def test_a_page_past_the_bound_is_refused(client, signed_in, asked):
    assert client.get("/api/search?q=abc&page=0").status_code == 422
    assert client.get("/api/search?q=abc&page=9999").status_code == 422


def test_an_anime_kind_is_refused_for_streamingcommunity(client, signed_in, asked):
    """One pattern cannot express two vocabularies; the source has no OVAs."""
    assert client.get("/api/search?q=abc&media_type=ova").status_code == 422


def test_the_dub_filter_is_refused_for_streamingcommunity(client, signed_in, asked):
    assert client.get("/api/search?q=abc&dubbed=true").status_code == 422


def test_an_unasked_dub_filter_is_not_a_refusal(client, signed_in, asked):
    """False is the default every search sends, not a request for a filter."""
    assert client.get("/api/search?q=abc&dubbed=false").status_code == 200


def test_no_configured_domain_is_still_a_409(client, signed_in, monkeypatch):
    """The 409 has to survive the generic 502 wrapper below it."""
    from app.routers import search as router
    monkeypatch.setattr(router, "configured_domain", lambda: "")

    assert client.get("/api/search?q=abc").status_code == 409
    assert client.get("/api/search?q=abc&source=animeunity").status_code != 409


# ── StreamingCommunity browse ─────────────────────────────────────────────────

def test_browse_archive_sends_the_sources_own_filters(monkeypatch):
    seen = {}

    def fake(domain, path="", *, params=None, timeout=10):
        seen["path"], seen["params"] = path, params
        return {"titles": [_title(1)]}

    monkeypatch.setattr(page, "fetch_site_props", fake)
    out = page.browse("example.test", page=2, media_type="movie", genre=4,
                      year=2020, country=11, sort="views")
    assert seen["path"] == "/archive"
    assert seen["params"] == {"page": 2, "type": "movie", "year": 2020, "sort": "views",
                              "genre[]": 4, "country[]": 11}
    assert [t["id"] for t in out] == [1]


def test_browse_ranked_list_ignores_filters(monkeypatch):
    seen = {}
    monkeypatch.setattr(page, "fetch_site_props",
                        lambda d, path="", *, params=None, timeout=10:
                        seen.update(path=path, params=params) or {"titles": []})
    page.browse("example.test", list_name="trending", genre=4)
    assert seen == {"path": "/browse/trending", "params": {}}
    with pytest.raises(ValueError):
        page.browse("example.test", list_name="nope")


def test_browse_endpoint_routes_animeunity_and_refuses_its_kinds_for_sc(client, signed_in, monkeypatch):
    calls = []
    monkeypatch.setattr(animeunity, "search", lambda *a, **kw: calls.append((a, kw)) or [])
    assert client.get("/api/search/browse?source=animeunity&media_type=ova&genre=3").status_code == 200
    assert calls and calls[0][0] == ("",) and calls[0][1]["genre"] == 3
    assert client.get("/api/search/browse?media_type=ova").status_code == 422
