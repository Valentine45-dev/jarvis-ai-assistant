"""P5 — vision_analysis runs OFF the Qt main thread (except source=browser).

Bug: vision_analysis dispatched synchronously on the Qt main thread, so its screen
capture + blocking Vision API call froze the UI. Most visible on the ctrl+shift+r
hotkey, which fires vision_analysis/describe from another app (nobody watching the
frozen window). Fix: route non-browser vision through the SAME worker harness as
code_execution. source=browser stays synchronous because vision.capture_browser_page()
uses Playwright, which is thread-affine to the main thread.
"""

from __future__ import annotations

import types

import pytest

pytest.importorskip("PyQt5")

from ui.main_window.execution_mixin import _ExecutionMixin  # noqa: E402


def _routing_stub():
    stub = types.SimpleNamespace()
    stub._OFFTHREAD_WORKFLOW_INTENTS = _ExecutionMixin._OFFTHREAD_WORKFLOW_INTENTS
    stub._ACTION_INTENTS = _ExecutionMixin._ACTION_INTENTS
    stub._workflow_is_offthread_safe = lambda result: (
        _ExecutionMixin._workflow_is_offthread_safe(stub, result)
    )
    stub._resolve_workflow_steps = lambda result: (
        _ExecutionMixin._resolve_workflow_steps(stub, result)
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


def _vision(params):
    return {"intent": "vision_analysis", "action": "describe", "parameters": params}


def _patch_dispatch(monkeypatch):
    import ui.main_window.execution_mixin as em
    dispatched = []
    monkeypatch.setattr(
        em, "dispatch",
        lambda *a, **k: dispatched.append((a, k)) or {"success": True, "output": "", "error": ""},
    )
    return dispatched


def test_vision_screenshot_routes_to_worker(monkeypatch):
    dispatched = _patch_dispatch(monkeypatch)
    stub = _routing_stub()
    _ExecutionMixin._execute_result(
        stub, _vision({"source": "screenshot"}), "vision_analysis", 0.99, "look", "VISION",
    )
    assert len(stub._spawn_calls) == 1, "screenshot vision must go off-thread"
    assert dispatched == [], "must NOT dispatch on the Qt main thread"
    assert stub._finish_calls == [], "finish happens later via the done-slot"


def test_vision_default_source_routes_to_worker(monkeypatch):
    # no source param -> defaults to screenshot -> off-thread
    dispatched = _patch_dispatch(monkeypatch)
    stub = _routing_stub()
    _ExecutionMixin._execute_result(
        stub, _vision({}), "vision_analysis", 0.99, "look", "VISION",
    )
    assert len(stub._spawn_calls) == 1
    assert dispatched == []


def test_vision_browser_source_stays_synchronous(monkeypatch):
    import core.memory
    monkeypatch.setattr(core.memory.memory, "inject_outcome", lambda **k: None)
    dispatched = _patch_dispatch(monkeypatch)
    stub = _routing_stub()
    _ExecutionMixin._execute_result(
        stub, _vision({"source": "browser"}), "vision_analysis", 0.99, "look", "VISION",
    )
    assert stub._spawn_calls == [], "browser-source vision must stay on the main thread (Playwright)"
    assert len(dispatched) == 1, "browser vision dispatches synchronously"
