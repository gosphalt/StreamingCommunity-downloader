"""A retried download runs against the domain configured now, not the dead one."""

import os

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


def _flaky_once(seen, error):
    def fn(domain, *, temp_dir, progress_factory, cancel_event):
        seen.append(domain)
        if len(seen) == 1:
            raise error
        return "/lib/film.mkv"
    return fn


def test_an_automatic_retry_moves_to_the_current_domain(monkeypatch):
    from app import jobs
    monkeypatch.setattr(jobs, "AUTO_RETRIES", 1)
    monkeypatch.setattr(jobs, "AUTO_RETRY_DELAY", 0)
    monkeypatch.setattr(JobManager, "_on_current_domain",
                        staticmethod(lambda fn, args: ("new.example",)))
    seen = []
    jm = JobManager()
    try:
        job = jm._make_job("Film", "film")
        jm._run_download(job, _flaky_once(seen, RuntimeError("Failed to resolve")), "old.example",
                         temp_dir="tmp/x", progress_factory=None, cancel_event=job.cancel_event)
        assert seen == ["old.example", "new.example"]
        assert job.status == "done"
    finally:
        jm._executor.shutdown(wait=False)


def test_an_unreachable_new_domain_keeps_the_stored_arguments(monkeypatch):
    from app import jobs
    monkeypatch.setattr(jobs, "AUTO_RETRIES", 1)
    monkeypatch.setattr(jobs, "AUTO_RETRY_DELAY", 0)

    def cannot_reach(fn, args):
        raise RuntimeError("«new.example» non risponde")
    monkeypatch.setattr(JobManager, "_on_current_domain", staticmethod(cannot_reach))
    seen = []
    jm = JobManager()
    try:
        job = jm._make_job("Film", "film")
        jm._run_download(job, _flaky_once(seen, RuntimeError("Failed to resolve")), "old.example",
                         temp_dir="tmp/x", progress_factory=None, cancel_event=job.cancel_event)
        assert seen == ["old.example", "old.example"]
        assert job.status == "done"
    finally:
        jm._executor.shutdown(wait=False)


def test_a_retry_on_a_new_domain_starts_from_scratch(monkeypatch, tmp_path):
    from app import jobs
    monkeypatch.setattr(jobs, "AUTO_RETRIES", 1)
    monkeypatch.setattr(jobs, "AUTO_RETRY_DELAY", 0)
    monkeypatch.setattr(JobManager, "_on_current_domain",
                        staticmethod(lambda fn, args: ("new.example",)))
    jm = JobManager()
    try:
        job = jm._make_job("Film", "film")
        stale = jobs._tmp_dir(job)
        os.makedirs(stale, exist_ok=True)
        open(os.path.join(stale, "old-segment.ts"), "w").close()
        seen = []
        jm._run_download(job, _flaky_once(seen, RuntimeError("Failed to resolve")), "old.example",
                         temp_dir="tmp/x", progress_factory=None, cancel_event=job.cancel_event)
        assert not os.path.exists(stale)
        assert job.status == "done"
    finally:
        jm._executor.shutdown(wait=False)
