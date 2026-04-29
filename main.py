"""
J.A.R.V.I.S. — Entry point.
Launches the HUD window with all views wired up.
"""

import sys
import ctypes
import threading
from datetime import datetime
import time

import psutil

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QStackedWidget,
    QShortcut,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QPainter, QPalette, QColor, QBrush, QRadialGradient, QFont,
    QFontMetrics, QKeySequence,
)

from ui.theme import (
    PRIMARY,
    CYAN,
    BG,
    RADIUS_LG,
    _c,
    _primary,
    load_jarvis_fonts,
    jarvis_logo_icon,
    tooltip_qss,
)
from ui.bars import TopBar, BottomBar
from ui.sidebar import HudSidebar
from ui.dashboard import DashboardView
from ui.voice import VoiceView
from ui.views.automation.view import AutomationView
from ui.history import HistoryView
from ui.settings import SettingsView
from ui.popovers import QuickSettingsPopover, SystemStatusPopover
from ui.command_palette import CommandPalette
from config.settings import config
from core.brain import ask_claude_async, TAG_INTENT_MAP
from core.controllers.command_controller import CommandController
from core.controllers.confirmation_controller import ConfirmationController
from core.executor import dispatch
from core.history_store import history_store
from core.controllers.runtime_context import RuntimeCommandContext
from core.controllers.response_composer import compose_execution_response
from core.controllers.session_flags import persist_session_flags, sync_session_flag_views
from core.signals import signals
from core.vapi_client import sync_assistant_async
from core.browser import browser

# Sidebar nav slot for the Settings page — kept as a constant so any future
# nav reorder only needs to change one line.
_SETTINGS_NAV_IDX = 4

# Maximum number of history entries kept in memory. Oldest are evicted when exceeded.
_HISTORY_MAX = 500

# Maximum characters sent to TTS for data-heavy actions (read_page, OCR, code output).
# ElevenLabs free tier has a monthly character quota — long read_page dumps burn it fast.
_TTS_MAX_CHARS = 800

