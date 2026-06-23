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

import ctypes
import sys
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QKeySequence,
)
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QShortcut,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config.settings import config
from core.brain import TAG_INTENT_MAP
from core.controllers.command_controller import CommandController
from core.controllers.confirmation_controller import ConfirmationController
from core.controllers.runtime_context import RuntimeCommandContext
from core.history_store import history_store
from core.signals import signals
from core.vapi_client import sync_assistant_async
from ui.bars import BottomBar, TopBar
from ui.command_palette import CommandPalette
from ui.components.terminal import TerminalPanel
from ui.dashboard import DashboardView
from ui.history import HistoryView
from ui.main_window.backend_signals_mixin import _BackendSignalsMixin
from ui.main_window.confirm_mixin import _ConfirmMixin

# Module-level constants live in constants.py so the method-group mixins can
# share them without importing this module (which would be an import cycle).
from ui.main_window.constants import (  # noqa: E402
    _SETTINGS_NAV_IDX,
)
from ui.main_window.execution_mixin import _ExecutionMixin
from ui.main_window.interrupt_mixin import _InterruptMixin
from ui.main_window.lifecycle_mixin import _LifecycleMixin
from ui.main_window.settings_mixin import _SettingsMixin
from ui.main_window.state_hud_mixin import _StateHudMixin
from ui.main_window.voice_mixin import _VoiceMixin
from ui.popovers import QuickSettingsPopover, SystemStatusPopover
from ui.settings import SettingsView
from ui.sidebar import HudSidebar
from ui.theme import (
    jarvis_logo_icon,
)
from ui.views.automation.view import AutomationView
from ui.voice import VoiceView


class JarvisWindow(
    _VoiceMixin,
    _ConfirmMixin,
    _ExecutionMixin,
    _BackendSignalsMixin,
    _SettingsMixin,
    _StateHudMixin,
    _LifecycleMixin,
    _InterruptMixin,
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

        # Live streaming transcript → command bar (Phase 3). The bridge is a
        # separate QObject; first access MUST be on the Qt main thread (here),
        # after which worker-thread emits queue safely. Only the streaming STT
        # path emits transcript_partial — the Google batch path never does, so
        # this is inert unless stt_provider="deepgram".
        from core.voice import voice_engine as _ve
        _ve.bridge.capture_ready.connect(
            self._on_capture_ready, Qt.QueuedConnection
        )
        _ve.bridge.transcript_partial.connect(
            self._on_transcript_partial, Qt.QueuedConnection
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
        # User-facing heads-up toasts (e.g. TTS fell back to a backup voice).
        # Emitted off the main thread → QueuedConnection.
        signals.notice.connect(self._on_notice, Qt.QueuedConnection)
        signals.document_generation_done.connect(
            self._on_document_generation_done, Qt.QueuedConnection,
        )
        # code_execution worker emits this off the main thread → QueuedConnection
        # delivers the result back to the main thread for finish / confirm-card.
        signals.code_execution_done.connect(
            self._on_code_execution_done, Qt.QueuedConnection,
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
        # code_execution runs on a worker thread (see execution_mixin). These two
        # are main-thread-only: in-flight blocks new commands, flight_token is the
        # owning command so an orphaned worker can't clear a newer command's guard.
        self._code_exec_in_flight: bool = False
        self._code_exec_flight_token: int = -1
        # Brain context stashed while a code_execution confirm card is shown, so the
        # post-confirm re-run preserves the real action/intent (set in the done-slot).
        self._code_exec_confirm_ctx: dict | None = None
        self._last_error_toast_msg = ""
        self._last_error_toast_ts = 0.0

        # Wire inline transcript confirmation card signals
        self._dashboard.left.transcript.confirmed.connect(self._on_confirmed)
        self._dashboard.left.transcript.cancelled.connect(self._on_cancelled)
        self._pending_result: dict | None = None
        self._confirm_mode: str | None = None  # "claude" | "executor" | None
        self._last_cmd_text: str = ""          # last prompt, for Esc-restore
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

        # Global Esc — interrupt whatever's in flight (thinking / speaking /
        # listening / awaiting confirmation). No-op when idle.
        self._interrupt_shortcut = QShortcut(QKeySequence("Escape"), self)
        self._interrupt_shortcut.setContext(Qt.ApplicationShortcut)
        self._interrupt_shortcut.activated.connect(self._on_interrupt_requested)

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
