"""Window-lifecycle + platform glue for JarvisWindow (R2-17a split).

Plain mixin — no QObject base, no signals defined here. Methods use only
``self``. Must NOT import ``window`` or ``app`` (no import cycle).

NOTE (condition 1): ``nativeEvent``, ``closeEvent``, and ``resizeEvent`` are
Qt virtual overrides. They are hosted here only after Slice 2 proves Qt
dispatches a mixin-hosted virtual. If that proof fails, ALL four event
handlers (incl. ``paintEvent``) stay on JarvisWindow in ``window.py``.
"""

from __future__ import annotations


class _LifecycleMixin:
    """Dark titlebar, Win+J native hotkey handling, close/resize events,
    window summon, and the command-palette toggle.

    Bodies are moved here in Slice 4; empty until then.
    """
