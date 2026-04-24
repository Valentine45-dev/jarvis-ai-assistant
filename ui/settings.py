"""SettingsView — SYSTEM_CONFIG: real AppConfig wired to interactive controls."""

from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

from config.settings import config
from ui.theme import BG, CYAN, FM, PRIMARY
from ui.widgets import GlassPanel, ToggleSwitch


def _mono(size: int, bold: bool = False):
    from PyQt5.QtGui import QFont
    f = QFont(FM, size)
    f.setBold(bold)
    return f


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


def _panel_header(title: str) -> tuple[QWidget, QFrame]:
    header = QWidget()
    header.setFixedHeight(36)
    header.setStyleSheet("background:transparent;")
    hl = QHBoxLayout(header)
    hl.setContentsMargins(14, 0, 14, 0)
    t = QLabel(title)
    t.setFont(_mono(10, bold=True))
    t.setStyleSheet(
        f"color:{CYAN};letter-spacing:2px;background:transparent;border:none;"
    )
    hl.addWidget(t)
    sep = QFrame()
    sep.setFrameShape(QFrame.HLine)
    sep.setStyleSheet("color:rgba(0,229,255,0.15);background:rgba(0,229,255,0.15);")
    sep.setFixedHeight(1)
    return header, sep


def _field(label: str, widget: QWidget, label_w: int = 120) -> QHBoxLayout:
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


# ─────────────────────────────────────────────────────────────────────────────


class SettingsView(QWidget):
    scanline_toggled = pyqtSignal(bool)   # preserved for future wiring

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── Header ────────────────────────────────────────────────────────────
        title = QLabel("SYSTEM_CONFIG")
        title.setStyleSheet(
            "QLabel{"
            f"color:{PRIMARY};"
            "font-family:'Space Grotesk';font-size:40px;font-weight:700;"
            "background:transparent;border:none;"
            "}"
        )
        subtitle = QLabel("RUNTIME CONFIGURATION  //  API & AUDIO SETTINGS")
        subtitle.setStyleSheet(
            "QLabel{color:rgba(132,147,150,0.9);font-family:'Roboto Mono';"
            "font-size:11px;letter-spacing:1px;background:transparent;border:none;}"
        )
        root.addWidget(title)
        root.addWidget(subtitle)

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
        self._anthro_key.setToolTip("Anthropic API key — kept in memory only unless saved")
        ab.addLayout(_field("ANTHROPIC_KEY", self._anthro_key))

        self._vapi_key = QLineEdit(config.vapi_api_key)
        self._vapi_key.setEchoMode(QLineEdit.Password)
        self._vapi_key.setPlaceholderText("vapi-...")
        self._vapi_key.setStyleSheet(_INPUT_SS)
        self._vapi_key.setToolTip("Vapi API key for STT/TTS")
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

        self._voice_input = QLineEdit(config.tts_voice)
        self._voice_input.setStyleSheet(_INPUT_SS)
        self._voice_input.setToolTip("TTS voice identifier")
        mb.addLayout(_field("VOICE_MATRIX", self._voice_input))

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

        # ── Lower: Audio Configuration ────────────────────────────────────────
        audio_panel = GlassPanel()
        audio_panel.set_fill_color(QColor(10, 17, 19, 220))
        audio_panel.setFixedHeight(150)
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

        # Mic sensitivity slider
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
        self._mic_slider.valueChanged.connect(
            lambda v: self._mic_val.setText(f"{v}%"))
        mic_row.addWidget(self._mic_slider, 1)
        mic_row.addWidget(self._mic_val)
        mic_col.addLayout(mic_row)
        ab2.addLayout(mic_col, 1)

        # TTS speed slider
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
        self._tts_slider.valueChanged.connect(
            lambda v: self._tts_val.setText(f"{v}%"))
        tts_row.addWidget(self._tts_slider, 1)
        tts_row.addWidget(self._tts_val)
        tts_col.addLayout(tts_row)
        ab2.addLayout(tts_col, 1)

        # Noise gate toggle
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
        root.addWidget(audio_panel)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _apply_cfg(self):
        config.anthropic_api_key = self._anthro_key.text().strip()
        config.vapi_api_key      = self._vapi_key.text().strip()
        config.claude_model      = self._model_combo.currentData()
        config.wake_word         = self._wake_input.text().strip() or "jarvis"
        config.tts_voice         = self._voice_input.text().strip()
        config.theme             = self._theme_combo.currentData()
        config.debug_mode        = self._debug_toggle.isChecked()
        config.mic_sensitivity   = self._mic_slider.value()
        config.tts_speed         = self._tts_slider.value()
        config.noise_gate        = self._noise_toggle.isChecked()

        try:
            config.save()
            self._apply_btn.setText("SAVED ✓")
        except Exception:
            self._apply_btn.setText("SAVE ERROR")

        QTimer.singleShot(2000, lambda: self._apply_btn.setText("APPLY_CFG"))

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        p.setPen(QPen(QColor(59, 73, 76, 28), 1))
        for x in range(0, self.width(), 50):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 50):
            p.drawLine(0, y, self.width(), y)
