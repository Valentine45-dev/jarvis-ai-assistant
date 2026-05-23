"""Tests for core.workflow_metrics — the per-step latency store.

Covers the four behaviours that matter for the UI surface and the workflow
runner:
  1. Recording a sample persists it; subsequent ``get_avg`` returns the mean.
  2. The rolling window caps stored samples at the most recent ``_WINDOW``.
  3. Missing workflow / missing step / unknown id returns ``None`` cleanly.
  4. Empty workflow_id and negative durations no-op (defensive).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

import core.workflow_metrics as wm


@pytest.fixture
def isolated_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[wm.WorkflowMetrics]:
    """Point the metrics store at a fresh tmp JSON for the test, then yield
    a brand-new instance bound to that file. Restores module-level singleton
    state on teardown so other tests aren't affected."""
    test_path = tmp_path / "workflow_metrics.json"
    monkeypatch.setattr(wm, "_METRICS_PATH", test_path)
    instance = wm.WorkflowMetrics()
    yield instance


def test_record_then_get_avg_returns_mean(isolated_metrics: wm.WorkflowMetrics) -> None:
    isolated_metrics.record("morning_routine", 0, 0.3)
    isolated_metrics.record("morning_routine", 0, 0.5)
    isolated_metrics.record("morning_routine", 0, 0.4)
    assert isolated_metrics.get_avg("morning_routine", 0) == pytest.approx(0.4)


def test_get_avg_unknown_workflow_returns_none(isolated_metrics: wm.WorkflowMetrics) -> None:
    assert isolated_metrics.get_avg("does_not_exist", 0) is None


def test_get_avg_unknown_step_returns_none(isolated_metrics: wm.WorkflowMetrics) -> None:
    isolated_metrics.record("mr", 0, 0.1)
    assert isolated_metrics.get_avg("mr", 999) is None


def test_rolling_window_caps_at_ten(isolated_metrics: wm.WorkflowMetrics) -> None:
    # Push 15 samples; only the last 10 should remain. With samples 6-15
    # (1-indexed) i.e. values 6..15, the mean is 10.5.
    for i in range(1, 16):
        isolated_metrics.record("wf", 0, float(i))
    avg = isolated_metrics.get_avg("wf", 0)
    assert avg == pytest.approx(10.5)


def test_empty_workflow_id_is_noop(isolated_metrics: wm.WorkflowMetrics) -> None:
    # Inline workflows don't carry an id — record() must silently ignore them
    # rather than writing under a "" key (which would corrupt the bucket).
    isolated_metrics.record("", 0, 0.5)
    assert isolated_metrics.get_avg("", 0) is None


def test_negative_duration_is_noop(isolated_metrics: wm.WorkflowMetrics) -> None:
    isolated_metrics.record("wf", 0, -1.0)
    assert isolated_metrics.get_avg("wf", 0) is None


def test_persistence_across_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second instance bound to the same file picks up prior records."""
    test_path = tmp_path / "workflow_metrics.json"
    monkeypatch.setattr(wm, "_METRICS_PATH", test_path)
    first = wm.WorkflowMetrics()
    first.record("mr", 2, 1.5)
    first.record("mr", 2, 2.5)
    second = wm.WorkflowMetrics()
    assert second.get_avg("mr", 2) == pytest.approx(2.0)


def test_reset_clears_one_workflow(isolated_metrics: wm.WorkflowMetrics) -> None:
    isolated_metrics.record("wf_a", 0, 0.1)
    isolated_metrics.record("wf_b", 0, 0.2)
    isolated_metrics.reset("wf_a")
    assert isolated_metrics.get_avg("wf_a", 0) is None
    assert isolated_metrics.get_avg("wf_b", 0) == pytest.approx(0.2)


def test_reset_all_clears_everything(isolated_metrics: wm.WorkflowMetrics) -> None:
    isolated_metrics.record("wf_a", 0, 0.1)
    isolated_metrics.record("wf_b", 0, 0.2)
    isolated_metrics.reset()
    assert isolated_metrics.get_avg("wf_a", 0) is None
    assert isolated_metrics.get_avg("wf_b", 0) is None
