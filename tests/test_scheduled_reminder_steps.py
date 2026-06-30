"""Fix: clock-anchored recurring reminders fire AT the scheduled time, not 30 min late.

Bug: "remind me every day at 1:18pm to check email" → create_workflow stored the step
as the NL string "set a reminder to check email" (no time — the time went to the cron
`schedule`). At fire time that string re-parsed through the brain → set_reminder with the
30-min DEFAULT, so the 1:18 cron fire scheduled a SECOND reminder for 1:48.

Fix (B1+B2 — the cron `schedule` owns the timing, so a reminder step fires immediately):
  B1: a concrete reminder_task/set_reminder step in a scheduled workflow → delay clamped <=5.
  B2: a reminder-ish STRING step in a scheduled workflow → rewritten to a concrete
      set_reminder{message, delay_seconds:5} so it can't re-parse to the 30-min default.
Applied ONLY when a `schedule` is present; one-shot reminders and general steps untouched.
(Part A — the brain emitting a concrete step — is a CLAUDE.md prompt rule, physical-only.)
"""

from __future__ import annotations

import core.handlers.automation_handler as ah
from core.handlers.automation_handler import (
    _normalize_scheduled_reminder_steps as _norm,
    _reminder_message_from_string as _msg,
)


# ── B2: reminder-string detection + message extraction ──────────────────────

def test_reminder_string_message_extraction():
    assert _msg("set a reminder to check email") == "check email"
    assert _msg("remind me to drink water") == "drink water"
    assert _msg("set reminder: stand up") == "stand up"
    # the cron schedule owns the time → strip an embedded time/recurrence phrase
    assert _msg("set a reminder to check email every day at 9am") == "check email"
    assert _msg("remind me to stretch in 5 minutes") == "stretch"


def test_non_reminder_strings_are_not_matched():
    assert _msg("open chrome") is None
    assert _msg("navigate to youtube.com") is None
    assert _msg("take a screenshot") is None


# ── B2: string step → concrete immediate reminder ───────────────────────────

def test_string_reminder_step_rewritten_to_concrete():
    out = _norm(["set a reminder to check email"])
    assert len(out) == 1
    step = out[0]
    assert isinstance(step, dict)
    assert step["intent"] == "reminder_task" and step["action"] == "set_reminder"
    assert step["parameters"]["message"] == "check email"
    assert step["parameters"]["delay_seconds"] == 5


def test_non_reminder_string_step_left_untouched():
    out = _norm(["open chrome", "navigate to youtube.com"])
    assert out == ["open chrome", "navigate to youtube.com"]   # unchanged strings


# ── B1: concrete reminder step → delay clamped ──────────────────────────────

def test_concrete_reminder_delay_clamped():
    out = _norm([{
        "intent": "reminder_task", "action": "set_reminder",
        "parameters": {"message": "check email", "delay_seconds": 1800},
    }])
    assert out[0]["parameters"]["delay_seconds"] == 5
    assert out[0]["parameters"]["message"] == "check email"   # message preserved


def test_concrete_reminder_small_delay_preserved_and_missing_defaulted():
    # a delay already <=5 is left as-is; a missing delay defaults to 5
    out = _norm([
        {"intent": "reminder_task", "action": "set_reminder",
         "parameters": {"message": "a", "delay_seconds": 3}},
        {"intent": "reminder_task", "action": "set_reminder",
         "parameters": {"message": "b"}},
    ])
    assert out[0]["parameters"]["delay_seconds"] == 3
    assert out[1]["parameters"]["delay_seconds"] == 5


def test_non_reminder_concrete_step_untouched():
    step = {"intent": "system_control", "action": "screenshot", "parameters": {}}
    out = _norm([step])
    assert out == [step]


# ── wiring: create_workflow normalises ONLY when a schedule is present ───────

class _FakeLib:
    def __init__(self): self.added = []
    def get(self, slug): return None
    def add(self, wf): self.added.append(wf)
    def list_all(self): return []


def test_create_workflow_with_schedule_normalises_reminder_string(monkeypatch):
    fake = _FakeLib()
    monkeypatch.setattr("core.automation.workflow_library", fake)
    res = ah._handle_automation_task("create_workflow", {
        "task_name": "daily_check_email",
        "schedule": "0 9 * * *",
        "steps": ["set a reminder to check email"],
    })
    assert res["success"] is True
    step = fake.added[0]["steps"][0]
    assert isinstance(step, dict) and step["action"] == "set_reminder"
    assert step["parameters"]["message"] == "check email"
    assert step["parameters"]["delay_seconds"] == 5


def test_create_workflow_without_schedule_leaves_string_untouched(monkeypatch):
    fake = _FakeLib()
    monkeypatch.setattr("core.automation.workflow_library", fake)
    res = ah._handle_automation_task("create_workflow", {
        "task_name": "manual_routine",
        "steps": ["set a reminder to check email"],   # no schedule → not normalised
    })
    assert res["success"] is True
    assert fake.added[0]["steps"] == ["set a reminder to check email"]
