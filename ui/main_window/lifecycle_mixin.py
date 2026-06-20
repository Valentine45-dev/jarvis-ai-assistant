"""Window-lifecycle + platform glue for JarvisWindow (R2-17a split).

Plain mixin — no QObject base, no signals defined here. Methods use only
``self``. Must NOT import ``window`` or ``app`` (no import cycle).

``nativeEvent``, ``closeEvent``, and ``resizeEvent`` are Qt virtual overrides.
Slice 2 proved (via the smoke harness on a real launch) that Qt dispatches a
mixin-hosted virtual, so they live here. Their ``super().<event>(...)`` calls
resolve through JarvisWindow's MRO to ``QMainWindow`` (the class immediately
after this mixin), exactly as when they lived on JarvisWindow.
"""

from __future__ import annotations

import sys
import ctypes

from core.browser import browser
from core.history_store import history_store


class _LifecycleMixin:
    """Dark titlebar, Win+J native hotkey handling, close/resize events,
    window summon, and the command-palette toggle."""

    def _summon_window(self) -> None:
        """Raise and activate the JARVIS window (Win+J from any app)."""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _toggle_palette(self):
        # Refresh recents from history before showing so the chips reflect the
        # most recent commands the user actually issued. We pull the user's
        # side ("you") from each history entry, newest first, dedup.
        seen: set[str] = set()
        recents: list[str] = []
        for entry in reversed(self._history):
            cmd = (entry.get("you") or "").strip()
            if not cmd or cmd in seen:
                continue
            seen.add(cmd)
            recents.append(cmd)
            if len(recents) >= 5:
                break
        self._palette.set_recents(recents)
        self._palette.toggle()

    def _on_palette_command(self, cmd: str):
        # Same path as the dashboard command bar — single funnel into routing.
        self._process_cmd(cmd)

    # The palette is a child widget of the main window. Qt sizes child
    # widgets via QMainWindow's central layout, but since the palette is
    # parented directly to the main window (not the central widget), we
    # need to keep it sized to the window manually.
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_palette") and self._palette.isVisible():
            self._palette.resize(self.size())
        if hasattr(self, "_dim_overlay") and self._dim_overlay.isVisible():
            self._dim_overlay.resize(self.size())

    def _apply_dark_titlebar(self):
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(value), ctypes.sizeof(value))
        except Exception:
            pass

    def nativeEvent(self, event_type, message):
        """Catch WM_HOTKEY from RegisterHotKey (Win+J system-wide summon)."""
        if sys.platform == "win32" and getattr(self, "_win_hotkey_id", None) is not None:
            try:
                from ctypes import wintypes
                WM_HOTKEY = 0x0312
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == self._win_hotkey_id:
                    self._summon_window()
                    return True, 0
            except Exception:
                pass
        return super().nativeEvent(event_type, message)

    def closeEvent(self, event):
        """Shut down all subsystems cleanly before the window closes."""
        if sys.platform == "win32" and self._win_hotkey_id is not None:
            try:
                ctypes.windll.user32.UnregisterHotKey(int(self.winId()), self._win_hotkey_id)
            except Exception:
                pass
        # F-4: detach the keyboard package's low-level hook so it doesn't
        # outlive the Python process on Windows (it can otherwise leave
        # the hotkeys "registered" until logout).
        try:
            from core.hotkeys import unregister_all as _unregister_hotkeys
            _unregister_hotkeys()
        except Exception:
            pass
        from core.wake_word import wake_detector
        wake_detector.stop()
        # Gracefully close the persistent Deepgram socket (no-op unless the
        # opt-in streaming path opened one).
        try:
            from core.voice import voice_engine
            voice_engine.close_persistent()
        except Exception:
            pass
        self._botbar._stop_rtt_thread()
        browser.stop()
        history_store.close()
        super().closeEvent(event)
