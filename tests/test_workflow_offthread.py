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
    # Rail tests want the immediate-append path, so mark the primary already done.
    stub._primary_done_token = token
    stub._pending_narration = None
    stub._NARRATION_FALLBACK_MS = _ExecutionMixin._NARRATION_FALLBACK_MS
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


# ── narration sequencing: never append BEFORE the primary lands ───────────────
#
# Root cause of the "reply written twice" bug: the narration daemon runs
# CONCURRENTLY with the primary TTS. When it won the race it appended its row
# first, so the primary's on_ready update landed on the narration row instead of
# replacing the "Computing." placeholder — leaving an orphaned empty-[] / UNKNOWN
# row. Fix: buffer the narration until the primary for that token finishes
# (on_done), then flush; a fallback timer guarantees it's never lost. These tests
# FORCE the narration-before-primary ordering — they don't hope to hit the race.

class _FakeTranscript:
    """Faithful mirror of TranscriptPanel's row model: add_exchange / append create
    rows, update_last_jarvis edits the LAST row. Lets us assert WHICH row the primary
    and narration land on."""

    def __init__(self):
        self.rows = []   # each: [you, y_time, jarvis, j_time, intent, conf, success]

    def add_exchange(self, you, y_time, jarvis="", j_time="", intent="", conf=None, success=None):
        self.rows.append([you, y_time, jarvis, j_time, intent, conf, success])

    def update_last_jarvis(self, text, j_time="", intent="", conf=None, success=None):
        if not self.rows:
            return
        r = self.rows[-1]
        r[2] = text
        r[3] = j_time or r[3]
        if intent:
            r[4] = intent
        if conf is not None:
            r[5] = conf
        if success is not None:
            r[6] = success

    def append_jarvis_scheduled(self, jarvis, j_time, intent="", conf=None, success=None):
        self.rows.append(["", "", jarvis, j_time, intent, conf, success])


def _seq_stub(token=20, *, primary_done=False, monkeypatch=None):
    import types
    from datetime import datetime
    from unittest.mock import MagicMock

    stub = types.SimpleNamespace()
    stub._transcript_update_token = token
    stub._primary_done_token = token if primary_done else -1
    stub._pending_narration = None
    stub._NARRATION_FALLBACK_MS = _ExecutionMixin._NARRATION_FALLBACK_MS
    stub._history = [{"you": "open the website http://dead.example", "jarvis": ""}]
    stub._session_start = datetime.now()
    stub._set_state = MagicMock()
    stub._confirm_mode = None
    stub._tts_done_signal = types.SimpleNamespace(emit=MagicMock())
    stub._dashboard = types.SimpleNamespace(
        left=types.SimpleNamespace(
            transcript=_FakeTranscript(),
            status_lbl=types.SimpleNamespace(setText=MagicMock()),
        ),
    )
    stub._history_view = types.SimpleNamespace(refresh_history=MagicMock())
    stub._voice_view = types.SimpleNamespace(append_jarvis_continuation=MagicMock())
    stub._terminal_view = types.SimpleNamespace(append_jarvis_response=MagicMock())
    # Bind the real methods under test.
    stub._flush_pending_narration = lambda t, forced=False: (
        _ExecutionMixin._flush_pending_narration(stub, t, forced))
    stub._on_action_followup_tts = lambda *a, **k: (
        _ExecutionMixin._on_action_followup_tts(stub, *a, **k))
    stub._update_transcript_if_current = lambda *a, **k: (
        _ExecutionMixin._update_transcript_if_current(stub, *a, **k))
    return stub


def _silence_timer_and_voice(monkeypatch):
    import types
    import core.voice as cv
    import ui.main_window.execution_mixin as em
    monkeypatch.setattr(cv, "voice_engine",
                        types.SimpleNamespace(say=lambda *a, **k: None))
    armed = []
    monkeypatch.setattr(
        em.QTimer, "singleShot",
        staticmethod(lambda ms, cb: armed.append((ms, cb))))
    return armed


