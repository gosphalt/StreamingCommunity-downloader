"""A finished job gives up its call (its arguments); a failed one keeps it for a retry."""

from datetime import datetime, timezone

from app.jobs import DownloadJob, JobManager


def _job(status):
    job = DownloadJob(job_id=f"j-{status}", title="t", type="film", status=status,
                      created_at=datetime.now(timezone.utc))
    job.call = (lambda: None, (), {})
    return job


def test_a_done_job_drops_its_call_and_persisting_it_is_harmless():
    mgr = JobManager()
    job = _job("done")
    mgr._finish(job)
    assert job.call is None
    mgr._persist(job)  # no call left to save: must not raise


def test_a_failed_job_keeps_its_call_for_a_retry():
    mgr = JobManager()
    job = _job("error")
    mgr._finish(job)
    assert job.call is not None
