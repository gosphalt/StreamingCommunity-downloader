"""AnimeUnity downloads go to the series library or the film library, as chosen."""
import pytest

from app import config, jobs
from app.routers import downloads


@pytest.fixture
def signed_in(client, admin_credentials):
    from app.auth.permissions import ALL_PERMISSIONS
    from tests.conftest import do_setup, make_user, session_for
    do_setup(client, admin_credentials)
    user = make_user("boss", "jf-boss-id", int(ALL_PERMISSIONS))
    client.cookies.clear()
    return session_for(client, user.id)


@pytest.fixture
def captured(monkeypatch):
    seen = {}

    def fake_submit(*args, **kwargs):
        seen.update(kwargs)
        return "job-1"

    monkeypatch.setattr(downloads.job_manager, "submit_anime_episode", fake_submit)
    return seen


def test_the_library_defaults_to_the_series_library(client, signed_in, captured):
    r = client.post("/api/download/anime", headers={"X-CSRF-Token": signed_in}, json={
        "anime_id": "12-one-piece", "anime_name": "One Piece", "episode": {"number": 1, "id": 1}})
    assert r.status_code == 202
    assert captured["library"] == "anime"


def test_a_film_goes_to_the_film_library(client, signed_in, captured):
    r = client.post("/api/download/anime", headers={"X-CSRF-Token": signed_in}, json={
        "anime_id": "1", "anime_name": "Sailor Moon", "anime_type": "Movie",
        "episode": {"number": 1, "id": 1}, "library": "film"})
    assert r.status_code == 202
    assert captured["library"] == "film"


def test_an_unknown_library_is_refused(client, signed_in, captured):
    r = client.post("/api/download/anime", headers={"X-CSRF-Token": signed_in}, json={
        "anime_id": "1", "anime_name": "x", "episode": {"number": 1, "id": 1}, "library": "eng"})
    assert r.status_code == 422
    assert captured == {}


def test_the_choice_picks_the_library_folder(monkeypatch, tmp_path):
    films, series = str(tmp_path / "film"), str(tmp_path / "anime")
    monkeypatch.setattr(config, "read_data", lambda: {"libraries": [
        {"type": "film", "path": films}, {"type": "anime", "path": series}]})
    assert jobs._get_library_path("film") == films
    assert jobs._get_library_path("anime") == series
