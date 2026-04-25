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

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

_WORKFLOWS_PATH = Path(__file__).parent.parent / "data" / "workflows.json"


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
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not _WORKFLOWS_PATH.exists():
            return
        try:
            data = json.loads(_WORKFLOWS_PATH.read_text(encoding="utf-8"))
            with self._lock:
                self._workflows = {w["id"]: w for w in data.get("workflows", [])}
        except Exception as exc:
            # Surface the error so a malformed workflows.json is diagnosable.
            print(f"[automation] Failed to load {_WORKFLOWS_PATH}: {exc}")

    def _save(self) -> None:
        # Caller must hold self._lock.
        data = {"workflows": list(self._workflows.values())}
        _WORKFLOWS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, name: str) -> dict[str, Any] | None:
        """Look up a workflow by id or display name (case-insensitive)."""
        with self._lock:
            # Exact id match
            if name in self._workflows:
                return dict(self._workflows[name])
            # Normalised id (e.g. "Morning Routine" → "morning_routine")
            slug = name.lower().replace(" ", "_")
            if slug in self._workflows:
                return dict(self._workflows[slug])
            # Display-name match
            low = name.lower()
            for wf in self._workflows.values():
                if wf.get("name", "").lower() == low:
                    return dict(wf)
        return None

    def list_all(self) -> list[dict]:
        """Return all workflows as a list (copy)."""
        with self._lock:
            return [dict(w) for w in self._workflows.values()]

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
                    datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                )
                self._save()
                changed = True
        if changed:
            _emit_changed()


# Module-level singleton — imported by executor.py and ui/automation.py
workflow_library = WorkflowLibrary()
