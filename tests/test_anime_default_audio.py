"""The audio an AnimeUnity download starts on, chosen once in Settings."""
import pytest

from app import config


@pytest.fixture
def signed_in(client, admin_credentials):
    from app.auth.permissions import ALL_PERMISSIONS
    from tests.conftest import do_setup, make_user, session_for
    do_setup(client, admin_credentials)
    user = make_user("boss", "jf-boss-id", int(ALL_PERMISSIONS))
    client.cookies.clear()
    return session_for(client, user.id)


def _stored(monkeypatch, value):
    monkeypatch.setattr(config, "get_settings", lambda: {"anime_default_audio": value})


def test_italian_is_the_default_and_unknown_values_fall_back(monkeypatch):
    _stored(monkeypatch, "jpn")
    assert config.anime_default_audio() == "jpn"
    _stored(monkeypatch, "eng")
    assert config.anime_default_audio() == "ita"


def test_an_anime_request_without_audio_takes_the_setting(monkeypatch):
    from app.routers.downloads import AnimeAllDownloadRequest, AnimeDownloadRequest
    _stored(monkeypatch, "jpn")
    body = AnimeAllDownloadRequest(anime_id="12", anime_name="One Piece")
    assert body.audio_languages == ["jpn"]
    single = AnimeDownloadRequest(anime_id="12", anime_name="One Piece",
                                  episode={"number": 1, "id": 1})
    assert single.audio_languages == ["jpn"]


def test_the_setting_is_saved_and_limited_to_its_two_choices(client, signed_in):
    headers = {"X-CSRF-Token": signed_in}
    assert client.put("/api/domain/settings", headers=headers,
                      json={"anime_default_audio": "jpn"}).status_code == 200
    assert config.get_settings()["anime_default_audio"] == "jpn"
    assert client.put("/api/domain/settings", headers=headers,
                      json={"anime_default_audio": "eng"}).status_code == 422


def test_the_title_page_reads_it_from_the_anime_route(client, signed_in, monkeypatch):
    _stored(monkeypatch, "jpn")
    r = client.get("/api/anime/default-audio")
    assert r.status_code == 200
    assert r.json() == {"audio": "jpn"}
