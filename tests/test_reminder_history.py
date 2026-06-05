"""Reminder history (Option A) — set / fire / cancel + list_reminders completed=true.

Covers the in-memory reminder history added alongside the fire-notification
feature: a fired or cancelled reminder is logged with
{message, scheduled_time, fired_at, status}, and `list_reminders` with
completed=true reads it back (most-recent-first). History is in-memory only and
resets on restart, so these tests just isolate the module globals per test.

A manual-fire Timer stand-in keeps the tests fast and deterministic: the real
threading.Timer only fires after the delay elapses (by which point the reminder
is registered and its scheduled_time is set), so the fake's fire() is called
*after* set_reminder() returns to mirror that ordering.
"""

from __future__ import annotations

import pytest

import core.handlers.reminders as r


@pytest.fixture(autouse=True)
def _isolate_reminder_state():
    """Clear module-global reminder/history state around each test."""
    def _clear():
        r._active_reminders.clear()
        r._reminder_meta.clear()
        with r._history_lock:
            r._reminder_history.clear()

    _clear()
    yield
    _clear()


class _ManualTimer:
    """threading.Timer stand-in that does NOT auto-fire.

    start() is a no-op; the test calls fire() to invoke the callback after
    set_reminder() has populated _active_reminders / _reminder_meta.
    """

    last: "_ManualTimer | None" = None

    def __init__(self, delay, fn):
        self.delay = delay
        self.fn = fn
        self.daemon = False
        self.cancelled = False
        _ManualTimer.last = self

    def start(self):  # real Timer would schedule; we fire manually instead
        pass

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.fn()


def _set(monkeypatch, message, delay=30):
    monkeypatch.setattr(r.threading, "Timer", _ManualTimer)
    return r._handle_reminder_task(
        "set_reminder", {"message": message, "delay_seconds": delay}
    )


def test_set_then_fire_records_fired_history(monkeypatch):
    out = _set(monkeypatch, "Stretch", delay=30)
    assert out["success"]
    assert r._reminder_meta  # active before firing

    _ManualTimer.last.fire()  # simulate the delay elapsing

    assert not r._active_reminders  # cleared on fire
    assert not r._reminder_meta
    assert len(r._reminder_history) == 1
    h = r._reminder_history[0]
    assert h["message"] == "Stretch"
    assert h["status"] == "fired"
    assert h["scheduled_time"]  # populated from the reminder meta
    assert h["fired_at"]        # populated at fire time


def test_set_then_cancel_records_cancelled_history(monkeypatch):
    _set(monkeypatch, "Drink water", delay=300)
    res = r._handle_reminder_task("cancel_reminder", {"message": "Drink water"})
    assert res["success"]
    assert _ManualTimer.last.cancelled
    assert not r._active_reminders

    assert len(r._reminder_history) == 1
    h = r._reminder_history[0]
    assert h["message"] == "Drink water"
    assert h["status"] == "cancelled"
    assert h["scheduled_time"]
    assert h["fired_at"] == ""  # never fired


def test_list_completed_empty():
    out = r._handle_reminder_task("list_reminders", {"completed": True})
    assert out["success"]
    assert "no completed" in out["output"].lower()


def test_list_completed_shows_history_most_recent_first(monkeypatch):
    _set(monkeypatch, "First", delay=30)
    _ManualTimer.last.fire()
    _set(monkeypatch, "Second", delay=300)
    r._handle_reminder_task("cancel_reminder", {"message": "Second"})

    out = r._handle_reminder_task("list_reminders", {"completed": True})
    body = out["output"]
    assert "First" in body and "Second" in body
    assert "[fired]" in body and "[cancelled]" in body
    # Most recent first: Second (cancelled later) before First (fired earlier)
    assert body.index("Second") < body.index("First")


def test_active_list_and_completed_list_are_separate(monkeypatch):
    _set(monkeypatch, "Active one", delay=300)

    active = r._handle_reminder_task("list_reminders", {})
    assert "Active one" in active["output"]
    assert "[fired]" not in active["output"]  # active list is not the history

    _ManualTimer.last.fire()
    completed = r._handle_reminder_task("list_reminders", {"completed": True})
    assert "Active one" in completed["output"]
    assert "[fired]" in completed["output"]
