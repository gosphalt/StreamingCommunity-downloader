"""Moving a job that waits for a slot: to the top, up, down or the bottom.

The line is ordered by (priority, ticket). A move reassigns tickets, so the
order the scheduler uses and the order the page numbers must both follow it.
"""

import threading
from types import SimpleNamespace

import pytest

from app.jobs import DownloadSlots


def _job(name, seq, priority=0):
    return SimpleNamespace(
        name=name, queue_seq=seq, priority=priority,
        pause_event=threading.Event(), cancel_event=threading.Event(),
    )


def _line(*jobs):
    slots = DownloadSlots(1)
    slots._line.extend(jobs)
    return slots


def _names(slots):
    return [j.name for j in sorted(slots._line, key=DownloadSlots._order_key, reverse=True)]


def test_top_and_bottom_put_a_job_at_the_edge():
    a, b, c = _job("a", 1), _job("b", 2), _job("c", 3)
    slots = _line(a, b, c)
    slots.move(b, "top")
    assert _names(slots) == ["b", "a", "c"]
    slots.move(b, "bottom")
    assert _names(slots) == ["a", "c", "b"]


def test_up_and_down_swap_with_the_neighbour():
    a, b, c = _job("a", 1), _job("b", 2), _job("c", 3)
    slots = _line(a, b, c)
    assert slots.move(c, "up") == [c, b]
    assert _names(slots) == ["a", "c", "b"]
    slots.move(a, "down")
    assert _names(slots) == ["c", "a", "b"]


def test_tickets_stay_unique_after_a_move():
    jobs = [_job(str(i), i + 1) for i in range(4)]
    slots = _line(*jobs)
    slots.move(jobs[0], "bottom")
    slots.move(jobs[3], "top")
    assert sorted(j.queue_seq for j in jobs) == [1, 2, 3, 4]


def test_a_job_already_at_the_edge_is_a_no_op():
    a, b = _job("a", 1), _job("b", 2)
    slots = _line(a, b)
    assert slots.move(a, "top") == [] and slots.move(a, "up") == []
    assert slots.move(b, "bottom") == [] and slots.move(b, "down") == []
    assert _names(slots) == ["a", "b"]


def test_a_job_outside_the_line_cannot_move():
    slots = _line(_job("a", 1))
    assert slots.move(_job("ghost", 9), "top") == []


def test_crossing_a_priority_boundary_takes_the_neighbours_priority():
    high, low = _job("high", 1, priority=10), _job("low", 2, priority=-10)
    slots = _line(high, low)
    # Moving the low job up puts it ahead of the high one, so it takes "high".
    slots.move(low, "up")
    assert low.priority == 10
    assert _names(slots) == ["low", "high"]


def test_the_scheduler_grants_the_next_slot_in_the_new_order():
    a, b = _job("a", 1), _job("b", 2)
    slots = _line(a, b)
    slots.move(b, "top")
    assert slots._next() is b


@pytest.mark.parametrize("where", ["top", "up", "down", "bottom"])
def test_moving_every_way_keeps_all_jobs_in_the_line(where):
    jobs = [_job(str(i), i + 1) for i in range(3)]
    slots = _line(*jobs)
    for j in jobs:
        slots.move(j, where)
    assert sorted(_names(slots)) == ["0", "1", "2"]
