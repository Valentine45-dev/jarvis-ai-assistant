"""JarvisWindow package (R2-17a decomposition of the old main.py monolith).

Public surface is unchanged. ``main.py`` at the repo root is now a thin shim
that re-exports from here, so ``uv run python main.py`` and ``def main()``
keep working exactly as before::

    from ui.main_window import JarvisWindow, main

``JarvisWindow`` is composed from plain method-group mixins (the same pattern
as ``core/browser``); all ``pyqtSignal`` definitions and every ``.connect()``
call stay on JarvisWindow itself in ``window.py``.
"""

from __future__ import annotations

from ui.main_window.window import JarvisWindow
from ui.main_window.app import main

__all__ = ["JarvisWindow", "main"]
