"""A job gets its place in the line when it is submitted, not when its thread starts.

With more jobs than threads, the ones without a thread must still have a ticket
(so the page can number them), and must not hold the line: only a job with a
thread waiting can take a slot.
"""

import threading
import time
from types import SimpleNamespace

from app.jobs import DownloadSlots


def _job(name):
    return SimpleNamespace(
        name=name, queue_seq=None, priority=0,
        pause_event=threading.Event(), cancel_event=threading.Event(),
    )


def _wait_until(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.01)
    return cond()


def test_enqueue_gives_a_ticket_before_any_thread_runs():
    slots = DownloadSlots(1)
    seen = []
    a, b = _job("a"), _job("b")
    slots.enqueue(a, on_queued=seen.append)
    slots.enqueue(b, on_queued=seen.append)
    assert a.queue_seq < b.queue_seq
    assert seen == [a, b]


def test_a_job_without_a_thread_does_not_hold_the_line():
    slots = DownloadSlots(1)
    a, b = _job("a"), _job("b")
    slots.enqueue(a)          # no thread will ever wait for a in this test
    slots.enqueue(b)
    got = []
    t = threading.Thread(target=lambda: got.append(slots.acquire(b)))
    t.start()
    t.join(timeout=2)
    assert got == [True]
    assert b.queue_seq is None      # it left the line once it held a slot
    assert a.queue_seq is not None  # a keeps its place, still waiting


def test_threaded_jobs_take_slots_in_ticket_order():
    slots = DownloadSlots(1)
    a, b = _job("a"), _job("b")
    slots.enqueue(a)
    slots.enqueue(b)
    got = []
    ta = threading.Thread(target=lambda: got.append(a.name) if slots.acquire(a) else None)
    tb = threading.Thread(target=lambda: got.append(b.name) if slots.acquire(b) else None)
    ta.start()
    assert _wait_until(lambda: got == ["a"])   # a is first in line and takes the only slot
    tb.start()
    assert _wait_until(lambda: id(b) in slots._waiters)
    time.sleep(0.05)
    assert got == ["a"]           # b has a thread but no slot: it waits
    slots.release()
    assert _wait_until(lambda: got == ["a", "b"])