class JarvisWindow(QMainWindow):
    VIEW_NAMES = ["Dashboard", "Voice", "Automation", "History", "Settings"]

    # Thread-bridge signals: worker threads → Qt main thread (always safe to emit)
    _brain_result_ready  = pyqtSignal(object)        # dict from brain.py
    _voice_text_ready    = pyqtSignal(str)           # transcribed speech text
    _voice_error_ready   = pyqtSignal(str)           # STT failure message
    _confirmation_resolved_ready = pyqtSignal(object)  # resolved confirmation dict
    _tts_ready           = pyqtSignal(object)        # transcript payload after TTS is ready
    _tts_done_signal     = pyqtSignal(int)           # fires (with token) when TTS audio ends
    _wake_word_signal    = pyqtSignal()              # wake word detected on detector thread
    _action_followup_tts = pyqtSignal(str, str, str, float, int)  # follow, jTime, intent, conf, token
    _RUN_WORKFLOW_PREFIX = "__run_workflow_id__:"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("J.A.R.V.I.S. \u2014 AI Assistant")
        self.setWindowIcon(jarvis_logo_icon())
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

        # Persistent amber warning banner — only shown when auto-confirm is active.
        # Sits between the TopBar and the content stack so it is always visible.
        from PyQt5.QtWidgets import QLabel as _QLabel
        self._auto_confirm_banner = _QLabel(
            "⚠  AUTO-CONFIRM ACTIVE — DESTRUCTIVE ACTIONS WILL EXECUTE WITHOUT PROMPT"
        )
        self._auto_confirm_banner.setAlignment(Qt.AlignCenter)
        self._auto_confirm_banner.setStyleSheet(
            "background:rgba(255,160,0,0.18);color:#ffb84d;"
            "border-bottom:1px solid rgba(255,160,0,0.45);"
            "font-family:'Roboto Mono';font-size:11px;font-weight:700;"
            "letter-spacing:1.5px;padding:5px 0;"
        )
        self._auto_confirm_banner.setVisible(False)
        right_lay.addWidget(self._auto_confirm_banner)

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
        self._history_view.history_cleared.connect(self._on_history_cleared)
        self._stack.addWidget(self._history_view)

        self._settings_view = SettingsView()
        self._settings_view.mic_muted_changed.connect(self._on_mic_mute_toggled)
        self._settings_view.tts_muted_changed.connect(self._on_tts_mute_toggled)
        self._settings_view.auto_confirm_changed.connect(self._on_auto_confirm_toggled)
        self._settings_view.dim_mode_changed.connect(self._on_dim_toggled)
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
        # Load last 100 completed entries from SQLite so history survives restarts.
        self._history: list[dict] = history_store.load_last_n(100)
        self._session_start = datetime.now()
        self._cmd_count = 0
        self._transcript_update_token = 0

        # Wire thread-bridge signals (worker threads → Qt main thread)
        self._brain_result_ready.connect(self._on_brain_result)
        self._voice_text_ready.connect(self._on_voice_heard)
        self._voice_error_ready.connect(self._on_voice_error_ui)
        self._confirmation_resolved_ready.connect(self._on_confirmation_resolved)
        self._tts_ready.connect(self._on_tts_ready)
        self._tts_done_signal.connect(self._on_tts_done, Qt.QueuedConnection)
        self._wake_word_signal.connect(self._on_wake_word, Qt.QueuedConnection)
        self._action_followup_tts.connect(
            self._on_action_followup_tts, Qt.QueuedConnection
        )

        # Start always-on wake-word detector (fires _wake_word_signal on detection)
        from core.wake_word import wake_detector
        wake_detector.start(lambda: self._wake_word_signal.emit())

        # Wire backend signals so reminders and errors surface in the HUD
        signals.status_changed.connect(self._on_status_signal)
        signals.reminder_action.connect(self._on_reminder_action)
        signals.error_occurred.connect(self._on_error_signal)
        self._last_error_toast_msg = ""
        self._last_error_toast_ts = 0.0

        # Wire inline transcript confirmation card signals
        self._dashboard.left.transcript.confirmed.connect(self._on_confirmed)
        self._dashboard.left.transcript.cancelled.connect(self._on_cancelled)
        self._pending_result: dict | None = None
        self._confirm_mode: str | None = None  # "claude" | "executor" | None
        self._last_result: dict | None = None   # Phase 5: last successfully dispatched intent
        self._runtime_ctx = RuntimeCommandContext()
        self._command_controller = CommandController(self._RUN_WORKFLOW_PREFIX)
        self._confirmation_controller = ConfirmationController()

        # ── Quick settings popover (TopBar sliders icon) ──────────────────────
        # Shared session flags are persisted in config and mirrored in both
        # quick settings and full settings.
        from core.voice import voice_engine
        self._auto_confirm = bool(getattr(config, "auto_confirm", False))
        voice_engine.set_mic_muted(bool(getattr(config, "mic_muted", False)))
        voice_engine.set_tts_muted(bool(getattr(config, "tts_muted", False)))
        self._quick_settings = QuickSettingsPopover(self)
        self._quick_settings.mic_muted_changed.connect(self._on_mic_mute_toggled)
        self._quick_settings.tts_muted_changed.connect(self._on_tts_mute_toggled)
        self._quick_settings.auto_confirm_changed.connect(self._on_auto_confirm_toggled)
        self._quick_settings.open_settings.connect(
            lambda: self._sidebar.goto(_SETTINGS_NAV_IDX)
        )
        self._topbar.settings_clicked.connect(self._show_quick_settings)
        self._topbar.battery_alert.connect(
            lambda msg, kind: self._dashboard.toast.show_toast(msg, kind)
        )

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

        # Global Win+J (Meta+J) — summon / raise the JARVIS window from anywhere.
        # QShortcut only fires when the Qt app has focus; the RegisterHotKey
        # path below covers the case where another app is in the foreground.
        self._summon_shortcut = QShortcut(QKeySequence("Meta+J"), self)
        self._summon_shortcut.setContext(Qt.ApplicationShortcut)
        self._summon_shortcut.activated.connect(self._summon_window)

        # System-wide Win+J via RegisterHotKey (Windows only).
        self._win_hotkey_id: int | None = None
        if sys.platform == "win32":
            try:
                MOD_WIN = 0x0008
                VK_J    = 0x4A
                _hid    = 0x4A12  # arbitrary unique ID (unlikely to collide)
                if ctypes.windll.user32.RegisterHotKey(int(self.winId()), _hid, MOD_WIN, VK_J):
                    self._win_hotkey_id = _hid
            except Exception:
                pass

        # ── System status popover (TopBar broadcast icon) ─────────────────────
        # Read-only health view of all subsystems. Refreshed on every open so
        # values are always live — no background polling needed.
        self._system_status = SystemStatusPopover(self)
        self._topbar.broadcast_clicked.connect(self._show_system_status)

        self._sys_tick()
        sys_t = QTimer(self)
        sys_t.timeout.connect(self._sys_tick)
        sys_t.start(2000)

        # Populate history view with entries loaded from SQLite on startup
        if self._history:
            self._cmd_count = len(self._history)
            self._history_view.refresh_history(self._history)

        # Sync JARVIS assistant config to Vapi platform (background, non-blocking)
        QTimer.singleShot(2000, sync_assistant_async)

        # Dim overlay — full-window dark layer toggled by Quick Settings.
        # WA_TransparentForMouseEvents lets clicks pass through to the UI below.
        self._dim_mode = bool(getattr(config, "dim_mode", False))
        self._dim_overlay = QWidget(self)
        self._dim_overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._dim_overlay.setStyleSheet("background:rgba(0,0,0,0.42);")
        if self._dim_mode:
            self._dim_overlay.resize(self.size())
            self._dim_overlay.raise_()
            self._dim_overlay.show()
        else:
            self._dim_overlay.hide()

        self._quick_settings.dim_mode_changed.connect(self._on_dim_toggled)
        self._sync_session_flag_views()

    def _sync_session_flag_views(self) -> None:
        """Keep quick-settings popover and settings page toggles in sync."""
        sync_session_flag_views(
            self._quick_settings,
            self._settings_view,
            auto_confirm=self._auto_confirm,
            dim_mode=self._dim_mode,
        )

    def _persist_session_flags(self) -> None:
        """Persist shared quick/full settings flags to config JSON."""
        persist_session_flags(auto_confirm=self._auto_confirm, dim_mode=self._dim_mode)

    def _nav(self, idx):
        self._stack.setCurrentIndex(idx)
        name = self.VIEW_NAMES[idx]
        self._topbar.set_view(name)
        self._botbar.set_view(name)
        if idx == _SETTINGS_NAV_IDX:
            # Re-sync toggles whenever Settings page is shown.
            self._sync_session_flag_views()
        if idx == _SETTINGS_NAV_IDX:
            self._sync_session_flag_views()

    def _toggle_mic(self):
        if self._state == "listening":
            self._set_state("idle")
        else:
            self._set_state("listening")
            self._voice_capture()

    def _voice_capture(self, auto_resume: bool = False):
        """Open the mic for one capture cycle.

        auto_resume=True: 15-second timeout, silent on timeout (no toast).
        auto_resume=False: 8-second timeout, toast on any error.
        """
        if self._state != "listening":
            return
        from core.voice import voice_engine
        timeout = 15.0 if auto_resume else 8.0

        def _on_err(err: str):
            # Suppress the toast when auto-resume simply timed out with no speech.
            # Guard emit against the window being deleted during shutdown.
            try:
                if auto_resume and "no speech" in err.lower():
                    self._voice_error_ready.emit("")
                else:
                    self._voice_error_ready.emit(err)
            except RuntimeError:
                pass

        voice_engine.listen(
            callback=lambda text: self._voice_text_ready.emit(text),
            on_error=_on_err,
            timeout=timeout,
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
        if msg:  # empty = silent auto-resume timeout, no toast needed
            self._dashboard.toast.show_toast(msg, "warning")

    def _on_wake_word(self):
        """Qt main thread — wake word detected. Start listening if idle."""
        if self._state != "idle":
            return
        from core.voice import voice_engine
        if voice_engine.mic_muted:
            return
        self._set_state("listening")
        self._voice_capture()

    def _on_tts_done(self, token: int):
        """Qt main thread — TTS audio has fully finished playing.

        Auto-resumes the mic for follow-up input unless:
        - the token is stale (a newer command replaced this one)
        - we are waiting for a confirmation card response
        - the mic is muted
        """
        if token != self._transcript_update_token:
            return
        if getattr(self, "_confirm_mode", None) in ("claude", "executor"):
            return
        from core.voice import voice_engine
        if voice_engine.mic_muted:
            self._set_state("idle")
            return
        # Auto-resume: listen for follow-up with a longer timeout.
        # If the user stays silent for 15 s, _on_voice_error_ui("") fires → idle.
        self._set_state("listening")
        self._voice_capture(auto_resume=True)

    def _on_status_signal(self, msg: str):
        """Qt main thread — backend status update (e.g., a reminder fires)."""
        self._dashboard.toast.show_toast(msg, "info")
        self._dashboard.left.status_lbl.setText(msg)

    def _on_error_signal(self, msg: str) -> None:
        """Qt main thread — throttled error toasts for noisy provider failures."""
        text = (msg or "").strip()
        if not text:
            return
        now = time.monotonic()
        is_voice_provider_error = (
            "voice switch failed" in text.lower()
            and "elevenlabs" in text.lower()
        )
        if (
            is_voice_provider_error
            and text == self._last_error_toast_msg
            and (now - self._last_error_toast_ts) < 4.0
        ):
            return
        self._last_error_toast_msg = text
        self._last_error_toast_ts = now
        self._dashboard.toast.show_toast(text, "error")

    def _on_reminder_action(self, payload: dict):
        """Qt main thread — delayed reminder with an executable JARVIS step."""
        from core.executor import dispatch
        from core.responders.assembler import responder
        from core.voice import voice_engine

        run = payload.get("run") or {}
        msg = str(payload.get("message", "Scheduled task"))
        sc = float(payload.get("schedule_confidence", 0.92))
        sc = max(0.0, min(1.0, sc))

        intent = str(run.get("intent", "unknown"))
        act = str(run.get("action", "none"))
        parameters = run.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {}

        result_dict = {
            "intent": intent,
            "action": act,
            "parameters": parameters,
            "requires_confirmation": False,
        }
        exec_out = dispatch(result_dict, confirmed=True)
        exec_ok = bool(exec_out.get("success"))

        display_resp = responder.build_scheduled(
            intent,
            act,
            exec_ok,
            exec_out.get("output", ""),
            exec_out.get("error", ""),
            params=parameters,
        )
        hud_conf = sc if exec_ok else 0.0
        j_time = datetime.now().strftime("%H:%M")

        entry = {
            "time": j_time,
            "you": "⏱ scheduled",
            "jarvis": display_resp,
            "jTime": j_time,
            "intent": intent,
            "conf": hud_conf,
            "status": "success" if exec_ok else "error",
        }
        self._history.append(entry)
        history_store.save_entry(entry)
        self._dashboard.left.transcript.append_jarvis_scheduled(
            display_resp, j_time, intent, hud_conf
        )

        secs = int((datetime.now() - self._session_start).total_seconds())
        h, m = divmod(secs // 60, 60)
        self._history_view.refresh_history(self._history, uptime_str=f"{h}h {m:02d}m")

        self._dashboard.left.hud_status.set_status(
            self._INTENT_HUD.get(intent, "STANDBY"))
        self._dashboard.left.last_action.set_action(intent, hud_conf)
        self._voice_view.set_execution(
            intent, act, hud_conf, exec_ok, exec_out.get("error"))

        self._dashboard.left.status_lbl.setText(display_resp[:120])
        toast_msg = (
            exec_out.get("error", "Scheduled action failed")
            if not exec_ok
            else f"Scheduled: {msg[:40]}"
        )
        self._dashboard.toast.show_toast(toast_msg, "error" if not exec_ok else "info")

        self._set_state("speaking")
        try:
            voice_engine.say(
                display_resp,
                on_ready=lambda: self._set_state("idle"),
            )
        except Exception:
            self._set_state("idle")

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
        direct_workflow_id, display_cmd = self._command_controller.parse_command(cmd)
        if self._state == "awaiting_confirmation":
            self._dashboard.toast.show_toast(
                "Please respond to the pending confirmation first, sir.", "warning")
            return
        self._transcript_update_token += 1
        now = datetime.now().strftime("%H:%M")
        # Cap history to avoid unbounded memory growth
        previous_cmd = self._runtime_ctx.get_previous_command(self._history)
        if len(self._history) >= _HISTORY_MAX:
            self._history = self._history[-(  _HISTORY_MAX - 1):]
        self._history.append({
            "time": now, "you": display_cmd, "jarvis": "", "jTime": "",
            "intent": "", "conf": 0.0, "status": "pending",
        })
        self._runtime_ctx.note_user_command(display_cmd)
        self._dashboard.left.transcript.add_exchange(display_cmd, now)
        self._botbar.increment_commands()
        self._cmd_count += 1
        self._set_state("thinking")
        self._dashboard.left.hud_status.set_status("PROCESSING")
        self._dashboard.left.status_lbl.setText(f'Processing: "{display_cmd}"')
        self._dashboard.left.typing.show_typing()

        # Priority: resolve pending confirmation before routing to brain — but if the
        # user typed a new full command (not a short yes/no), drop stale pending and
        # route the new command to the brain (avoids misfiring "standing down" on sentences).
        from core.executor import (
            abandon_pending_confirmation,
            get_pending_confirmation,
            resolve_confirmation,
        )

        if get_pending_confirmation():
            if self._command_controller.pending_should_yield_to_new_command(cmd):
                abandon_pending_confirmation()
                self._hide_confirm_card()
                self._confirm_mode = None
                self._pending_result = None
                try:
                    self._voice_view.clear_pending()
                except Exception:
                    pass
            else:
                resolved = resolve_confirmation(cmd)
                self._on_confirmation_resolved(resolved)
                return

        # Phase 5: repeat-last-command shorthand — bypass Claude entirely.
        if self._command_controller.is_repeat_phrase(display_cmd) and self._last_result:
            r = self._last_result
            self._execute_result(
                r,
                r.get("intent", "unknown"),
                float(r.get("confidence", 0.85)),
                r.get("response", ""),
                r.get("hud_status", self._INTENT_HUD.get(r.get("intent", "unknown"), "STANDBY")),
            )
            return

        if direct_workflow_id:
            self._execute_result(
                {
                    "intent": "automation_task",
                    "action": "run_workflow",
                    "parameters": {"task_name": direct_workflow_id},
                    "requires_confirmation": False,
                    "confidence": 1.0,
                    "response": "Running workflow now, sir.",
                    "hud_status": "AUTOMATION",
                },
                "automation_task",
                1.0,
                "Running workflow now, sir.",
                "AUTOMATION",
            )
            return

        # Normal flow: route through Claude
        def _on_result(result: dict):
            if result.get("_unknown_tag"):
                self._dashboard.toast.show_toast(
                    f"Unknown tag @{result['_unknown_tag']} — routed by NLP", "warning"
                )
            self._brain_result_ready.emit(result)

        ask_claude_async(
            cmd,
            callback=_on_result,
            context=self._runtime_ctx.build_brain_context(previous_cmd),
        )

    def _on_brain_result(self, result: dict):
        """Runs on the Qt main thread after brain.py returns."""
        intent = result.get("intent", "unknown")
        conf   = float(result.get("confidence", 0.85))
        resp   = result.get("response", "")
        hud    = result.get("hud_status", self._INTENT_HUD.get(intent, "STANDBY"))

        # Confirmation-required: show inline confirm card and hold
        if result.get("requires_confirmation"):
            # Auto-confirm short-circuits the hold — used when the user has
            # explicitly opted in via Quick Settings. The dispatch() gate still
            # enforces _CONFIRMATION_REQUIRED_ACTIONS; we just pass confirmed=True.
            if self._auto_confirm:
                self._execute_result(result, intent, conf, resp, hud, confirmed=True)
                return
            self._pending_result = result
            self._confirm_mode = "claude"
            prompt = resp or "Awaiting confirmation, sir."
            j_time = datetime.now().strftime("%H:%M")
            if self._history:
                self._history[-1].update({
                    "jarvis": prompt, "jTime": j_time,
                    "intent": intent, "conf": conf,
                })
            # Same TTS + typewriter lockstep as _execute_result (do not type before audio).
            self._transcript_update_token += 1
            transcript_token = self._transcript_update_token
            transcript_payload = (transcript_token, prompt, j_time, intent, conf)
            self._dashboard.left.typing.hide_typing()
            self._show_confirm_card(prompt)
            self._voice_view.set_pending(intent, result.get("action", ""), conf, prompt)
            try:
                from core.voice import voice_engine
                voice_engine.say(
                    prompt,
                    on_ready=lambda: self._tts_ready.emit(transcript_payload),
                )
            except Exception:
                self._tts_ready.emit(transcript_payload)
            return

        self._execute_result(result, intent, conf, resp, hud)

    # Intents where personality.say() drives the spoken response (honest pass/fail)
    _ACTION_INTENTS: frozenset = frozenset({
        "open_app", "close_app", "search_web", "type_text", "control_mouse",
        "system_control", "file_operation", "code_execution", "browser_automation",
        "read_screen", "automation_task", "reminder_task", "weather",
    })
    _FACTUAL_ACTIONS: frozenset = frozenset({
        "tell_time", "tell_date", "status_report", "list_voices",
    })
    # (intent, action) pairs where a post-execution suggestion adds value on success.
    # Deliberately narrow — only actions with an obvious, useful next step.
    _SUGGEST_ON_SUCCESS: frozenset = frozenset({
        ("open_app",           "open_browser"),
        ("open_app",           "open_url"),
        ("browser_automation", "navigate"),
        ("file_operation",     "create_file"),
        ("file_operation",     "create_directory"),
        ("search_web",         "google_search"),
        ("search_web",         "youtube_search"),
        ("search_web",         "web_search_generic"),
    })

    def _on_confirmation_resolved(self, resolved: dict):
        """Called on the Qt main thread after a pending confirmation is resolved."""
        j_time = datetime.now().strftime("%H:%M")
        self._dashboard.left.typing.hide_typing()

        # A confirmation resolution can itself schedule a follow-up confirmation
        # (workflow continuation with another file-op step). Keep the confirm
        # card loop alive instead of dropping out after the first step.
        if self._confirmation_controller.needs_followup_confirmation(resolved):
            display_resp = self._confirmation_controller.prompt_from_result(resolved)
            self._confirm_mode = "executor"
            if self._history:
                self._history[-1].update({
                    "jarvis": display_resp,
                    "jTime": j_time,
                    "intent": "confirmation",
                    "conf": 1.0,
                    "status": "pending",
                })
            self._show_confirm_card(display_resp)
            self._dashboard.toast.show_toast(display_resp, "warning")
            return

        display_resp = self._confirmation_controller.final_display_response(resolved)

        if self._history:
            self._history[-1].update({
                "jarvis": display_resp, "jTime": j_time,
                "intent": "confirmation", "conf": 1.0,
                "status": self._confirmation_controller.final_history_status(resolved),
            })

        self._set_state("processing")
        self._dashboard.left.status_lbl.setText(display_resp)
        self._dashboard.left.hud_status.set_status(self._confirmation_controller.final_hud_status(resolved))

        self._transcript_update_token += 1
        t = self._transcript_update_token
        payload = (t, display_resp, j_time, "confirmation", 1.0)
        try:
            from core.voice import voice_engine
            voice_engine.say(
                display_resp,
                on_ready=lambda: self._tts_ready.emit(payload),
                on_done=lambda: self._tts_done_signal.emit(t),
            )
        except Exception:
            self._tts_ready.emit(payload)
            self._tts_done_signal.emit(t)

        kind = self._confirmation_controller.final_toast_kind(resolved)
        self._dashboard.toast.show_toast(display_resp, kind)

    def _execute_result(self, result: dict, intent: str, conf: float, resp: str, hud: str,
                        confirmed: bool = False):
        """Dispatch to OS + update all HUD surfaces."""
        # `automation_task` + `run_workflow` must run `dispatch()` on the Qt *main* thread.
        # Playwright's sync API (greenlets) is bound to the thread that started the browser
        # (`browser.start()` at startup). Running workflows in a background `threading.Thread`
        # caused: "Cannot switch to a different thread" on any step that touches Playwright
        # (e.g. open YouTube + search in one line).
        if (intent == "automation_task"
                and result.get("action") == "run_workflow"
                and (result.get("parameters") or {}).get("steps")):
            self._dashboard.left.status_lbl.setText("Running workflow — please wait…")
            self._set_state("processing")

        exec_out = dispatch(result, confirmed=confirmed)

        # Phase 5: remember last successful dispatch for "do it again" shorthand.
        if exec_out.get("success") and intent in self._ACTION_INTENTS:
            self._last_result = result

        from core.memory import memory
        memory.inject_outcome(
            intent=intent,
            action=result.get("action", ""),
            success=bool(exec_out.get("success")),
            output=exec_out.get("output", ""),
            error=exec_out.get("error", ""),
        )

        self._finish_execute(result, intent, conf, resp, hud, exec_out)

    def _finish_execute(self, result: dict, intent: str, conf: float, resp: str, hud: str,
                        exec_out: dict) -> None:
        """Update all HUD surfaces after dispatch completes (must run on main thread)."""
        exec_ok = bool(exec_out.get("success"))
        if exec_ok:
            self._runtime_ctx.absorb_execution(intent, result, exec_out)

        j_time = datetime.now().strftime("%H:%M")
        self._dashboard.left.typing.hide_typing()

        # ── needs_confirmation from executor (e.g. folder not found) ────────
        # Not the same as Claude's requires_confirmation — this is the executor
        # asking the user a yes/no mid-execution.
        if exec_out.get("needs_confirmation") and self._auto_confirm:
            # Auto-confirm is active — skip the UI hold and execute immediately.
            from core.executor import resolve_confirmation
            resolved = resolve_confirmation("yes")
            self._on_confirmation_resolved(resolved)
            return
        if exec_out.get("needs_confirmation"):
            display_resp = self._confirmation_controller.prompt_from_result(exec_out)
            self._confirm_mode = "executor"
            if self._history:
                self._history[-1].update({"jarvis": display_resp, "jTime": j_time,
                                          "intent": intent, "conf": conf})
            # Match normal commands: do not run the JARVIS typewriter until TTS is ready
            # (same as voice_engine.say → _tts_ready → update_last_jarvis).
            self._transcript_update_token += 1
            transcript_token = self._transcript_update_token
            transcript_payload = (transcript_token, display_resp, j_time, intent, conf)
            self._show_confirm_card(display_resp)
            self._dashboard.toast.show_toast(display_resp, "warning")
            try:
                from core.voice import voice_engine
                voice_engine.say(
                    display_resp,
                    on_ready=lambda: self._tts_ready.emit(transcript_payload),
                )
            except Exception:
                self._tts_ready.emit(transcript_payload)
            return

        primary, follow, display_resp = compose_execution_response(
            intent=intent,
            result=result,
            exec_out=exec_out,
            resp=resp,
            action_intents=self._ACTION_INTENTS,
            factual_actions=self._FACTUAL_ACTIONS,
        )

        # One dashboard line for the first TTS; a second line is appended when `follow` is set.
        hist_jarvis = (
            primary if (intent in self._ACTION_INTENTS and follow) else display_resp
        )
        tts_line = (
            primary if (intent in self._ACTION_INTENTS and follow) else display_resp
        )
        # Guard: data-heavy outputs (read_page, OCR, code) can be thousands of chars.
        # Truncate only the TTS clip — the full text is still shown in the transcript.
        if tts_line and len(tts_line) > _TTS_MAX_CHARS:
            tts_line = tts_line[:_TTS_MAX_CHARS].rstrip() + "…"

        # Gauge + transcript: `conf` is Claude's routing confidence, not run success.
        # When the executor fails, show 0% / FAIL so the HUD does not read "95% HIGH" for a failed run.
        hud_conf = 0.0 if not exec_ok else conf

        if self._history:
            self._history[-1].update({
                "jarvis": hist_jarvis, "jTime": j_time,
                "intent": intent, "conf": hud_conf,
                "status": "success" if exec_ok else "error",
            })
            history_store.save_entry(self._history[-1])

        self._confidence = round(hud_conf * 100)
        self._dashboard.right.gauge.set_value(self._confidence)
        v = self._confidence
        if not exec_ok:
            self._dashboard.right.conf_label.setText("FAIL")
        else:
            self._dashboard.right.conf_label.setText(
                "HIGH" if v > 90 else "MED" if v > 70 else "LOW")

        self._dashboard.left.hud_status.set_status(hud)
        self._dashboard.left.last_action.set_action(intent, hud_conf)

        secs = int((datetime.now() - self._session_start).total_seconds())
        self._dashboard.right.greeting.set_stats(self._cmd_count, secs)
        h, m = divmod(secs // 60, 60)
        self._history_view.refresh_history(self._history, uptime_str=f"{h}h {m:02d}m")
        self._voice_view.update_transcript(
            self._history[-1]["you"] if self._history else "", tts_line, intent, hud_conf)
        # Phase 2: surface the real executor outcome on the Voice page
        self._voice_view.set_execution(
            intent,
            result.get("action", ""),
            hud_conf,
            exec_ok,
            exec_out.get("error"),
        )

        self._set_state("processing")
        self._dashboard.left.status_lbl.setText(tts_line)

        self._transcript_update_token += 1
        transcript_token = self._transcript_update_token
        transcript_payload = (transcript_token, tts_line, j_time, intent, hud_conf)

        has_follow = bool(follow and intent in self._ACTION_INTENTS)
        tok = transcript_token

        def _queue_followup() -> None:
            if not follow or intent not in self._ACTION_INTENTS:
                return
            follow_intent = str(exec_out.get("last_step_intent") or intent)
            self._action_followup_tts.emit(
                follow, j_time, follow_intent, float(hud_conf), transcript_token
            )

        def _on_primary_done() -> None:
            if has_follow:
                _queue_followup()
            else:
                self._tts_done_signal.emit(tok)

        # TTS runs on a worker thread; emit a Qt signal when audio is ready so
        # transcript animation starts on the main thread at the real playback point.
        try:
            from core.voice import voice_engine
            voice_engine.say(
                tts_line,
                on_ready=lambda: self._tts_ready.emit(transcript_payload),
                on_done=_on_primary_done,
            )
            if exec_out.get("quit_application"):
                audio_len = len(tts_line) + (len(follow) if follow else 0)
                delay_ms = 400 if voice_engine.tts_muted else min(
                    30000, 1800 + audio_len * 72
                )
                QTimer.singleShot(delay_ms, QApplication.instance().quit)
        except Exception:
            self._tts_ready.emit(transcript_payload)
            if exec_out.get("quit_application"):
                QTimer.singleShot(500, QApplication.instance().quit)

        # Phase 2 (failures) + Phase 3 (success suggestions).
        # A daemon thread generates a context-aware spoken follow-up:
        #   - Failure: Claude names the cause and suggests a next step.
        #   - Success on whitelisted actions: Claude offers a natural continuation.
        # Primary TTS fires immediately; narration arrives ~300-600ms later via signal.
        _action_key = result.get("action", "")
        _want_narration = (
            (not exec_ok and intent in self._ACTION_INTENTS)
            or (exec_ok and (intent, _action_key) in self._SUGGEST_ON_SUCCESS)
            or (_action_key == "run_workflow")   # Phase 4: always narrate workflows
        )
        if _want_narration:
            _tok      = transcript_token
            _j_time   = j_time
            _conf     = float(hud_conf)
            _intent   = intent
            _action   = _action_key
            _success  = exec_ok
            _output   = exec_out.get("output", "")
            _error    = exec_out.get("error", "")
            _user_cmd = self._history[-1].get("you", "") if self._history else ""

            def _async_narration() -> None:
                from core.brain import ask_post_execution
                narration = ask_post_execution(
                    _user_cmd, _intent, _action,
                    success=_success, output=_output, error=_error,
                )
                if narration:
                    self._action_followup_tts.emit(
                        narration, _j_time, _intent, _conf, _tok
                    )

            threading.Thread(target=_async_narration, daemon=True).start()

        kind = "error" if not exec_out["success"] else "success"
        toast_msg = (
            exec_out["error"] if not exec_out["success"]
            else f"Command executed — {intent}"
        )
        if exec_out.get("quit_application"):
            toast_msg = "Shutting down JARVIS"
        self._dashboard.toast.show_toast(toast_msg, kind)

    def _on_tts_ready(self, payload: object):
        token, text, j_time, intent, conf = payload
        self._set_state_if_current(token, "speaking")
        self._update_transcript_if_current(token, text, j_time, intent, conf)
        # After the speaking animation window, lock in awaiting_confirmation if
        # a confirm card is still active; otherwise stay in "speaking" until
        # on_done fires the _tts_done_signal which drives the actual transition.
        def _post_speaking() -> None:
            if token != self._transcript_update_token:
                return
            if getattr(self, "_confirm_mode", None) in ("claude", "executor"):
                self._set_state("awaiting_confirmation")

        QTimer.singleShot(2000, _post_speaking)

    def _on_action_followup_tts(
        self,
        follow: str,
        j_time: str,
        follow_intent: str,
        conf: float,
        token: int,
    ) -> None:
        """After the primary line finishes, append the compact done line + speak it."""
        if token != self._transcript_update_token:
            return
        if self._history:
            prev = (self._history[-1].get("jarvis") or "").strip()
            self._history[-1]["jarvis"] = f"{prev}\n{follow}" if prev else follow
        self._dashboard.left.transcript.append_jarvis_scheduled(
            follow, j_time, follow_intent, conf
        )
        self._dashboard.left.status_lbl.setText(follow[:200])
        secs = int((datetime.now() - self._session_start).total_seconds())
        h, m = divmod(secs // 60, 60)
        self._history_view.refresh_history(self._history, uptime_str=f"{h}h {m:02d}m")
        try:
            self._voice_view.append_jarvis_continuation(follow, follow_intent, conf)
        except Exception:
            pass
        from core.voice import voice_engine
        tok = token
        try:
            self._set_state("speaking")
            voice_engine.say(follow, on_done=lambda: self._tts_done_signal.emit(tok))
        except Exception:
            self._tts_done_signal.emit(tok)

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
        self._hide_confirm_card()
        mode = self._confirm_mode
        self._confirm_mode = None
        if mode == "claude" and self._pending_result:
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
        elif mode == "executor":
            # Resolve executor confirmation off the UI thread — the callback may
            # continue a workflow and call Claude for later steps.
            def _resolve_async() -> None:
                from core.executor import resolve_confirmation
                resolved = resolve_confirmation("yes")
                self._confirmation_resolved_ready.emit(resolved)
            threading.Thread(target=_resolve_async, daemon=True).start()

    def _on_cancelled(self):
        self._hide_confirm_card()
        mode = self._confirm_mode
        self._confirm_mode = None
        self._pending_result = None
        if mode == "executor":
            from core.executor import resolve_confirmation
            resolve_confirmation("no")

        msg = self._confirmation_controller.CANCEL_MESSAGE
        j_time = datetime.now().strftime("%H:%M")

        if self._history:
            self._history[-1].update({
                "jarvis": msg, "jTime": j_time,
                "intent": "confirmation", "conf": 1.0,
                "status": "warning",
            })

        self._set_state("processing")
        self._dashboard.left.hud_status.set_status("CANCELLED")
        self._dashboard.left.status_lbl.setText(msg)
        self._voice_view.clear_pending()

        # Route through _tts_ready so the transcript typewriter fires and
        # state transitions to speaking → idle (mirrors _on_confirmation_resolved)
        self._transcript_update_token += 1
        t = self._transcript_update_token
        payload = (t, msg, j_time, "confirmation", 1.0)
        try:
            from core.voice import voice_engine
            voice_engine.say(
                msg,
                on_ready=lambda: self._tts_ready.emit(payload),
                on_done=lambda: self._tts_done_signal.emit(t),
            )
        except Exception:
            self._tts_ready.emit(payload)
            self._tts_done_signal.emit(t)

    # ── Inline confirm card helpers ───────────────────────────────────────────

    def _show_confirm_card(self, prompt: str) -> None:
        """Show the transcript confirm card and enter awaiting_confirmation state."""
        wait_line = self._dashboard.left.transcript.show_confirm(prompt)
        self._dashboard.left.typing.hide_typing()
        self._set_state("awaiting_confirmation")
        self._dashboard.left.status_lbl.setText(wait_line)

    def _hide_confirm_card(self) -> None:
        self._dashboard.left.transcript.hide_confirm()

    def _on_history_cleared(self) -> None:
        """Sync main._history and SQLite DB when the user clicks CLEAR HISTORY."""
        self._history.clear()
        self._cmd_count = 0
        history_store.clear()

    # ── Quick settings popover handlers ───────────────────────────────────────

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
        # sit in a "listening" pose while the engine is muted.
        if muted and self._state == "listening":
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

    # ── Command palette handlers ──────────────────────────────────────────────

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

    def _set_state(self, s):
        self._state = s

        # Keep wake detector paused while the system is active.
        # The deferred resume guards against stale QTimer callbacks: if JARVIS
        # transitions idle→thinking in <300ms (always), without the guard the
        # old timer fires and re-enables the detector mid-execution.
        from core.wake_word import wake_detector
        if s == "idle":
            def _resume_if_still_idle():
                if self._state == "idle":
                    wake_detector.resume()
            QTimer.singleShot(300, _resume_if_still_idle)
        else:
            wake_detector.pause()

        orb_map = {
            "idle": 0, "listening": 1, "thinking": 2, "processing": 2,
            "speaking": 3, "awaiting_confirmation": 2,
        }
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
        elif s == "awaiting_confirmation":
            self._dashboard.left.hud_status.set_status("AWAITING RESPONSE")

        pill = self._dashboard.left.state_pill
        _pill_labels = {"awaiting_confirmation": "WAITING"}
        pill.setText(_pill_labels.get(s, s.upper()))
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
        elif s == "awaiting_confirmation":
            self._dashboard.left.state_pill.setStyleSheet(
                "color:rgba(255,190,50,0.90);border:1px solid rgba(255,190,50,0.40);"
                f"background:rgba(255,190,50,0.08);{pill_base}")
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
        from core.wake_word import wake_detector
        wake_detector.stop()
        self._botbar._stop_rtt_thread()
        browser.stop()
        history_store.close()
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
    app.setWindowIcon(jarvis_logo_icon())

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
    # Fusion defaults can make QToolTip text nearly invisible; QSS + palette for ToolTip roles
    pal.setColor(QPalette.ToolTipBase, _c(25, 33, 34))
    pal.setColor(QPalette.ToolTipText, _c(220, 232, 235))
    app.setPalette(pal)
    app.setStyleSheet(tooltip_qss())

    w = JarvisWindow()
    w.setMinimumSize(1280, 800)
    w.showMaximized()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
