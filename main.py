"""
J.A.R.V.I.S. — Entry point.
Launches the HUD window with all views wired up.
"""

import sys
import ctypes
from datetime import datetime

import psutil

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QShortcut,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QPainter, QPalette, QColor, QBrush, QRadialGradient, QFont,
    QFontMetrics, QKeySequence,
)

from ui.theme import PRIMARY, CYAN, BG, RADIUS_LG, _c, _primary, load_jarvis_fonts
from ui.bars import TopBar, BottomBar
from ui.sidebar import HudSidebar
from ui.dashboard import DashboardView
from ui.voice import VoiceView
from ui.automation import AutomationView
from ui.history import HistoryView
from ui.settings import SettingsView
from ui.popovers import QuickSettingsPopover, SystemStatusPopover
from ui.command_palette import CommandPalette
from data.mock import MOCK_HISTORY
from core.brain import ask_claude_async, TAG_INTENT_MAP
from core.executor import dispatch
from core.signals import signals
from core.vapi_client import sync_assistant_async
from core.browser import browser

# Sidebar nav slot for the Settings page — kept as a constant so any future
# nav reorder only needs to change one line.
_SETTINGS_NAV_IDX = 4


class JarvisWindow(QMainWindow):
    VIEW_NAMES = ["Dashboard", "Voice", "Automation", "History", "Settings"]

    # Thread-bridge signals: worker threads → Qt main thread (always safe to emit)
    _brain_result_ready = pyqtSignal(object)   # dict from brain.py
    _voice_text_ready   = pyqtSignal(str)      # transcribed speech text
    _voice_error_ready  = pyqtSignal(str)      # STT failure message
    _tts_ready          = pyqtSignal(object)   # transcript payload after TTS is ready

    def __init__(self):
        super().__init__()
        self.setWindowTitle("J.A.R.V.I.S. \u2014 AI Assistant")
        self.setMinimumSize(1280, 800)
        self.resize(1440, 900)
        self._apply_dark_titlebar()

        central = QWidget()
        self.setCentralWidget(central)

        # Layout matches the reference HTML:
        #   [ Sidebar (full height) | [ TopBar / Stack / BottomBar ] ]
        # so the sidebar's brand divider (at y=64) and the TopBar's bottom
        # border (also at y=64) form one continuous horizontal line across
        # the screen.
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._sidebar = HudSidebar()
        self._sidebar.nav_changed.connect(self._nav)
        root.addWidget(self._sidebar)

        right_col = QWidget()
        right_lay = QVBoxLayout(right_col)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        self._topbar = TopBar()
        right_lay.addWidget(self._topbar)

        self._stack = QStackedWidget()
        self._dashboard = DashboardView()
        self._stack.addWidget(self._dashboard)

        self._voice_view = VoiceView()
        self._voice_view.mic_toggled.connect(self._toggle_mic)
        self._stack.addWidget(self._voice_view)

        self._automation_view = AutomationView()
        self._automation_view.run_command.connect(self._process_cmd)
        self._stack.addWidget(self._automation_view)

        self._history_view = HistoryView()
        self._stack.addWidget(self._history_view)

        self._settings_view = SettingsView()
        self._stack.addWidget(self._settings_view)
        right_lay.addWidget(self._stack, 1)

        self._botbar = BottomBar()
        right_lay.addWidget(self._botbar)

        root.addWidget(right_col, 1)

        self._dashboard.left.mic.clicked.connect(self._toggle_mic)
        self._dashboard.left.command_sent.connect(self._process_cmd)
        self._dashboard.right.command_requested.connect(self._fill_input)
        self._dashboard.right._cpu.cpu_updated.connect(self._topbar.set_cpu)

        self._state = "idle"
        self._confidence = 95
        self._history = list(MOCK_HISTORY)
        self._session_start = datetime.now()
        self._cmd_count = 0
        self._transcript_update_token = 0

        # Wire thread-bridge signals (worker threads → Qt main thread)
        self._brain_result_ready.connect(self._on_brain_result)
        self._voice_text_ready.connect(self._on_voice_heard)
        self._voice_error_ready.connect(self._on_voice_error_ui)
        self._tts_ready.connect(self._on_tts_ready)

        # Wire backend signals so reminders and errors surface in the HUD
        signals.status_changed.connect(self._on_status_signal)
        signals.error_occurred.connect(
            lambda msg: self._dashboard.toast.show_toast(msg, "error"))

        # Wire confirmation bar signals
        self._dashboard.left.confirm_bar.confirmed.connect(self._on_confirmed)
        self._dashboard.left.confirm_bar.cancelled.connect(self._on_cancelled)
        self._pending_result: dict | None = None

        # ── Quick settings popover (TopBar sliders icon) ──────────────────────
        # Transient session flag — bypass confirmation for destructive actions.
        # OFF by default (and intentionally not persisted) so a stale toggle
        # can never silently survive a restart.
        self._auto_confirm = False
        self._quick_settings = QuickSettingsPopover(self)
        self._quick_settings.mic_muted_changed.connect(self._on_mic_mute_toggled)
        self._quick_settings.tts_muted_changed.connect(self._on_tts_mute_toggled)
        self._quick_settings.auto_confirm_changed.connect(self._on_auto_confirm_toggled)
        self._quick_settings.open_settings.connect(
            lambda: self._sidebar.goto(_SETTINGS_NAV_IDX)
        )
        self._topbar.settings_clicked.connect(self._show_quick_settings)

        # ── Command palette (TopBar terminal icon + Ctrl+K) ───────────────────
        # Parented to the main window so it can paint a full-window dim
        # backdrop and resize with the window without extra plumbing.
        self._palette = CommandPalette(self, frozenset(TAG_INTENT_MAP.keys()))
        self._palette.command_submitted.connect(self._on_palette_command)
        self._topbar.terminal_clicked.connect(self._toggle_palette)
        # Global Ctrl+K — works from any view, even with no input focused.
        self._palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self._palette_shortcut.setContext(Qt.ApplicationShortcut)
        self._palette_shortcut.activated.connect(self._toggle_palette)

        # ── System status popover (TopBar broadcast icon) ─────────────────────
        # Read-only health view of all subsystems. Refreshed on every open so
        # values are always live — no background polling needed.
        self._system_status = SystemStatusPopover(self)
        self._topbar.broadcast_clicked.connect(self._show_system_status)

        for h in self._history:
            self._dashboard.left.transcript.add_exchange(
                h["you"], h["time"], h["jarvis"], h["jTime"])

        self._sys_tick()
        sys_t = QTimer(self)
        sys_t.timeout.connect(self._sys_tick)
        sys_t.start(2000)

        # Sync JARVIS assistant config to Vapi platform (background, non-blocking)
        QTimer.singleShot(2000, sync_assistant_async)

        # Dim overlay — full-window dark layer toggled by Quick Settings.
        # WA_TransparentForMouseEvents lets clicks pass through to the UI below.
        self._dim_mode = False
        self._dim_overlay = QWidget(self)
        self._dim_overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._dim_overlay.setStyleSheet("background:rgba(0,0,0,0.42);")
        self._dim_overlay.hide()

        self._quick_settings.dim_mode_changed.connect(self._on_dim_toggled)

    def _nav(self, idx):
        self._stack.setCurrentIndex(idx)
        name = self.VIEW_NAMES[idx]
        self._topbar.set_view(name)
        self._botbar.set_view(name)

    def _toggle_mic(self):
        if self._state == "listening":
            self._set_state("idle")
        else:
            self._set_state("listening")
            self._voice_capture()

    def _voice_capture(self):
        if self._state != "listening":
            return
        from core.voice import voice_engine
        voice_engine.listen(
            callback=lambda text: self._voice_text_ready.emit(text),
            on_error=lambda err: self._voice_error_ready.emit(err),
            timeout=8.0,
        )

    def _on_voice_heard(self, text: str):
        """Qt main thread — STT captured speech successfully."""
        if self._state == "listening" and text.strip():
            self._process_cmd(text)
        else:
            self._set_state("idle")

    def _on_voice_error_ui(self, msg: str):
        """Qt main thread — STT timed out or failed."""
        self._set_state("idle")
        self._dashboard.toast.show_toast(msg, "warning")

    def _on_status_signal(self, msg: str):
        """Qt main thread — backend status update (e.g., a reminder fires)."""
        self._dashboard.toast.show_toast(msg, "info")
        self._dashboard.left.status_lbl.setText(msg)

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

    # Intent → HUD status label mapping
    _INTENT_HUD = {
        "open_app":        "LAUNCHING APP",
        "close_app":       "TERMINATING",
        "search_web":      "WEB SEARCH",
        "type_text":       "INPUT MODE",
        "control_mouse":   "MOUSE CONTROL",
        "system_control":  "SYS CONTROL",
        "automation_task": "AUTOMATION",
        "read_screen":     "OCR SCAN",
        "browser_automation": "BROWSER CTRL",
        "file_operation":  "FILE OPS",
        "code_execution":  "EXECUTING",
        "jarvis_meta":     "STANDBY",
        "unknown":         "UNKNOWN",
    }

    def _process_cmd(self, cmd: str):
        self._transcript_update_token += 1
        now = datetime.now().strftime("%H:%M")
        self._history.append({
            "time": now, "you": cmd, "jarvis": "", "jTime": "",
            "intent": "", "conf": 0.0,
        })
        self._dashboard.left.transcript.add_exchange(cmd, now)
        self._botbar.increment_commands()
        self._cmd_count += 1
        self._set_state("thinking")
        self._dashboard.left.hud_status.set_status("PROCESSING")
        self._dashboard.left.status_lbl.setText(f'Processing: "{cmd}"')
        self._dashboard.left.typing.show_typing()

        # Priority: resolve pending confirmation before routing to brain.
        # This handles "yes/no" replies to executor confirmation prompts
        # (e.g. "folder doesn't exist — shall I create it?").
        from core.executor import get_pending_confirmation, resolve_confirmation
        if get_pending_confirmation():
            resolved = resolve_confirmation(cmd)
            self._on_confirmation_resolved(resolved)
            return

        # Normal flow: route through Claude
        def _on_result(result: dict):
            if result.get("_unknown_tag"):
                self._dashboard.toast.show_toast(
                    f"Unknown tag @{result['_unknown_tag']} — routed by NLP", "warning"
                )
            self._brain_result_ready.emit(result)

        ask_claude_async(cmd, callback=_on_result)

    def _on_brain_result(self, result: dict):
        """Runs on the Qt main thread after brain.py returns."""
        intent = result.get("intent", "unknown")
        conf   = float(result.get("confidence", 0.85))
        resp   = result.get("response", "")
        hud    = result.get("hud_status", self._INTENT_HUD.get(intent, "STANDBY"))

        # Confirmation-required: show confirm bar and hold
        if result.get("requires_confirmation"):
            # Auto-confirm short-circuits the hold — used when the user has
            # explicitly opted in via Quick Settings. The dispatch() gate still
            # enforces _CONFIRMATION_REQUIRED_ACTIONS; we just pass confirmed=True.
            if self._auto_confirm:
                self._execute_result(result, intent, conf, resp, hud, confirmed=True)
                return
            self._pending_result = result
            self._dashboard.left.typing.hide_typing()
            self._set_state("idle")
            self._dashboard.left.status_lbl.setText(resp or "Awaiting confirmation, sir.")
            # Mirror the pending state on the Voice page so the inspector
            # turns amber instead of looking idle while user decides.
            self._voice_view.set_pending(
                intent, result.get("action", ""), conf,
                resp or "Awaiting confirmation, sir.",
            )
            return

        self._execute_result(result, intent, conf, resp, hud)

    # Intents where personality.say() drives the spoken response (honest pass/fail)
    _ACTION_INTENTS: frozenset = frozenset({
        "open_app", "close_app", "search_web", "type_text", "control_mouse",
        "system_control", "file_operation", "code_execution", "browser_automation",
        "read_screen", "automation_task", "reminder_task",
    })
    _FACTUAL_ACTIONS: frozenset = frozenset({"tell_time", "tell_date", "status_report"})

    def _on_confirmation_resolved(self, resolved: dict):
        """Called on the Qt main thread after a pending confirmation is resolved."""
        j_time = datetime.now().strftime("%H:%M")
        self._dashboard.left.typing.hide_typing()

        display_resp = resolved.get("output", "")
        if not display_resp:
            display_resp = "Done, sir." if resolved.get("success") else "Understood, standing down, sir."

        if self._history:
            self._history[-1].update({
                "jarvis": display_resp, "jTime": j_time,
                "intent": "confirmation", "conf": 1.0,
            })

        self._set_state("processing")
        self._dashboard.left.status_lbl.setText(display_resp)
        self._dashboard.left.hud_status.set_status("CONFIRMED" if resolved.get("success") else "CANCELLED")

        self._transcript_update_token += 1
        t = self._transcript_update_token
        payload = (t, display_resp, j_time, "confirmation", 1.0)
        try:
            from core.voice import voice_engine
            voice_engine.say(display_resp, on_ready=lambda: self._tts_ready.emit(payload))
        except Exception:
            self._tts_ready.emit(payload)

        kind = "success" if resolved.get("success") else "info"
        self._dashboard.toast.show_toast(display_resp, kind)

    def _execute_result(self, result: dict, intent: str, conf: float, resp: str, hud: str,
                        confirmed: bool = False):
        """Dispatch to OS + update all HUD surfaces."""
        exec_out = dispatch(result, confirmed=confirmed)

        j_time = datetime.now().strftime("%H:%M")
        self._dashboard.left.typing.hide_typing()

        # ── needs_confirmation from executor (e.g. folder not found) ────────
        # Not the same as Claude's requires_confirmation — this is the executor
        # asking the user a yes/no mid-execution.
        if exec_out.get("needs_confirmation"):
            display_resp = exec_out.get("output", "Awaiting your confirmation, sir.")
            self._dashboard.left.status_lbl.setText(display_resp)
            self._set_state("idle")
            self._transcript_update_token += 1
            t = self._transcript_update_token
            payload = (t, display_resp, j_time, intent, conf)
            try:
                from core.voice import voice_engine
                voice_engine.say(display_resp, on_ready=lambda: self._tts_ready.emit(payload))
            except Exception:
                self._tts_ready.emit(payload)
            self._dashboard.toast.show_toast(display_resp, "warning")
            if self._history:
                self._history[-1].update({"jarvis": display_resp, "jTime": j_time,
                                          "intent": intent, "conf": conf})
            return

        # ── Build spoken response — personality-driven, honest about failure ──
        from core.personality import say as personality_say

        if intent in self._ACTION_INTENTS:
            status       = "ok" if exec_out["success"] else "err"
            display_resp = personality_say(
                intent, result.get("action", ""),
                status,
                exec_out.get("output", ""),
                exec_out.get("error", ""),
            )
        elif intent == "jarvis_meta":
            if result.get("action") in self._FACTUAL_ACTIONS and exec_out.get("output"):
                display_resp = exec_out["output"]
            elif result.get("action") == "conversational" and exec_out.get("output"):
                # Page cache answer
                display_resp = exec_out["output"]
            else:
                display_resp = resp   # Claude's conversational response
        else:
            display_resp = resp       # unknown / other — use Claude's response

        if self._history:
            self._history[-1].update({
                "jarvis": display_resp, "jTime": j_time,
                "intent": intent, "conf": conf,
            })

        self._confidence = round(conf * 100)
        self._dashboard.right.gauge.set_value(self._confidence)
        v = self._confidence
        self._dashboard.right.conf_label.setText(
            "HIGH" if v > 90 else "MED" if v > 70 else "LOW")

        self._dashboard.left.hud_status.set_status(hud)
        self._dashboard.left.last_action.set_action(intent, conf)

        secs = int((datetime.now() - self._session_start).total_seconds())
        self._dashboard.right.greeting.set_stats(self._cmd_count, secs)
        h, m = divmod(secs // 60, 60)
        self._history_view.refresh_history(self._history, uptime_str=f"{h}h {m:02d}m")
        self._voice_view.update_transcript(
            self._history[-1]["you"] if self._history else "", display_resp, intent, conf)
        # Phase 2: surface the real executor outcome on the Voice page
        self._voice_view.set_execution(
            intent,
            result.get("action", ""),
            conf,
            bool(exec_out.get("success")),
            exec_out.get("error"),
        )

        self._set_state("processing")
        self._dashboard.left.status_lbl.setText(display_resp)

        self._transcript_update_token += 1
        transcript_token = self._transcript_update_token
        transcript_payload = (transcript_token, display_resp, j_time, intent, conf)

        # TTS runs on a worker thread; emit a Qt signal when audio is ready so
        # transcript animation starts on the main thread at the real playback point.
        try:
            from core.voice import voice_engine
            voice_engine.say(
                display_resp,
                on_ready=lambda: self._tts_ready.emit(transcript_payload),
            )
        except Exception:
            self._tts_ready.emit(transcript_payload)

        kind = "error" if not exec_out["success"] else "success"
        toast_msg = (
            exec_out["error"] if not exec_out["success"]
            else f"Command executed — {intent}"
        )
        self._dashboard.toast.show_toast(toast_msg, kind)

    def _on_tts_ready(self, payload: object):
        token, text, j_time, intent, conf = payload
        self._set_state_if_current(token, "speaking")
        self._update_transcript_if_current(token, text, j_time, intent, conf)
        QTimer.singleShot(
            2000,
            lambda: self._set_state_if_current(token, "idle"),
        )

    def _update_transcript_if_current(
        self, token: int, text: str, j_time: str, intent: str, conf: float
    ):
        """Ignore transcript updates after a newer command/response."""
        if token != self._transcript_update_token:
            return
        self._dashboard.left.transcript.update_last_jarvis(text, j_time, intent, conf)

    def _set_state_if_current(self, token: int, state: str):
        """Ignore stale state timers after a newer command/response starts."""
        if token != self._transcript_update_token:
            return
        self._set_state(state)

    def _on_confirmed(self):
        if self._pending_result:
            r = self._pending_result
            self._pending_result = None
            self._execute_result(
                r,
                r.get("intent", "unknown"),
                float(r.get("confidence", 0.85)),
                r.get("response", ""),
                r.get("hud_status", "STANDBY"),
                confirmed=True,
            )

    def _on_cancelled(self):
        self._pending_result = None
        self._set_state("idle")
        self._dashboard.left.status_lbl.setText("Command cancelled, sir.")
        self._voice_view.clear_pending()

    # ── Quick settings popover handlers ───────────────────────────────────────

    def _show_quick_settings(self):
        # Sync the popover's toggle state with the live engine flags every time
        # it opens — defends against drift if anything else mutated them.
        from core.voice import voice_engine
        self._quick_settings.sync_state(
            mic_muted=voice_engine.mic_muted,
            tts_muted=voice_engine.tts_muted,
            auto_confirm=self._auto_confirm,
            dim_mode=self._dim_mode,
        )
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
        self._dashboard.toast.show_toast(
            "Microphone muted." if muted else "Microphone live.",
            "warning" if muted else "info",
        )
        # If we're currently mid-listen, drop back to idle so the UI doesn't
        # sit in a "listening" pose while the engine is muted.
        if muted and self._state == "listening":
            self._set_state("idle")

    def _on_tts_mute_toggled(self, muted: bool):
        from core.voice import voice_engine
        voice_engine.set_tts_muted(muted)
        self._dashboard.toast.show_toast(
            "TTS output muted." if muted else "TTS output enabled.",
            "warning" if muted else "info",
        )

    def _on_auto_confirm_toggled(self, on: bool):
        self._auto_confirm = bool(on)
        self._dashboard.toast.show_toast(
            "Auto-confirm ON — destructive actions run instantly."
            if on else "Auto-confirm OFF — confirmation prompts restored.",
            "error" if on else "info",
        )

    def _on_dim_toggled(self, on: bool):
        self._dim_mode = bool(on)
        if on:
            self._dim_overlay.resize(self.size())
            self._dim_overlay.raise_()
            self._dim_overlay.show()
        else:
            self._dim_overlay.hide()

    # ── Command palette handlers ──────────────────────────────────────────────

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

    def _set_state(self, s):
        self._state = s
        orb_map = {"idle": 0, "listening": 1, "thinking": 2, "processing": 2, "speaking": 3}
        self._dashboard.left.orb.set_state(orb_map.get(s, 0))
        self._dashboard.left.mic.set_listening(s == "listening")

        self._fade_status_text()

        # Waveform only visible when audio is active; last_action strip otherwise
        active_audio = s in ("listening", "speaking")
        self._dashboard.left.waveform.setVisible(active_audio)
        self._dashboard.left.waveform.set_active(active_audio)

        # HUD status for state changes
        if s == "idle":
            self._dashboard.left.hud_status.set_status("STANDBY")
        elif s == "listening":
            self._dashboard.left.hud_status.set_status("LISTENING")
        elif s == "thinking":
            pass  # set by _process_cmd
        elif s == "processing":
            self._dashboard.left.hud_status.set_status("PROCESSING")
        elif s == "speaking":
            self._dashboard.left.hud_status.set_status("SPEAKING")

        pill = self._dashboard.left.state_pill
        pill.setText(s.upper())
        pf = QFont(pill.font())
        pf.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        pill.setMinimumWidth(max(120, QFontMetrics(pf).horizontalAdvance(pill.text()) + 46))
        self._voice_view.set_state(s)

        pill_base = (
            f"border-radius:{RADIUS_LG}px;letter-spacing:1.5px;padding:0 20px;"
        )
        if s == "listening":
            self._dashboard.left.state_pill.setStyleSheet(
                f"color:{CYAN};border:1px solid rgba(0,212,255,0.40);"
                f"background:rgba(0,212,255,0.09);{pill_base}")
            self._dashboard.left.status_lbl.setText("Listening\u2026")
        elif s == "idle":
            self._dashboard.left.state_pill.setStyleSheet(
                "color:rgba(210,220,245,0.88);border:1px solid rgba(0,102,255,0.28);"
                f"background:rgba(0,102,255,0.05);{pill_base}")
            self._dashboard.left.status_lbl.setText("Awaiting command, sir.")
        else:
            self._dashboard.left.state_pill.setStyleSheet(
                "color:rgba(210,220,245,0.88);border:1px solid rgba(0,102,255,0.42);"
                f"background:rgba(0,102,255,0.06);{pill_base}")

    def _fade_status_text(self):
        """Quick opacity fade on the status label for state transitions."""
        lbl = self._dashboard.left.status_lbl
        lbl.setStyleSheet("color:rgba(200,215,240,0.0);")
        self._fade_step = 0

        def _step():
            self._fade_step += 1
            alpha = min(0.42, self._fade_step * 0.06)
            lbl.setStyleSheet(f"color:rgba(200,215,240,{alpha});")
            if self._fade_step < 7:
                QTimer.singleShot(25, _step)

        QTimer.singleShot(25, _step)

    def _sys_tick(self):
        # CPU is owned by _CpuCard's internal 1s timer — no duplicate poll here.
        # Memory is owned by _MemCard's internal 2s timer — no duplicate poll here.
        session_delta = datetime.now() - self._session_start
        s_hours, s_rem = divmod(int(session_delta.total_seconds()), 3600)
        s_mins = s_rem // 60
        self._dashboard.right.uptime_card.val.setText(f"{s_hours}h {s_mins}m")
        # Bar fills up over a 4-hour session
        session_pct = min(100, (session_delta.total_seconds() / 14400) * 100)
        self._dashboard.right.uptime_card.set_bar(session_pct)

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

    def closeEvent(self, event):
        """Shut down the browser session cleanly before the window closes."""
        browser.stop()
        super().closeEvent(event)

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(BG))

        g1 = QRadialGradient(w * 0.25, h * 0.35, max(w, h) * 0.55)
        g1.setColorAt(0, _primary(8))
        g1.setColorAt(1, _primary(0))
        p.fillRect(0, 0, w, h, QBrush(g1))

        g2 = QRadialGradient(w * 0.75, h * 0.65, max(w, h) * 0.5)
        g2.setColorAt(0, _c(0, 212, 255, 5))
        g2.setColorAt(1, _c(0, 212, 255, 0))
        p.fillRect(0, 0, w, h, QBrush(g2))

        p.end()


def main():
    import signal
    signal.signal(signal.SIGINT,  lambda *_: (browser.stop(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda *_: (browser.stop(), sys.exit(0)))

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Register bundled .ttf files (Roboto Mono, etc.) into Qt's font database
    # so QSS `font-family:'Roboto Mono'` declarations actually resolve
    # instead of silently falling back to a default monospace.
    load_jarvis_fonts()

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(PRIMARY))
    pal.setColor(QPalette.Base, _c(9, 9, 11))
    pal.setColor(QPalette.Text, QColor(PRIMARY))
    pal.setColor(QPalette.Button, _c(39, 39, 42))
    pal.setColor(QPalette.ButtonText, QColor(PRIMARY))
    pal.setColor(QPalette.Highlight, QColor(PRIMARY))
    pal.setColor(QPalette.HighlightedText, QColor(BG))
    pal.setColor(QPalette.PlaceholderText, _primary(46))
    app.setPalette(pal)

    w = JarvisWindow()
    w.setMinimumSize(1280, 800)
    w.showMaximized()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
