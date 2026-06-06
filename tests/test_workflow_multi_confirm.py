"""Regression: a workflow with TWO confirmation steps must resume through both.

This reproduces the exact bug the R3-6 fix first introduced: the workflow runner
re-registers a leaf step's confirmation by WRAPPING it with a resume continuation
(replace_confirmation) while the slot is still occupied. An over-strict guard on
that path made the whole workflow fail with "Please resolve the current
confirmation first." before creating anything.

The fake dispatch mimics a confirm-required leaf (like create_file) by calling
request_confirmation itself and returning needs_confirmation — same shape the
real executor produces — so the workflow runner exercises the real wrap path.
"""

from __future__ import annotations

import pytest

import core.executor as ex
from core.handlers.automation_handler import _handle_automation_task
from core.handlers.shared import (
    abandon_pending_confirmation,
    get_pending_confirmation,
    request_confirmation,
    resolve_confirmation,
)


@pytest.fixture(autouse=True)
def _clean_slot() -> None:
    abandon_pending_confirmation()
    yield
    abandon_pending_confirmation()


def _install_fake_dispatch(monkeypatch: pytest.MonkeyPatch, executed: list[str]) -> None:
    def fake_dispatch(step: dict, **_kw) -> dict:
        if step.get("action") == "create_file":
            name = step.get("parameters", {}).get("path")

            def _leaf(name=name) -> dict:
                executed.append(name)
                return {"success": True, "output": f"created {name}", "error": ""}

            return request_confirmation(f"Create {name}?", _leaf)
        return {"success": True, "output": "ok", "error": ""}

    monkeypatch.setattr(ex, "dispatch", fake_dispatch)


def test_two_confirm_workflow_resumes_through_both(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: list[str] = []
    _install_fake_dispatch(monkeypatch, executed)

    wf = {"steps": [
        {"intent": "file_operation", "action": "create_file", "parameters": {"path": "r6a.txt"}},
        {"intent": "file_operation", "action": "create_file", "parameters": {"path": "r6b.txt"}},
    ]}

    # Step 1 pauses for confirmation — must NOT fail with "resolve the current
    # confirmation first" (the regression). Nothing created yet.
    out = _handle_automation_task("run_workflow", wf)
    assert out.get("needs_confirmation") is True, out
    assert executed == []
    assert get_pending_confirmation() is not None

    # Confirm step 1 → leaf creates r6a, workflow advances to step 2's confirm.
    out = resolve_confirmation("yes")
    assert executed == ["r6a.txt"]
    assert out.get("needs_confirmation") is True
    assert get_pending_confirmation() is not None

    # Confirm step 2 → leaf creates r6b, workflow completes.
    out = resolve_confirmation("yes")
    assert executed == ["r6a.txt", "r6b.txt"]
    assert out.get("success") is True
    assert get_pending_confirmation() is None


def test_declining_first_confirm_stops_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: list[str] = []
    _install_fake_dispatch(monkeypatch, executed)

    wf = {"steps": [
        {"intent": "file_operation", "action": "create_file", "parameters": {"path": "r6a.txt"}},
        {"intent": "file_operation", "action": "create_file", "parameters": {"path": "r6b.txt"}},
    ]}

    out = _handle_automation_task("run_workflow", wf)
    assert out.get("needs_confirmation") is True

    # "no" → stand down: nothing created, no lingering pending slot.
    out = resolve_confirmation("no")
    assert executed == []
    assert get_pending_confirmation() is None
