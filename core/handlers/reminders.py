"""Handler: reminder_task — set, cancel, list timed reminders."""

from __future__ import annotations

import threading
import uuid
from typing import Any

from core.handlers.shared import _ok, _err, _tlog
from core.handlers.automation_handler import (
    _DANGEROUS_STEPS,
    _CONFIRMATION_REQUIRED_ACTIONS,
)

_active_reminders: dict[str, threading.Timer] = {}
_reminder_meta: dict[str, dict[str, Any]] = {}


def _format_run_summary(run: dict[str, Any]) -> str:
    intent = run.get("intent", "")
    act    = run.get("action", "")
    p      = run.get("parameters") or {}
    if intent == "open_app":
        if act == "open_browser":
            return f"open browser ({p.get('browser', 'default')})"
        if act == "open_url":
            return "open URL"
        return f"{act}: {p.get('app_name', p.get('url', ''))}"[:80]
    if intent == "search_web":
        return f"search: {p.get('query', '')}"[:80]
    if intent == "system_control":
        return f"{act}"
    if intent == "browser_automation":
        return f"{act}"
    if intent == "read_screen":
        return f"{act}"
    if intent == "jarvis_meta":
        return f"{act}"
    return f"{intent}/{act}"


def _is_schedulable_reminder_action(intent: str, act: str) -> bool:
    if not intent or not act:
        return False
    if intent in (
        "code_execution", "automation_task", "reminder_task",
        "file_operation", "close_app", "type_text", "control_mouse",
    ):
        return False
    if (intent, act) in _DANGEROUS_STEPS:
        return False
    if (intent, act) in _CONFIRMATION_REQUIRED_ACTIONS:
        return False
    if intent == "system_control":
        return act in (
            "screenshot", "volume_up", "volume_down", "volume_mute",
            "lock_screen", "brightness_up", "brightness_down",
        )
    if intent == "jarvis_meta":
        return act in ("tell_time", "tell_date", "status_report", "list_voices")
    if intent == "browser_automation":
        return act in (
            "navigate", "new_tab", "read_page", "fill_form",
            "extract_text", "click_element", "screenshot",
        )
    if intent in ("open_app", "search_web", "read_screen"):
        return True
    return False


def _validate_reminder_run(run: Any) -> tuple[dict[str, Any] | None, str | None]:
    if run is None:
        return None, None
    if not isinstance(run, dict):
        return None, "parameters.run must be an object"
    intent = str(run.get("intent", "")).strip()
    act    = str(run.get("action", "")).strip()
    params = run.get("parameters")
    if not isinstance(params, dict):
        params = {}
    if not _is_schedulable_reminder_action(intent, act):
        return None, (
            f"Scheduled action not allowed for '{intent}/{act}' — "
            "use a safe action (open app, search, screenshot, navigate, etc.)."
        )
    return {"intent": intent, "action": act, "parameters": params}, None


def _handle_reminder_task(action: str, params: dict) -> dict:
    if action == "set_reminder":
        msg    = str(params.get("message", "Reminder")).strip() or "Reminder"
        delay  = max(5, int(params.get("delay_seconds", 60)))
        _entry_mins, _entry_secs = delay // 60, delay % 60
        if _entry_mins and _entry_secs:
            _entry_time_str = f"{_entry_mins}m {_entry_secs}s"
        elif _entry_mins:
            _entry_time_str = f"{_entry_mins}m"
        else:
            _entry_time_str = f"{_entry_secs}s"
        _tlog(f"❯ reminder — {msg!r} in {_entry_time_str}")

        run_raw = params.get("run")
        run_norm, verr = _validate_reminder_run(run_raw)
        if verr:
            _tlog(f"✗ {verr}")
            return _err(verr)

        sched_conf = params.get("schedule_confidence")
        try:
            sc = float(sched_conf) if sched_conf is not None else 0.92
        except (TypeError, ValueError):
            sc = 0.92
        sc = max(0.0, min(1.0, sc))

        rid = str(params.get("reminder_id") or uuid.uuid4().hex[:12])

        def _fire() -> None:
            _active_reminders.pop(rid, None)
            meta = _reminder_meta.pop(rid, None) or {}
            m = meta.get("message", msg)
            r = meta.get("run")
            try:
                from core.signals import signals
                if r and isinstance(r, dict):
                    signals.reminder_action.emit({
                        "reminder_id": rid,
                        "message": m,
                        "run": r,
                        "schedule_confidence": float(meta.get("schedule_confidence", 0.92)),
                    })
                else:
                    signals.status_changed.emit(f"REMINDER: {m}")
            except Exception:
                pass

        t = threading.Timer(delay, _fire)
        t.daemon = True
        t.start()
        _active_reminders[rid] = t
        _reminder_meta[rid] = {
            "message": msg,
            "run": run_norm,
            "schedule_confidence": sc,
        }
        mins = delay // 60
        secs = delay % 60
        if mins and secs:
            time_str = f"{mins}m {secs}s"
        elif mins:
            time_str = f"{mins}m"
        else:
            time_str = f"{secs}s"
        _tlog("✓ scheduled")
        if run_norm:
            summ = _format_run_summary(run_norm)
            return _ok(f"In {time_str}: {summ}")
        return _ok(f"In {time_str}: {msg}")

    if action == "cancel_reminder":
        want = str(params.get("message", "")).strip()
        _tlog(f"❯ cancel reminder — {want!r}")
        if not want:
            _tlog("✗ no message provided")
            return _err("No message provided for cancel_reminder.")
        to_del: list[str] = []
        for rid, meta in list(_reminder_meta.items()):
            if str(meta.get("message", "")).strip() == want:
                to_del.append(rid)
        cancelled = 0
        for rid in to_del:
            t = _active_reminders.pop(rid, None)
            _reminder_meta.pop(rid, None)
            if t:
                t.cancel()
                cancelled += 1
        if cancelled:
            _tlog(f"✓ cancelled {cancelled} reminder{'s' if cancelled != 1 else ''}")
            return _ok(
                f"Cancelled {cancelled} reminder(s) for: {want}"
                if cancelled > 1
                else f"Reminder cancelled: {want}"
            )
        _tlog(f"✗ no active reminder matching: {want}")
        return _err(f"No active reminder matching: {want}")

    if action == "list_reminders":
        if not _reminder_meta:
            return _ok("No active reminders.")
        lines: list[str] = []
        # R3-11: snapshot before iterating — a reminder's Timer thread may pop
        # from _reminder_meta mid-iteration ("dict changed size" RuntimeError).
        for rid, meta in list(_reminder_meta.items()):
            m = str(meta.get("message", ""))
            r = meta.get("run")
            if r:
                lines.append(f"- [{rid}] {m} → {_format_run_summary(r)}")
            else:
                lines.append(f"- [{rid}] {m}")
        return _ok("\n".join(lines))

    return _err(f"Unknown reminder action: {action}")
