"""VoiceView — VOICE_CORE.

Redesigned 2026-05 to match the shared HUD grammar:
  - Top 5-tile hero strip (State · Capture · Device · Wake word · TTS provider)
  - Left active panel: big circular mic + waveform + idle hint
  - Right panel: transcript with intent badges (divide-y rows, last 20 turns)
  - Bottom action bar: Start / Pause wake / Clear + hotkey hint

Public API preserved so main.py needs no changes:
  - mic_toggled signal
  - set_state(state)
  - update_transcript(cmd, resp, intent, conf)
  - append_jarvis_continuation(resp, intent, conf)
  - set_execution(intent, action, conf, success, error)
  - set_pending(intent, action, conf, message)
  - clear_pending()
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import qtawesome as qta
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.settings import config
from ui.components.design import (
    AMBER,
    BG_PANEL,
    CYAN_FAINT,
    CYAN_SOFT,
    GREEN,
    GREEN_DIM,
    INK,
    INK_DIM,
    INK_FAINT,
    RED,
    DivideRow,
    HeroMetric,
    IntentBadge,
    PanelCard,
    StatusPip,
)
from ui.theme import BG, CYAN, FM
from ui.widgets import WaveformStrip


# ── Big circular mic button (kept from prior implementation; mostly the same) ──


class _BigMicButton(QPushButton):
    """Large circular mic that pulses while listening."""

    DIAMETER = 160

    pressed_toggled = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._listening = False
        self._pulse_phase = 0.0
        self.setFixedSize(self.DIAMETER, self.DIAMETER)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Toggle microphone (Voice command capture)")
        self.setText("")
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(60)
        self._pulse_timer.timeout.connect(self._tick)

    def set_listening(self, listening: bool) -> None:
        if listening == self._listening:
            return
        self._listening = listening
        if listening:
            self._pulse_phase = 0.0
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
        self.update()

    def _tick(self) -> None:
        self._pulse_phase = (self._pulse_phase + 0.08) % 2.0
        self.update()

    def mousePressEvent(self, e) -> None:
        super().mousePressEvent(e)
        self.pressed_toggled.emit()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        cx = self.width() / 2
        cy = self.height() / 2
        base_r = self.DIAMETER / 2 - 4

        if self._listening:
            pulse = abs(1.0 - self._pulse_phase)
            ring_r = base_r + 8 + pulse * 10
            ring_alpha = int(70 * (1.0 - pulse))
            p.setPen(QPen(QColor(0, 229, 255, ring_alpha), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(int(cx - ring_r), int(cy - ring_r),
                          int(ring_r * 2), int(ring_r * 2))

        if self._listening:
            fill_color = QColor(0, 229, 255, 38)
            border_color = QColor(0, 229, 255, 210)
            border_w = 2
        else:
            fill_color = QColor(0, 102, 255, 20)
            border_color = QColor(0, 229, 255, 100)
            border_w = 1
        p.setPen(QPen(border_color, border_w))
        p.setBrush(fill_color)
        p.drawEllipse(int(cx - base_r), int(cy - base_r),
                      int(base_r * 2), int(base_r * 2))

        inner_r = base_r - 12
        p.setPen(QPen(QColor(0, 229, 255, 40), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(int(cx - inner_r), int(cy - inner_r),
                      int(inner_r * 2), int(inner_r * 2))

        icon = qta.icon("fa5s.microphone", color=CYAN)
        icon_size = 48
        p.drawPixmap(int(cx - icon_size / 2), int(cy - icon_size / 2),
                     icon.pixmap(icon_size, icon_size))


# ── Transcript list ──────────────────────────────────────────────────────────


class _TranscriptList(QWidget):
    """Scrollable divide-y rows: time + (user or intent-badge) + content.

    Each ``update_transcript`` call adds two rows (you, then JARVIS).
    Older rows beyond ``MAX_ROWS`` get pruned.
    """

    MAX_ROWS = 40

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 6px; }"
            "QScrollBar::handle:vertical {"
            "background: rgba(0,229,255,0.30); border-radius: 3px; min-height: 20px;"
            "}"
            "QScrollBar::handle:vertical:hover { background: rgba(0,229,255,0.55); }"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height: 0; }"
        )

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._rows_lay = QVBoxLayout(self._container)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(0)
        self._rows_lay.addStretch(1)
        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, 1)

        # Track rows (excluding the trailing stretch) so we can prune.
        self._row_count = 0

    # Sizing constants applied across all transcript rows. Qt mono fonts
    # render visually smaller than browser mono at the same px, so we sit
    # above the HTML spec (11.5px / 8px) to match the visual weight.
    _ROW_PAD_Y      = 11      # ~22px total vertical padding per row
    _TEXT_SIZE      = 13      # 'you' / 'jarvis' line text
    _TIME_SIZE      = 11      # leading HH:MM:SS column
    _META_SIZE      = 11      # confidence %, etc.

    def add_user(self, time_str: str, text: str) -> None:
        row = DivideRow(padding_y=self._ROW_PAD_Y)
        t = QLabel(time_str[:8])
        t.setFixedWidth(54)
        t.setStyleSheet(
            f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: {self._TIME_SIZE}px; }}"
        )
        row.add(t)
        you_lbl = QLabel(f'"{text}"')
        you_lbl.setStyleSheet(
            f"QLabel {{ color: {GREEN_DIM}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: {self._TEXT_SIZE}px; }}"
        )
        you_lbl.setWordWrap(True)
        you_lbl.setToolTip(text)
        row.add(you_lbl, stretch=1)
        self._insert_row(row)

    def add_jarvis(self, time_str: str, text: str, intent: str, conf: float,
                   *, status: str = "ok") -> None:
        row = DivideRow(padding_y=self._ROW_PAD_Y)
        t = QLabel(time_str[:8])
        t.setFixedWidth(54)
        t.setStyleSheet(
            f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: {self._TIME_SIZE}px; }}"
        )
        row.add(t)
        badge_key = "fail" if status == "fail" else intent
        row.add(IntentBadge(badge_key))

        resp = QLabel(text)
        resp.setWordWrap(True)
        resp.setToolTip(text)
        color = RED if status == "fail" else INK
        resp.setStyleSheet(
            f"QLabel {{ color: {color}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: {self._TEXT_SIZE}px; }}"
        )
        row.add(resp, stretch=1)

        if status != "fail" and 0.0 < conf < 1.0:
            pct = QLabel(f"{int(conf * 100)}%")
            pct.setStyleSheet(
                f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
                f"font-family: '{FM}'; font-size: {self._META_SIZE}px; }}"
            )
            row.add(pct)
        self._insert_row(row)

    def add_system(self, text: str) -> None:
        row = DivideRow(padding_y=self._ROW_PAD_Y)
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"QLabel {{ color: {AMBER}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: {self._TEXT_SIZE}px; letter-spacing: 1px; }}"
        )
        lbl.setWordWrap(True)
        row.add(lbl, stretch=1)
        self._insert_row(row)

    def _insert_row(self, row: QWidget) -> None:
        # Insert before the trailing stretch
        self._rows_lay.insertWidget(self._rows_lay.count() - 1, row)
        self._row_count += 1
        # Prune oldest rows above the cap
        while self._row_count > self.MAX_ROWS:
            item = self._rows_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            self._row_count -= 1
        # Scroll to bottom on next event-loop tick so the layout settles first
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())


# ── Action button helper ─────────────────────────────────────────────────────


def _action_button(text: str, *, primary: bool = False, danger: bool = False) -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    if primary:
        bg = CYAN
        color = "#001a1f"
        border = CYAN
        hover = "background: #5ff2ff;"
    elif danger:
        bg = "transparent"
        color = RED
        border = RED
        hover = "background: rgba(255,107,107,0.10);"
    else:
        bg = "transparent"
        color = CYAN
        border = CYAN_SOFT
        hover = "background: rgba(0,229,255,0.10);"
    btn.setStyleSheet(
        "QPushButton {"
        f"background: {bg};"
        f"color: {color};"
        f"border: 1px solid {border};"
        f"font-family: '{FM}';"
        "font-size: 11px;"
        "font-weight: 700;"
        "padding: 11px 22px;"   # roomier — was 6x14, now ~2x vertical breathing room
        "letter-spacing: 2.5px;"
        "}"
        "QPushButton:hover {" + hover + "}"
    )
    return btn


# ── Hotkey hint label ────────────────────────────────────────────────────────


def _hotkey_hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
        f"font-family: '{FM}'; font-size: 10px; letter-spacing: 1.4px; }}"
    )
    return lbl


# ── Main view ───────────────────────────────────────────────────────────────


class VoiceView(QWidget):
    """VOICE_CORE. See module docstring."""

    mic_toggled = pyqtSignal()

    _STATE_LABEL: dict[str, tuple[str, str]] = {
        # state -> (display, color)
        "idle":      ("IDLE",      INK_DIM),
        "listening": ("LISTENING", GREEN),
        "thinking":  ("THINKING",  CYAN),
        "speaking":  ("SPEAKING",  CYAN),
        "awaiting":  ("AWAITING",  AMBER),
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = "idle"
        self._bg_px: Optional[QPixmap] = None
        self._bg_sz = (-1, -1)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # ── Header ──────────────────────────────────────────────────────────
        head = QHBoxLayout()
        head.setSpacing(12)
        title = QLabel("VOICE_CORE")
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

        subtitle = QLabel("COMMAND INTERFACE · AUDIO PIPELINE")
        subtitle.setStyleSheet(
            "QLabel {"
            f"color: {INK_DIM};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "letter-spacing: 2px;"
            "padding-bottom: 6px;"  # nudge the baseline up so it visually
                                    # sits alongside the bigger title's lower-case zone
            "}"
        )
        head.addWidget(subtitle, 0, Qt.AlignBottom)
        head.addStretch(1)
        root.addLayout(head)

        # ── Hero strip ──────────────────────────────────────────────────────
        self._hero_wrap = self._build_hero_strip()
        root.addWidget(self._hero_wrap)

        # ── Main 2-column body ──────────────────────────────────────────────
        cols = QHBoxLayout()
        cols.setSpacing(14)
        cols.addWidget(self._build_left_panel(), 1)
        cols.addWidget(self._build_right_panel(), 1)
        root.addLayout(cols, 1)

        # ── Bottom action bar ───────────────────────────────────────────────
        actions = self._build_action_bar()
        root.addWidget(actions)

    # ── Builders ─────────────────────────────────────────────────────────────

    def _build_hero_strip(self) -> QWidget:
        """Top 5-metric row. No outer container, no dividers between cells —
        the dotted page backdrop shows through. Metrics float on it as
        labels + values, separated by horizontal gap. Mirrors the HTML
        mockup layout exactly.
        """
        wrap = QWidget()
        wrap.setStyleSheet("QWidget { background: transparent; }")
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(4, 6, 4, 6)
        lay.setSpacing(28)  # the visual "gap" between metrics — mockup uses 14px,
                            # bumped here to compensate for the lost dividers

        # 5 tiles. Per-metric value sizes mirror the HTML mockup explicitly:
        # Capture lvl is the largest (32px) because "−18" is the hero number;
        # State sits at 22 because LISTENING is short and bold-cased;
        # text-heavy metrics (Device, TTS) get 14 to avoid wrapping; Wake gets
        # 18 because `"jarvis"` is short but should read prominently.
        self._hm_state = HeroMetric("State", "IDLE", sub="mic closed",
                                    value_color=INK_DIM, value_size=22)
        self._hm_capture = HeroMetric("Capture lvl", "—", unit="dB",
                                      sub="ambient only", value_size=32)
        device_name = "Default · 16kHz"
        if config.mic_device != -1:
            try:
                import sounddevice as _sd  # type: ignore
                d = _sd.query_devices(config.mic_device)
                device_name = f"{d['name'][:24]}"
            except Exception:
                pass
        self._hm_device = HeroMetric("Device", device_name,
                                     sub=("noise-gate ON" if config.noise_gate else "noise-gate OFF"),
                                     value_size=14)
        self._hm_wake = HeroMetric("Wake word", f'"{config.wake_word}"',
                                   sub="listening" if config.wake_word_enabled else "disabled",
                                   value_color=GREEN if config.wake_word_enabled else INK_DIM,
                                   value_size=18)
        self._hm_tts = HeroMetric("TTS provider", "—", sub="resolving…",
                                  value_size=14)
        self._refresh_tts_tile()

        for metric in (self._hm_state, self._hm_capture, self._hm_device,
                       self._hm_wake, self._hm_tts):
            lay.addWidget(metric, 1)
        return wrap

    def _refresh_tts_tile(self) -> None:
        """Best-effort provider resolution at construction time."""
        if config.elevenlabs_api_key:
            self._hm_tts.set_value("ElevenLabs", color=CYAN)
            self._hm_tts.set_sub("primary")
        elif getattr(config, "gemini_api_key", ""):
            self._hm_tts.set_value("Gemini · Kore", color=CYAN)
            self._hm_tts.set_sub("free tier")
        else:
            self._hm_tts.set_value("pyttsx3", color=INK_DIM)
            self._hm_tts.set_sub("local fallback")

    def _build_left_panel(self) -> PanelCard:
        panel = PanelCard(active=True)
        body = panel.body()

        body.addStretch(1)

        # Centered mic
        mic_row = QHBoxLayout()
        mic_row.addStretch(1)
        self._mic = _BigMicButton()
        self._mic.pressed_toggled.connect(self.mic_toggled.emit)
        mic_row.addWidget(self._mic)
        mic_row.addStretch(1)
        body.addLayout(mic_row)

        hint = QLabel(f'Tap or say "{config.wake_word}"')
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(
            "QLabel {"
            f"color: {INK_FAINT};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "letter-spacing: 3px;"
            "text-transform: uppercase;"
            "}"
        )
        body.addWidget(hint)

        body.addSpacing(16)

        # Waveform
        wf_title = QLabel("WAVEFORM · LIVE")
        wf_title.setStyleSheet(
            "QLabel {"
            f"color: {CYAN};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 9.5px;"
            "font-weight: 700;"
            "letter-spacing: 2.2px;"
            "}"
        )
        body.addWidget(wf_title)
        self._waveform = WaveformStrip()
        self._waveform.setMinimumHeight(60)
        self._waveform.set_active(False)
        body.addWidget(self._waveform)

        body.addStretch(2)
        return panel

    def _build_right_panel(self) -> PanelCard:
        panel = PanelCard()

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        title = QLabel("TRANSCRIPT · THIS SESSION")
        title.setStyleSheet(
            "QLabel {"
            f"color: {CYAN};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 9.5px;"
            "font-weight: 700;"
            "letter-spacing: 2.2px;"
            "}"
        )
        head.addWidget(title)
        head.addStretch(1)
        self._exchange_count = QLabel("0 exchanges")
        self._exchange_count.setStyleSheet(
            f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 9.5px; letter-spacing: 1.2px; }}"
        )
        head.addWidget(self._exchange_count)
        panel.body().addLayout(head)

        self._transcript = _TranscriptList()
        panel.add(self._transcript, stretch=1)
        return panel

    def _build_action_bar(self) -> QWidget:
        """Bottom action bar. No outer container — buttons float on the
        dotted page backdrop with a `QWidget` (not `QFrame`) wrapper so
        no border/background cascades to inner labels (the hotkey hint).
        """
        bar = QWidget()
        bar.setStyleSheet("QWidget { background: transparent; }")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(10)

        self._btn_start = _action_button("⏵ START LISTENING", primary=True)
        self._btn_start.clicked.connect(self.mic_toggled.emit)
        lay.addWidget(self._btn_start)

        self._btn_pause = _action_button("⏸ PAUSE WAKE")
        # Pause/resume is handled externally; we just toggle visible label.
        # Wire to wake_word_changed via mic_toggled? Keep stub for now.
        lay.addWidget(self._btn_pause)

        self._btn_clear = _action_button("⌫ CLEAR TRANSCRIPT")
        self._btn_clear.clicked.connect(self._on_clear_transcript)
        lay.addWidget(self._btn_clear)

        lay.addStretch(1)
        lay.addWidget(_hotkey_hint("HOTKEY  Ctrl+Shift+M  toggles mic"))
        return bar

    # ── Event handlers ───────────────────────────────────────────────────────

    def _on_clear_transcript(self) -> None:
        # Drop all child rows from the transcript list
        lay = self._transcript._rows_lay  # noqa: SLF001 — local accessor
        while lay.count() > 1:  # leave the trailing stretch
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._transcript._row_count = 0
        self._exchange_count.setText("0 exchanges")

    # ── Public API (preserved) ───────────────────────────────────────────────

    def set_state(self, state: str) -> None:
        self._state = state
        # Update hero tile
        display, color = self._STATE_LABEL.get(state, (state.upper(), INK_DIM))
        self._hm_state.set_value(display, color=color)
        if state == "listening":
            self._hm_state.set_sub("mic open")
            self._mic.set_listening(True)
            self._waveform.set_active(True)
        elif state == "thinking":
            self._hm_state.set_sub("routing through Claude")
            self._mic.set_listening(False)
            self._waveform.set_active(False)
        elif state == "speaking":
            self._hm_state.set_sub("TTS playback")
            self._mic.set_listening(False)
            self._waveform.set_active(False)
        elif state == "awaiting":
            self._hm_state.set_sub("user confirmation needed")
            self._mic.set_listening(False)
            self._waveform.set_active(False)
        else:  # idle
            self._hm_state.set_sub("mic closed")
            self._mic.set_listening(False)
            self._waveform.set_active(False)

    def update_transcript(self, cmd: str, resp: str, intent: str, conf: float) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self._transcript.add_user(now, cmd)
        self._transcript.add_jarvis(now, resp, intent, conf)
        # Each exchange = 1 user + 1 jarvis row → 2 rows; "exchanges" counts pairs.
        pairs = self._transcript._row_count // 2  # noqa: SLF001
        self._exchange_count.setText(f"{pairs} exchange{'s' if pairs != 1 else ''}")

    def append_jarvis_continuation(self, resp: str, intent: str, conf: float) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self._transcript.add_jarvis(now, resp, intent, conf)

    def set_execution(
        self,
        intent: str,
        action: str,
        conf: float,
        success: bool,
        error: Optional[str] = None,
    ) -> None:
        if not success:
            short = (error or "Failed").strip()
            if len(short) > 80:
                short = short[:77] + "…"
            now = datetime.now().strftime("%H:%M:%S")
            self._transcript.add_jarvis(now, short, intent, conf, status="fail")

    def set_pending(self, intent: str, action: str, conf: float, message: str) -> None:
        self.set_state("awaiting")
        self._transcript.add_system(
            f"Confirmation required · {intent}/{action} · {message[:80]}"
        )

    def clear_pending(self) -> None:
        self.set_state(self._state if self._state != "awaiting" else "idle")
        self._transcript.add_system("Confirmation cancelled.")

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
