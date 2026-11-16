"""A download records how long it ran, not how long it waited in the queue."""

import time
from datetime import datetime, timezone

from app.jobs import DownloadJob, JobManager


def _job(status):
    return DownloadJob(job_id=f"r-{status}", title="t", type="film", status=status,
                       created_at=datetime.now(timezone.utc))


def test_a_finished_download_records_its_run_time_in_the_api():
    mgr = JobManager()
    job = _job("done")
    job.run_started = time.monotonic() - 5
    mgr._finish(job)
    assert 4 < job.run_seconds < 60
    assert mgr._job_to_dict(job)["run_seconds"] == job.run_seconds


def test_a_job_cancelled_before_it_ran_has_no_run_time():
    mgr = JobManager()
    job = _job("cancelled")
    mgr._finish(job)
    assert job.run_seconds is None


def test_a_running_job_reports_the_time_so_far_and_a_queued_one_none():
    mgr = JobManager()
    job = _job("running")
    job.run_started = time.monotonic() - 3
    assert 2 < mgr._job_to_dict(job)["run_seconds"] < 60
    assert mgr._job_to_dict(_job("queued"))["run_seconds"] is None
