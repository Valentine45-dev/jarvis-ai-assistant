"""Cron-style workflow scheduler (F-3).

Reads `schedule` from each workflow in ``data/workflows.json`` — a standard
cron expression like ``"0 9 * * 1-5"`` (9:00 AM every weekday). A daemon
thread iterates the list, sleeps until the soonest next-fire, then emits
``signals.scheduled_workflow_fire`` so the main thread can dispatch the
workflow through the normal executor path.

Design notes:
  - We schedule by walltime, not delay-from-now. Restarting JARVIS in the
    middle of the day picks up the next scheduled fire correctly without
    drift.
  - Workflows without a ``schedule`` are ignored entirely. Workflows with
    a malformed cron expression are logged and skipped — never crash the
    whole loop.
  - The watcher reloads on ``signals.workflow_library_changed`` (already
    emitted by WorkflowLibrary when workflows.json changes), so adding /
    editing / deleting a scheduled workflow takes effect within ~2s
    without restarting the app.
  - Dedupe + catch-up (R3-8/R3-9): we persist the last *scheduled instant*
    fired per workflow to ``data/scheduler_state.json`` and, each tick, fire
    the most-recent slot only if it's strictly newer than that mark. This
    means a fast ``"* * * * *"`` cron fires at most once per minute, a restart
    within the same minute does not refire, and a slot missed during
    sleep/suspend is caught up once on the next tick (only the latest missed
    slot — a long downtime collapses to a single fire, never a storm).

Security:
  - Scheduled fires bypass ``config.auto_confirm`` so any
    confirmation-required step inside a scheduled workflow still
    presents the card. That logic lives in main.py — the scheduler
    just sets ``_scheduled: True`` on the result it emits via the
    signal-to-slot bridge.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.log import debug as _dbg, info as _info

# How often the loop wakes up to recompute "is anything due". 5 s is small
# enough that a freshly-edited cron with a near-future fire isn't missed,
# and big enough not to burn CPU on an idle laptop.
_LOOP_TICK_SECONDS = 5.0

# R3-8/R3-9: persist the last *scheduled instant* fired per workflow so the
# dedupe survives a restart (no double-fire within the same minute) and a tick
# after downtime can catch up a missed slot. Sidecar file (not workflows.json)
# so firing doesn't trip the workflow-library file-watcher / reload churn.
_STATE_PATH = Path(__file__).parent.parent / "data" / "scheduler_state.json"
_state_lock = threading.Lock()
_last_fired: dict[str, datetime] = {}   # {workflow_id: last fired scheduled instant}
_state_loaded = False


def _load_state() -> None:
    """Load the persisted last-fired marks once. Tolerant: a missing file or a
    bad entry is skipped, never fatal."""
    global _last_fired, _state_loaded
    with _state_lock:
        if _state_loaded:
            return
        _state_loaded = True
        try:
            if _STATE_PATH.exists():
                raw = json.loads(_STATE_PATH.read_text(encoding="utf-8")) or {}
                parsed: dict[str, datetime] = {}
                for wf_id, iso in raw.items():
                    try:
                        parsed[wf_id] = datetime.fromisoformat(iso)
                    except (ValueError, TypeError):
                        continue
                _last_fired = parsed
        except Exception as exc:
            _dbg("scheduler", f"could not load state: {exc!r}")


def _persist_locked() -> None:
    """Atomically write the state file. Caller MUST hold _state_lock."""
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {wf_id: dt.isoformat() for wf_id, dt in _last_fired.items()}
        tmp = _STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, _STATE_PATH)
    except Exception as exc:
        _dbg("scheduler", f"could not save state: {exc!r}")


def _record_fired(wf_id: str, instant: datetime) -> None:
    """Record (and persist) the scheduled instant just fired for a workflow."""
    with _state_lock:
        _last_fired[wf_id] = instant
        _persist_locked()


def _croniter():
    """Lazy import — keeps the scheduler optional if the dep isn't there yet."""
    try:
        from croniter import croniter
        return croniter
    except ImportError:
        return None


