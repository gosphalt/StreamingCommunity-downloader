"""A retried download runs against the domain configured now, not the dead one."""

from app import config
from app.core import tv
from app.core.film import download_film
from app.core.tv import download_episode
from app.jobs import JobManager


def test_a_film_retry_moves_to_the_current_domain():
    config.update_data({"domain": "new.example"})
    args = (7, "Film", "old.example")

    assert JobManager._on_current_domain(download_film, args) == (7, "Film", "new.example")


def test_an_episode_retry_gets_a_token_from_the_new_domain(monkeypatch):
    config.update_data({"domain": "new.example"})
    monkeypatch.setattr(tv, "get_token", lambda tv_id, domain: f"tok-{tv_id}-{domain}")
    args = (5, [{"id": 1}], 0, "old.example", "stale", "Show", 2)

    assert JobManager._on_current_domain(download_episode, args) == (
        5, [{"id": 1}], 0, "new.example", "tok-5-new.example", "Show", 2)


def test_nothing_changes_when_the_domain_is_the_same():
    config.update_data({"domain": "same.example"})
    args = (7, "Film", "same.example")

    assert JobManager._on_current_domain(download_film, args) is args
