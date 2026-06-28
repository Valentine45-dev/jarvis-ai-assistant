"""Tests for running browser-free inline workflows off the Qt main thread.

A multi-step `automation_task`/`run_workflow` used to dispatch synchronously on the Qt
main thread, briefly freezing the UI. An INLINE workflow whose every step is a
structured dict with a Playwright-free / Qt-free intent now runs on the same worker
harness as code_execution; anything that could touch Playwright (or any NL-string step
resolved mid-run) stays on the main thread.

These tests cover the eligibility classifier (the safety crux), the routing decision in
_execute_result, and the thread-aware _yield_ui pump.
"""

from __future__ import annotations

import threading
import types

import pytest

pytest.importorskip("PyQt5")

from ui.main_window.execution_mixin import _ExecutionMixin  # noqa: E402


def _wf(steps):
    return {
        "intent": "automation_task",
        "action": "run_workflow",
        "parameters": {"steps": steps},
    }


def _eligible(result) -> bool:
    stub = types.SimpleNamespace(
        _OFFTHREAD_WORKFLOW_INTENTS=_ExecutionMixin._OFFTHREAD_WORKFLOW_INTENTS,
    )
    stub._resolve_workflow_steps = lambda r: _ExecutionMixin._resolve_workflow_steps(stub, r)
    return _ExecutionMixin._workflow_is_offthread_safe(stub, result)


def _saved(task_name):
    return {"intent": "automation_task", "action": "run_workflow",
            "parameters": {"task_name": task_name}}


# ── eligibility classifier ──────────────────────────────────────────────────


def test_all_structured_whitelist_steps_are_eligible():
    steps = [
        {"intent": "file_operation", "action": "create_directory",
         "parameters": {"path": "tests/temp"}},
        {"intent": "file_operation", "action": "create_file",
         "parameters": {"path": "tests/temp/x.txt", "content": ""}},
        {"intent": "system_control", "action": "volume_mute", "parameters": {}},
    ]
    assert _eligible(_wf(steps)) is True


def test_natural_language_string_step_is_ineligible():
    # A string step is resolved mid-run and could become a browser action.
    steps = [
        {"intent": "file_operation", "action": "create_file", "parameters": {}},
        "take a screenshot of the page",
    ]
    assert _eligible(_wf(steps)) is False


def test_browser_step_is_ineligible():
    assert _eligible(_wf([
        {"intent": "browser_automation", "action": "navigate",
         "parameters": {"url": "https://example.com"}},
    ])) is False


def test_non_whitelist_intents_are_ineligible():
    # search_web / open_app can drive the Playwright session; vision_analysis's
    # source="browser" path also uses Playwright; jarvis_meta isn't vetted.
    assert _eligible(_wf([
        {"intent": "search_web", "action": "google_search", "parameters": {}},
    ])) is False
    assert _eligible(_wf([
        {"intent": "open_app", "action": "open_browser", "parameters": {}},
    ])) is False
    assert _eligible(_wf([
        {"intent": "vision_analysis", "action": "describe", "parameters": {"source": "browser"}},
    ])) is False
    assert _eligible(_wf([
        {"intent": "jarvis_meta", "action": "change_theme", "parameters": {}},
    ])) is False


def test_vetted_input_screen_weather_intents_are_eligible():
    # type_text / control_mouse (pyautogui + pyperclip), read_screen (pyautogui +
    # pytesseract), weather (network) are all Qt-free / Playwright-free.
    steps = [
        {"intent": "type_text", "action": "type_text", "parameters": {"text": "hi"}},
        {"intent": "control_mouse", "action": "click", "parameters": {"x": 1, "y": 2}},
        {"intent": "read_screen", "action": "ocr_full", "parameters": {}},
        {"intent": "weather", "action": "get_current_weather", "parameters": {}},
    ]
    assert _eligible(_wf(steps)) is True


def test_empty_or_missing_steps_are_ineligible():
    assert _eligible(_wf([])) is False
    assert _eligible({"intent": "automation_task", "action": "run_workflow",
                      "parameters": {}}) is False


# ── saved-by-name / cron workflows (D) ──────────────────────────────────────


def test_saved_workflow_steps_resolved_and_eligible(monkeypatch):
    # A saved-by-name workflow (no inline steps) resolves its persisted steps from
    # the library; an all-whitelist saved workflow runs off-thread like an inline one.
    import core.automation as ca
    wf = {"id": "morning", "name": "Morning", "enabled": True, "steps": [
        {"intent": "system_control", "action": "volume_mute", "parameters": {}},
        {"intent": "file_operation", "action": "create_directory",
         "parameters": {"path": "tests/temp"}},
    ]}
    monkeypatch.setattr(ca.workflow_library, "get", lambda n: wf if n == "morning" else None)
    assert _eligible(_saved("morning")) is True


