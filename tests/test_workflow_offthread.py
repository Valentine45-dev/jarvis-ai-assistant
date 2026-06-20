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
    return _ExecutionMixin._workflow_is_offthread_safe(stub, result)


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
    # search_web / open_app can drive the Playwright session; jarvis_meta isn't vetted.
    assert _eligible(_wf([
        {"intent": "search_web", "action": "google_search", "parameters": {}},
    ])) is False
    assert _eligible(_wf([
        {"intent": "open_app", "action": "open_browser", "parameters": {}},
    ])) is False
    assert _eligible(_wf([
        {"intent": "jarvis_meta", "action": "change_theme", "parameters": {}},
    ])) is False


def test_empty_or_missing_steps_are_ineligible():
    assert _eligible(_wf([])) is False
    assert _eligible({"intent": "automation_task", "action": "run_workflow",
                      "parameters": {}}) is False


# ── routing in _execute_result ──────────────────────────────────────────────


def _routing_stub():
    stub = types.SimpleNamespace()
    stub._OFFTHREAD_WORKFLOW_INTENTS = _ExecutionMixin._OFFTHREAD_WORKFLOW_INTENTS
    stub._ACTION_INTENTS = _ExecutionMixin._ACTION_INTENTS
    # Bind the real classifier so _execute_result's self._workflow_is_offthread_safe works.
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
