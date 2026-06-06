"""R3-22: an external edit to workflows.json right after JARVIS's own save must
still be picked up — the old one-tick boolean skip could adopt the external
mtime as the baseline and silently drop the edit.

Drives _watch_tick() directly (extracted from the 2 s poll loop) with explicit
mtimes so the timing is deterministic.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

import pytest

import core.automation as automation


@pytest.fixture
def lib(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[automation.WorkflowLibrary]:
    monkeypatch.setattr(automation, "_WORKFLOWS_PATH", tmp_path / "workflows.json")
    yield automation.WorkflowLibrary()


def _write(path: Path, workflows: list[dict], mtime: float) -> None:
    path.write_text(json.dumps({"workflows": workflows}), encoding="utf-8")
    os.utime(path, (mtime, mtime))                 # pin mtime so the test is deterministic


def test_external_edit_after_save_is_reloaded(lib: automation.WorkflowLibrary, tmp_path: Path) -> None:
    path = tmp_path / "workflows.json"

    # JARVIS's own save records its write mtime as the baseline.
    lib.add({"id": "ours", "name": "ours", "enabled": True, "steps": []})
    assert lib.get("ours") is not None

    # An external edit lands with a DIFFERENT mtime (hand-edit / git pull).
    _write(path, [{"id": "external", "name": "external", "enabled": True, "steps": []}],
           mtime=lib._last_mtime + 5.0)

    lib._watch_tick()

    # The external edit must be reflected, not swallowed.
    assert lib.get("external") is not None
    assert lib.get("ours") is None


def test_unchanged_mtime_does_not_reload(lib: automation.WorkflowLibrary) -> None:
    lib.add({"id": "ours", "name": "ours", "enabled": True, "steps": []})
    # No file change → mtime equals the recorded baseline → no reload, no error.
    lib._watch_tick()
    assert lib.get("ours") is not None


def test_invalid_json_is_ignored(lib: automation.WorkflowLibrary, tmp_path: Path) -> None:
    path = tmp_path / "workflows.json"
    lib.add({"id": "ours", "name": "ours", "enabled": True, "steps": []})
    # Editor mid-write: bump mtime but leave invalid JSON → keep in-memory intact.
    path.write_text("{ not valid json", encoding="utf-8")
    os.utime(path, (lib._last_mtime + 5.0, lib._last_mtime + 5.0))
    lib._watch_tick()
    assert lib.get("ours") is not None             # not clobbered by the bad write
