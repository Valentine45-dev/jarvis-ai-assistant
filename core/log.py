"""Tiny debug-gated logger.

Wraps stdout printing behind `config.debug_mode` so production runs stay quiet.
Also normalises non-ASCII characters before printing to avoid UnicodeEncodeError
on Windows consoles with cp1252 encoding.

Readability: each tag gets a colour (lightweight ANSI, no dependency) and a blank
line is emitted whenever the tag changes, so consecutive [brain] / [tts] / [voice]
groups don't run together. Colour auto-disables when stdout isn't a TTY (piped to a
file), and is enabled on Windows via the VT-processing console mode.

Usage:
    from core.log import debug, info, error
    debug("voice", "started capture")
    info("doc", "rendering pdf")
    error("browser", f"navigation failed: {exc}")
"""

from __future__ import annotations

import sys

# Per-tag ANSI colour (foreground SGR code). Unlisted tags use the default.
_TAG_COLORS: dict[str, str] = {
    "brain": "96",       # bright cyan
    "tts": "95",         # bright magenta
    "voice": "93",       # bright yellow
    "stt": "94",         # bright blue
    "confirm": "92",     # bright green
    "browser": "36",     # cyan
    "automation": "33",  # yellow
    "code_exec": "32",   # green
    "doc": "35",         # magenta
    "scheduler": "90",   # grey
    "wake": "90",
    "hotkeys": "90",
    "vapi": "90",
}
_DEFAULT_COLOR = "37"   # white
_RESET = "\033[0m"

_color_enabled: bool | None = None   # resolved once, lazily
_last_tag: str | None = None         # for blank-line-on-tag-change


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


def _supports_color(stream) -> bool:
    """True when *stream* is an interactive terminal that can render ANSI. On
    Windows, also flips the console into VT-processing mode (once)."""
    try:
        if not stream.isatty():
            return False
    except Exception:
        return False
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        return True
    except Exception:
        return False


def _format(tag: str, msg: str, *, color: bool) -> str:
    prefix = f"[{tag}]"
    if color:
        code = _TAG_COLORS.get(tag, _DEFAULT_COLOR)
        prefix = f"\033[{code}m{prefix}{_RESET}"
    return f"{prefix} {_safe(msg)}"


def _emit(tag: str, msg: str, *, stream=None) -> None:
    global _color_enabled, _last_tag
    out = stream or sys.stdout
    if _color_enabled is None:
        _color_enabled = _supports_color(out)
    # Blank line between different log groups so [brain]/[tts]/[voice] don't merge.
    if _last_tag is not None and tag != _last_tag:
        print(file=out)
    _last_tag = tag
    print(_format(tag, msg, color=_color_enabled), file=out)


def debug(tag: str, msg: str) -> None:
    """Debug-only line. No-op when debug_mode is False."""
    if not _enabled():
        return
    _emit(tag, msg)


def info(tag: str, msg: str) -> None:
    """Same gating as debug today — split kept for future log-level routing."""
    if not _enabled():
        return
    _emit(tag, msg)


def error(tag: str, msg: str) -> None:
    """Always printed; errors should be visible even outside debug mode."""
    color = _supports_color(sys.stderr)
    prefix = f"[{tag}]"
    if color:
        prefix = f"\033[91m{prefix}{_RESET}"   # bright red for errors
    print(f"{prefix} {_safe(msg)}", file=sys.stderr)
