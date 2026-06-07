"""State-machine + HUD painting for JarvisWindow (R2-17a split).

Plain mixin — no QObject base, no signals defined here. Methods use only
``self``. Must NOT import ``window`` or ``app`` (no import cycle).

NOTE (condition 1): ``paintEvent`` is a Qt virtual override. It is hosted
here only after Slice 2 proves — via a real ``uv run python main.py`` launch
and the smoke harness — that Qt dispatches a mixin-hosted virtual. If that
proof fails, ALL four event handlers stay on JarvisWindow in ``window.py``.
"""

from __future__ import annotations


class _StateHudMixin:
    """``_set_state`` machine, status-text fade, session tick, history-clear
    sync, and (pending Slice 2 proof) ``paintEvent``.

    Bodies are moved here in Slice 2; empty until then.
    """
