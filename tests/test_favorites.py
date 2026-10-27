"""Favorites: a per-user bookmark, the panel's own without accounts."""

from tests.conftest import enable_open_mode

BODY = {
    "source": "streamingcommunity", "kind": "tv", "external_id": "77",
    "title": "Test Series", "slug": "test-series", "year": "2019",
}


def test_a_title_can_be_starred_listed_and_removed(client):
    enable_open_mode()

    assert client.post("/api/favorites", json=BODY).status_code == 201
    listed = client.get("/api/favorites").json()["favorites"]
    assert [f["title"] for f in listed] == ["Test Series"]

    assert client.delete("/api/favorites/streamingcommunity/tv/77").status_code == 200
    assert client.get("/api/favorites").json()["favorites"] == []


def test_starring_twice_keeps_one_row_without_accounts(client):
    enable_open_mode()

    client.post("/api/favorites", json=BODY)
    client.post("/api/favorites", json=BODY)

    assert len(client.get("/api/favorites").json()["favorites"]) == 1


def test_a_film_and_a_series_with_the_same_id_are_different_favorites(client):
    enable_open_mode()

    client.post("/api/favorites", json=BODY)
    client.post("/api/favorites", json={**BODY, "kind": "movie"})

    assert len(client.get("/api/favorites").json()["favorites"]) == 2
