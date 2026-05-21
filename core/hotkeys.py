"""Global hotkey bindings (F-4).

Uses the `keyboard` package to register OS-level hotkeys that fire
regardless of which app is focused. Each binding maps a hotkey string
(e.g. ``"ctrl+shift+j"``) to an action name. When the hotkey fires,
the keyboard library invokes our callback on its own listener thread —
we then emit ``signals.hotkey_triggered`` so the Qt main thread can
handle the actual UI side effect (focus command bar, toggle mic, etc.).

Action names handled in main.py's ``_on_hotkey`` slot:
  - ``focus_command_bar``  — give keyboard focus to the input field
  - ``toggle_mic_mute``    — flip the mic mute flag
  - ``toggle_tts_mute``    — flip the TTS mute flag
  - ``take_screenshot``    — dispatch a system_control/screenshot
  - ``read_screen``        — dispatch a vision_analysis/describe

Configuration:
  Bindings live in ``config.hotkeys`` as a dict mapping hotkey-string ->
  action-name. Defaults are seeded in config/settings.py; users can
  override per-binding via Settings UI or by editing data/jarvis.json
  directly. An empty mapping disables the system entirely.

Platform notes:
  - ``keyboard`` is Windows-first. On Linux it usually requires root
    privileges for the low-level hook, so we silently degrade to "no
    hotkeys" if registration fails. macOS is not supported by this
    package; same degradation path applies.
"""

from __future__ import annotations

import threading

from core.log import debug as _dbg, info as _info


# Default action set we'll wire in main.py. Used only for reference
# documentation; the actual {hotkey -> action} map comes from config.
KNOWN_ACTIONS: frozenset[str] = frozenset({
    "focus_command_bar",
    "toggle_mic_mute",
    "toggle_tts_mute",
    "take_screenshot",
    "read_screen",
})

_registered: list[object] = []   # keyboard.add_hotkey return handles
_start_lock = threading.Lock()
_started = False


def _keyboard():
    """Lazy import — degrades gracefully when the dep is missing."""
    try:
        import keyboard
        return keyboard
    except ImportError:
        return None
    except Exception as exc:
        # Some systems error on import when the OS hook isn't accessible.
        _dbg("hotkeys", f"keyboard import failed: {exc!r}")
        return None


def _emit(action: str) -> None:
    """Bridge: called from the keyboard listener thread; queue the action
    onto the Qt main thread via the central signals hub."""
    try:
        from core.signals import signals
        signals.hotkey_triggered.emit(action)
    except Exception as exc:
        _dbg("hotkeys", f"emit({action!r}) failed: {exc!r}")


def register_bindings(bindings: dict[str, str]) -> int:
    """Install all hotkeys from a ``{hotkey: action}`` dict.

    Idempotent on the global state: re-calling clears prior bindings
    first so the Settings UI can hot-swap without leaking stale hooks.
    Returns the number of bindings successfully installed.
    """
    global _started
    keyboard = _keyboard()
    if keyboard is None:
        return 0

    with _start_lock:
        # Clear any prior bindings to avoid double-fires when re-registering.
        for handle in _registered:
            try:
                keyboard.remove_hotkey(handle)
            except (KeyError, ValueError):
                pass
        _registered.clear()

        installed = 0
        for hotkey, action in (bindings or {}).items():
            hotkey = (hotkey or "").strip().lower()
            action = (action or "").strip()
            if not hotkey or not action:
                continue
            if action not in KNOWN_ACTIONS:
                _dbg("hotkeys", f"ignoring unknown action {action!r} on {hotkey!r}")
                continue
            try:
                # suppress=False so the underlying app still receives the keys
                # — we just observe. trigger_on_release=False fires on press.
                handle = keyboard.add_hotkey(
                    hotkey,
                    lambda a=action: _emit(a),
                    suppress=False,
                    trigger_on_release=False,
                )
                _registered.append(handle)
                installed += 1
            except Exception as exc:
                # Don't crash JARVIS on a single bad binding (typos, OS
                # permission failure, key not present on this layout, ...).
                _dbg("hotkeys", f"failed to bind {hotkey!r} -> {action!r}: {exc!r}")

        if installed and not _started:
            _info("hotkeys", f"installed {installed} hotkey binding(s)")
            _started = True
        return installed


def unregister_all() -> None:
    """Remove every binding. Used on app shutdown so the keyboard hook
    doesn't outlive the process on Windows."""
    keyboard = _keyboard()
    if keyboard is None:
        return
    with _start_lock:
        for handle in _registered:
            try:
                keyboard.remove_hotkey(handle)
            except (KeyError, ValueError):
                pass
        _registered.clear()
