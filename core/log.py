"""Tiny debug-gated logger.

Wraps stdout printing behind `config.debug_mode` so production runs stay quiet.
Also normalises non-ASCII characters before printing to avoid UnicodeEncodeError
on Windows consoles with cp1252 encoding.

Usage:
    from core.log import debug, info, error
    debug("voice", "started capture")
    info("doc", "rendering pdf")
    error("browser", f"navigation failed: {exc}")
"""

from __future__ import annotations

import sys


def _safe(s: str) -> str:
    """Best-effort encode to whatever the console uses; never raise."""
    try:
        enc = (sys.stdout.encoding or "utf-8").lower()
    except Exception:
        enc = "utf-8"
    if enc in ("utf-8", "utf8"):
        return s
    try:
        return s.encode(enc, errors="replace").decode(enc, errors="replace")
    except Exception:
        return s.encode("ascii", errors="replace").decode("ascii")


def _enabled() -> bool:
    try:
        from config.settings import config
        return bool(config.debug_mode)
    except Exception:
        return False


def debug(tag: str, msg: str) -> None:
    """Debug-only line. No-op when debug_mode is False."""
    if not _enabled():
        return
    print(_safe(f"[{tag}] {msg}"))


def info(tag: str, msg: str) -> None:
    """Same gating as debug today — split kept for future log-level routing."""
    if not _enabled():
        return
    print(_safe(f"[{tag}] {msg}"))


def error(tag: str, msg: str) -> None:
    """Always printed; errors should be visible even outside debug mode."""
    print(_safe(f"[{tag}] {msg}"), file=sys.stderr)
