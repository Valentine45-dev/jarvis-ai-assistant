"""Tests for the enable_workflow / disable_workflow automation actions.

These are the voice equivalent of the AUTOMATE-page ON/OFF toggle. They route
through ``_handle_automation_task`` and flip the workflow's ``enabled`` flag via
``WorkflowLibrary.set_enabled`` without touching the steps.

Covered:
  1. disable then enable flips the flag and reports the right verb.
  2. Idempotent — disabling an already-off (or enabling an already-on) workflow
     reports the current state and does not error.
  3. Unknown workflow → clean error, no crash.
  4. Missing task_name → clean error.
  5. Steps are preserved across a disable/enable cycle (non-destructive).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

import core.automation as automation
from core.handlers.automation_handler import _handle_automation_task


@pytest.fixture
def isolated_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[automation.WorkflowLibrary]:
    """Point WorkflowLibrary at a fresh tmp JSON and swap the module singleton
    so the handler's ``from core.automation import workflow_library`` picks it up.
    Seeds one enabled workflow ('demo') with two steps."""
    monkeypatch.setattr(automation, "_WORKFLOWS_PATH", tmp_path / "workflows.json")
    lib = automation.WorkflowLibrary()
    lib.add({
        "id": "demo", "name": "demo", "trigger": "Manual",
        "enabled": True, "last_run": "",
        "steps": [
            {"intent": "open_app", "action": "open_browser", "parameters": {"browser": "chrome"}},
            {"intent": "system_control", "action": "screenshot", "parameters": {}},
        ],
    })
    monkeypatch.setattr(automation, "workflow_library", lib)
    yield lib


def test_disable_then_enable_flips_flag(isolated_library: automation.WorkflowLibrary) -> None:
    r = _handle_automation_task("disable_workflow", {"task_name": "demo"})
    assert r["success"] is True
    assert "paused" in r["output"].lower()
    assert isolated_library.get("demo")["enabled"] is False

    r = _handle_automation_task("enable_workflow", {"task_name": "demo"})
    assert r["success"] is True
    assert "enabled" in r["output"].lower()
    assert isolated_library.get("demo")["enabled"] is True


def test_disable_is_idempotent(isolated_library: automation.WorkflowLibrary) -> None:
    _handle_automation_task("disable_workflow", {"task_name": "demo"})
    r = _handle_automation_task("disable_workflow", {"task_name": "demo"})
    assert r["success"] is True
    assert "already" in r["output"].lower()
    assert isolated_library.get("demo")["enabled"] is False


def test_enable_already_on_is_idempotent(isolated_library: automation.WorkflowLibrary) -> None:
    r = _handle_automation_task("enable_workflow", {"task_name": "demo"})
    assert r["success"] is True
    assert "already" in r["output"].lower()
    assert isolated_library.get("demo")["enabled"] is True


def test_unknown_workflow_errors_cleanly(isolated_library: automation.WorkflowLibrary) -> None:
    r = _handle_automation_task("disable_workflow", {"task_name": "nope"})
    assert r["success"] is False
    assert "not found" in (r.get("error") or r.get("output") or "").lower()


def test_missing_task_name_errors(isolated_library: automation.WorkflowLibrary) -> None:
    r = _handle_automation_task("enable_workflow", {})
    assert r["success"] is False


def test_toggle_preserves_steps(isolated_library: automation.WorkflowLibrary) -> None:
    before = isolated_library.get("demo")["steps"]
    _handle_automation_task("disable_workflow", {"task_name": "demo"})
    _handle_automation_task("enable_workflow", {"task_name": "demo"})
    after = isolated_library.get("demo")["steps"]
    assert after == before
    assert len(after) == 2
