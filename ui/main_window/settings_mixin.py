"""Settings / quick-settings / session-flag glue for JarvisWindow (R2-17a split).

Plain mixin — no QObject base, no signals defined here. Methods use only
``self``. Must NOT import ``window`` or ``app`` (no import cycle).
"""

from __future__ import annotations

from core.controllers.session_flags import persist_session_flags, sync_session_flag_views
from ui.main_window.constants import _SETTINGS_NAV_IDX


class _SettingsMixin:
    """View nav, quick-action prefixes, mute / auto-confirm / dim toggles,
    and the quick/full settings popover handlers."""

    def _sync_session_flag_views(self) -> None:
        """Keep quick-settings popover and settings page toggles in sync."""
        sync_session_flag_views(
            self._quick_settings,
            self._settings_view,
            auto_confirm=self._auto_confirm,
            dim_mode=self._dim_mode,
            wake_word=self._wake_word_enabled,
        )

    def _persist_session_flags(self) -> None:
        """Persist shared quick/full settings flags to config JSON."""
        persist_session_flags(
            auto_confirm=self._auto_confirm,
            dim_mode=self._dim_mode,
            wake_word=self._wake_word_enabled,
        )

    def _nav(self, idx):
        self._stack.setCurrentIndex(idx)
        name = self.VIEW_NAMES[idx]
        self._topbar.set_view(name)
        self._botbar.set_view(name)
        if idx == _SETTINGS_NAV_IDX:
            # Re-sync toggles whenever Settings page is shown.
            self._sync_session_flag_views()

    # Maps quick-action labels to input prefixes.
    # Trailing space = user must complete the command.
    # No trailing space = command is ready to send as-is.
    _QUICK_PREFIXES = {
        "Browser":    "Open Browser ",       # e.g. "Open Browser NBA news"
        "Weather":    "Check weather in ",   # e.g. "Check weather in Tokyo"
        "Schedule":   "Show my schedule for ", # e.g. "Show my schedule for today"
        "System":     "Run system report",
        "Screenshot": "Take a screenshot",
        "Lock":       "Lock the screen",
    }

    def _fill_input(self, label):
        """Pre-fill the command bar with a smart prefix for the quick action."""
        text = self._QUICK_PREFIXES.get(label, label + " ")
        inp = self._dashboard.left.cmd_bar.get_input()
        inp.setText(text)
        inp.setFocus()
        inp.setCursorPosition(len(text))   # cursor at end, ready to type

    def _show_quick_settings(self):
        # Sync both surfaces every open to prevent toggle drift.
        self._sync_session_flag_views()
        anchor = self._topbar.icon_button("settings")
        self._quick_settings.show_below(anchor)

    def _show_system_status(self):
        # refresh() pulls fresh values from config / voice_engine / browser /
        # executor on every open, so the popover never shows stale state.
        self._system_status.refresh()
        anchor = self._topbar.icon_button("broadcast")
        self._system_status.show_below(anchor)

    def _on_mic_mute_toggled(self, muted: bool):
        from core.voice import voice_engine
        voice_engine.set_mic_muted(muted)
        self._sync_session_flag_views()
        self._persist_session_flags()
        self._dashboard.toast.show_toast(
            "Microphone muted." if muted else "Microphone live.",
            "warning" if muted else "info",
        )
        # If we're currently mid-listen, drop back to idle so the UI doesn't
        # sit in a "listening"/"connecting" pose while the engine is muted.
        if muted and self._state in ("listening", "connecting"):
            self._set_state("idle")

    def _on_tts_mute_toggled(self, muted: bool):
        from core.voice import voice_engine
        voice_engine.set_tts_muted(muted)
        self._sync_session_flag_views()
        self._persist_session_flags()
        self._dashboard.toast.show_toast(
            "TTS output muted." if muted else "TTS output enabled.",
            "warning" if muted else "info",
        )

    def _on_auto_confirm_toggled(self, on: bool):
        self._auto_confirm = bool(on)
        self._auto_confirm_banner.setVisible(on)
        self._sync_session_flag_views()
        self._persist_session_flags()
        self._dashboard.toast.show_toast(
            "Auto-confirm ON — destructive actions run instantly."
            if on else "Auto-confirm OFF — confirmation prompts restored.",
            "error" if on else "info",
        )

    def _on_dim_toggled(self, on: bool):
        self._dim_mode = bool(on)
        self._sync_session_flag_views()
        self._persist_session_flags()
        if on:
            self._dim_overlay.resize(self.size())
            self._dim_overlay.raise_()
            self._dim_overlay.show()
        else:
            self._dim_overlay.hide()