def test_narration_before_primary_is_buffered_then_flushed(monkeypatch):
    """The full bug scenario, with narration FORCED to arrive before the primary."""
    armed = _silence_timer_and_voice(monkeypatch)
    T = 20
    stub = _seq_stub(T, primary_done=False)
    tr = stub._dashboard.left.transcript

    # 1) The command row exists with the "Computing." thinking placeholder (empty []
    #    timestamp, no intent) — exactly the live state when narration wins the race.
    tr.add_exchange("open the website http://dead.example", "17:17")
    tr.update_last_jarvis("Computing.", "", "", None)
    assert len(tr.rows) == 1

    # 2) Narration arrives BEFORE the primary lands → must BUFFER, not append.
    stub._on_action_followup_tts(
        "Looks like a DNS miss — check the address.", "17:17",
        "browser_automation", 0.97, T, False)
    assert len(tr.rows) == 1, "narration must NOT append before the primary lands"
    assert stub._pending_narration is not None, "narration must be buffered"
    assert armed, "a fallback timer must be armed so the narration can't be lost"

    # 3) Primary lands on the COMMAND row (replaces 'Computing.', real ts + chips).
    stub._update_transcript_if_current(
        T, "Couldn't load dead.example. net::ERR_NAME_NOT_RESOLVED",
        "17:17", "browser_automation", 0.97, False)
    assert tr.rows[0][2].startswith("Couldn't load"), "primary must replace 'Computing.'"
    assert tr.rows[0][3] == "17:17"                 # real timestamp, not []
    assert tr.rows[0][4] == "browser_automation"    # real intent chip
    assert tr.rows[0][5] == 0.97                     # real conf chip

    # 4) Primary finishes → flush the buffered narration as its OWN row, AFTER.
    stub._primary_done_token = T
    stub._flush_pending_narration(T)
    assert len(tr.rows) == 2, "narration appends as a second row after the primary"
    assert tr.rows[1][2] == "Looks like a DNS miss — check the address."
    assert tr.rows[1][0] == ""                       # JARVIS-only row (no YOU)

    # No orphaned 'Computing.' row survives anywhere.
    assert all("Computing." not in (r[2] or "") for r in tr.rows)
    assert stub._pending_narration is None


def test_narration_after_primary_appends_immediately(monkeypatch):
    # Control: when the primary already finished, the narration appends right away
    # (no buffering) — the normal, non-racing path.
    _silence_timer_and_voice(monkeypatch)
    T = 21
    stub = _seq_stub(T, primary_done=True)
    tr = stub._dashboard.left.transcript
    tr.add_exchange("open github", "17:18")
    tr.update_last_jarvis("On it.", "17:18", "open_app", 0.98)

    stub._on_action_followup_tts("Want me to navigate?", "17:18", "open_app", 0.98, T, True)
    assert len(tr.rows) == 2
    assert tr.rows[1][2] == "Want me to navigate?"
    assert stub._pending_narration is None


def test_narration_fallback_flushes_when_primary_never_signals(monkeypatch):
    # MANDATORY fallback: if the primary never marks itself done (e.g. the say()
    # exception path fires no on_done), the armed timer force-flushes so the
    # narration is NEVER lost.
    armed = _silence_timer_and_voice(monkeypatch)
    T = 22
    stub = _seq_stub(T, primary_done=False)
    tr = stub._dashboard.left.transcript
    tr.add_exchange("open the website http://dead.example", "17:19")
    tr.update_last_jarvis("Computing.", "", "", None)

    stub._on_action_followup_tts("DNS failed — try the full URL.", "17:19",
                                 "browser_automation", 0.97, T, False)
    assert stub._pending_narration is not None and armed

    # Fire the armed fallback timer (primary on_done never came).
    _ms, cb = armed[-1]
    cb()
    assert any(r[2] == "DNS failed — try the full URL." for r in tr.rows), \
        "fallback must flush the buffered narration so it's not lost"
    assert stub._pending_narration is None


def test_narration_dropped_when_command_superseded(monkeypatch):
    # If a newer command started before the buffered narration flushes, it's a stale
    # line and must be dropped (not appended onto the new command's rows).
    armed = _silence_timer_and_voice(monkeypatch)
    T = 23
    stub = _seq_stub(T, primary_done=False)
    tr = stub._dashboard.left.transcript
    tr.add_exchange("open the website http://dead.example", "17:20")
    tr.update_last_jarvis("Computing.", "", "", None)
    stub._on_action_followup_tts("stale narration", "17:20",
                                 "browser_automation", 0.97, T, False)

    stub._transcript_update_token = T + 1     # a newer command supersedes
    _ms, cb = armed[-1]
    cb()                                       # fallback fires for the OLD token
    assert all(r[2] != "stale narration" for r in tr.rows), \
        "a superseded narration must not append onto a newer command"