def _next_fire(cron_expr: str, base: Optional[datetime] = None) -> Optional[datetime]:
    """Return the next walltime this cron expression fires after ``base``.

    None when the expression is invalid or croniter isn't installed. The
    caller logs and skips on None — never crashes.
    """
    croniter = _croniter()
    if croniter is None:
        return None
    try:
        itr = croniter(cron_expr, base or datetime.now())
        return itr.get_next(datetime)
    except (ValueError, KeyError, TypeError):
        return None


def _due_fire(cron_expr: str, now: datetime, last: Optional[datetime]) -> Optional[datetime]:
    """Return the scheduled instant to fire now, or None to skip.

    The most-recent scheduled instant at/before ``now`` is ``croniter.get_prev``.
      - ``last is None`` (never fired / fresh install): fire only if that instant
        is within the current minute. This preserves the original first-fire
        behaviour and avoids replaying a slot that passed before the workflow
        existed (or before this process ever saw it).
      - ``last`` set: fire iff that instant is strictly newer than ``last``
        (R3-9 catch-up). Because we only look at the single most-recent instant,
        a long downtime collapses to ONE fire — not one per missed slot.

    R3-8: after a restart, the persisted ``last`` equals the just-fired instant,
    so ``prev_fire <= last`` and we skip — no double-fire within the same minute.
    """
    croniter = _croniter()
    if croniter is None:
        return None
    try:
        prev_fire = croniter(cron_expr, now).get_prev(datetime)
    except (ValueError, KeyError, TypeError):
        return None
    if last is None:
        cutoff = now.replace(second=0, microsecond=0)
        return prev_fire if prev_fire >= cutoff else None
    return prev_fire if prev_fire > last else None


def _watch_loop() -> None:
    """Daemon-thread main loop. Iterates scheduled workflows on each tick."""
    while True:
        time.sleep(_LOOP_TICK_SECONDS)
        try:
            _tick()
        except Exception as exc:
            # Never let a single bad tick kill the scheduler thread.
            _dbg("scheduler", f"tick error swallowed: {exc!r}")


def _tick(now: Optional[datetime] = None) -> None:
    """One pass: load workflows, fire any whose schedule is due now.

    ``now`` is injectable for tests (frozen clock); production passes None and
    uses the wall clock."""
    from core.automation import workflow_library
    from core.signals import signals

    _load_state()
    workflows = workflow_library.list_all()
    if now is None:
        now = datetime.now()

    for wf in workflows:
        if not wf.get("enabled", True):
            continue
        cron_expr = (wf.get("schedule") or "").strip()
        if not cron_expr:
            continue
        wf_id = wf.get("id") or ""
        if not wf_id:
            continue

        # Validate once per tick — invalid expressions just don't fire.
        if _next_fire(cron_expr) is None:
            _dbg("scheduler", f"invalid cron for workflow {wf_id!r}: {cron_expr!r}")
            continue

        with _state_lock:
            last = _last_fired.get(wf_id)
        fire_instant = _due_fire(cron_expr, now, last)
        if fire_instant is None:
            continue

        # Persist BEFORE emitting so a crash mid-dispatch can't cause a refire
        # of the same instant on the next start.
        _record_fired(wf_id, fire_instant)
        _info("scheduler", f"firing workflow {wf_id!r} (schedule={cron_expr!r})")
        try:
            signals.scheduled_workflow_fire.emit(wf_id)
        except Exception as exc:
            _dbg("scheduler", f"emit failed for {wf_id!r}: {exc!r}")


_started = False
_start_lock = threading.Lock()


def start() -> None:
    """Spawn the scheduler daemon thread. Idempotent — safe to call
    multiple times; subsequent calls are no-ops."""
    global _started
    with _start_lock:
        if _started:
            return
        if _croniter() is None:
            _dbg("scheduler", "croniter not installed; scheduler disabled")
            return
        t = threading.Thread(
            target=_watch_loop,
            name="WorkflowScheduler",
            daemon=True,
        )
        t.start()
        _started = True
        _info("scheduler", "cron scheduler started")
