"""Jobs beyond max_concurrent_downloads queue instead of failing or blocking.

ThreadPoolExecutor(64) accepts every submission, and _run_download waits on
DownloadSlots before flipping a job to "running". The slots grant in arrival
order, which is what lets the downloads page number the waiting line (#26).
"""

import threading
import time

from app.jobs import JobManager


def test_jobs_beyond_the_limit_wait_instead_of_erroring():
    jm = JobManager()
    jm.update_max_concurrent(2)

    lock = threading.Lock()
    concurrent = 0
    peak = 0
    release = threading.Event()

    def fake_download(*args, **kwargs):
        nonlocal concurrent, peak
        with lock:
            concurrent += 1
            peak = max(peak, concurrent)
        release.wait(timeout=2)
        with lock:
            concurrent -= 1
        return "ok"

    try:
        jobs = [jm._make_job(f"t{i}", "film") for i in range(6)]
        for job in jobs:
            jm._submit_job(job, fake_download)

        time.sleep(0.2)  # let the first wave hit the semaphore
        assert 1 <= peak <= 2, "more jobs ran at once than max_concurrent_downloads allowed"

        release.set()
        deadline = time.time() + 3
        while time.time() < deadline and any(j.status not in ("done", "error") for j in jobs):
            time.sleep(0.02)

        assert all(j.status == "done" for j in jobs), "a queued job never got its turn"
    finally:
        jm._executor.shutdown(wait=False)


