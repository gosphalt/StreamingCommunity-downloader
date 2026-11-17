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
    # Only a job with a thread waiting can be granted a slot; these tests stand in for those threads.
    for j in jobs:
        slots._waiters[id(j)] = threading.Condition(slots._cond)
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


def test_a_block_moves_past_the_neighbour_keeping_its_order():
    a, b, c, d, e = (_job(n, i) for i, n in enumerate("abcde", 1))
    slots = _line(a, b, c, d, e)
    # the block b,c,d moves up: a jumps below it
    slots.move_group([b, c, d], "up")
    assert _names(slots) == ["b", "c", "d", "a", "e"]
    # down passes the single neighbour below: a goes back above the block
    slots.move_group([b, c, d], "down")
    assert _names(slots) == ["a", "b", "c", "d", "e"]
    slots.move_group([b, c, d], "down")
    assert _names(slots) == ["a", "e", "b", "c", "d"]


def test_a_block_already_at_the_edge_does_not_move():
    a, b, c = _job("a", 1), _job("b", 2), _job("c", 3)
    slots = _line(a, b, c)
    assert slots.move_group([a, b], "up") == []
    assert slots.move_group([b, c], "down") == []
    assert _names(slots) == ["a", "b", "c"]


def test_a_block_takes_the_priority_of_the_neighbour_it_lands_beside():
    a, b, c = _job("a", 1, priority=10), _job("b", 2), _job("c", 3)
    slots = _line(a, b, c)
    slots.move_group([b, c], "up")
    assert [j.priority for j in (b, c)] == [10, 10]
    assert _names(slots) == ["b", "c", "a"]
