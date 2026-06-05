"""R3-8 / R3-9: scheduler persists the last-fired instant and catches up.

R3-8 — no double-fire when JARVIS restarts within the same minute as a fire.
R3-9 — a slot missed during sleep/suspend is caught up once on the next tick.

The decision lives in the pure helper ``_due_fire`` (no Qt, no clock, no I/O),
which is exercised directly. ``_tick`` is then driven with a frozen clock, a
fake workflow library, and a fake signals object to prove the end-to-end
restart/catch-up behaviour.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterator

import pytest

croniter = pytest.importorskip("croniter")  # scheduler is a no-op without it

import core.scheduler as sched


# ── _due_fire (pure) ────────────────────────────────────────────────────────

def test_due_fire_first_sight_in_current_minute_fires() -> None:
    now = datetime(2026, 6, 6, 9, 30, 15)
    assert sched._due_fire("30 9 * * *", now, None) == datetime(2026, 6, 6, 9, 30, 0)


def test_due_fire_first_sight_old_slot_skips() -> None:
    # Brand-new daily workflow seen at 2 PM — the 09:30 slot already passed
    # before we ever saw it, so don't replay it.
    now = datetime(2026, 6, 6, 14, 0, 0)
    assert sched._due_fire("30 9 * * *", now, None) is None


def test_due_fire_restart_same_minute_no_double() -> None:
    # R3-8: fired the 09:30 slot, restarted at 09:30:40 — must NOT refire.
    last = datetime(2026, 6, 6, 9, 30, 0)
    now = datetime(2026, 6, 6, 9, 30, 40)
    assert sched._due_fire("* * * * *", now, last) is None


def test_due_fire_catch_up_after_downtime() -> None:
    # R3-9: last fired yesterday; machine asleep 09:29–09:34, woke at 09:34.
    # The 09:30 slot today is newer than last → fire it once (catch-up).
    last = datetime(2026, 6, 5, 9, 30, 0)
    now = datetime(2026, 6, 6, 9, 34, 0)
    assert sched._due_fire("30 9 * * *", now, last) == datetime(2026, 6, 6, 9, 30, 0)


def test_due_fire_per_minute_advances_each_minute() -> None:
    last = datetime(2026, 6, 6, 9, 30, 0)
    now = datetime(2026, 6, 6, 9, 31, 3)
    assert sched._due_fire("* * * * *", now, last) == datetime(2026, 6, 6, 9, 31, 0)


def test_due_fire_long_downtime_collapses_to_one_slot() -> None:
    # Asleep ~a day with a per-minute cron: get_prev returns only the most
    # recent minute, so we fire once, not 1440 times.
    last = datetime(2026, 6, 5, 9, 30, 0)
    now = datetime(2026, 6, 6, 9, 30, 30)
    fired = sched._due_fire("* * * * *", now, last)
    assert fired == datetime(2026, 6, 6, 9, 30, 0)


def test_due_fire_invalid_cron_returns_none() -> None:
    assert sched._due_fire("not a cron", datetime(2026, 6, 6, 9, 30, 0), None) is None


# ── Persistence ─────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the state sidecar at a tmp file and reset module-level state."""
    monkeypatch.setattr(sched, "_STATE_PATH", tmp_path / "scheduler_state.json")
    monkeypatch.setattr(sched, "_last_fired", {})
    monkeypatch.setattr(sched, "_state_loaded", False)
    yield


def test_state_round_trips(isolated_state: None) -> None:
    sched._record_fired("ping", datetime(2026, 6, 6, 9, 30, 0))
    # Simulate a restart: drop in-memory state, force a reload from disk.
    sched._last_fired = {}
    sched._state_loaded = False
    sched._load_state()
    assert sched._last_fired["ping"] == datetime(2026, 6, 6, 9, 30, 0)


def test_load_tolerates_garbage(isolated_state: None) -> None:
    sched._STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    sched._STATE_PATH.write_text('{"ping": "not-a-date", "ok": "2026-06-06T09:30:00"}',
                                 encoding="utf-8")
    sched._state_loaded = False
    sched._load_state()
    assert "ping" not in sched._last_fired          # bad entry skipped
    assert sched._last_fired["ok"] == datetime(2026, 6, 6, 9, 30, 0)


# ── _tick integration (injected clock + fakes) ──────────────────────────────

class _FakeSignal:
    def __init__(self) -> None:
        self.fired: list[str] = []

    def emit(self, wf_id: str) -> None:
        self.fired.append(wf_id)


def _install_tick_doubles(monkeypatch: pytest.MonkeyPatch, workflows: list[dict]) -> _FakeSignal:
    import core.automation
    import core.signals

    class _Lib:
        def list_all(self) -> list[dict]:
            return [dict(w) for w in workflows]

    sig = _FakeSignal()

    class _Signals:
        scheduled_workflow_fire = sig

    monkeypatch.setattr(core.automation, "workflow_library", _Lib())
    monkeypatch.setattr(core.signals, "signals", _Signals())
    return sig


def test_tick_no_double_fire_across_restart(isolated_state: None, monkeypatch: pytest.MonkeyPatch) -> None:
    sig = _install_tick_doubles(monkeypatch, [{"id": "ping", "enabled": True, "schedule": "* * * * *"}])

    sched._tick(now=datetime(2026, 6, 6, 9, 30, 5))
    assert sig.fired == ["ping"]                    # first sight, slot in current minute → fire

    # Simulate a restart within the same minute: in-memory state gone, reload
    # from the persisted sidecar, tick again at :40.
    sched._last_fired = {}
    sched._state_loaded = False
    sched._tick(now=datetime(2026, 6, 6, 9, 30, 40))
    assert sig.fired == ["ping"]                    # R3-8: still once, not twice


def test_tick_catches_up_missed_slot(isolated_state: None, monkeypatch: pytest.MonkeyPatch) -> None:
    sig = _install_tick_doubles(monkeypatch, [{"id": "daily", "enabled": True, "schedule": "30 9 * * *"}])

    # Pretend it last fired yesterday, then the machine was asleep over 09:30
    # today and woke at 09:34.
    sched._record_fired("daily", datetime(2026, 6, 5, 9, 30, 0))
    sched._tick(now=datetime(2026, 6, 6, 9, 34, 0))
    assert sig.fired == ["daily"]                   # R3-9: missed slot caught up

    # Same minute, next tick — must not refire.
    sched._tick(now=datetime(2026, 6, 6, 9, 34, 5))
    assert sig.fired == ["daily"]


def test_tick_skips_disabled(isolated_state: None, monkeypatch: pytest.MonkeyPatch) -> None:
    sig = _install_tick_doubles(monkeypatch, [{"id": "off", "enabled": False, "schedule": "* * * * *"}])
    sched._tick(now=datetime(2026, 6, 6, 9, 30, 5))
    assert sig.fired == []
