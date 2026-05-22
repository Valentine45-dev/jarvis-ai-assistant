"""SettingsView — SYSTEM_CONFIG.

Redesigned 2026-05 to match the shared HUD grammar:
  - Top 6-tile health strip (Anthropic · ElevenLabs · Gemini · Mic · Wake · Browser)
  - Three sectioned columns:
        API & connectivity   ·  Voice & audio  ·  Behaviour & visuals
  - Each section: PanelCard + divide-y rows with inline labels + descriptions
  - Theme picker: 5 visual swatch tiles (Stark / Teal / Amber / Indigo / Matrix)
  - Bottom apply bar with an "unsaved" pip

Public API preserved so main.py needs no changes:
  - signals: scanline_toggled, mic_muted_changed, tts_muted_changed,
             auto_confirm_changed, dim_mode_changed, wake_word_changed
  - sync_state(mic_muted, tts_muted, auto_confirm, dim_mode, wake_word)
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from config.settings import config
from core.voice import _EL_VOICES
from ui.components.design import (
    AMBER,
    BG_PANEL,
    CYAN_FAINT,
    CYAN_SOFT,
    GREEN,
    INK,
    INK_DIM,
    INK_FAINT,
    RED,
    HeroMetric,
    PanelCard,
    StatusPip,
)
from ui.theme import BG, CYAN, FM
from ui.widgets import ToggleSwitch, _mono


# ── Stylesheet constants ────────────────────────────────────────────────────


_INPUT_SS = (
    "QLineEdit {"
    "background: rgba(8,15,17,0.85);"
    f"border: 1px solid {CYAN_FAINT};"
    f"color: {CYAN};"
    f"font-family: '{FM}';"
    "font-size: 11px;"
    "letter-spacing: 0.5px;"
    "padding: 5px 10px;"
    "}"
    "QLineEdit:focus { border: 1px solid rgba(0,229,255,0.65); }"
)

_COMBO_SS = (
    "QComboBox {"
    "background: rgba(8,15,17,0.85);"
    f"border: 1px solid {CYAN_FAINT};"
    f"color: {CYAN};"
    f"font-family: '{FM}';"
    "font-size: 11px;"
    "padding: 5px 10px;"
    "}"
    "QComboBox:focus { border: 1px solid rgba(0,229,255,0.65); }"
    "QComboBox::drop-down { border: none; width: 20px; }"
    "QComboBox QAbstractItemView {"
    "background: rgba(10,20,22,0.97);"
    f"color: {CYAN};"
    f"font-family: '{FM}';"
    "font-size: 11px;"
    "selection-background-color: rgba(0,229,255,0.15);"
    f"border: 1px solid {CYAN_FAINT};"
    "}"
)

_SLIDER_SS = (
    "QSlider::groove:horizontal {"
    "height: 4px; background: rgba(0,229,255,0.12); border-radius: 2px;"
    "}"
    "QSlider::sub-page:horizontal {"
    f"background: {CYAN_SOFT}; border-radius: 2px;"
    "}"
    "QSlider::handle:horizontal {"
    f"background: {CYAN};"
    "width: 12px; height: 12px;"
    "border-radius: 6px;"
    "margin: -4px 0;"
    "}"
)


# ── Theme swatch picker ──────────────────────────────────────────────────────


class _ThemeSwatch(QFrame):
    """Single theme tile: accent + bg swatches and a label. Click to select."""

    clicked = pyqtSignal(str)  # theme key

    def __init__(self, key: str, name: str, accent: str, bg: str, *,
                 active: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._key = key
        self._active = active
        self._accent = accent
        self._bg = bg

        self.setFixedHeight(58)
        self.setCursor(Qt.PointingHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        # Swatch row: two coloured bars side by side
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        accent_bar = QFrame()
        accent_bar.setStyleSheet(
            f"QFrame {{ background: {accent}; border: none; }}"
        )
        accent_bar.setFixedHeight(16)
        bg_bar = QFrame()
        bg_bar.setStyleSheet(
            f"QFrame {{ background: {bg}; border: 1px solid rgba(255,255,255,0.10); }}"
        )
        bg_bar.setFixedHeight(16)
        row.addWidget(accent_bar)
        row.addWidget(bg_bar)
        lay.addLayout(row)

        self._name_lbl = QLabel(name.upper())
        lay.addWidget(self._name_lbl)
        lay.addStretch(1)

        self._refresh_style()

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        self._refresh_style()

    def _refresh_style(self) -> None:
        if self._active:
            border = f"2px solid {self._accent}"
            bg = "rgba(0,229,255,0.06)"
            label_color = self._accent
        else:
            border = f"1px solid {CYAN_FAINT}"
            bg = "transparent"
            label_color = INK_DIM
        self.setStyleSheet(
            "QFrame {"
            f"background: {bg};"
            f"border: {border};"
            "}"
        )
        self._name_lbl.setStyleSheet(
            "QLabel {"
            f"color: {label_color};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 9.5px;"
            "font-weight: 700;"
            "letter-spacing: 1.8px;"
            "}"
        )

    def mousePressEvent(self, _event) -> None:
        self.clicked.emit(self._key)


# ── Health strip ─────────────────────────────────────────────────────────────


class _HealthStrip(QFrame):
    """Top 6-tile horizontal status row.

    Each tile: status pip + label + state text. Replaces the legacy
    3-pill compact strip with something the user can actually read.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame {"
            f"background: {BG_PANEL};"
            f"border: 1px solid {CYAN_FAINT};"
            "}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._tiles: dict[str, tuple[StatusPip, QLabel]] = {}
        self._add_tile(lay, "anthropic", "ANTHROPIC")
        self._add_tile(lay, "elevenlabs", "ELEVENLABS")
        self._add_tile(lay, "gemini",     "GEMINI TTS")
        self._add_tile(lay, "mic",        "MIC")
        self._add_tile(lay, "wake",       "WAKE WORD")
        self._add_tile(lay, "browser",    "BROWSER", last=True)

        self.refresh()

    def _add_tile(self, lay: QHBoxLayout, key: str, label_text: str, *, last: bool = False) -> None:
        cell = QFrame()
        cell.setStyleSheet(
            "QFrame {"
            "background: transparent;"
            + ("border: none;" if last else f"border-right: 1px solid {CYAN_FAINT};")
            + "}"
        )
        cl = QHBoxLayout(cell)
        cl.setContentsMargins(14, 10, 14, 10)
        cl.setSpacing(10)

        pip = StatusPip("off")
        cl.addWidget(pip, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        name = QLabel(label_text)
        name.setStyleSheet(
            "QLabel {"
            f"color: {INK_FAINT};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 9px;"
            "font-weight: 700;"
            "letter-spacing: 2px;"
            "}"
        )
        col.addWidget(name)
        val = QLabel("—")
        val.setStyleSheet(
            "QLabel {"
            f"color: {INK_DIM};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 11px;"
            "}"
        )
        col.addWidget(val)
        cl.addLayout(col, 1)

        lay.addWidget(cell, 1)
        self._tiles[key] = (pip, val)

    def _set_tile(self, key: str, pip_state: str, value: str, value_color: str) -> None:
        pip, val = self._tiles[key]
        pip.set_state(pip_state)
        val.setText(value)
        val.setStyleSheet(
            f"QLabel {{ color: {value_color}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 11px; }}"
        )

    def refresh(self) -> None:
        """Re-read config + best-effort detect the live state of each provider."""
        # Anthropic
        if config.anthropic_api_key:
            self._set_tile("anthropic", "on", "connected", GREEN)
        else:
            self._set_tile("anthropic", "err", "no key", RED)

        # ElevenLabs
        if config.elevenlabs_api_key:
            self._set_tile("elevenlabs", "on", "key set", GREEN)
        else:
            self._set_tile("elevenlabs", "off", "not configured", INK_DIM)

        # Gemini
        gemini_key = getattr(config, "gemini_api_key", "")
        if gemini_key:
            self._set_tile("gemini", "on", "free tier", GREEN)
        else:
            self._set_tile("gemini", "off", "not configured", INK_DIM)

        # Mic — best effort via sounddevice
        try:
            import sounddevice as _sd  # type: ignore
            inputs = [d for d in _sd.query_devices() if d.get("max_input_channels", 0) > 0]
            if inputs:
                self._set_tile("mic", "on", "detected", GREEN)
            else:
                self._set_tile("mic", "warn", "no inputs", AMBER)
        except Exception:
            self._set_tile("mic", "warn", "unavailable", AMBER)

        # Wake word
        if getattr(config, "wake_word_enabled", True):
            self._set_tile("wake", "on", "listening", GREEN)
        else:
            self._set_tile("wake", "off", "disabled", INK_DIM)

        # Browser — Playwright session: best-effort
        try:
            from core.browser import browser as _b
            if getattr(_b, "_context", None):
                self._set_tile("browser", "on", "running", GREEN)
            else:
                self._set_tile("browser", "off", "not started", INK_DIM)
        except Exception:
            self._set_tile("browser", "off", "not started", INK_DIM)


# ── Field-row helper used inside section panels ─────────────────────────────


def _section_row(
    label: str,
    control: QWidget,
    helper: str = "",
    *,
    parent: Optional[QWidget] = None,
) -> QWidget:
    """One divide-y row inside a section panel.

    Layout:
        ┌─────────────────────────────────────────┐
        │  LABEL                       [control]  │
        │  (optional helper text on a 2nd line)   │
        └─────────────────────────────────────────┘
    """
    w = QFrame(parent)
    # `border: none` before `border-bottom` so the parent PanelCard's
    # `QFrame { border: ... }` cascade doesn't paint top/left/right edges
    # on each row (same bug as DivideRow — see its docstring).
    w.setStyleSheet(
        "QFrame {"
        "background: transparent;"
        "border: none;"
        "border-bottom: 1px solid rgba(0,229,255,0.07);"
        "}"
    )
    outer = QVBoxLayout(w)
    outer.setContentsMargins(0, 8, 0, 8)
    outer.setSpacing(4)

    row = QHBoxLayout()
    row.setSpacing(12)
    lbl = QLabel(label.upper())
    lbl.setStyleSheet(
        "QLabel {"
        f"color: {INK};"
        "background: transparent;"
        "border: none;"
        f"font-family: '{FM}';"
        "font-size: 10.5px;"
        "letter-spacing: 1.5px;"
        "}"
    )
    row.addWidget(lbl, 1)
    row.addWidget(control, 0)
    outer.addLayout(row)

    if helper:
        hl = QLabel(helper)
        hl.setStyleSheet(
            "QLabel {"
            f"color: {INK_FAINT};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 9.5px;"
            "letter-spacing: 0.3px;"
            "}"
        )
        hl.setWordWrap(True)
        outer.addWidget(hl)
    return w


# ── Main view ───────────────────────────────────────────────────────────────


class SettingsView(QWidget):
    """SYSTEM_CONFIG. See module docstring."""

    scanline_toggled     = pyqtSignal(bool)
    mic_muted_changed    = pyqtSignal(bool)
    tts_muted_changed    = pyqtSignal(bool)
    auto_confirm_changed = pyqtSignal(bool)
    dim_mode_changed     = pyqtSignal(bool)
    wake_word_changed    = pyqtSignal(bool)

    # Theme catalogue: keys match config.theme; mockup constants reused.
    _THEMES: tuple[tuple[str, str, str, str], ...] = (
        # (key, display, accent, bg)
        ("cyan",     "Stark",   "#00e5ff", "#080A0A"),
        ("teal",     "Teal",    "#3dc7d6", "#0a1010"),
        ("amber",    "Amber",   "#ffaa00", "#0d0a04"),
        ("indigo",   "Indigo",  "#818cf8", "#060912"),
        ("matrix",   "Matrix",  "#00ff66", "#050a06"),
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._bg_px: Optional[QPixmap] = None
        self._bg_sz = (-1, -1)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # ── Header ──────────────────────────────────────────────────────────
        head = QHBoxLayout()
        head.setSpacing(12)
        title = QLabel("SYSTEM_CONFIG")
        title.setStyleSheet(
            "QLabel {"
            f"color: {CYAN};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 32px;"
            "font-weight: 700;"
            "letter-spacing: 5px;"
            "}"
        )
        head.addWidget(title, 0, Qt.AlignBottom)

        subtitle = QLabel("RUNTIME CONFIGURATION · API · AUDIO · SESSION FLAGS")
        subtitle.setStyleSheet(
            "QLabel {"
            f"color: {INK_DIM};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "letter-spacing: 2px;"
            "padding-bottom: 6px;"
            "}"
        )
        head.addWidget(subtitle, 0, Qt.AlignBottom)
        head.addStretch(1)

        self._unsaved_lbl = QLabel("● UNSAVED")
        self._unsaved_lbl.setStyleSheet(
            "QLabel {"
            f"color: {AMBER};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 9px;"
            "font-weight: 700;"
            "letter-spacing: 2px;"
            "}"
        )
        self._unsaved_lbl.setVisible(False)
        head.addWidget(self._unsaved_lbl)
        root.addLayout(head)

        # ── Health strip ────────────────────────────────────────────────────
        self._health = _HealthStrip()
        root.addWidget(self._health)

        # ── 3-column body ───────────────────────────────────────────────────
        cols = QHBoxLayout()
        cols.setSpacing(14)
        cols.addWidget(self._build_api_panel(), 1)
        cols.addWidget(self._build_voice_panel(), 1)
        cols.addWidget(self._build_behaviour_panel(), 1)
        root.addLayout(cols, 1)

        # ── Apply bar ───────────────────────────────────────────────────────
        apply_bar = QFrame()
        apply_bar.setStyleSheet(
            "QFrame {"
            f"background: {BG_PANEL};"
            f"border: 1px solid {CYAN_FAINT};"
            "}"
        )
        abl = QHBoxLayout(apply_bar)
        abl.setContentsMargins(14, 8, 14, 8)
        abl.setSpacing(12)

        hint = QLabel("Apply writes API keys to .env and other prefs to data/jarvis.json.")
        hint.setStyleSheet(
            f"QLabel {{ color: {INK_DIM}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 10px; }}"
        )
        abl.addWidget(hint, 1)

        self._apply_btn = QPushButton("APPLY_CFG")
        self._apply_btn.setCursor(Qt.PointingHandCursor)
        self._apply_btn.setToolTip("Save configuration")
        self._apply_btn.setStyleSheet(
            "QPushButton {"
            "background: transparent;"
            f"color: {CYAN};"
            f"border: 1px solid {CYAN_SOFT};"
            f"font-family: '{FM}';"
            "font-size: 11px;"
            "font-weight: 700;"
            "padding: 6px 18px;"
            "letter-spacing: 2px;"
            "}"
            "QPushButton:hover { background: rgba(0,229,255,0.10); }"
            "QPushButton:pressed { background: rgba(0,229,255,0.18); }"
        )
        self._apply_btn.clicked.connect(self._apply_cfg)
        abl.addWidget(self._apply_btn)
        root.addWidget(apply_bar)

        # Wire dirty markers on every field
        self._wire_dirty_indicators()

    # ── Panel builders ───────────────────────────────────────────────────────

    def _build_api_panel(self) -> PanelCard:
        panel = PanelCard("API & connectivity", active=True)

        self._anthro_key = QLineEdit(config.anthropic_api_key)
        self._anthro_key.setEchoMode(QLineEdit.Password)
        self._anthro_key.setPlaceholderText("sk-ant-…")
        self._anthro_key.setStyleSheet(_INPUT_SS)
        panel.add(_section_row(
            "Anthropic key", self._anthro_key,
            "Required. Routes every command through Claude.",
        ))

        self._eleven_key = QLineEdit(config.elevenlabs_api_key)
        self._eleven_key.setEchoMode(QLineEdit.Password)
        self._eleven_key.setPlaceholderText("el-…")
        self._eleven_key.setStyleSheet(_INPUT_SS)
        panel.add(_section_row(
            "ElevenLabs key", self._eleven_key,
            "Primary TTS provider. Falls back to Gemini when quota-locked.",
        ))

        self._gemini_key = QLineEdit(getattr(config, "gemini_api_key", ""))
        self._gemini_key.setEchoMode(QLineEdit.Password)
        self._gemini_key.setPlaceholderText("AIza…")
        self._gemini_key.setStyleSheet(_INPUT_SS)
        panel.add(_section_row(
            "Gemini key", self._gemini_key,
            "Fallback TTS. 10 calls/day on the free tier.",
        ))

        self._vapi_key = QLineEdit(config.vapi_api_key)
        self._vapi_key.setEchoMode(QLineEdit.Password)
        self._vapi_key.setPlaceholderText("vapi-…")
        self._vapi_key.setStyleSheet(_INPUT_SS)
        panel.add(_section_row(
            "Vapi key", self._vapi_key,
            "Optional. Syncs the JARVIS assistant config for web/phone deployment.",
        ))

        self._model_combo = QComboBox()
        self._model_combo.setStyleSheet(_COMBO_SS)
        for display, model_id in (
            ("Claude Sonnet 4.6", "claude-sonnet-4-6"),
            ("Claude Opus 4.7",   "claude-opus-4-7"),
            ("Claude Haiku 4.5",  "claude-haiku-4-5-20251001"),
        ):
            self._model_combo.addItem(display, userData=model_id)
        current_idx = next(
            (i for i in range(self._model_combo.count())
             if self._model_combo.itemData(i) == config.claude_model), 0
        )
        self._model_combo.setCurrentIndex(current_idx)
        panel.add(_section_row(
            "Claude model", self._model_combo,
            "Sonnet 4.6 for routing. Opus available for heavier reasoning.",
        ))

        self._debug_toggle = ToggleSwitch(config.debug_mode)
        panel.add(_section_row(
            "Debug mode", self._debug_toggle,
            "Print raw brain JSON, FOLLOW lines, and per-handler traces to stderr.",
        ))

        panel.body().addStretch(1)
        return panel

    def _build_voice_panel(self) -> PanelCard:
        panel = PanelCard("Voice & audio")

        self._voice_combo = QComboBox()
        self._voice_combo.setStyleSheet(_COMBO_SS)
        for key in sorted(_EL_VOICES.keys()):
            self._voice_combo.addItem(key.replace("-", " ").title(), userData=key)
        voice_idx = next(
            (i for i in range(self._voice_combo.count())
             if self._voice_combo.itemData(i) == config.tts_voice), 0
        )
        self._voice_combo.setCurrentIndex(voice_idx)
        panel.add(_section_row(
            "Voice profile", self._voice_combo,
            "ElevenLabs voice ID. Falls back to pyttsx3 when no TTS provider available.",
        ))

        self._wake_input = QLineEdit(config.wake_word)
        self._wake_input.setStyleSheet(_INPUT_SS)
        self._wake_input.setFixedWidth(160)
        panel.add(_section_row(
            "Wake word", self._wake_input,
            "Phrase that activates voice input. Lowercase; one or two words works best.",
        ))

        self._mic_device_combo = QComboBox()
        self._mic_device_combo.setStyleSheet(_COMBO_SS)
        self._mic_device_combo.addItem("System Default", -1)
        try:
            import sounddevice as _sd  # type: ignore
            for idx, dev in enumerate(_sd.query_devices()):
                if dev["max_input_channels"] > 0:
                    self._mic_device_combo.addItem(
                        f"[{idx}] {dev['name'][:36]}", idx
                    )
                    if idx == config.mic_device:
                        self._mic_device_combo.setCurrentIndex(
                            self._mic_device_combo.count() - 1
                        )
        except Exception:
            pass
        panel.add(_section_row(
            "Mic device", self._mic_device_combo,
            "Input device for STT. System default works for most laptops.",
        ))

        # Sensitivity slider
        sens_row = QHBoxLayout()
        sens_row.setSpacing(10)
        self._mic_slider = QSlider(Qt.Horizontal)
        self._mic_slider.setRange(0, 100)
        self._mic_slider.setValue(config.mic_sensitivity)
        self._mic_slider.setStyleSheet(_SLIDER_SS)
        self._mic_slider.setFixedWidth(140)
        self._mic_val = QLabel(f"{config.mic_sensitivity}")
        self._mic_val.setFixedWidth(28)
        self._mic_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._mic_val.setStyleSheet(
            f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 10px; }}"
        )
        self._mic_slider.valueChanged.connect(lambda v: self._mic_val.setText(f"{v}"))
        sens_row.addWidget(self._mic_slider)
        sens_row.addWidget(self._mic_val)
        sens_wrap = QWidget()
        sens_wrap.setLayout(sens_row)
        panel.add(_section_row("Mic sensitivity", sens_wrap,
                               "Threshold for voice detection. Lower → more sensitive."))

        # TTS speed slider
        tts_row = QHBoxLayout()
        tts_row.setSpacing(10)
        self._tts_slider = QSlider(Qt.Horizontal)
        self._tts_slider.setRange(50, 200)
        self._tts_slider.setValue(config.tts_speed)
        self._tts_slider.setStyleSheet(_SLIDER_SS)
        self._tts_slider.setFixedWidth(140)
        self._tts_val = QLabel(f"{config.tts_speed}")
        self._tts_val.setFixedWidth(28)
        self._tts_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._tts_val.setStyleSheet(
            f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 10px; }}"
        )
        self._tts_slider.valueChanged.connect(lambda v: self._tts_val.setText(f"{v}"))
        tts_row.addWidget(self._tts_slider)
        tts_row.addWidget(self._tts_val)
        tts_wrap = QWidget()
        tts_wrap.setLayout(tts_row)
        panel.add(_section_row("TTS speed", tts_wrap,
                               "Speech rate of the TTS engine. 100 = default."))

        # Noise gate + wake word listener
        self._noise_toggle = ToggleSwitch(config.noise_gate)
        panel.add(_section_row("Noise gate", self._noise_toggle,
                               "Filter ambient noise before voice detection."))

        self._flag_wake = ToggleSwitch(getattr(config, "wake_word_enabled", True))
        self._flag_wake.toggled.connect(self.wake_word_changed.emit)
        panel.add(_section_row("Wake listener", self._flag_wake,
                               "Listen for the wake word in the background."))

        panel.body().addStretch(1)
        return panel

    def _build_behaviour_panel(self) -> PanelCard:
        panel = PanelCard("Behaviour & visuals")

        # Session-mute toggles (mic / TTS)
        self._flag_mic = ToggleSwitch(getattr(config, "mic_muted", False))
        self._flag_mic.toggled.connect(self.mic_muted_changed.emit)
        panel.add(_section_row("Mute mic", self._flag_mic,
                               "Block voice capture session-wide. Hotkey: Ctrl+Shift+M."))

        self._flag_tts = ToggleSwitch(getattr(config, "tts_muted", False))
        self._flag_tts.toggled.connect(self.tts_muted_changed.emit)
        panel.add(_section_row("Mute TTS", self._flag_tts,
                               "Suppress spoken responses. Transcript still updates."))

        self._flag_conf = ToggleSwitch(getattr(config, "auto_confirm", False))
        self._flag_conf.toggled.connect(self.auto_confirm_changed.emit)
        panel.add(_section_row("Auto-confirm", self._flag_conf,
                               "Skip confirmation prompts. Destructive actions run instantly."))

        self._flag_dim = ToggleSwitch(getattr(config, "dim_mode", False))
        self._flag_dim.toggled.connect(self.dim_mode_changed.emit)
        panel.add(_section_row("Dim mode", self._flag_dim,
                               "Reduce brightness for low-light use."))

        self._scan_toggle = ToggleSwitch(True)
        self._scan_toggle.toggled.connect(self.scanline_toggled.emit)
        panel.add(_section_row("Scanline FX", self._scan_toggle,
                               "Animated horizontal scanline overlay across the HUD."))

        # ── Theme swatch picker ─────────────────────────────────────────────
        theme_label = QLabel("HUD THEME")
        theme_label.setStyleSheet(
            "QLabel {"
            f"color: {INK};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 10.5px;"
            "letter-spacing: 1.5px;"
            "margin-top: 8px;"
            "}"
        )
        panel.body().addWidget(theme_label)

        swatch_grid = QHBoxLayout()
        swatch_grid.setSpacing(6)
        self._swatches: dict[str, _ThemeSwatch] = {}
        current_theme = getattr(config, "theme", "cyan")
        for key, name, accent, bg in self._THEMES:
            sw = _ThemeSwatch(key, name, accent, bg, active=(key == current_theme))
            sw.clicked.connect(self._on_swatch_clicked)
            self._swatches[key] = sw
            swatch_grid.addWidget(sw, 1)
        panel.body().addLayout(swatch_grid)

        # Hidden field — tracks the selected theme for _apply_cfg to read
        self._selected_theme = current_theme

        theme_helper = QLabel("5 variants. Stark Cyan is default.")
        theme_helper.setStyleSheet(
            "QLabel {"
            f"color: {INK_FAINT};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 9.5px;"
            "}"
        )
        panel.body().addWidget(theme_helper)

        panel.body().addStretch(1)
        return panel

    # ── Event handlers ───────────────────────────────────────────────────────

    def _on_swatch_clicked(self, key: str) -> None:
        if key == self._selected_theme:
            return
        self._selected_theme = key
        for k, sw in self._swatches.items():
            sw.set_active(k == key)
        self._mark_dirty()

    def _wire_dirty_indicators(self) -> None:
        for sig in (
            self._anthro_key.textChanged,
            self._eleven_key.textChanged,
            self._gemini_key.textChanged,
            self._vapi_key.textChanged,
            self._wake_input.textChanged,
        ):
            sig.connect(lambda _: self._mark_dirty())
        self._voice_combo.currentIndexChanged.connect(lambda _: self._mark_dirty())
        self._model_combo.currentIndexChanged.connect(lambda _: self._mark_dirty())
        self._debug_toggle.toggled.connect(lambda _: self._mark_dirty())
        self._scan_toggle.toggled.connect(lambda _: self._mark_dirty())
        self._mic_slider.valueChanged.connect(lambda _: self._mark_dirty())
        self._tts_slider.valueChanged.connect(lambda _: self._mark_dirty())
        self._noise_toggle.toggled.connect(lambda _: self._mark_dirty())
        self._mic_device_combo.currentIndexChanged.connect(lambda _: self._mark_dirty())

    def _mark_dirty(self) -> None:
        self._unsaved_lbl.setVisible(True)

    def _mark_clean(self) -> None:
        self._unsaved_lbl.setVisible(False)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _apply_cfg(self) -> None:
        from core.signals import signals
        from core.voice import voice_engine

        config.anthropic_api_key = self._anthro_key.text().strip()
        config.elevenlabs_api_key = self._eleven_key.text().strip()
        if hasattr(config, "gemini_api_key"):
            config.gemini_api_key = self._gemini_key.text().strip()
        config.vapi_api_key      = self._vapi_key.text().strip()
        config.claude_model      = self._model_combo.currentData()
        config.wake_word         = self._wake_input.text().strip() or "jarvis"

        selected_voice = self._voice_combo.currentData() or config.tts_voice
        voice_err = ""
        if selected_voice != config.tts_voice:
            ok, msg, _kind = voice_engine.switch_tts_voice(
                selected_voice,
                validate_provider=True,
                persist=False,
            )
            if not ok:
                voice_err = msg
                selected_voice = config.tts_voice
                voice_idx = next(
                    (i for i in range(self._voice_combo.count())
                     if self._voice_combo.itemData(i) == selected_voice),
                    0,
                )
                self._voice_combo.setCurrentIndex(voice_idx)
        config.tts_voice = selected_voice

        config.theme            = self._selected_theme
        config.debug_mode       = self._debug_toggle.isChecked()
        config.mic_sensitivity  = self._mic_slider.value()
        config.tts_speed        = self._tts_slider.value()
        config.noise_gate       = self._noise_toggle.isChecked()
        config.mic_device       = self._mic_device_combo.currentData()
        # Session flags snapshot
        config.mic_muted        = self._flag_mic.isChecked()
        config.tts_muted        = self._flag_tts.isChecked()
        config.auto_confirm     = self._flag_conf.isChecked()
        config.dim_mode         = self._flag_dim.isChecked()
        config.wake_word_enabled = self._flag_wake.isChecked()

        try:
            config.save()
            self._apply_btn.setText("SAVED ✓" if not voice_err else "SAVED (VOICE UNCHANGED)")
            self._mark_clean()
            self._health.refresh()
            if voice_err:
                signals.error_occurred.emit(voice_err)
        except Exception:
            self._apply_btn.setText("SAVE ERROR")

        QTimer.singleShot(2000, lambda: self._apply_btn.setText("APPLY_CFG"))

    # ── External hooks ───────────────────────────────────────────────────────

    def showEvent(self, event) -> None:
        """Re-sync voice combo from live config each time the page is shown."""
        voice_idx = next(
            (i for i in range(self._voice_combo.count())
             if self._voice_combo.itemData(i) == config.tts_voice),
            0,
        )
        self._voice_combo.setCurrentIndex(voice_idx)
        super().showEvent(event)

    def sync_state(
        self,
        mic_muted: bool,
        tts_muted: bool,
        auto_confirm: bool,
        dim_mode: bool = False,
        wake_word: bool = True,
    ) -> None:
        """Reflect external flag values without re-emitting toggle signals."""
        for tog, val in (
            (self._flag_mic,  mic_muted),
            (self._flag_tts,  tts_muted),
            (self._flag_conf, auto_confirm),
            (self._flag_dim,  dim_mode),
            (self._flag_wake, wake_word),
        ):
            tog.blockSignals(True)
            try:
                tog.setChecked(val)
            finally:
                tog.blockSignals(False)

    # ── Paint (dotted backdrop) ──────────────────────────────────────────────

    def _rebuild_bg(self) -> None:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            self._bg_px = None
            return
        px = QPixmap(w, h)
        p = QPainter(px)
        p.fillRect(0, 0, w, h, QColor(BG))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 229, 255, 18))
        for x in range(0, w + 28, 28):
            for y in range(0, h + 28, 28):
                p.drawEllipse(x - 1, y - 1, 2, 2)
        p.end()
        self._bg_px = px
        self._bg_sz = (w, h)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._bg_px = None

    def paintEvent(self, _event) -> None:
        w, h = self.width(), self.height()
        if self._bg_px is None or self._bg_sz != (w, h):
            self._rebuild_bg()
        p = QPainter(self)
        if self._bg_px is not None:
            p.drawPixmap(0, 0, self._bg_px)
