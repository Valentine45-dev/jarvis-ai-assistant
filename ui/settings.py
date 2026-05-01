"""SettingsView — SYSTEM_CONFIG: real AppConfig wired to interactive controls."""

from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

from config.settings import config
from core.voice import _EL_VOICES
from ui.theme import BG, CYAN, FM, GREEN, PRIMARY, RED, WARNING
from ui.widgets import GlassPanel, StatusPip, ToggleSwitch, _mono, _panel_header


_INPUT_SS = (
    "QLineEdit{"
    "background:rgba(8,15,17,0.85);"
    "border:1px solid rgba(0,229,255,0.30);"
    f"color:{CYAN};"
    f"font-family:'{FM}';"
    "font-size:12px;letter-spacing:1px;padding:6px 10px;"
    "}"
    "QLineEdit:focus{border:1px solid rgba(0,229,255,0.65);}"
)

_COMBO_SS = (
    "QComboBox{"
    "background:rgba(8,15,17,0.85);"
    "border:1px solid rgba(0,229,255,0.30);"
    f"color:{CYAN};"
    f"font-family:'{FM}';"
    "font-size:12px;padding:6px 10px;"
    "}"
    "QComboBox:focus{border:1px solid rgba(0,229,255,0.65);}"
    "QComboBox::drop-down{border:none;width:20px;}"
    "QComboBox QAbstractItemView{"
    "background:rgba(10,20,22,0.97);"
    f"color:{CYAN};"
    f"font-family:'{FM}';"
    "font-size:12px;selection-background-color:rgba(0,229,255,0.15);"
    "border:1px solid rgba(0,229,255,0.30);"
    "}"
)

_SLIDER_SS = (
    "QSlider::groove:horizontal{"
    "height:4px;background:rgba(0,229,255,0.12);border-radius:2px;"
    "}"
    f"QSlider::sub-page:horizontal{{background:rgba(0,229,255,0.45);border-radius:2px;}}"
    "QSlider::handle:horizontal{"
    f"background:{CYAN};width:12px;height:12px;"
    "border-radius:6px;margin:-4px 0;"
    "}"
)


