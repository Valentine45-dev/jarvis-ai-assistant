"""Confirmation-flow routing for JarvisWindow (R2-17a split).

Plain mixin — no QObject base, no signals defined here. Methods use only
``self``. Must NOT import ``window`` or ``app`` (no import cycle).
"""

from __future__ import annotations


class _ConfirmMixin:
    """Confirm-card show/hide, confirmation resolution, and the
    ``_resume_executor_confirm`` main-thread hand-off.

    Bodies are moved here in Slice 7; empty until then.
    """
