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
        granted=False, slot_counted=False, on_grant=None,
    )


def _wait_until(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.01)
    return cond()


def test_enqueue_gives_a_ticket_before_any_thread_runs():
    slots = DownloadSlots(1)
    slots._busy = slots._limit      # the slot is taken: both wait in the line
    seen = []
    a, b = _job("a"), _job("b")
    slots.enqueue(a, on_queued=seen.append)
    slots.enqueue(b, on_queued=seen.append)
    assert a.queue_seq < b.queue_seq
    assert seen == [a, b]


def test_a_granted_job_starts_its_thread_only_when_granted():
    """A job waiting for a slot holds no thread: its thread is started by the grant."""
    slots = DownloadSlots(1)
    started = []
    a, b = _job("a"), _job("b")
    slots.enqueue(a, on_grant=lambda: started.append("a"))
    slots.enqueue(b, on_grant=lambda: started.append("b"))
    assert started == ["a"]          # a got the only slot; b waits with no thread
    assert b.queue_seq is not None
    slots.release()                  # a's download ends
    assert started == ["a", "b"]     # b's thread starts now, not before
    assert slots.acquire(b) is True  # and its thread takes the grant it was given


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


def test_a_priority_job_without_a_thread_gets_the_next_slot():
    """The reported case: the next job by priority, submitted behind a long batch,
    must start next even though no thread exists for it yet."""
    slots = DownloadSlots(1)
    started = []
    batch = [_job(f"b{i}") for i in range(5)]
    for j in batch:
        slots.enqueue(j, on_grant=lambda j=j: started.append(j.name))
    urgent = _job("whiplash")
    slots.enqueue(urgent, on_grant=lambda: started.append("whiplash"))
    urgent.priority = 10
    slots.wake()
    slots.release()                 # the running download ends
    assert started == ["b0", "whiplash"]


def test_a_job_cancelled_while_queued_leaves_without_taking_a_slot():
    slots = DownloadSlots(1)
    started = []
    a, b = _job("a"), _job("b")
    slots.enqueue(a, on_grant=lambda: started.append("a"))
    slots.enqueue(b, on_grant=lambda: started.append("b"))
    b.cancel_event.set()
    slots.wake()
    assert "b" in started           # it is let go at once...
    assert slots.acquire(b) is False  # ...and its thread finds it cancelled
    assert slots._busy == 1         # without taking the slot a still holds