def _section_lbl(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(_mono(8, bold=True))
    lbl.setStyleSheet(
        "color:rgba(186,201,204,0.50);letter-spacing:2px;"
        "background:transparent;border:none;"
    )
    return lbl



def _field(label: str, widget: QWidget, label_w: int = 132) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(10)
    lbl = QLabel(label)
    lbl.setFixedWidth(label_w)
    lbl.setFont(_mono(9))
    lbl.setStyleSheet(
        "color:rgba(186,201,204,0.65);background:transparent;border:none;"
    )
    row.addWidget(lbl)
    row.addWidget(widget, 1)
    return row


# ── Connection health strip ────────────────────────────────────────────────

class _HealthStrip(QWidget):
    """Three-pill strip showing live connection state for key subsystems."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(50)
        self.setStyleSheet(
            "background:rgba(8,15,17,0.55);"
            "border:1px solid rgba(0,229,255,0.09);"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(0)

        self._anthro_pip, self._anthro_val = self._pill(lay, "ANTHROPIC")
        self._div(lay)
        self._eleven_pip, self._eleven_val = self._pill(lay, "ELEVENLABS")
        self._div(lay)
        self._browser_pip, self._browser_val = self._pill(lay, "BROWSER")
        lay.addStretch(1)

        self.refresh()

    def _pill(self, layout, label: str):
        pill = QWidget()
        pill.setStyleSheet("background:transparent;")
        pl = QHBoxLayout(pill)
        pl.setContentsMargins(14, 0, 14, 0)
        pl.setSpacing(7)

        pip = StatusPip("standby")
        pip.setFixedSize(8, 8)
        pl.addWidget(pip, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(1)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            "color:rgba(132,147,150,0.45);font-family:'Roboto Mono';"
            "font-size:8px;letter-spacing:1px;background:transparent;border:none;"
        )
        val = QLabel("—")
        val.setStyleSheet(
            "color:rgba(132,147,150,0.65);font-family:'Roboto Mono';"
            "font-size:10px;font-weight:700;background:transparent;border:none;"
        )
        col.addWidget(lbl)
        col.addWidget(val)
        pl.addLayout(col)
        layout.addWidget(pill)
        return pip, val

    @staticmethod
    def _div(layout):
        d = QFrame()
        d.setFrameShape(QFrame.VLine)
        d.setStyleSheet(
            "color:rgba(0,229,255,0.10);background:rgba(0,229,255,0.10);"
        )
        d.setFixedWidth(1)
        layout.addWidget(d)

    def _set_pill(self, pip: StatusPip, val_lbl: QLabel, ok: bool,
                  ok_text: str = "CONNECTED", fail_text: str = "MISSING"):
        color = GREEN if ok else RED
        pip.set_status("active" if ok else "error")
        val_lbl.setText(ok_text if ok else fail_text)
        val_lbl.setStyleSheet(
            f"color:{color};font-family:'Roboto Mono';"
            "font-size:10px;font-weight:700;background:transparent;border:none;"
        )

    def refresh(self):
        """Re-read live state. Call after config save or on page show."""
        self._set_pill(
            self._anthro_pip, self._anthro_val,
            bool(config.anthropic_api_key),
        )
        self._set_pill(
            self._eleven_pip, self._eleven_val,
            bool(config.elevenlabs_api_key),
        )
        try:
            from core.browser import browser
            ready = browser.is_ready
        except Exception:
            ready = False
        self._set_pill(
            self._browser_pip, self._browser_val,
            ready, ok_text="READY", fail_text="STARTING",
        )
        if not ready:
            # amber instead of red — browser may still be initialising
            self._browser_pip.set_status("standby")
            self._browser_val.setStyleSheet(
                f"color:{WARNING};font-family:'Roboto Mono';"
                "font-size:10px;font-weight:700;background:transparent;border:none;"
            )


# ─────────────────────────────────────────────────────────────────────────────


class SettingsView(QWidget):
    scanline_toggled     = pyqtSignal(bool)
    mic_muted_changed    = pyqtSignal(bool)
    tts_muted_changed    = pyqtSignal(bool)
    auto_confirm_changed = pyqtSignal(bool)
    dim_mode_changed     = pyqtSignal(bool)
    wake_word_changed    = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg_px: "QPixmap | None" = None
        self._bg_sz = (-1, -1)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── Header ────────────────────────────────────────────────────────────
        head = QHBoxLayout()
        title = QLabel("SYSTEM_CONFIG")
        title.setStyleSheet(
            "QLabel{"
            f"color:{PRIMARY};"
            "font-family:'Space Grotesk';font-size:40px;font-weight:700;"
            "background:transparent;border:none;"
            "}"
        )
        head.addWidget(title, 1)

        self._unsaved_lbl = QLabel("● UNSAVED")
        self._unsaved_lbl.setFont(_mono(9, bold=True))
        self._unsaved_lbl.setStyleSheet(
            f"color:{WARNING};letter-spacing:2px;background:transparent;border:none;"
        )
        self._unsaved_lbl.setVisible(False)
        head.addWidget(self._unsaved_lbl, 0, Qt.AlignVCenter)
        root.addLayout(head)

        subtitle = QLabel("RUNTIME CONFIGURATION  //  API, AUDIO & SESSION FLAGS")
        subtitle.setStyleSheet(
            "QLabel{color:rgba(132,147,150,0.9);font-family:'Roboto Mono';"
            "font-size:11px;letter-spacing:1px;background:transparent;border:none;}"
        )
        root.addWidget(subtitle)

        # ── Health strip ──────────────────────────────────────────────────────
        self._health = _HealthStrip()
        root.addWidget(self._health)

        # ── Upper row: API config + JARVIS meta ───────────────────────────────
        upper = QHBoxLayout()
        upper.setSpacing(12)

        # Left: API Configuration
        api_panel = GlassPanel()
        api_panel.set_fill_color(QColor(10, 17, 19, 220))
        api_lay = QVBoxLayout(api_panel)
        api_lay.setContentsMargins(0, 0, 0, 0)
        api_lay.setSpacing(0)

        hdr, sep = _panel_header("API CONFIGURATION")
        api_lay.addWidget(hdr)
        api_lay.addWidget(sep)

        api_body = QWidget()
        api_body.setStyleSheet("background:transparent;")
        ab = QVBoxLayout(api_body)
        ab.setContentsMargins(14, 14, 14, 14)
        ab.setSpacing(12)

        self._anthro_key = QLineEdit(config.anthropic_api_key)
        self._anthro_key.setEchoMode(QLineEdit.Password)
        self._anthro_key.setPlaceholderText("sk-ant-...")
        self._anthro_key.setStyleSheet(_INPUT_SS)
        self._anthro_key.setToolTip("Anthropic API key — kept in .env, not saved to JSON")
        ab.addLayout(_field("ANTHROPIC_KEY", self._anthro_key))

        self._eleven_key = QLineEdit(config.elevenlabs_api_key)
        self._eleven_key.setEchoMode(QLineEdit.Password)
        self._eleven_key.setPlaceholderText("el-...")
        self._eleven_key.setStyleSheet(_INPUT_SS)
        self._eleven_key.setToolTip("ElevenLabs API key for TTS — kept in .env, not saved to JSON")
        ab.addLayout(_field("ELEVENLABS_KEY", self._eleven_key))

        self._vapi_key = QLineEdit(config.vapi_api_key)
        self._vapi_key.setEchoMode(QLineEdit.Password)
        self._vapi_key.setPlaceholderText("vapi-...")
        self._vapi_key.setStyleSheet(_INPUT_SS)
        self._vapi_key.setToolTip("Vapi API key")
        ab.addLayout(_field("VAPI_KEY", self._vapi_key))

        self._model_combo = QComboBox()
        self._model_combo.setStyleSheet(_COMBO_SS)
        self._model_combo.setToolTip("Claude model used for intent routing")
        _models = [
            ("Claude Sonnet 4.6", "claude-sonnet-4-6"),
            ("Claude Opus 4.7",   "claude-opus-4-7"),
            ("Claude Haiku 4.5",  "claude-haiku-4-5-20251001"),
        ]
        for display, model_id in _models:
            self._model_combo.addItem(display, userData=model_id)
        current_idx = next(
            (i for i, (_, mid) in enumerate(_models) if mid == config.claude_model), 0
        )
        self._model_combo.setCurrentIndex(current_idx)
        ab.addLayout(_field("MODEL", self._model_combo))

        debug_row = QHBoxLayout()
        debug_row.setSpacing(10)
        debug_lbl = QLabel("DEBUG_MODE")
        debug_lbl.setFixedWidth(120)
        debug_lbl.setFont(_mono(9))
        debug_lbl.setStyleSheet(
            "color:rgba(186,201,204,0.65);background:transparent;border:none;"
        )
        self._debug_toggle = ToggleSwitch(config.debug_mode)
        debug_row.addWidget(debug_lbl)
        debug_row.addWidget(self._debug_toggle)
        debug_row.addStretch(1)
        ab.addLayout(debug_row)

        ab.addStretch(1)
        api_lay.addWidget(api_body, 1)
        upper.addWidget(api_panel, 1)

        # Right: JARVIS Meta
        meta_panel = GlassPanel()
        meta_panel.set_fill_color(QColor(10, 17, 19, 220))
        meta_lay = QVBoxLayout(meta_panel)
        meta_lay.setContentsMargins(0, 0, 0, 0)
        meta_lay.setSpacing(0)

        mhdr, msep = _panel_header("JARVIS_META")
        meta_lay.addWidget(mhdr)
        meta_lay.addWidget(msep)

        meta_body = QWidget()
        meta_body.setStyleSheet("background:transparent;")
        mb = QVBoxLayout(meta_body)
        mb.setContentsMargins(14, 14, 14, 14)
        mb.setSpacing(12)

        self._voice_combo = QComboBox()
        self._voice_combo.setStyleSheet(_COMBO_SS)
        self._voice_combo.setToolTip("Select an available ElevenLabs voice profile")
        for key in sorted(_EL_VOICES.keys()):
            self._voice_combo.addItem(key.replace("-", " ").title(), userData=key)
        voice_idx = next(
            (i for i in range(self._voice_combo.count())
             if self._voice_combo.itemData(i) == config.tts_voice),
            0,
        )
        self._voice_combo.setCurrentIndex(voice_idx)
        mb.addLayout(_field("VOICE_MATRIX", self._voice_combo))

        self._wake_input = QLineEdit(config.wake_word)
        self._wake_input.setStyleSheet(_INPUT_SS)
        self._wake_input.setToolTip("Wake word to activate voice input")
        mb.addLayout(_field("WAKE_PROTOCOL", self._wake_input))

        self._theme_combo = QComboBox()
        self._theme_combo.setStyleSheet(_COMBO_SS)
        for theme in ("cyan", "gold", "emerald", "crimson"):
            self._theme_combo.addItem(theme.upper(), userData=theme)
        theme_idx = next(
            (i for i in range(self._theme_combo.count())
             if self._theme_combo.itemData(i) == config.theme), 0
        )
        self._theme_combo.setCurrentIndex(theme_idx)
        mb.addLayout(_field("HUD_THEME", self._theme_combo))

        scan_row = QHBoxLayout()
        scan_row.setSpacing(10)
        scan_lbl = QLabel("SCANLINE_FX")
        scan_lbl.setFixedWidth(120)
        scan_lbl.setFont(_mono(9))
        scan_lbl.setStyleSheet(
            "color:rgba(186,201,204,0.65);background:transparent;border:none;"
        )
        self._scan_toggle = ToggleSwitch(True)
        self._scan_toggle.toggled.connect(self.scanline_toggled.emit)
        scan_row.addWidget(scan_lbl)
        scan_row.addWidget(self._scan_toggle)
        scan_row.addStretch(1)
        mb.addLayout(scan_row)

        mb.addStretch(1)

        self._apply_btn = QPushButton("APPLY_CFG")
        self._apply_btn.setCursor(Qt.PointingHandCursor)
        self._apply_btn.setToolTip("Save configuration")
        self._apply_btn.setStyleSheet(
            "QPushButton{"
            f"color:{CYAN};border:1px solid rgba(0,229,255,0.60);"
            "font-family:'Roboto Mono';font-size:12px;font-weight:700;"
            "padding:8px;background:transparent;"
            "}"
            "QPushButton:hover{background:rgba(0,229,255,0.08);}"
            "QPushButton:pressed{background:rgba(0,229,255,0.16);}"
        )
        self._apply_btn.clicked.connect(self._apply_cfg)
        mb.addWidget(self._apply_btn)

        meta_lay.addWidget(meta_body, 1)
        upper.addWidget(meta_panel, 1)

        root.addLayout(upper, 1)

        # ── Session flags ─────────────────────────────────────────────────────
        flags_panel = GlassPanel()
        flags_panel.set_fill_color(QColor(10, 17, 19, 220))
        flags_lay = QVBoxLayout(flags_panel)
        flags_lay.setContentsMargins(0, 0, 0, 0)
        flags_lay.setSpacing(0)

        sfhdr, sfsep = _panel_header("SESSION_FLAGS")
        flags_lay.addWidget(sfhdr)
        flags_lay.addWidget(sfsep)

        sfbody = QWidget()
        sfbody.setStyleSheet("background:transparent;")
        sfb = QHBoxLayout(sfbody)
        sfb.setContentsMargins(14, 10, 14, 10)
        sfb.setSpacing(32)

        sf_left = QVBoxLayout()
        sf_left.setSpacing(4)
        self._flag_mic = self._make_flag_row(
            sf_left, "MUTE_MIC",
            "Block voice capture session-wide.",
        )
        self._flag_mic.toggled.connect(self.mic_muted_changed.emit)
        self._flag_tts = self._make_flag_row(
            sf_left, "MUTE_TTS",
            "Suppress spoken responses; transcript still updates.",
        )
        self._flag_tts.toggled.connect(self.tts_muted_changed.emit)

        sf_right = QVBoxLayout()
        sf_right.setSpacing(4)
        self._flag_conf = self._make_flag_row(
            sf_right, "AUTO_CONFIRM",
            "Skip confirmation prompts. Destructive actions run instantly.",
            warn=True,
        )
        self._flag_conf.toggled.connect(self.auto_confirm_changed.emit)
        self._flag_dim = self._make_flag_row(
            sf_right, "DIM_MODE",
            "Reduce brightness for low-light use.",
        )
        self._flag_dim.toggled.connect(self.dim_mode_changed.emit)
        self._flag_wake = self._make_flag_row(
            sf_left, "WAKE_WORD",
            "Listen for 'Jarvis' to activate voice input.",
        )
        self._flag_wake.setChecked(True)
        self._flag_wake.toggled.connect(self.wake_word_changed.emit)

        sfb.addLayout(sf_left, 1)
        sfb.addLayout(sf_right, 1)
        flags_lay.addWidget(sfbody)
        root.addWidget(flags_panel)

        # ── Lower: Audio Configuration ────────────────────────────────────────
        audio_panel = GlassPanel()
        audio_panel.set_fill_color(QColor(10, 17, 19, 220))
        audio_lay = QVBoxLayout(audio_panel)
        audio_lay.setContentsMargins(0, 0, 0, 0)
        audio_lay.setSpacing(0)

        ahdr, asep = _panel_header("AUDIO_CONFIG")
        audio_lay.addWidget(ahdr)
        audio_lay.addWidget(asep)

        audio_body = QWidget()
        audio_body.setStyleSheet("background:transparent;")
        ab2 = QHBoxLayout(audio_body)
        ab2.setContentsMargins(14, 12, 14, 12)
        ab2.setSpacing(24)

        mic_col = QVBoxLayout()
        mic_col.setSpacing(6)
        mic_col.addWidget(_section_lbl("MIC_SENSITIVITY"))
        mic_row = QHBoxLayout()
        self._mic_slider = QSlider(Qt.Horizontal)
        self._mic_slider.setRange(0, 100)
        self._mic_slider.setValue(config.mic_sensitivity)
        self._mic_slider.setStyleSheet(_SLIDER_SS)
        self._mic_val = QLabel(f"{config.mic_sensitivity}%")
        self._mic_val.setFixedWidth(34)
        self._mic_val.setFont(_mono(10))
        self._mic_val.setStyleSheet(f"color:{CYAN};background:transparent;border:none;")
        self._mic_slider.valueChanged.connect(lambda v: self._mic_val.setText(f"{v}%"))
        mic_row.addWidget(self._mic_slider, 1)
        mic_row.addWidget(self._mic_val)
        mic_col.addLayout(mic_row)
        ab2.addLayout(mic_col, 1)

        tts_col = QVBoxLayout()
        tts_col.setSpacing(6)
        tts_col.addWidget(_section_lbl("TTS_SPEED"))
        tts_row = QHBoxLayout()
        self._tts_slider = QSlider(Qt.Horizontal)
        self._tts_slider.setRange(50, 200)
        self._tts_slider.setValue(config.tts_speed)
        self._tts_slider.setStyleSheet(_SLIDER_SS)
        self._tts_val = QLabel(f"{config.tts_speed}%")
        self._tts_val.setFixedWidth(38)
        self._tts_val.setFont(_mono(10))
        self._tts_val.setStyleSheet(f"color:{CYAN};background:transparent;border:none;")
        self._tts_slider.valueChanged.connect(lambda v: self._tts_val.setText(f"{v}%"))
        tts_row.addWidget(self._tts_slider, 1)
        tts_row.addWidget(self._tts_val)
        tts_col.addLayout(tts_row)
        ab2.addLayout(tts_col, 1)

        ng_col = QVBoxLayout()
        ng_col.setSpacing(6)
        ng_col.addWidget(_section_lbl("NOISE_GATE"))
        ng_row = QHBoxLayout()
        self._noise_toggle = ToggleSwitch(config.noise_gate)
        ng_row.addWidget(self._noise_toggle)
        ng_row.addStretch(1)
        ng_col.addLayout(ng_row)
        ng_col.addStretch(1)
        ab2.addLayout(ng_col)

        audio_lay.addWidget(audio_body, 1)

        # ── Mic input device selector ─────────────────────────────────────────
        dev_body = QWidget()
        dev_lay = QHBoxLayout(dev_body)
        dev_lay.setContentsMargins(14, 8, 14, 8)
        dev_lay.setSpacing(12)
        dev_lay.addWidget(_section_lbl("MIC_INPUT_DEVICE"))

        self._mic_device_combo = QComboBox()
        self._mic_device_combo.setStyleSheet(
            f"QComboBox{{background:rgba(0,212,255,0.07);color:#d2dcf5;"
            f"border:1px solid rgba(0,212,255,0.25);border-radius:4px;"
            f"font-family:{FM};font-size:11px;padding:3px 8px;}}"
            f"QComboBox::drop-down{{border:none;}}"
            f"QComboBox QAbstractItemView{{background:#0d1f24;color:#d2dcf5;"
            f"selection-background-color:rgba(0,212,255,0.20);}}"
        )
        self._mic_device_combo.addItem("System Default", -1)
        try:
            import sounddevice as _sd
            for idx, dev in enumerate(_sd.query_devices()):
                if dev["max_input_channels"] > 0:
                    self._mic_device_combo.addItem(
                        f"[{idx}] {dev['name']}", idx
                    )
                    if idx == config.mic_device:
                        self._mic_device_combo.setCurrentIndex(
                            self._mic_device_combo.count() - 1
                        )
        except Exception:
            pass
        dev_lay.addWidget(self._mic_device_combo, 1)
        audio_lay.addWidget(dev_body)

        root.addWidget(audio_panel)

        # ── Wire all fields → unsaved indicator ───────────────────────────────
        for sig in (
            self._anthro_key.textChanged,
            self._eleven_key.textChanged,
            self._vapi_key.textChanged,
            self._wake_input.textChanged,
        ):
            sig.connect(lambda _: self._mark_dirty())

        self._voice_combo.currentIndexChanged.connect(lambda _: self._mark_dirty())
        self._model_combo.currentIndexChanged.connect(lambda _: self._mark_dirty())
        self._theme_combo.currentIndexChanged.connect(lambda _: self._mark_dirty())
        self._debug_toggle.toggled.connect(lambda _: self._mark_dirty())
        self._scan_toggle.toggled.connect(lambda _: self._mark_dirty())
        self._mic_slider.valueChanged.connect(lambda _: self._mark_dirty())
        self._tts_slider.valueChanged.connect(lambda _: self._mark_dirty())
        self._noise_toggle.toggled.connect(lambda _: self._mark_dirty())
        self._mic_device_combo.currentIndexChanged.connect(lambda _: self._mark_dirty())

    # ── Unsaved indicator ─────────────────────────────────────────────────────

    def _mark_dirty(self):
        self._unsaved_lbl.setVisible(True)

    def _mark_clean(self):
        self._unsaved_lbl.setVisible(False)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _apply_cfg(self):
        from core.signals import signals
        from core.voice import voice_engine

        config.anthropic_api_key = self._anthro_key.text().strip()
        config.elevenlabs_api_key = self._eleven_key.text().strip()
        config.vapi_api_key       = self._vapi_key.text().strip()
        config.claude_model       = self._model_combo.currentData()
        config.wake_word          = self._wake_input.text().strip() or "jarvis"
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
        config.theme              = self._theme_combo.currentData()
        config.debug_mode         = self._debug_toggle.isChecked()
        config.mic_sensitivity    = self._mic_slider.value()
        config.tts_speed          = self._tts_slider.value()
        config.noise_gate         = self._noise_toggle.isChecked()
        config.mic_device         = self._mic_device_combo.currentData()
        # Session flags — capture current toggle state so APPLY_CFG is a
        # complete snapshot of all settings, not just API/audio fields.
        config.mic_muted          = self._flag_mic.isChecked()
        config.tts_muted          = self._flag_tts.isChecked()
        config.auto_confirm       = self._flag_conf.isChecked()
        config.dim_mode           = self._flag_dim.isChecked()
        config.wake_word_enabled  = self._flag_wake.isChecked()

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

    def showEvent(self, event):
        """Sync input fields from live config each time the Settings page is shown.

        Prevents stale values (e.g. voice changed via command) from being
        written back when the user clicks APPLY_CFG.
        """
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
        self._flag_mic.setChecked(mic_muted)
        self._flag_tts.setChecked(tts_muted)
        self._flag_conf.setChecked(auto_confirm)
        self._flag_dim.setChecked(dim_mode)
        self._flag_wake.setChecked(wake_word)

    @staticmethod
    def _make_flag_row(
        layout: QVBoxLayout,
        label: str,
        helper: str,
        warn: bool = False,
    ) -> ToggleSwitch:
        row = QWidget()
        row.setStyleSheet("background:transparent;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 5, 0, 5)
        rl.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(2)
        lbl = QLabel(label)
        lbl.setFont(_mono(9, bold=True))
        lbl.setStyleSheet(
            "color:rgba(195,245,255,0.90);letter-spacing:1px;"
            "background:transparent;border:none;"
        )
        col.addWidget(lbl)
        hlp = QLabel(helper)
        hlp.setStyleSheet(
            ("color:rgba(255,219,60,0.85);" if warn else "color:rgba(160,180,185,0.72);")
            + "font-family:'Roboto Mono';font-size:9px;"
            "letter-spacing:0.3px;background:transparent;border:none;"
        )
        hlp.setWordWrap(True)
        col.addWidget(hlp)
        rl.addLayout(col, 1)
        tog = ToggleSwitch(False)
        rl.addWidget(tog, 0, Qt.AlignVCenter)
        layout.addWidget(row)
        return tog

    def _rebuild_bg(self) -> None:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            self._bg_px = None
            return
        px = QPixmap(w, h)
        p = QPainter(px)
        p.fillRect(0, 0, w, h, QColor(BG))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 229, 255, 20))
        for x in range(0, w + 28, 28):
            for y in range(0, h + 28, 28):
                p.drawEllipse(x - 1, y - 1, 2, 2)
        p.end()
        self._bg_px = px
        self._bg_sz = (w, h)

    def resizeEvent(self, e: object) -> None:
        super().resizeEvent(e)
        self._bg_px = None

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        if self._bg_px is None or self._bg_sz != (w, h):
            self._rebuild_bg()
        p = QPainter(self)
        if self._bg_px is not None:
            p.drawPixmap(0, 0, self._bg_px)