def test_saved_workflow_with_browser_step_is_ineligible(monkeypatch):
    import core.automation as ca
    wf = {"id": "b", "enabled": True, "steps": [
        {"intent": "browser_automation", "action": "navigate", "parameters": {}},
    ]}
    monkeypatch.setattr(ca.workflow_library, "get", lambda n: wf)
    assert _eligible(_saved("b")) is False


def test_saved_workflow_with_string_step_is_ineligible(monkeypatch):
    # A persisted NL-string step could resolve to a browser action mid-run.
    import core.automation as ca
    wf = {"id": "s", "enabled": True, "steps": [
        {"intent": "system_control", "action": "volume_mute", "parameters": {}},
        "take a screenshot of the page",
    ]}
    monkeypatch.setattr(ca.workflow_library, "get", lambda n: wf)
    assert _eligible(_saved("s")) is False


def test_disabled_or_missing_saved_workflow_stays_synchronous(monkeypatch):
    # Disabled/missing → None → main thread, so the handler reports the real
    # disabled/not-found error rather than the worker swallowing it.
    import core.automation as ca
    disabled = {"id": "d", "enabled": False, "steps": [
        {"intent": "system_control", "action": "volume_mute", "parameters": {}},
    ]}
    monkeypatch.setattr(ca.workflow_library, "get",
                        lambda n: disabled if n == "d" else None)
    assert _eligible(_saved("d")) is False        # disabled
    assert _eligible(_saved("ghost")) is False    # missing


# ── routing in _execute_result ──────────────────────────────────────────────


def _routing_stub():
    stub = types.SimpleNamespace()
    stub._OFFTHREAD_WORKFLOW_INTENTS = _ExecutionMixin._OFFTHREAD_WORKFLOW_INTENTS
    stub._ACTION_INTENTS = _ExecutionMixin._ACTION_INTENTS
    # Bind the real classifier so _execute_result's self._workflow_is_offthread_safe works.
    stub._resolve_workflow_steps = lambda result: (
        _ExecutionMixin._resolve_workflow_steps(stub, result)
    )
    stub._workflow_is_offthread_safe = lambda result: (
        _ExecutionMixin._workflow_is_offthread_safe(stub, result)
    )
    stub._spawn_calls = []
    stub._spawn_code_worker = lambda *a, **k: stub._spawn_calls.append((a, k))
    stub._finish_calls = []
    stub._finish_execute = lambda *a, **k: stub._finish_calls.append((a, k))
    stub._set_state = lambda *_: None
    stub._last_result = None
    stub._dashboard = types.SimpleNamespace(
        left=types.SimpleNamespace(
            status_lbl=types.SimpleNamespace(setText=lambda *_: None),
        ),
        toast=types.SimpleNamespace(show_toast=lambda *a, **k: None),
    )
    return stub


def test_eligible_workflow_routes_to_worker(monkeypatch):
    import ui.main_window.execution_mixin as em

    dispatched = []
    monkeypatch.setattr(
        em, "dispatch",
        lambda *a, **k: dispatched.append((a, k)) or {"success": True, "output": "", "error": ""},
    )
    stub = _routing_stub()
    result = _wf([{"intent": "file_operation", "action": "create_directory",
                   "parameters": {"path": "tests/temp"}}])

    _ExecutionMixin._execute_result(stub, result, "automation_task", 0.9, "ok", "AUTOMATION")

    assert len(stub._spawn_calls) == 1, "eligible workflow must spawn the worker"
    assert dispatched == [], "must NOT dispatch inline on the main thread"
    assert stub._finish_calls == [], "finish happens later via the done-slot, not inline"


def test_ineligible_workflow_dispatches_synchronously(monkeypatch):
    import core.memory
    import ui.main_window.execution_mixin as em

    monkeypatch.setattr(core.memory.memory, "inject_outcome", lambda **k: None)
    dispatched = []
    monkeypatch.setattr(
        em, "dispatch",
        lambda *a, **k: dispatched.append((a, k)) or {"success": True, "output": "", "error": ""},
    )
    stub = _routing_stub()
    result = _wf([{"intent": "browser_automation", "action": "navigate",
                   "parameters": {"url": "https://example.com"}}])

    _ExecutionMixin._execute_result(stub, result, "automation_task", 0.9, "ok", "AUTOMATION")

    assert stub._spawn_calls == [], "browser workflow must stay on the main thread"
    assert len(dispatched) == 1, "ineligible workflow dispatches synchronously"


