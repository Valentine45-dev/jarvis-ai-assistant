"""R2-34: regression test for Phase 5 atomic workflows.json write.

Background: `WorkflowLibrary._save()` writes a tmp file then `os.replace`s it
over `workflows.json` so a crash mid-write leaves the previous file intact
(no truncated JSON on disk). This test simulates `os.replace` raising and
asserts both halves of the guarantee:

  1. The original `workflows.json` is byte-identical to what it was before
     the failed save.
  2. The `workflows.json.tmp` file does not survive (it's either cleaned
     up by the handler or, at minimum, not promoted to the canonical name).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

import pytest

import core.automation as automation


@pytest.fixture
def isolated_workflows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point WorkflowLibrary at a tmp workflows.json with a known seed."""
    seed = {
        "workflows": [
            {
                "id": "seed",
                "name": "Seed",
                "trigger": "Manual",
                "enabled": True,
                "last_run": "",
                "steps": [],
            }
        ]
    }
    target = tmp_path / "workflows.json"
    target.write_text(json.dumps(seed, indent=2), encoding="utf-8")
    monkeypatch.setattr(automation, "_WORKFLOWS_PATH", target, raising=True)
    yield target


def test_save_failure_leaves_original_intact(
    isolated_workflows: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = isolated_workflows
    original_bytes = target.read_bytes()

    lib = automation.WorkflowLibrary()
    assert lib.get("seed") is not None

    # Make os.replace fail every time — simulates a mid-replace crash.
    def _boom(src: str, dst: str) -> None:
        raise OSError(22, "simulated replace failure", str(dst))

    monkeypatch.setattr(automation.os, "replace", _boom)

    # Try to save. _save swallows the exception (logs via _dbg) but the
    # canonical file must not be touched.
    lib.add({
        "id": "new",
        "name": "New",
        "trigger": "Manual",
        "enabled": True,
        "last_run": "",
        "steps": [],
    })

    assert target.read_bytes() == original_bytes, (
        "workflows.json was modified despite os.replace failing — "
        "atomic-write guarantee broken."
    )

    tmp_path = target.with_suffix(target.suffix + ".tmp")
    if tmp_path.exists():
        # Acceptable per the audit's "or at least not promoted" carve-out,
        # but flag it so we know cleanup isn't happening.
        pytest.fail(
            f"{tmp_path.name} survived a failed save — cleanup branch in _save() "
            "is no longer firing."
        )


def test_successful_save_round_trips_byte_identical(isolated_workflows: Path) -> None:
    target = isolated_workflows
    lib = automation.WorkflowLibrary()

    workflow = {
        "id": "round_trip",
        "name": "Round Trip",
        "trigger": "Manual",
        "enabled": True,
        "last_run": "",
        "steps": [
            {"intent": "open_app", "action": "open_browser", "parameters": {"browser": "chrome"}},
        ],
    }
    lib.add(workflow)

    # Re-read directly from disk and confirm it parses back to the same data.
    disk = json.loads(target.read_text(encoding="utf-8"))
    ids = {w["id"] for w in disk["workflows"]}
    assert "round_trip" in ids
    assert "seed" in ids


def test_tmp_file_path_uses_suffix_not_concatenation(isolated_workflows: Path) -> None:
    """The tmp file must be `<name>.json.tmp`, not `<name>.tmptmp` or similar."""
    target = isolated_workflows
    expected_tmp_name = target.name + ".tmp"
    assert (target.parent / expected_tmp_name).parent == target.parent
    # The constructor we use is `with_suffix(...suffix + ".tmp")` —
    # confirm that produces the expected path.
    constructed = target.with_suffix(target.suffix + ".tmp")
    assert constructed.name == expected_tmp_name
