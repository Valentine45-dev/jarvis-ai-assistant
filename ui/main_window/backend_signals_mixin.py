"""Backend-signal slots for JarvisWindow (R2-17a split).

Plain mixin — no QObject base, no signals defined here. Methods use only
``self``. Must NOT import ``window`` or ``app`` (no import cycle).
"""

from __future__ import annotations


class _BackendSignalsMixin:
    """Slots wired to ``core.signals`` (status, reminders, errors), the F-4
    hotkey dispatcher, and the F-3 scheduled-workflow fire handler.

    Bodies are moved here in Slice 5; empty until then.
    """
