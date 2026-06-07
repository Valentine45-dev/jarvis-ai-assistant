"""Settings / quick-settings / session-flag glue for JarvisWindow (R2-17a split).

Plain mixin — no QObject base, no signals defined here. Methods use only
``self``. Must NOT import ``window`` or ``app`` (no import cycle).
"""

from __future__ import annotations


class _SettingsMixin:
    """View nav, quick-action prefixes, mute / auto-confirm / dim toggles,
    and the quick/full settings popover handlers.

    Bodies are moved here in Slice 3; empty until then.
    """
