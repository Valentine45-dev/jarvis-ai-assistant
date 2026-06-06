"""
Named workflow library.

Loads and persists workflow definitions in data/workflows.json.
Each workflow is a dict:
  {
    "id":       str   — slug used for lookup ("morning_routine")
    "name":     str   — display name ("Morning Routine")
    "trigger":  str   — human label ("Manual", "Daily 7:00 AM")
    "enabled":  bool
    "last_run": str   — ISO timestamp of last execution, "" if never
    "steps":    list  — [{intent, action, parameters}, ...]
  }

The executor calls workflow_library.get(task_name) when brain.py routes
an automation_task/run_workflow command with task_name but no inline steps.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.log import debug as _dbg, info as _info

_WORKFLOWS_PATH = Path(__file__).parent.parent / "data" / "workflows.json"

# How often the mtime watcher checks data/workflows.json. 2s is fast enough
# that hand-edits show up before the user can ask for "list workflows" again,
# slow enough to be free at idle.
_WATCH_POLL_SECONDS = 2.0


def _emit_changed() -> None:
    try:
        from core.signals import signals
        signals.workflow_library_changed.emit()
    except Exception:
        pass


class WorkflowLibrary:
    """Thread-safe named workflow store backed by data/workflows.json."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._workflows: dict[str, dict] = {}
        # mtime of workflows.json the last time we read or wrote it. The
        # background watcher diffs against this to detect external edits.
        # R3-22: _save() records OUR write's exact mtime here, so the watcher
        # skips only that precise value. A concurrent external edit produces a
        # different mtime and is no longer mistaken for our own write (the old
        # one-tick boolean skip could adopt an external mtime and drop the edit).
        self._last_mtime: float = 0.0
        # R3-18: the file-watcher daemon starts LAZILY on first read (get /
        # list_all), not at import time — so merely importing core.automation
        # (e.g. in tests/CLI/headless reuse) has no background-I/O side effect.
        self._watcher_started: bool = False
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not _WORKFLOWS_PATH.exists():
            return
        try:
            data = json.loads(_WORKFLOWS_PATH.read_text(encoding="utf-8"))
            with self._lock:
                self._workflows = {w["id"]: w for w in data.get("workflows", [])}
                try:
                    self._last_mtime = _WORKFLOWS_PATH.stat().st_mtime
                except OSError:
                    self._last_mtime = 0.0
        except Exception as exc:
            # Surface the error so a malformed workflows.json is diagnosable.
            _dbg("automation", f"Failed to load {_WORKFLOWS_PATH}: {exc}")

    def _save(self) -> None:
        # Caller must hold self._lock.
        # Write atomically via tmp+os.replace so a crash mid-write leaves the
        # previous version of workflows.json intact rather than truncated.
        data = {"workflows": list(self._workflows.values())}
        tmp = _WORKFLOWS_PATH.with_suffix(_WORKFLOWS_PATH.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, _WORKFLOWS_PATH)
            # R3-22: record OUR write's exact mtime as the baseline. The watcher
            # skips when the observed mtime equals this; an external edit (a
            # different mtime) is no longer mistaken for our own write.
            try:
                self._last_mtime = _WORKFLOWS_PATH.stat().st_mtime
            except OSError:
                pass
        except Exception as exc:
            _dbg("automation", f"Failed to save {_WORKFLOWS_PATH}: {exc}")
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

    # ── External-edit watcher ─────────────────────────────────────────────────

    def _ensure_watcher(self) -> None:
        """R3-18: start the watcher once, on first read. Idempotent + thread-safe."""
        with self._lock:
            if self._watcher_started:
                return
            self._watcher_started = True
        self._start_watcher()

    def _start_watcher(self) -> None:
        """Start a daemon thread that polls workflows.json's mtime.

        When the file changes underneath us (manual hand-edit, git pull, …),
        reload from disk and emit workflow_library_changed so the UI refreshes.
        Our own _save() updates _last_mtime to the written mtime, so the tick
        that observes our write skips without a phantom reload (R3-22).
        """
        t = threading.Thread(
            target=self._watch_loop,
            name="WorkflowLibraryWatcher",
            daemon=True,
        )
        t.start()

    def _watch_loop(self) -> None:
        while True:
            time.sleep(_WATCH_POLL_SECONDS)
            self._watch_tick()

    def _watch_tick(self) -> None:
        """One watcher pass: reload workflows.json iff it changed externally.
        Extracted from the loop so it's unit-testable without the 2 s sleep."""
        try:
            mtime = _WORKFLOWS_PATH.stat().st_mtime
        except OSError:
            # File temporarily missing (rename-in-progress, network share
            # hiccup) — skip this tick and try again.
            return

        with self._lock:
            # R3-22: skip only when the observed mtime is exactly the one our
            # own _save() recorded (or unchanged). An external edit lands on a
            # different mtime → falls through to reload, even right after our
            # write (the old one-tick boolean would have swallowed it).
            if mtime == self._last_mtime:
                return

        # File changed externally — reload. _load() takes the lock itself.
        try:
            raw = _WORKFLOWS_PATH.read_text(encoding="utf-8")
        except OSError:
            # Editor mid-write (Notepad truncates then writes). Wait for
            # the next tick — _last_mtime stays unchanged, so we'll retry.
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            # Editor saved a partial/invalid JSON. Don't clobber the
            # in-memory library; just log and try again next tick.
            _dbg("automation", f"workflows.json change ignored — invalid JSON: {exc}")
            return

        with self._lock:
            self._workflows = {w["id"]: w for w in data.get("workflows", [])}
            self._last_mtime = mtime
            count = len(self._workflows)
        _info("automation", f"workflows.json changed on disk — reloaded {count} workflows")
        _emit_changed()

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, name: str) -> dict[str, Any] | None:
        """Look up a workflow by id or display name (case-insensitive)."""
        self._ensure_watcher()
        with self._lock:
            # R3-14: deepcopy so callers that mutate the returned workflow's
            # nested `steps` list don't corrupt the authoritative in-memory copy
            # (a shallow dict() shares the same steps list by reference).
            # Exact id match
            if name in self._workflows:
                return copy.deepcopy(self._workflows[name])
            # Normalised id (e.g. "Morning Routine" → "morning_routine")
            slug = name.lower().replace(" ", "_")
            if slug in self._workflows:
                return copy.deepcopy(self._workflows[slug])
            # Display-name match
            low = name.lower()
            for wf in self._workflows.values():
                if wf.get("name", "").lower() == low:
                    return copy.deepcopy(wf)
        return None

    def list_all(self) -> list[dict]:
        """Return all workflows as a list (deep copy — see R3-14)."""
        self._ensure_watcher()
        with self._lock:
            return [copy.deepcopy(w) for w in self._workflows.values()]

    def add(self, workflow: dict) -> None:
        """Add or replace a workflow, persist, and notify the UI."""
        with self._lock:
            self._workflows[workflow["id"]] = workflow
            self._save()
        _emit_changed()

    def remove(self, workflow_id: str) -> bool:
        """Remove a workflow by id. Returns False if not found."""
        with self._lock:
            if workflow_id not in self._workflows:
                return False
            del self._workflows[workflow_id]
            self._save()
        _emit_changed()
        return True

    def rename(self, workflow_id: str, new_name: str) -> bool:
        """Rename a workflow by id. Returns False if not found or new name taken."""
        new_slug = new_name.lower().replace(" ", "_")
        with self._lock:
            if workflow_id not in self._workflows:
                return False
            if new_slug in self._workflows and new_slug != workflow_id:
                return False
            wf = self._workflows.pop(workflow_id)
            wf["id"] = new_slug
            wf["name"] = new_name
            self._workflows[new_slug] = wf
            self._save()
        _emit_changed()
        return True

    def set_enabled(self, workflow_id: str, enabled: bool) -> bool:
        """Toggle a workflow's enabled flag. Returns False if not found."""
        with self._lock:
            if workflow_id not in self._workflows:
                return False
            self._workflows[workflow_id]["enabled"] = enabled
            self._save()
        _emit_changed()
        return True

    def mark_run(self, workflow_id: str) -> None:
        """Record the current UTC timestamp as last_run for the workflow."""
        changed = False
        with self._lock:
            if workflow_id in self._workflows:
                self._workflows[workflow_id]["last_run"] = (
                    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                )
                self._save()
                changed = True
        if changed:
            _emit_changed()


# Module-level singleton — imported by executor.py and ui/automation.py
workflow_library = WorkflowLibrary()
