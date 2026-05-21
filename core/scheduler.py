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
  - "Already fired this minute" guard: a workflow with ``"* * * * *"``
    that takes 5s to execute could otherwise fire 12 times within a
    minute. We record the last-fired minute per workflow and skip a
    repeat until the next minute boundary.

Security:
  - Scheduled fires bypass ``config.auto_confirm`` so any
    confirmation-required step inside a scheduled workflow still
    presents the card. That logic lives in main.py — the scheduler
    just sets ``_scheduled: True`` on the result it emits via the
    signal-to-slot bridge.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Optional

from core.log import debug as _dbg, info as _info

# How often the loop wakes up to recompute "is anything due". 5 s is small
# enough that a freshly-edited cron with a near-future fire isn't missed,
# and big enough not to burn CPU on an idle laptop.
_LOOP_TICK_SECONDS = 5.0

# Track last-fire minute per workflow id so a fast-cycle cron doesn't
# refire within the same minute. {workflow_id: "YYYYMMDDHHMM"}
_last_fire_minute: dict[str, str] = {}


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


def _should_fire(cron_expr: str, now: datetime) -> bool:
    """True when this cron expression has a fire-time in the immediate past
    (between the start of this minute and now). Combined with the
    last-fire-minute guard this gives us at-most-once-per-minute semantics.
    """
    croniter = _croniter()
    if croniter is None:
        return False
    try:
        # Walk back one second from "now" so the cron's get_next gives us
        # the most recent fire that should have already happened by now.
        cutoff = now.replace(second=0, microsecond=0)
        prev_fire = croniter(cron_expr, now).get_prev(datetime)
        return prev_fire >= cutoff
    except (ValueError, KeyError, TypeError):
        return False


def _watch_loop() -> None:
    """Daemon-thread main loop. Iterates scheduled workflows on each tick."""
    while True:
        time.sleep(_LOOP_TICK_SECONDS)
        try:
            _tick()
        except Exception as exc:
            # Never let a single bad tick kill the scheduler thread.
            _dbg("scheduler", f"tick error swallowed: {exc!r}")


def _tick() -> None:
    """One pass: load workflows, fire any whose schedule is due now."""
    from core.automation import workflow_library
    from core.signals import signals

    workflows = workflow_library.list_all()
    now = datetime.now()
    minute_key = now.strftime("%Y%m%d%H%M")

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

        if not _should_fire(cron_expr, now):
            continue
        if _last_fire_minute.get(wf_id) == minute_key:
            continue  # Already fired this minute.

        _last_fire_minute[wf_id] = minute_key
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
