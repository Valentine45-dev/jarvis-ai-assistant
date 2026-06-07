"""
J.A.R.V.I.S. — Entry point shim.

The HUD lives in the ``ui.main_window`` package (R2-17a split of the former
1844-LOC ``main.py`` monolith). This file stays at the repo root so the launch
contract is unchanged::

    uv run python main.py

It re-exports the public surface so existing callers keep working:
    from main import JarvisWindow, main
"""

from ui.main_window import JarvisWindow, main

__all__ = ["JarvisWindow", "main"]


if __name__ == "__main__":
    main()