def _wait_for(predicate, timeout=3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_waiting_jobs_start_in_the_order_they_queued():
    jm = JobManager()
    jm.update_max_concurrent(1)
    started, gate = [], threading.Event()

    def fake_download(name, **kwargs):
        started.append(name)
        gate.wait(timeout=2)
        return "ok"

    try:
        jobs = [jm._make_job(f"t{i}", "film") for i in range(6)]
        for i, job in enumerate(jobs):
            jm._submit_job(job, fake_download, f"t{i}")
            # One at a time into the line, so arrival order is unambiguous.
            assert _wait_for(lambda: job.status == "running" or job.queue_seq is not None)
        gate.set()
        assert _wait_for(lambda: all(j.status == "done" for j in jobs))
        assert started == [f"t{i}" for i in range(6)]
        assert all(j.queue_seq is None for j in jobs)
    finally:
        jm._executor.shutdown(wait=False)


def test_raising_the_limit_lets_jobs_already_waiting_start():
    """The limit used to be a semaphore that was replaced: jobs already waiting
    stayed under the old one, and new ones ran beside them under the new."""
    jm = JobManager()
    jm.update_max_concurrent(1)
    gate = threading.Event()

    def fake_download(*args, **kwargs):
        gate.wait(timeout=2)
        return "ok"

    try:
        jobs = [jm._make_job(f"t{i}", "film") for i in range(4)]
        for job in jobs:
            jm._submit_job(job, fake_download)
        assert _wait_for(lambda: sum(j.status == "running" for j in jobs) == 1)

        jm.update_max_concurrent(3)
        assert _wait_for(lambda: sum(j.status == "running" for j in jobs) == 3)
        time.sleep(0.1)
        assert sum(j.status == "running" for j in jobs) == 3
    finally:
        gate.set()
        jm._executor.shutdown(wait=False)


def test_a_job_cancelled_while_waiting_leaves_the_line_at_once():
    jm = JobManager()
    jm.update_max_concurrent(1)
    gate = threading.Event()
    calls = []

    def fake_download(name, **kwargs):
        calls.append(name)
        gate.wait(timeout=2)
        return "ok"

    try:
        first, waiting = jm._make_job("a", "film"), jm._make_job("b", "film")
        jm._submit_job(first, fake_download, "a")
        assert _wait_for(lambda: first.status == "running")
        jm._submit_job(waiting, fake_download, "b")
        assert _wait_for(lambda: waiting.queue_seq is not None)

        jm.cancel(waiting.job_id)
        # Gone from the line while the first download still holds the slot.
        assert _wait_for(lambda: waiting.queue_seq is None)
        assert waiting.status == "cancelled"
        gate.set()
        assert _wait_for(lambda: first.status == "done")
        assert calls == ["a"]
    finally:
        gate.set()
        jm._executor.shutdown(wait=False)


def test_higher_priority_jumps_the_line_and_paused_is_skipped():
    jm = JobManager()
    jm.update_max_concurrent(1)
    order, gate = [], threading.Event()

    def blocker(*a, **k):
        gate.wait(timeout=3)

    def record(name):
        return lambda *a, **k: order.append(name)

    try:
        first = jm._make_job("first", "film")
        jm._submit_job(first, blocker)
        assert _wait_for(lambda: first.status == "running")
        low, high, held = (jm._make_job(n, "film") for n in ("low", "high", "held"))
        for j in (low, held, high):
            jm._submit_job(j, record(j.title))
            time.sleep(0.05)
        jm.set_priority(high.job_id, 10)
        jm.set_paused(held.job_id, True)
        gate.set()
        assert _wait_for(lambda: order == ["high", "low"])
        assert held.status == "queued"
        jm.set_paused(held.job_id, False)
        assert _wait_for(lambda: order == ["high", "low", "held"])
    finally:
        gate.set()
        jm._executor.shutdown(wait=False)


def test_pausing_a_running_download_hands_its_slot_to_the_next():
    jm = JobManager()
    jm.update_max_concurrent(1)
    ran, finish = [], threading.Event()

    class Bar:  # what WebProgressBar offers the download loop
        closed = False
        def __init__(self, job):
            self.pause_event, self.on_pause = job.pause_event, lambda: jm._hold(job)
        @property
        def paused(self):
            return self.pause_event.is_set()
        def update(self):
            if self.paused:
                self.on_pause()

    first, second = jm._make_job("first", "film"), jm._make_job("second", "film")

    def first_download(*a, **k):
        first.bar = bar = Bar(first)
        while not finish.is_set():
            bar.update()
            time.sleep(0.02)
        ran.append("first")

    try:
        jm._submit_job(first, first_download)
        assert _wait_for(lambda: first.status == "running" and first.bar)
        jm._submit_job(second, lambda *a, **k: ran.append("second"))
        time.sleep(0.1)
        assert second.status == "queued"
        assert jm.set_paused(first.job_id, True)
        assert _wait_for(lambda: ran == ["second"]), "the paused download kept its slot"
        jm.set_paused(first.job_id, False)
        assert _wait_for(lambda: first.status == "running")
        finish.set()
        assert _wait_for(lambda: ran == ["second", "first"] and first.status == "done")
    finally:
        finish.set()
        jm._executor.shutdown(wait=False)


def test_a_running_job_outside_the_download_phase_cannot_be_paused():
    jm = JobManager()
    gate = threading.Event()
    job = jm._make_job("joining", "film")
    try:
        jm._submit_job(job, lambda *a, **k: gate.wait(2))
        assert _wait_for(lambda: job.status == "running")
        assert not jm.set_paused(job.job_id, True)
    finally:
        gate.set()
        jm._executor.shutdown(wait=False)


def test_waiting_for_a_slot_after_a_resume_is_not_a_stall():
    from app.progress import WebProgressBar
    bar = WebProgressBar(10, None, None)
    bar.pause_event = threading.Event()
    assert not bar.paused
    bar.yielded = lambda: True  # resumed, still waiting for its slot
    assert bar.paused


def test_the_pool_covers_a_full_batch():
    from app.routers.downloads import MAX_BATCH_JOBS
    jm = JobManager()
    try:
        assert jm._executor._max_workers >= MAX_BATCH_JOBS
    finally:
        jm._executor.shutdown(wait=False)