def test_saved_by_name_workflow_routes_to_worker(monkeypatch):
    # A saved-by-name run (task_name, no inline steps) must now also go off-thread
    # when its persisted steps are all whitelist-safe.
    import core.automation as ca
    import ui.main_window.execution_mixin as em

    wf = {"id": "tidy", "enabled": True, "steps": [
        {"intent": "file_operation", "action": "create_directory",
         "parameters": {"path": "tests/temp"}},
    ]}
    monkeypatch.setattr(ca.workflow_library, "get", lambda n: wf if n == "tidy" else None)
    dispatched = []
    monkeypatch.setattr(
        em, "dispatch",
        lambda *a, **k: dispatched.append((a, k)) or {"success": True, "output": "", "error": ""},
    )
    stub = _routing_stub()
    _ExecutionMixin._execute_result(stub, _saved("tidy"), "automation_task", 0.9, "ok", "AUTOMATION")

    assert len(stub._spawn_calls) == 1, "eligible saved workflow must spawn the worker"
    assert dispatched == [], "must NOT dispatch on the main thread"


def test_scheduled_offthread_workflow_never_auto_confirms(monkeypatch):
    # F-3 safety: a scheduled (cron) fire that needs confirmation must show the
    # card even with auto_confirm ON — it must NOT spawn a resolve("yes") worker.
    import core.voice
    monkeypatch.setattr(core.voice, "voice_engine",
                        types.SimpleNamespace(say=lambda *a, **k: None))

    stub = types.SimpleNamespace()
    stub._transcript_update_token = 7
    stub._code_exec_flight_token = 7
    stub._code_exec_in_flight = True
    stub._auto_confirm = True
    stub._spawn_calls = []
    stub._spawn_code_worker = lambda *a, **k: stub._spawn_calls.append((a, k))
    stub._shown = []
    stub._show_confirm_card = lambda msg: stub._shown.append(msg)
    stub._confirm_mode = None
    stub._confirmation_controller = types.SimpleNamespace(
        prompt_from_result=lambda e: "Delete file X?")
    stub._history = [{}]
    stub._tts_ready = types.SimpleNamespace(emit=lambda *_: None)
    stub._dashboard = types.SimpleNamespace(
        left=types.SimpleNamespace(
            typing=types.SimpleNamespace(hide_typing=lambda: None)),
        toast=types.SimpleNamespace(show_toast=lambda *a, **k: None),
    )

    payload = {
        "exec_out": {"needs_confirmation": True},
        "result": {"intent": "automation_task", "action": "run_workflow",
                   "parameters": {"task_name": "cleanup"}, "_scheduled": True},
        "intent": "automation_task", "conf": 0.9, "resp": "x", "hud": "AUTOMATION",
        "token": 7,
    }
    _ExecutionMixin._on_code_execution_done(stub, payload)

    assert stub._spawn_calls == [], "scheduled fire must NOT auto-confirm off-thread"
    assert stub._shown == ["Delete file X?"], "must show the confirmation card instead"


def test_non_scheduled_offthread_workflow_auto_confirms(monkeypatch):
    # Control: a NON-scheduled needs-confirmation result with auto_confirm ON still
    # auto-resolves off-thread (the scheduled guard is the only difference).
    stub = types.SimpleNamespace()
    stub._transcript_update_token = 3
    stub._code_exec_flight_token = 3
    stub._auto_confirm = True
    stub._spawn_calls = []
    stub._spawn_code_worker = lambda *a, **k: stub._spawn_calls.append((a, k))

    payload = {
        "exec_out": {"needs_confirmation": True},
        "result": {"intent": "code_execution", "action": "run_shell", "parameters": {}},
        "intent": "code_execution", "conf": 0.9, "resp": "x", "hud": "EXECUTING",
        "token": 3,
    }
    _ExecutionMixin._on_code_execution_done(stub, payload)

    assert len(stub._spawn_calls) == 1, "non-scheduled auto_confirm should resolve off-thread"


# ── thread-aware _yield_ui ──────────────────────────────────────────────────


def test_yield_ui_noop_off_main_thread(monkeypatch):
    import PyQt5.QtWidgets as qtw

    import core.handlers.automation_handler as ah

    pumped = {"n": 0}

    class _FakeApp:
        def processEvents(self):
            pumped["n"] += 1

    monkeypatch.setattr(qtw.QApplication, "instance", staticmethod(lambda: _FakeApp()))

    done = {}

    def _run():
        ah._yield_ui()
        done["ok"] = True

    t = threading.Thread(target=_run)
    t.start()
    t.join(2.0)

    assert done.get("ok") is True, "_yield_ui raised on a worker thread"
    assert pumped["n"] == 0, "processEvents must NOT run off the main thread"


