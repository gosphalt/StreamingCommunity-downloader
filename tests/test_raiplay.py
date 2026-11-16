"""RaiPlay: catalogue, programme and season reading, the download, and the routes.

The JSON shapes are the ones RaiPlay serves (checked against the live site when
this was written); the network is replaced, so the suite stays offline.
"""
import os

import pytest

from app.core import raiplay, youtube

VIDEO = "/video/2016/06/winx-club-s1e1-una-fata-a-gardenia-494b95ca-d750-405e-9cce-fb4badcc1cc2.json"
SET = "/programmi/winxclub/ContentSet-cc515719-3ae4-4dce-ab84-1f25990d998b.json"


def _catalogue_row(name, pid, tipology="Programmi Tv", year="2004"):
    return {"name": name, "PathID": pid, "tipology": tipology, "PLRanno": year}


@pytest.fixture
def signed_in(client, admin_credentials):
    from app.auth.permissions import ALL_PERMISSIONS
    from tests.conftest import do_setup, make_user, session_for
    do_setup(client, admin_credentials)
    user = make_user("boss", "jf-boss-id", int(ALL_PERMISSIONS))
    client.cookies.clear()
    return session_for(client, user.id)


@pytest.fixture
def web(monkeypatch):
    """Serve canned JSON by path. Any unknown path fails the test."""
    state = {"json": {}, "calls": []}

    def fake_get(path):
        state["calls"].append(path)
        if path not in state["json"]:
            raise AssertionError(f"unexpected request {path}")
        return state["json"][path]

    monkeypatch.setattr(raiplay, "_get_json", fake_get)
    monkeypatch.setattr(raiplay, "_catalogue", {"at": 0.0, "items": []})
    return state


def test_the_catalogue_id_becomes_the_programme_path():
    assert raiplay._slug_path("http://www.rai.it/raiplay/programmi/winxclub/?json") == \
        "/programmi/winxclub.json"
    assert raiplay._slug_path("http://www.rai.it/raiplay/programmi/a b/?json") is None
    assert raiplay._slug_path("") is None


def test_search_matches_names_case_insensitively_and_tags_films(web):
    web["json"][raiplay.CATALOGUE] = {"W": [
        _catalogue_row("Winx Club", "http://www.rai.it/raiplay/programmi/winxclub/?json"),
        _catalogue_row("Volare", "http://www.rai.it/raiplay/programmi/volare/?json",
                       tipology="Film", year="2023"),
        _catalogue_row("", "http://www.rai.it/raiplay/programmi/vuoto/?json"),
    ]}

    hits = raiplay.search("WINX")
    assert [h["name"] for h in hits] == ["Winx Club"]
    assert hits[0]["path"] == "/programmi/winxclub.json"
    assert hits[0]["media_type"] == "tv"
    assert raiplay.search("volare")[0]["media_type"] == "film"


def test_the_catalogue_is_cached_between_searches(web):
    web["json"][raiplay.CATALOGUE] = {"W": [_catalogue_row(
        "Winx Club", "http://www.rai.it/raiplay/programmi/winxclub/?json")]}
    raiplay.search("winx")
    raiplay.search("club")
    assert web["calls"].count(raiplay.CATALOGUE) == 1


def test_an_empty_query_searches_nothing(web):
    assert raiplay.search("   ") == []
    assert web["calls"] == []


def test_a_programme_path_is_checked_before_any_request(web):
    with pytest.raises(raiplay.RaiPlayError):
        raiplay.program("/programmi/../../etc.json")
    with pytest.raises(raiplay.RaiPlayError):
        raiplay.program("https://evil.test/programmi/x.json")
    assert web["calls"] == []


def test_a_series_lists_its_season_sets(web):
    web["json"]["/programmi/winxclub.json"] = {
        "program_info": {"name": "Winx Club", "year": "2004", "typology": "Kids"},
        "layout": "multi",
        "blocks": [{"sets": [{"name": "Stagione 1", "path_id": SET}]}],
    }
    info = raiplay.program("/programmi/winxclub.json")
    assert info["media_type"] == "tv"
    assert info["seasons"] == [{"path": SET, "name": "Stagione 1"}]
    assert info["video"] is None


def test_a_film_carries_its_video(web):
    web["json"]["/programmi/volare.json"] = {
        "program_info": {"name": "Volare", "year": "2023", "typology": "Film"},
        "layout": "single",
        "blocks": [],
        "first_item_path": VIDEO,
    }
    info = raiplay.program("/programmi/volare.json")
    assert info["media_type"] == "film"
    assert info["video"] == VIDEO


def test_a_season_keeps_only_playable_video_paths(web):
    web["json"][SET] = {"items": [
        {"path_id": VIDEO, "season": "1", "episode": "1",
         "episode_title": "Una fata a Gardenia", "duration_in_minutes": "22 min"},
        {"path_id": "/video/../../secret.json", "season": "1", "episode": "2"},
    ]}
    episodes = raiplay.season(SET)
    assert [e["video"] for e in episodes] == [VIDEO]
    assert episodes[0]["episode"] == "1" and episodes[0]["title"] == "Una fata a Gardenia"


