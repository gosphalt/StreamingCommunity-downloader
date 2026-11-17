"""An AnimeUnity episode list says which episodes are already in the library,
as a StreamingCommunity season does."""
import asyncio
import os

import pytest

from app.core import paths
from app.core import animeunity
from app.requests import resolver
from app.routers import anime as anime_router
from app.routers.tv import _mark_in_library


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(resolver, "library_dir", lambda media_type: str(tmp_path))
    return tmp_path


def _write(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(b"x")


def test_an_anime_episode_on_disk_is_flagged_in_the_anime_folder(library):
    _write(paths.episode_path(str(library), "Serie", 1, "2", "2020"))
    rows = [{"n": "1"}, {"n": "2"}]
    _mark_in_library(rows, "Serie", 1, "2020", "anime-1", "anime")
    assert [r["in_library"] for r in rows] == [False, True]


def test_the_route_answers_each_episode_with_its_mark(library, monkeypatch):
    _write(paths.episode_path(str(library), "Serie", 1, "3", "2020"))
    monkeypatch.setattr(animeunity, "get_episodes", lambda anime_id: [
        {"id": 10, "number": 1}, {"id": 11, "number": 3}])
    out = asyncio.run(anime_router.get_episodes("77", title="Serie", year="2020"))
    assert [(e["number"], e["in_library"]) for e in out] == [(1, False), (3, True)]


def test_without_a_title_the_route_marks_nothing(library, monkeypatch):
    monkeypatch.setattr(animeunity, "get_episodes", lambda anime_id: [{"id": 10, "number": 1}])
    out = asyncio.run(anime_router.get_episodes("77", title="", year=""))
    assert "in_library" not in out[0]
