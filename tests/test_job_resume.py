"""A download in flight survives a restart; its segments are kept for the retry."""

import threading

from app import job_store, jobs
from app.jobs import JobManager


def _terminal_events(jm):
    """job_id -> Event set when that job's terminal listener has run. The listener
    fires after the job's record and folder are settled, unlike the status."""
    events = {}

    def on_finished(job):
        events.setdefault(job.job_id, threading.Event()).set()
    jm.add_listener(on_finished)

    def wait(job_id, timeout=3):
        events.setdefault(job_id, threading.Event()).wait(timeout)
        return jm.get(job_id)
    return wait


def _fake_download(fails_first=False, calls=None):
    """A stand-in with the name of a real app.core function, so a record can name it."""
    calls = [] if calls is None else calls

    def fake(*args, temp_dir, progress_factory, cancel_event, audio_languages=None):
        calls.append((args[0], temp_dir, audio_languages))
        if fails_first and len(calls) == 1:
            raise RuntimeError("503")
        return "/lib/ep.mkv"
    fake.__module__ = "app.core.tv"
    fake.__qualname__ = "download_episode"
    return fake


def _submit(jm, tmp_path, fn, phases=("video",)):
    job = jm._make_job("Serie S01E01", "episode", phases=list(phases), external_id="12")
    jm._submit_job(job, fn, 77, audio_languages=["ita"],
                   temp_dir=str(tmp_path / job.job_id), progress_factory=None,
                   cancel_event=job.cancel_event)
    return job


def test_a_finished_job_leaves_neither_record_nor_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "TMP_DIR", tmp_path)
    jm = JobManager()
    wait = _terminal_events(jm)
    job = _submit(jm, tmp_path, _fake_download())
    (tmp_path / job.job_id).mkdir()
    (tmp_path / job.job_id / "0.ts").write_bytes(b"x")

    assert wait(job.job_id).status == "done"
    assert job_store.load_all() == []
    assert not (tmp_path / job.job_id).exists()


def test_a_running_job_is_recorded_with_what_a_restart_needs(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "TMP_DIR", tmp_path)
    release = threading.Event()

    def blocking(tv_id, *, temp_dir, progress_factory, cancel_event, audio_languages=None):
        release.wait(3)
        return "/lib/ep.mkv"
    blocking.__module__ = "app.core.tv"
    blocking.__qualname__ = "download_episode"

    jm = JobManager()
    wait = _terminal_events(jm)
    job = _submit(jm, tmp_path, blocking)
    try:
        ((saved_id, record),) = job_store.load_all()
        assert saved_id == job.job_id
        assert record["fn"] == "app.core.tv:download_episode"
        assert record["args"] == [77]
        assert record["kwargs"] == {"audio_languages": ["ita"]}
        assert record["job"]["external_id"] == "12"
        assert record["job"]["tmp_id"] is None
    finally:
        release.set()
    wait(job.job_id)


def test_an_interrupted_job_runs_again_with_its_segments_in_place(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "TMP_DIR", tmp_path)
    calls = []
    monkeypatch.setattr("app.core.tv.download_episode", _fake_download(calls=calls))

    # What a crashed process leaves behind: a record and some segments on disk.
    job_id = "11111111-2222-3333-4444-555555555555"
    (tmp_path / job_id).mkdir()
    (tmp_path / job_id / "0.ts").write_bytes(b"segment")
    job_store.save(job_id, {
        "fn": "app.core.tv:download_episode",
        "args": [77, [], 1, "example.test", "tok", "Serie", 1],
        "kwargs": {"audio_languages": ["ita"]},
        "job": {"title": "Serie S01E01", "type": "episode", "phases": ["video"],
                "external_id": "12", "tmp_id": None},
    })

    jm = JobManager()
    wait = _terminal_events(jm)
    assert jm.resume_interrupted() == 1
    assert wait(job_id).status == "done"

    assert calls == [(77, str(tmp_path / job_id), ["ita"])]
    assert (tmp_path / job_id / "0.ts").exists() is False   # cleared once done
    assert job_store.load_all() == []


def test_a_record_naming_a_function_outside_app_core_is_dropped_not_run(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "TMP_DIR", tmp_path)
    job_store.save("22222222-2222-3333-4444-555555555555", {
        "fn": "os:system", "args": ["true"], "kwargs": {},
        "job": {"title": "x", "type": "episode"},
    })
    assert JobManager().resume_interrupted() == 0
    assert job_store.load_all() == []


def test_a_failed_job_keeps_its_segments_for_a_manual_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "TMP_DIR", tmp_path)
    calls = []
    jm = JobManager()
    wait = _terminal_events(jm)
    job = _submit(jm, tmp_path, _fake_download(fails_first=True, calls=calls))
    (tmp_path / job.job_id).mkdir()
    (tmp_path / job.job_id / "0.ts").write_bytes(b"x")

    assert wait(job.job_id).status == "error"
    assert job_store.load_all() == []                  # nothing to resume after a failure
    assert (tmp_path / job.job_id / "0.ts").exists()   # but the segments stay for the retry

    new_id = jm.retry(job.job_id)
    assert wait(new_id).status == "done"
    assert calls[1][1] == str(tmp_path / job.job_id)   # the retry reuses the folder
    assert not (tmp_path / job.job_id).exists()        # and frees it once done


def test_dismissing_a_failed_job_frees_its_segments(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "TMP_DIR", tmp_path)
    jm = JobManager()
    wait = _terminal_events(jm)
    job = _submit(jm, tmp_path, _fake_download(fails_first=True))
    (tmp_path / job.job_id).mkdir()
    assert wait(job.job_id).status == "error"
    assert jm.dismiss(job.job_id)
    assert not (tmp_path / job.job_id).exists()
