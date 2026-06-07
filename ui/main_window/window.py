"""
J.A.R.V.I.S. — JarvisWindow (the HUD main window).

R2-17a: split out of the old root-level ``main.py`` monolith. ``main.py`` is
now a thin shim that re-exports ``JarvisWindow`` and ``main`` from this package.

JarvisWindow stays ONE ``QMainWindow`` / ``QObject``: all ``pyqtSignal``
definitions and every ``.connect()`` call live on this class, in ``__init__``.
Method *groups* are factored into plain mixin classes (the ``core/browser``
pattern) which provide only methods and use only ``self``. The mixins define
disjoint method names, so MRO order is irrelevant to correctness —
``QMainWindow`` (last) supplies the real ``__init__`` via ``super().__init__()``.
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
    QLabel,
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
from ui.components.terminal import TerminalPanel
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

from ui.main_window.voice_mixin import _VoiceMixin
from ui.main_window.confirm_mixin import _ConfirmMixin
from ui.main_window.execution_mixin import _ExecutionMixin
from ui.main_window.backend_signals_mixin import _BackendSignalsMixin
from ui.main_window.settings_mixin import _SettingsMixin
from ui.main_window.state_hud_mixin import _StateHudMixin
from ui.main_window.lifecycle_mixin import _LifecycleMixin

# Module-level constants live in constants.py so the method-group mixins can
# share them without importing this module (which would be an import cycle).
from ui.main_window.constants import (  # noqa: E402
    _SETTINGS_NAV_IDX,
    _HISTORY_MAX,
    _TTS_MAX_CHARS,
)

class JarvisWindow(
    _VoiceMixin,
    _ConfirmMixin,
    _ExecutionMixin,
    _BackendSignalsMixin,
    _SettingsMixin,
    _StateHudMixin,
    _LifecycleMixin,
    QMainWindow,
):
    VIEW_NAMES = ["Dashboard", "Voice", "Automation", "History", "Settings", "Terminal"]

    # Thread-bridge signals: worker threads → Qt main thread (always safe to emit)
    _brain_result_ready  = pyqtSignal(object)        # dict from brain.py
    _voice_text_ready    = pyqtSignal(str)           # transcribed speech text
    _voice_error_ready   = pyqtSignal(str)           # STT failure message
    _confirmation_resolved_ready = pyqtSignal(object)  # resolved confirmation dict
    # Bridges a UI confirm click back onto the Qt main thread so the executor
    # callback (and any subsequent Playwright/dispatch calls) run thread-affine.
    _resume_executor_confirm = pyqtSignal(str)  # "yes" | "no"
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
        self._auto_confirm_banner = QLabel(
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
        self._settings_view.wake_word_changed.connect(self._on_wake_word_toggle)
        self._stack.addWidget(self._settings_view)

        self._terminal_view = TerminalPanel()
        self._terminal_view.command_submitted.connect(self._on_terminal_command)
        self._stack.addWidget(self._terminal_view)

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
        self._resume_executor_confirm.connect(
            self._on_resume_executor_confirm, Qt.QueuedConnection
        )
        self._tts_ready.connect(self._on_tts_ready)
        self._tts_done_signal.connect(self._on_tts_done, Qt.QueuedConnection)
        self._wake_word_signal.connect(self._on_wake_word, Qt.QueuedConnection)
        self._action_followup_tts.connect(
            self._on_action_followup_tts, Qt.QueuedConnection
        )


        # Start always-on wake-word detector (fires _wake_word_signal on detection)
        self._wake_word_enabled = bool(getattr(config, "wake_word_enabled", True))
        from core.wake_word import wake_detector
        wake_detector.start(lambda: self._wake_word_signal.emit())
        if not self._wake_word_enabled:
            wake_detector.pause()

        # Wire backend signals so reminders and errors surface in the HUD
        signals.status_changed.connect(self._on_status_signal)
        signals.reminder_action.connect(self._on_reminder_action)
        signals.reminder_fired.connect(self._on_reminder_fired)
        signals.error_occurred.connect(self._on_error_signal)
        signals.document_generation_done.connect(
            self._on_document_generation_done, Qt.QueuedConnection,
        )
        # F-3: cron scheduler emits this from a worker thread; QueuedConnection
        # bridges onto the Qt main thread so the workflow dispatch runs
        # thread-affine to Playwright etc.
        signals.scheduled_workflow_fire.connect(
            self._on_scheduled_workflow_fire, Qt.QueuedConnection,
        )
        # Start the scheduler daemon. Idempotent; no-op if croniter missing.
        from core.scheduler import start as _start_scheduler
        _start_scheduler()

        # F-4: global hotkeys. Listener runs on the `keyboard` package's own
        # thread; QueuedConnection delivers the action name to our slot on
        # the Qt main thread.
        signals.hotkey_triggered.connect(
            self._on_hotkey, Qt.QueuedConnection,
        )
        try:
            from core.hotkeys import register_bindings as _register_hotkeys
            installed = _register_hotkeys(getattr(config, "hotkeys", {}) or {})
            if installed:
                # Quiet — no toast on startup; user already configured these.
                pass
        except Exception as exc:
            # Hotkeys are nice-to-have; don't let registration failure
            # (Linux without root, weird Windows policy, etc.) block launch.
            print(f"[hotkeys] registration skipped: {exc!r}")
        self._doc_async_ctx: dict | None = None
        self._last_error_toast_msg = ""
        self._last_error_toast_ts = 0.0

        # Wire inline transcript confirmation card signals
        self._dashboard.left.transcript.confirmed.connect(self._on_confirmed)
        self._dashboard.left.transcript.cancelled.connect(self._on_cancelled)
        self._pending_result: dict | None = None
        self._confirm_mode: str | None = None  # "claude" | "executor" | None
        self._cmd_from_terminal = False          # set when a cmd originates in the Terminal box
                                                 # so _process_cmd doesn't open a 2nd block for it
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
        self._quick_settings.wake_word_changed.connect(self._on_wake_word_toggle)
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

    # Intent → HUD status label mapping
    _INTENT_HUD = {
        "open_app":           "LAUNCHING APP",
        "close_app":          "TERMINATING",
        "search_web":         "WEB SEARCH",
        "type_text":          "INPUT MODE",
        "control_mouse":      "MOUSE CONTROL",
        "system_control":     "SYS CONTROL",
        "automation_task":    "AUTOMATION",
        "read_screen":        "OCR SCAN",
        "browser_automation": "BROWSER CTRL",
        "file_operation":     "FILE OPS",
        "code_execution":     "EXECUTING",
        "jarvis_meta":        "STANDBY",
        "reminder_task":      "REMINDER SET",
        "weather":            "WEATHER",
        "document_creation":  "DOCUMENT",
        "unknown":            "UNKNOWN",
    }

    def _on_terminal_command(self, text: str) -> None:
        """Command typed in the Terminal box. The terminal already opened its own
        block in _on_submit, so flag it to stop _process_cmd opening a second one."""
        self._cmd_from_terminal = True
        self._process_cmd(text)

    def _process_cmd(self, cmd: str):
        # Capture + reset immediately so an early-return guard below can't leave
        # the flag set and mislabel the next (dashboard) command.
        from_terminal = self._cmd_from_terminal
        self._cmd_from_terminal = False
        direct_workflow_id, display_cmd = self._command_controller.parse_command(cmd)

        # An outstanding EXECUTOR confirmation (e.g. delete_file) is answered by
        # this reply. A short yes/no/hedged answer is resolved HERE — so the R3-7
        # negation guard runs and "yes — wait, no" stands down — instead of being
        # rejected by the awaiting-confirmation guard below. A full new directive
        # abandons the stale confirmation and falls through to normal routing.
        from core.executor import (
            abandon_pending_confirmation,
            get_pending_confirmation,
            resolve_confirmation,
        )
        from core.handlers.shared import is_decisive_confirmation_reply
        if get_pending_confirmation():
            if not self._command_controller.pending_should_yield_to_new_command(cmd):
                if is_decisive_confirmation_reply(cmd):
                    # A clear yes/no answers the card — mirror the button path:
                    # hide the card + clear the mode before resolving.
                    self._hide_confirm_card()
                    self._confirm_mode = None
                    resolved = resolve_confirmation(cmd)
                    self._on_confirmation_resolved(resolved)
                    return
                # Ambiguous input (e.g. "open chrome") — neither a clear yes/no
                # nor a full new directive. Keep the card up and re-ask, instead
                # of silently standing down (cancelling) on it.
                self._dashboard.toast.show_toast(
                    "Please answer the confirmation first — yes or no.", "warning")
                return
            abandon_pending_confirmation()
            self._hide_confirm_card()
            self._confirm_mode = None
            self._pending_result = None
            try:
                self._voice_view.clear_pending()
            except Exception:
                pass
            if self._state == "awaiting_confirmation":
                self._set_state("idle")

        if self._state == "awaiting_confirmation":
            # Claude inline confirmation (button-driven; no executor pending).
            self._dashboard.toast.show_toast(
                "Please respond to the pending confirmation first.", "warning")
            return
        from core.handlers.document_handler import is_document_generation_in_flight
        if is_document_generation_in_flight():
            self._dashboard.toast.show_toast(
                "Document generation in progress — please wait.", "warning",
            )
            return
        # R3-1/R3-2: a workflow pumps processEvents() between steps, which can
        # re-enter here. Reject a new command while one is running (a confirmation
        # reply already short-circuited above via the pending-confirmation block).
        from core.handlers.automation_handler import is_workflow_in_flight
        if is_workflow_in_flight():
            self._dashboard.toast.show_toast(
                "A workflow is running — please wait.", "warning",
            )
            return
        self._transcript_update_token += 1
        now = datetime.now().strftime("%H:%M")
        # Cap history to avoid unbounded memory growth
        previous_cmd = self._runtime_ctx.get_previous_command(self._history)
        if len(self._history) >= _HISTORY_MAX:
            self._history = self._history[-(_HISTORY_MAX - 1):]
        self._history.append({
            "time": now, "you": display_cmd, "jarvis": "", "jTime": "",
            "intent": "", "conf": 0.0, "status": "pending",
        })
        self._runtime_ctx.note_user_command(display_cmd)
        self._dashboard.left.transcript.add_exchange(display_cmd, now)
        # Global console: mirror EVERY command into the Terminal page so it shows
        # all JARVIS activity (browser, files, system…), not only what's typed in
        # the terminal box. Skip when the command came from the terminal itself —
        # _on_submit already opened that block.
        if not from_terminal:
            try:
                self._terminal_view.begin_external_command(display_cmd)
            except Exception:
                pass
        self._botbar.increment_commands()
        self._cmd_count += 1
        self._set_state("thinking")
        self._dashboard.left.hud_status.set_status("PROCESSING")
        self._dashboard.left.status_lbl.setText(f'Processing: "{display_cmd}"')
        self._dashboard.left.typing.show_typing()

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
                    "response": "Running workflow now.",
                    "hud_status": "AUTOMATION",
                },
                "automation_task",
                1.0,
                "Running workflow now.",
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
            # F-3 carve-out: scheduled workflow fires NEVER bypass the card,
            # even when auto_confirm is on, so a daily cron can't silently
            # run a destructive step while the user is away from the desk.
            if self._auto_confirm and not result.get("_scheduled"):
                self._execute_result(result, intent, conf, resp, hud, confirmed=True)
                return
            self._pending_result = result
            self._confirm_mode = "claude"
            prompt = resp or "Awaiting confirmation."
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
        # Without this, compose_execution_response() skips the ResponseAssembler
        # for vision and only speaks the brain's "Scanning…" acknowledgement —
        # the actual analysis (the OUTPUT_IS_RESPONSE pools, already built) is
        # dropped. Routing vision through the assembler makes JARVIS speak the
        # real answer ("Found it — the close button is top-right …").
        "vision_analysis",
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

        # R2-15: document_creation runs on a worker thread — finish on signal.
        if exec_out.get("document_async"):
            self._doc_async_ctx = {
                "result": result,
                "intent": intent,
                "conf": conf,
                "resp": resp,
                "hud": hud,
            }
            self._dashboard.left.status_lbl.setText(
                "Generating document — please wait…",
            )
            self._set_state("processing")
            spoken = exec_out.get("output") or resp
            self._dashboard.left.hud_status.set_status(hud or "DOCUMENT")
            self._dashboard.toast.show_toast(spoken, "info")
            try:
                from core.voice import voice_engine
                voice_engine.say(spoken)
            except Exception:
                pass
            return

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

    def _on_document_generation_done(self, payload: dict) -> None:
        """R2-15: worker-thread document pipeline finished — finish on main thread."""
        ctx = self._doc_async_ctx
        self._doc_async_ctx = None
        if not ctx:
            return
        exec_out = payload.get("exec_out") or {}
        from core.memory import memory
        memory.inject_outcome(
            intent=ctx["intent"],
            action=ctx["result"].get("action", ""),
            success=bool(exec_out.get("success")),
            output=exec_out.get("output", ""),
            error=exec_out.get("error", ""),
        )
        if exec_out.get("success") and ctx["intent"] in self._ACTION_INTENTS:
            self._last_result = ctx["result"]
        self._finish_execute(
            ctx["result"],
            ctx["intent"],
            ctx["conf"],
            ctx["resp"],
            ctx["hud"],
            exec_out,
        )

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

        # Mirror the brain debug block — surface the personality follow-up
        # line (the data-rich tail spoken after the primary response) so
        # the operator can see what's queued for the second TTS clip.
        # No-op outside debug_mode and when no follow-up is produced.
        if follow and config.debug_mode:
            from core.log import debug as _brain_dbg
            _brain_dbg("brain", f"FOLLOW  : {follow!r}")

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
        from core.responders.utils import _SKIP_TTS, in_rule_set
        _skip_tts = in_rule_set(intent, result.get("action", ""), _SKIP_TTS)
        try:
            from core.voice import voice_engine
            if _skip_tts:
                # Action mutates audio routing (mute/unmute) — skip audio playback
                # but still fire the transcript-ready signal and the on_done
                # continuation so the rest of the pipeline runs unchanged.
                self._tts_ready.emit(transcript_payload)
                _on_primary_done()
            else:
                voice_engine.say(
                    tts_line,
                    on_ready=lambda: self._tts_ready.emit(transcript_payload),
                    on_done=_on_primary_done,
                )
            if exec_out.get("quit_application"):
                audio_len = len(tts_line) + (len(follow) if follow else 0)
                delay_ms = 400 if (voice_engine.tts_muted or _skip_tts) else min(
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
        # Mirror the reply into the redesigned Terminal page so a command typed
        # there gets JARVIS's response inline. No-op unless an awaiting terminal
        # block exists (i.e. the command actually originated in the terminal).
        # While a confirmation is pending this text is only the PROMPT, so keep
        # the block awaiting (final=False) — the eventual result lands next.
        try:
            self._terminal_view.append_jarvis_response(
                text, intent=intent, final=not bool(self._confirm_mode)
            )
        except Exception:
            pass

    def _set_state_if_current(self, token: int, state: str):
        """Ignore stale state timers after a newer command/response starts."""
        if token != self._transcript_update_token:
            return
        self._set_state(state)