def test_yield_ui_pumps_on_main_thread(monkeypatch):
    import PyQt5.QtWidgets as qtw

    import core.handlers.automation_handler as ah

    pumped = {"n": 0}

    class _FakeApp:
        def processEvents(self):
            pumped["n"] += 1

    monkeypatch.setattr(qtw.QApplication, "instance", staticmethod(lambda: _FakeApp()))

    ah._yield_ui()  # pytest's main thread

    assert pumped["n"] == 1, "processEvents should pump once on the main thread"


# ── confidence vs outcome decoupling (HUD must never show 0% on a failure) ────

def test_confidence_display_never_zeroed_on_failure():
    """Confidence is the routing confidence (did JARVIS understand you) — it must
    stay the REAL value even when execution fails; failure shows via the 'FAIL'
    label, not by zeroing the number. Regression guard for the old
    `hud_conf = 0.0 if not exec_ok` behaviour."""
    disp = _ExecutionMixin._confidence_display

    # Success: real % + confidence band.
    assert disp(0.97, True) == (97, "HIGH")
    assert disp(0.80, True) == (80, "MED")
    assert disp(0.50, True) == (50, "LOW")

    # Failure: SAME real % (not 0!) + FAIL label.
    assert disp(0.97, False) == (97, "FAIL")    # the bug: used to be (0, "FAIL")
    assert disp(0.97, False)[0] == 97           # explicit: percentage preserved
    assert disp(0.50, False) == (50, "FAIL")

    # Bounds are clamped; None-ish conf is safe.
    assert disp(1.0, True) == (100, "HIGH")
    assert disp(0.0, True) == (0, "LOW")


# ── follow-up narration line inherits the action's outcome rail ──────────────
#
# The post-execution narration (on a FAILURE, the "couldn't reach X — try Y" line)
# is appended via _on_action_followup_tts. It used to omit success → None → a
# neutral/info (cyan) rail even when the action failed, while the primary line above
# it showed red. success is now threaded through the signal so the explanatory line
# matches the primary line's rail.

def _followup_stub(token=11):
    import types
    from datetime import datetime
    from unittest.mock import MagicMock

    stub = types.SimpleNamespace()
    stub._transcript_update_token = token
    stub._history = [{"you": "open github", "jarvis": "On it."}]
    stub._session_start = datetime.now()
    stub._set_state = MagicMock()
    stub._tts_done_signal = types.SimpleNamespace(emit=MagicMock())
    stub._dashboard = types.SimpleNamespace(
        left=types.SimpleNamespace(
            transcript=types.SimpleNamespace(append_jarvis_scheduled=MagicMock()),
            status_lbl=types.SimpleNamespace(setText=MagicMock()),
        ),
    )
    stub._history_view = types.SimpleNamespace(refresh_history=MagicMock())
    stub._voice_view = types.SimpleNamespace(append_jarvis_continuation=MagicMock())
    return stub


def _run_followup(monkeypatch, *, success):
    import types
    import core.voice as cv
    monkeypatch.setattr(cv, "voice_engine",
                        types.SimpleNamespace(say=lambda *a, **k: None))
    stub = _followup_stub()
    _ExecutionMixin._on_action_followup_tts(
        stub, "Couldn't reach GitHub — check your connection.", "15:04",
        "browser_automation", 0.95, stub._transcript_update_token, success,
    )
    return stub


def test_followup_failure_line_gets_fail_rail(monkeypatch):
    stub = _run_followup(monkeypatch, success=False)
    kwargs = stub._dashboard.left.transcript.append_jarvis_scheduled.call_args.kwargs
    assert kwargs.get("success") is False     # red rail, matching the failed primary line


def test_followup_success_line_gets_ok_rail(monkeypatch):
    stub = _run_followup(monkeypatch, success=True)
    kwargs = stub._dashboard.left.transcript.append_jarvis_scheduled.call_args.kwargs
    assert kwargs.get("success") is True


def test_followup_default_success_is_backcompat():
    # The slot keeps a default so an un-migrated 5-arg emit still renders (success=True).
    import types
    from datetime import datetime
    from unittest.mock import MagicMock
    stub = _followup_stub()
    import core.voice as cv
    cv_saved = cv.voice_engine
    cv.voice_engine = types.SimpleNamespace(say=lambda *a, **k: None)
    try:
        _ExecutionMixin._on_action_followup_tts(
            stub, "Done.", "15:04", "open_app", 0.9, stub._transcript_update_token,
        )
        kwargs = stub._dashboard.left.transcript.append_jarvis_scheduled.call_args.kwargs
        assert kwargs.get("success") is True
    finally:
        cv.voice_engine = cv_saved
