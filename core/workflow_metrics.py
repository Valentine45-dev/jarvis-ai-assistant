"""Per-step latency telemetry for workflows.

A small companion store to ``core.automation.workflow_library`` that
records how long each step of a workflow took on its last N runs and
exposes the rolling mean.

Why a separate file from ``data/workflows.json``:
  - Workflow definitions are user-curated config; metrics are noisy
    runtime data. Mixing them would make hand-editing workflows.json
    painful (every run rewrites the file).
  - The library is reload-aware via a file watcher; metrics writes
    would constantly trip it. Keeping them separate avoids the churn.

The schema is intentionally tiny — a flat dict keyed by workflow id,
each value a dict keyed by stringified step index (JSON doesn't allow
int keys at the top level of a nested object reliably). Values are
lists of float seconds, capped at the most recent ``_WINDOW`` samples.

Public API:
  workflow_metrics.record(workflow_id, step_index, duration_seconds)
  workflow_metrics.get_avg(workflow_id, step_index) -> float | None
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

from core.log import debug as _dbg


_METRICS_PATH = Path(__file__).parent.parent / "data" / "workflow_metrics.json"

# How many of the most recent samples to keep per (workflow, step). Bigger
# windows smooth out outliers but lag behind genuine speedups; 10 is a
# decent balance for the kind of workflows JARVIS runs (a few times a day
# at most).
_WINDOW = 10


class WorkflowMetrics:
    """Thread-safe persistent store of per-step durations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # { workflow_id: { "step_index_str": [duration_seconds, ...] } }
        self._data: dict[str, dict[str, list[float]]] = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not _METRICS_PATH.exists():
            return
        try:
            raw = json.loads(_METRICS_PATH.read_text(encoding="utf-8"))
            metrics = raw.get("metrics") if isinstance(raw, dict) else None
            if isinstance(metrics, dict):
                # Defensive: keep only well-shaped entries. Anything funky on
                # disk gets dropped silently rather than crashing the app.
                clean: dict[str, dict[str, list[float]]] = {}
                for wf_id, steps in metrics.items():
                    if not isinstance(steps, dict):
                        continue
                    step_clean: dict[str, list[float]] = {}
                    for k, samples in steps.items():
                        if not isinstance(samples, list):
                            continue
                        step_clean[str(k)] = [
                            float(s) for s in samples
                            if isinstance(s, (int, float)) and s >= 0
                        ]
                    if step_clean:
                        clean[str(wf_id)] = step_clean
                with self._lock:
                    self._data = clean
        except Exception as exc:
            _dbg("workflow_metrics", f"Failed to load {_METRICS_PATH}: {exc}")

    def _save(self) -> None:
        # Caller must hold self._lock.
        # Atomic write via tmp+replace so a crash mid-write leaves the previous
        # metrics file intact rather than truncated.
        payload = {"metrics": self._data}
        tmp = _METRICS_PATH.with_suffix(_METRICS_PATH.suffix + ".tmp")
        try:
            _METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, _METRICS_PATH)
        except Exception as exc:
            _dbg("workflow_metrics", f"Failed to save {_METRICS_PATH}: {exc}")
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

    # ── Public API ────────────────────────────────────────────────────────────

    def record(self, workflow_id: str, step_index: int, duration_seconds: float) -> None:
        """Append a duration sample and persist. No-ops for empty workflow_id
        (inline workflows have no stable identity)."""
        if not workflow_id or duration_seconds < 0:
            return
        key = str(step_index)
        with self._lock:
            steps = self._data.setdefault(workflow_id, {})
            samples = steps.setdefault(key, [])
            samples.append(float(duration_seconds))
            # Trim from the front so we keep the most recent _WINDOW.
            if len(samples) > _WINDOW:
                del samples[: len(samples) - _WINDOW]
            self._save()

    def get_avg(self, workflow_id: str, step_index: int) -> Optional[float]:
        """Mean of the stored samples, or None when nothing's been recorded."""
        if not workflow_id:
            return None
        key = str(step_index)
        with self._lock:
            steps = self._data.get(workflow_id)
            if not steps:
                return None
            samples = steps.get(key)
            if not samples:
                return None
            return sum(samples) / len(samples)

    def reset(self, workflow_id: Optional[str] = None) -> None:
        """Clear metrics for one workflow, or all when workflow_id is None.

        Used by tests and (potentially) a future 'reset stats' UI affordance.
        """
        with self._lock:
            if workflow_id is None:
                self._data = {}
            else:
                self._data.pop(workflow_id, None)
            self._save()


# Module-level singleton — imported by the workflow runner + StepBreakdown.
workflow_metrics = WorkflowMetrics()
