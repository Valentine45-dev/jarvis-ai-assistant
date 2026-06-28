"""Unit tests for scheduled reminder action validation (no timers)."""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# _validate_reminder_run is re-exported from core.executor; _format_run_summary
# is not — both originally lived under executor but were moved into the
# reminders handler. Import each from its current canonical home so this test
# doesn't break the next time someone tidies the executor's re-export list.
from core import executor as ex
from core.handlers.reminders import _format_run_summary


def test_validate_reminder_run_none():
    d, err = ex._validate_reminder_run(None)
    assert d is None and err is None


def test_validate_reminder_run_safe_open():
    d, err = ex._validate_reminder_run(
        {"intent": "open_app", "action": "open_browser", "parameters": {"browser": "chrome"}}
    )
    assert err is None and d is not None
    assert d["intent"] == "open_app"


def test_validate_reminder_run_blocks_file_op():
    d, err = ex._validate_reminder_run(
        {"intent": "file_operation", "action": "delete_file", "parameters": {"path": "x"}}
    )
    assert d is None and err and "not allowed" in err.lower()


def test_format_run_summary():
    s = _format_run_summary(
        {"intent": "search_web", "action": "google_search", "parameters": {"query": "jarvis"}}
    )
    assert "search" in s.lower() or "jarvis" in s.lower()


# ── confidence vs outcome decoupling on the reminder-ACTION path (§26 sibling) ─
#
# _finish_execute (the main command path) shows the real routing % even on a
# failed run; §26 fixed that but MISSED _on_reminder_action — the delayed-reminder
# -with-an-executable-step slot, which re-implemented the conf logic inline as
# `sc if exec_ok else 0.0` and so reported 0% on any failed scheduled action. This
# drives the REAL slot with a FAILED dispatch and asserts the real schedule % flows
# to the LAST ACTION chip, the Voice page, and the persisted history — not 0%.

def _reminder_action_stub():
    import types
    from unittest.mock import MagicMock

    stub = types.SimpleNamespace()
    stub._history = []
    stub._INTENT_HUD = {"system_control": "SYS CONTROL"}
    stub._session_start = datetime.now()
    stub._set_state = MagicMock()
    stub._dashboard = types.SimpleNamespace(
        left=types.SimpleNamespace(
            hud_status=types.SimpleNamespace(set_status=MagicMock()),
            last_action=types.SimpleNamespace(set_action=MagicMock()),
            status_lbl=types.SimpleNamespace(setText=MagicMock()),
            transcript=types.SimpleNamespace(append_jarvis_scheduled=MagicMock()),
        ),
        toast=types.SimpleNamespace(show_toast=MagicMock()),
    )
    stub._history_view = types.SimpleNamespace(refresh_history=MagicMock())
    stub._voice_view = types.SimpleNamespace(set_execution=MagicMock())
    return stub


def _run_reminder_action(monkeypatch, *, success: bool, sc: float = 0.92):
    """Drive the real _on_reminder_action with a stubbed dispatch outcome."""
    import types

    import core.executor as ce
    import core.responders.assembler as ca
    import core.voice as cv
    import ui.main_window.backend_signals_mixin as bsm
    from ui.main_window.backend_signals_mixin import _BackendSignalsMixin

    exec_out = (
        {"success": True, "output": "done", "error": ""}
        if success
        else {"success": False, "output": "", "error": "boom"}
    )
    monkeypatch.setattr(ce, "dispatch", lambda *a, **k: exec_out)
    monkeypatch.setattr(
        ca, "responder",
        types.SimpleNamespace(build_scheduled=lambda *a, **k: "Scheduled reply."),
    )
    monkeypatch.setattr(
        cv, "voice_engine",
        types.SimpleNamespace(say=lambda *a, **k: None),
    )
    # Don't hit disk for history persistence.
    monkeypatch.setattr(bsm, "history_store",
                        types.SimpleNamespace(save_entry=lambda *a, **k: None))

    stub = _reminder_action_stub()
    payload = {
        "message": "tidy up",
        "schedule_confidence": sc,
        "run": {"intent": "system_control", "action": "volume_mute", "parameters": {}},
    }
    _BackendSignalsMixin._on_reminder_action(stub, payload)
    return stub


def test_reminder_action_failure_preserves_real_confidence(monkeypatch):
    sc = 0.92
    stub = _run_reminder_action(monkeypatch, success=False, sc=sc)

    # History entry: real schedule confidence, NOT zeroed (the §26 bug wrote 0.0 here).
    assert stub._history, "the failed scheduled action must still be logged"
    assert stub._history[-1]["conf"] == sc
    assert stub._history[-1]["status"] == "error"

    # LAST ACTION chip (line 162) gets the real %, not 0.
    intent, conf = stub._dashboard.left.last_action.set_action.call_args.args
    assert conf == sc

    # Voice page execution readout (line 164): real % + the failure flag separately.
    v_args = stub._voice_view.set_execution.call_args.args
    assert v_args[2] == sc          # conf preserved
    assert v_args[3] is False       # exec_ok carries the failure, not the number

    # Sys-log rail is unchanged: success=exec_ok (False) drives the red rail.
    sched_kwargs = stub._dashboard.left.transcript.append_jarvis_scheduled.call_args.kwargs
    assert sched_kwargs.get("success") is False


def test_reminder_action_success_reports_confidence(monkeypatch):
    # Control: the success path was always correct — confirm it still is.
    sc = 0.92
    stub = _run_reminder_action(monkeypatch, success=True, sc=sc)
    assert stub._history[-1]["conf"] == sc
    assert stub._history[-1]["status"] == "success"
    assert stub._dashboard.left.last_action.set_action.call_args.args[1] == sc
    sched_kwargs = stub._dashboard.left.transcript.append_jarvis_scheduled.call_args.kwargs
    assert sched_kwargs.get("success") is True
