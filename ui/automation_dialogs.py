"""Compatibility shim for moved automation dialogs module."""

from ui.views.automation.dialogs import ConfirmDeleteDialog, GlassDialog, NewWorkflowDialog

__all__ = ["GlassDialog", "NewWorkflowDialog", "ConfirmDeleteDialog"]