def test_a_season_path_must_name_a_content_set(web):
    with pytest.raises(raiplay.RaiPlayError):
        raiplay.season("/programmi/winxclub.json")


def test_drm_is_refused_before_the_download_starts(web):
    web["json"][VIDEO] = {"rights_management": {"rights": {"drm": {"widevine": True}}}}
    with pytest.raises(raiplay.RaiPlayError, match="DRM"):
        raiplay._check_playable(VIDEO)


def test_a_video_path_outside_the_catalogue_is_refused(web):
    with pytest.raises(raiplay.RaiPlayError):
        raiplay._check_playable("/video/../x.json")
    assert web["calls"] == []


@pytest.fixture
def fetch(monkeypatch, web):
    """Stand in for yt-dlp: write the file it would leave and remember the URL."""
    seen = {}

    def fake_fetch_media(url, temp_dir, key, progress_factory=None, cancel_event=None):
        seen["url"] = url
        os.makedirs(temp_dir, exist_ok=True)
        path = os.path.join(temp_dir, f"{key}.mkv")
        with open(path, "wb") as f:
            f.write(b"video")
        return path

    web["json"][VIDEO] = {"rights_management": {"rights": {"drm": {}}}}
    monkeypatch.setattr(youtube, "fetch_media", fake_fetch_media)
    return seen


def test_an_episode_lands_in_the_series_folder(tmp_path, fetch):
    final = raiplay.download_raiplay(VIDEO, "Una fata a Gardenia", "episode",
                                     str(tmp_path / "lib"), str(tmp_path / "tmp"),
                                     year="2004", series="Winx Club", season="1",
                                     episode="1")
    assert final.endswith(os.path.join("Winx Club (2004)", "Season 01",
                                       "Winx Club S01E01.mkv"))
    assert os.path.exists(final)
    assert fetch["url"] == ("https://www.raiplay.it/video/2016/06/"
                            "winx-club-s1e1-una-fata-a-gardenia-494b95ca-d750-405e-9cce-fb4badcc1cc2.html")


def test_a_film_lands_in_its_own_folder(tmp_path, fetch):
    final = raiplay.download_raiplay(VIDEO, "Volare", "film", str(tmp_path / "lib"),
                                     str(tmp_path / "tmp"), year="2023")
    assert final.endswith(os.path.join("Volare (2023)", "Volare (2023).mkv"))
    assert os.path.exists(final)


def test_a_refused_video_never_reaches_yt_dlp(tmp_path, fetch, web):
    web["json"][VIDEO] = {"rights_management": {"rights": {"drm": {"x": 1}}}}
    with pytest.raises(raiplay.RaiPlayError):
        raiplay.download_raiplay(VIDEO, "x", "film", str(tmp_path / "lib"),
                                 str(tmp_path / "tmp"), year="2023")
    assert "url" not in fetch


# ── routes ───────────────────────────────────────────────────────────────────

def test_the_download_route_refuses_a_path_it_did_not_validate(client, signed_in):
    r = client.post("/api/download/raiplay", headers={"X-CSRF-Token": signed_in}, json={
        "kind": "film", "video": "https://evil.test/x.json", "title": "x"})
    assert r.status_code == 400


def test_an_episode_needs_its_series_season_and_number(client, signed_in):
    r = client.post("/api/download/raiplay", headers={"X-CSRF-Token": signed_in}, json={
        "kind": "episode", "video": VIDEO, "title": "x", "series": "Winx Club"})
    assert r.status_code == 400


def test_a_valid_request_is_queued_as_a_job(client, signed_in, monkeypatch):
    from app.routers import downloads
    seen = {}

    def fake_submit(video, title, kind, **kwargs):
        seen.update(video=video, kind=kind, **kwargs)
        return "job-1"

    monkeypatch.setattr(downloads.job_manager, "submit_raiplay", fake_submit)
    r = client.post("/api/download/raiplay", headers={"X-CSRF-Token": signed_in}, json={
        "kind": "episode", "video": VIDEO, "title": "Una fata", "series": "Winx Club",
        "season": "1", "episode": "1", "year": "2004"})
    assert r.status_code == 202
    assert r.json() == {"job_id": "job-1", "status": "queued"}
    assert seen["video"] == VIDEO and seen["series"] == "Winx Club"


def test_the_search_route_answers_from_the_catalogue(client, signed_in, monkeypatch):
    monkeypatch.setattr(raiplay, "search", lambda q, limit=40: [{"path": "/programmi/x.json",
                                                                 "name": "X"}])
    r = client.get("/api/raiplay/search", params={"q": "x"})
    assert r.status_code == 200
    assert r.json() == [{"path": "/programmi/x.json", "name": "X"}]


def test_a_season_named_by_its_year_is_accepted(client, signed_in, monkeypatch):
    # RaiPlay numbers some dated programmes by year: "2019" is a valid season.
    from app.routers import downloads
    monkeypatch.setattr(downloads.job_manager, "submit_raiplay", lambda *a, **k: "job-2")
    r = client.post("/api/download/raiplay", headers={"X-CSRF-Token": signed_in}, json={
        "kind": "episode", "video": VIDEO, "title": "Puntata", "series": "Volare",
        "season": "2019", "episode": "1"})
    assert r.status_code == 202
