"""R3-18: the workflow file-watcher daemon must start lazily (on first read),
not as a side effect of constructing WorkflowLibrary / importing core.automation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

import core.automation as automation


@pytest.fixture
def fresh_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Point at a non-existent tmp file so construction's _load is a clean no-op.
    monkeypatch.setattr(automation, "_WORKFLOWS_PATH", tmp_path / "workflows.json")
    yield


def test_watcher_not_started_at_construction(fresh_path: None) -> None:
    lib = automation.WorkflowLibrary()
    assert lib._watcher_started is False           # no background poller yet


def test_watcher_starts_on_first_list_all(fresh_path: None) -> None:
    lib = automation.WorkflowLibrary()
    lib.list_all()
    assert lib._watcher_started is True


def test_watcher_starts_on_first_get(fresh_path: None) -> None:
    lib = automation.WorkflowLibrary()
    lib.get("anything")
    assert lib._watcher_started is True


def test_ensure_watcher_is_idempotent(fresh_path: None) -> None:
    lib = automation.WorkflowLibrary()
    lib.list_all()
    lib.list_all()
    lib.get("x")
    assert lib._watcher_started is True            # still just one start, no error
