"""Compatibility shim for moved automation components module."""

from ui.views.automation.components import StepBreakdown, WorkflowRow, step_label

__all__ = ["WorkflowRow", "StepBreakdown", "step_label"]
