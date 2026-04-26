"""VoiceView — VOICE_CORE: live command console. Phase 1 + 2."""

from __future__ import annotations

import html as _html
from datetime import datetime

import qtawesome as qta
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QTextCursor
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from ui.theme import BG, CYAN, FM, GREEN, PRIMARY, RED, WARNING
from ui.widgets import GlassPanel, SegmentedBar, StatusPip, TerminalLog, WaveformStrip


def _mono(size: int, bold: bool = False):
    from PyQt5.QtGui import QFont
    f = QFont(FM, size)
    f.setBold(bold)
    return f


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


_STATE_LABELS = {
    "idle":       ("AWAITING INPUT",        "rgba(195,245,255,0.35)"),
    "listening":  ("LISTENING",             CYAN),
    "thinking":   ("PROCESSING",            CYAN),
    "processing": ("PROCESSING",            CYAN),
    "speaking":   ("SPEAKING",              GREEN),
    "awaiting":   ("AWAITING CONFIRMATION", WARNING),
}

_MIC_STATES = {
    "idle":       ("STANDBY",    "standby", "rgba(132,147,150,0.65)"),
    "listening":  ("LISTENING",  "active",  CYAN),
    "thinking":   ("PROCESSING", "active",  CYAN),
    "processing": ("PROCESSING", "active",  CYAN),
    "speaking":   ("SPEAKING",   "active",  GREEN),
    "awaiting":   ("PAUSED",     "standby", WARNING),
}


# ─────────────────────────────────────────────────────────────────────────────
# Page mic button — large circular CTA, pulses when listening
# ─────────────────────────────────────────────────────────────────────────────

class _PageMicButton(QPushButton):
    """Large circular mic button intended to live inside the inspector body."""

    DIAMETER = 96

    pressed_toggled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._listening = False
        self._pulse_phase = 0.0
        self.setFixedSize(self.DIAMETER, self.DIAMETER)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Toggle microphone (Voice command capture)")
        self.setText("")
        # Strip default QPushButton chrome — we paint everything ourselves
        self.setStyleSheet("QPushButton{background:transparent;border:none;}")

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(60)
        self._pulse_timer.timeout.connect(self._tick)

    def set_listening(self, listening: bool):
        if listening == self._listening:
            return
        self._listening = listening
        if listening:
            self._pulse_phase = 0.0
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
        self.update()

    def _tick(self):
        # 1..0..1 oscillation via abs(1 - phase), ~1.5s per full cycle at 60ms tick
        self._pulse_phase = (self._pulse_phase + 0.08) % 2.0
        self.update()

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        self.pressed_toggled.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        cx = self.width() / 2
        cy = self.height() / 2
        base_r = self.DIAMETER / 2 - 2

        # Outer pulse ring (only while listening)
        if self._listening:
            pulse = abs(1.0 - self._pulse_phase)   # 0..1..0
            ring_r = base_r + 6 + pulse * 8
            ring_alpha = int(60 * (1.0 - pulse))
            p.setPen(QPen(QColor(0, 229, 255, ring_alpha), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(int(cx - ring_r), int(cy - ring_r),
                          int(ring_r * 2), int(ring_r * 2))

        # Body
        if self._listening:
            fill_color = QColor(0, 229, 255, 32)
            border_color = QColor(0, 229, 255, 200)
            border_w = 2
        else:
            fill_color = QColor(0, 102, 255, 18)
            border_color = QColor(0, 229, 255, 90)
            border_w = 1
        p.setPen(QPen(border_color, border_w))
        p.setBrush(fill_color)
        p.drawEllipse(int(cx - base_r), int(cy - base_r),
                      int(base_r * 2), int(base_r * 2))

        # Inner highlight ring for depth
        inner_r = base_r - 8
        p.setPen(QPen(QColor(0, 229, 255, 35), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(int(cx - inner_r), int(cy - inner_r),
                      int(inner_r * 2), int(inner_r * 2))

        # Icon
        icon_color = CYAN if self._listening else PRIMARY
        icon = qta.icon("fa5s.microphone", color=icon_color)
        icon_size = 30
        p.drawPixmap(int(cx - icon_size / 2), int(cy - icon_size / 2),
                     icon.pixmap(icon_size, icon_size))


# ─────────────────────────────────────────────────────────────────────────────
# Status strip — compact row of system readiness indicators
# ─────────────────────────────────────────────────────────────────────────────

class _StatusStrip(QWidget):
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

        self._mic_pip, self._mic_val = self._pill(
            lay, "MIC STATE", "STANDBY", "rgba(132,147,150,0.65)", pip_status="standby"
        )
        self._divider(lay)
        self._pill(lay, "ROUTER", "CONNECTED", GREEN, pip_status="active")
        self._divider(lay)
        self._pill(lay, "PIPELINE", "READY", GREEN, pip_status="active")
        self._divider(lay)
        _, self._conf_val = self._pill(
            lay, "LAST CONF", "—", "rgba(132,147,150,0.65)", no_pip=True
        )
        lay.addStretch(1)

    def _pill(self, layout, label: str, value: str, value_color: str,
              pip_status: str = "standby", no_pip: bool = False):
        pill = QWidget()
        pill.setStyleSheet("background:transparent;")
        pl = QHBoxLayout(pill)
        pl.setContentsMargins(14, 0, 14, 0)
        pl.setSpacing(7)

        pip = None
        if not no_pip:
            pip = StatusPip(pip_status)
            pip.setFixedSize(8, 8)
            pl.addWidget(pip, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(1)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            "color:rgba(132,147,150,0.45);font-family:'Roboto Mono';"
            "font-size:8px;letter-spacing:1px;background:transparent;border:none;"
        )
        val = QLabel(value)
        val.setStyleSheet(
            f"color:{value_color};font-family:'Roboto Mono';"
            "font-size:10px;font-weight:700;background:transparent;border:none;"
        )
        col.addWidget(lbl)
        col.addWidget(val)
        pl.addLayout(col)

        layout.addWidget(pill)
        return pip, val

    @staticmethod
    def _divider(layout):
        d = QFrame()
        d.setFrameShape(QFrame.VLine)
        d.setStyleSheet("color:rgba(0,229,255,0.10);background:rgba(0,229,255,0.10);")
        d.setFixedWidth(1)
        layout.addWidget(d)

    def set_state(self, state: str):
        label, pip_status, color = _MIC_STATES.get(
            state, ("STANDBY", "standby", "rgba(132,147,150,0.65)")
        )
        self._mic_val.setText(label)
        self._mic_val.setStyleSheet(
            f"color:{color};font-family:'Roboto Mono';"
            "font-size:10px;font-weight:700;background:transparent;border:none;"
        )
        self._mic_pip.set_status(pip_status)

    def set_conf(self, conf: float):
        color = CYAN if conf >= 0.9 else WARNING if conf >= 0.7 else RED
        self._conf_val.setText(f"{int(conf * 100)}%")
        self._conf_val.setStyleSheet(
            f"color:{color};font-family:'Roboto Mono';"
            "font-size:10px;font-weight:700;background:transparent;border:none;"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Transcript timeline — styled conversation turns in a read-only QTextEdit
# ─────────────────────────────────────────────────────────────────────────────

class _TranscriptTimeline(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(
            "QTextEdit{"
            "background:transparent;border:none;"
            f"font-family:'{FM}';font-size:11px;"
            "color:rgba(195,245,255,0.85);"
            "padding:8px 12px;"
            "}"
        )
        self._insert("[SYS]", "rgba(132,147,150,0.45)", "Voice pipeline ready.",        "rgba(132,147,150,0.6)")
        self._insert("[SYS]", "rgba(132,147,150,0.45)", "Microphone standby. Awaiting activation.", "rgba(132,147,150,0.6)")

    def _insert(self, prefix: str, prefix_color: str, text: str, text_color: str,
                timestamp: str = ""):
        ts_html = (
            f'<span style="color:rgba(132,147,150,0.38);font-size:9px;">{_html.escape(timestamp)}&nbsp;&nbsp;</span>'
            if timestamp else ""
        )
        row = (
            f'{ts_html}'
            f'<span style="color:{prefix_color};font-weight:700;">{_html.escape(prefix)}</span>'
            f'&nbsp;<span style="color:{text_color};">{_html.escape(text)}</span>'
        )
        self.moveCursor(QTextCursor.End)
        if not self.document().isEmpty():
            self.insertHtml("<br>")
        self.insertHtml(row)
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(
            self.verticalScrollBar().maximum()
        ))

    def add_system(self, text: str):
        self._insert("[SYS]", "rgba(132,147,150,0.45)", text, "rgba(132,147,150,0.65)")

    def add_user(self, timestamp: str, text: str):
        self._insert("›", CYAN, text, "rgba(195,245,255,0.92)", timestamp)

    def add_jarvis(self, timestamp: str, text: str, intent: str, conf: float):
        tag = f"  [{intent.replace('_', '·')} {int(conf * 100)}%]"
        # Use _insert but inline the tag manually
        ts_html = (
            f'<span style="color:rgba(132,147,150,0.38);font-size:9px;">{_html.escape(timestamp)}&nbsp;&nbsp;</span>'
        )
        row = (
            f'{ts_html}'
            f'<span style="color:{GREEN};font-weight:700;">»</span>'
            f'&nbsp;<span style="color:rgba(131,251,165,0.80);">{_html.escape(text)}</span>'
            f'<span style="color:rgba(132,147,150,0.45);font-size:9px;"> {_html.escape(tag.strip())}</span>'
        )
        self.moveCursor(QTextCursor.End)
        if not self.document().isEmpty():
            self.insertHtml("<br>")
        self.insertHtml(row)
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(
            self.verticalScrollBar().maximum()
        ))


# ─────────────────────────────────────────────────────────────────────────────
# Command inspector — right panel: state, waveform, intent/conf breakdown
# ─────────────────────────────────────────────────────────────────────────────

class _CommandInspector(GlassPanel):
    # Re-emitted from the embedded page mic button so VoiceView can route it
    mic_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.set_fill_color(QColor(10, 17, 19, 220))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        hdr, sep = _panel_header("ACTIVE COMMAND")
        outer.addWidget(hdr)
        outer.addWidget(sep)

        body = QWidget()
        body.setStyleSheet("background:transparent;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(6)

        # ── State label ───────────────────────────────────────────────────────
        self._state_lbl = QLabel("AWAITING INPUT")
        self._state_lbl.setFont(_mono(14, bold=True))
        self._state_lbl.setAlignment(Qt.AlignCenter)
        self._state_lbl.setStyleSheet(
            "color:rgba(195,245,255,0.35);letter-spacing:3px;"
            "background:transparent;border:none;"
        )
        bl.addWidget(self._state_lbl)

        # ── Waveform ──────────────────────────────────────────────────────────
        self._waveform = WaveformStrip()
        self._waveform.setFixedHeight(28)
        self._waveform.set_active(False)
        self._waveform.setVisible(False)
        bl.addWidget(self._waveform)

        bl.addSpacing(6)

        # ── Page mic button ───────────────────────────────────────────────────
        # Centered, prominent CTA. Mirrors the dashboard mic but lives on
        # the Voice page itself so the page is functionally self-sufficient.
        mic_row = QHBoxLayout()
        mic_row.setContentsMargins(0, 0, 0, 0)
        mic_row.addStretch(1)
        self._mic_button = _PageMicButton()
        self._mic_button.pressed_toggled.connect(self.mic_clicked.emit)
        mic_row.addWidget(self._mic_button)
        mic_row.addStretch(1)
        bl.addLayout(mic_row)

        self._mic_hint = QLabel("CLICK TO ACTIVATE")
        self._mic_hint.setAlignment(Qt.AlignCenter)
        self._mic_hint.setStyleSheet(
            "color:rgba(132,147,150,0.55);font-family:'Roboto Mono';"
            "font-size:9px;letter-spacing:2px;background:transparent;border:none;"
        )
        bl.addWidget(self._mic_hint)

        bl.addStretch(1)

        # ── Inspector separator ───────────────────────────────────────────────
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(
            "color:rgba(0,229,255,0.10);background:rgba(0,229,255,0.10);"
        )
        sep2.setFixedHeight(1)
        bl.addWidget(sep2)

        # ── INTENT ───────────────────────────────────────────────────────────
        self._intent_val = self._field(bl, "INTENT", "—", CYAN)

        # ── ACTION ────────────────────────────────────────────────────────────
        self._action_val = self._field(bl, "ACTION", "—", "rgba(132,147,150,0.45)")

        # ── CONFIDENCE ────────────────────────────────────────────────────────
        conf_head = QLabel("CONFIDENCE")
        conf_head.setStyleSheet(
            "color:rgba(132,147,150,0.5);font-family:'Roboto Mono';"
            "font-size:9px;letter-spacing:1px;background:transparent;border:none;"
        )
        bl.addWidget(conf_head)

        conf_row = QHBoxLayout()
        conf_row.setSpacing(8)
        self._conf_bar = SegmentedBar(segments=10, value=0.0, color=CYAN)
        self._conf_bar.setFixedHeight(7)
        self._conf_pct = QLabel("—")
        self._conf_pct.setFixedWidth(32)
        self._conf_pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._conf_pct.setStyleSheet(
            f"color:{CYAN};font-family:'Roboto Mono';font-size:10px;"
            "font-weight:700;background:transparent;border:none;"
        )
        conf_row.addWidget(self._conf_bar, 1)
        conf_row.addWidget(self._conf_pct)
        bl.addLayout(conf_row)

        # ── STATUS ────────────────────────────────────────────────────────────
        self._status_val = self._field(bl, "STATUS", "—", "rgba(132,147,150,0.45)")

        outer.addWidget(body, 1)

    @staticmethod
    def _field(layout, label_text: str, value_text: str, value_color: str) -> QLabel:
        lbl = QLabel(label_text)
        lbl.setStyleSheet(
            "color:rgba(132,147,150,0.5);font-family:'Roboto Mono';"
            "font-size:9px;letter-spacing:1px;background:transparent;border:none;"
        )
        layout.addWidget(lbl)
        val = QLabel(value_text)
        val.setFont(_mono(11))
        val.setStyleSheet(
            f"color:{value_color};background:transparent;border:none;"
        )
        layout.addWidget(val)
        return val

    def set_state(self, state: str):
        text, color = _STATE_LABELS.get(state, ("AWAITING INPUT", "rgba(195,245,255,0.35)"))
        self._state_lbl.setText(text)
        self._state_lbl.setStyleSheet(
            f"color:{color};letter-spacing:3px;background:transparent;border:none;"
        )
        audio_active = state in ("listening", "speaking")
        self._waveform.setVisible(audio_active)
        self._waveform.set_active(audio_active)

        # Mic button reflects listening state for the pulse animation
        self._mic_button.set_listening(state == "listening")
        self._mic_hint.setText({
            "idle":       "CLICK TO ACTIVATE",
            "listening":  "LISTENING — CLICK TO STOP",
            "thinking":   "PROCESSING…",
            "processing": "EXECUTING…",
            "speaking":   "RESPONDING…",
            "awaiting":   "CONFIRM ON DASHBOARD",
        }.get(state, "CLICK TO ACTIVATE"))

    def set_last_result(self, intent: str, conf: float):
        self._intent_val.setText(intent.replace("_", "·"))
        self._intent_val.setStyleSheet(
            f"color:{CYAN};background:transparent;border:none;"
        )
        color = CYAN if conf >= 0.9 else WARNING if conf >= 0.7 else RED
        self._conf_bar.color = QColor(color)
        self._conf_bar.set_value(conf)
        self._conf_pct.setText(f"{int(conf * 100)}%")
        self._conf_pct.setStyleSheet(
            f"color:{color};font-family:'Roboto Mono';font-size:10px;"
            "font-weight:700;background:transparent;border:none;"
        )

    def set_action(self, action: str | None):
        """Phase 2: show the resolved action name from the executor."""
        text = (action or "—").replace("_", "·")
        color = "rgba(195,245,255,0.85)" if action else "rgba(132,147,150,0.45)"
        self._action_val.setText(text)
        self._action_val.setStyleSheet(
            f"color:{color};background:transparent;border:none;"
        )

    def set_status(self, text: str, kind: str = "ok"):
        """Phase 2: show executor status — ok / fail / pending."""
        color = {
            "ok":      GREEN,
            "fail":    RED,
            "pending": WARNING,
            "idle":    "rgba(132,147,150,0.45)",
        }.get(kind, "rgba(132,147,150,0.65)")
        self._status_val.setText(text or "—")
        self._status_val.setStyleSheet(
            f"color:{color};background:transparent;border:none;"
        )

    def reset(self):
        """Wipe inspector fields back to idle defaults."""
        self._intent_val.setText("—")
        self._intent_val.setStyleSheet(
            "color:rgba(132,147,150,0.45);background:transparent;border:none;"
        )
        self.set_action(None)
        self.set_status("—", kind="idle")
        self._conf_bar.set_value(0.0)
        self._conf_pct.setText("—")
        self._conf_pct.setStyleSheet(
            f"color:{CYAN};font-family:'Roboto Mono';font-size:10px;"
            "font-weight:700;background:transparent;border:none;"
        )


# ─────────────────────────────────────────────────────────────────────────────
# VoiceView — top-level page widget
# ─────────────────────────────────────────────────────────────────────────────

class VoiceView(QWidget):
    mic_toggled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "idle"

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        # ── Page header ───────────────────────────────────────────────────────
        title = QLabel("VOICE_CORE")
        title.setStyleSheet(
            "QLabel{"
            f"color:{PRIMARY};"
            "font-family:'Space Grotesk';font-size:40px;font-weight:700;"
            "background:transparent;border:none;"
            "}"
        )
        subtitle = QLabel("COMMAND INTERFACE  //  AUDIO PIPELINE")
        subtitle.setStyleSheet(
            "QLabel{color:rgba(132,147,150,0.9);font-family:'Roboto Mono';"
            "font-size:11px;letter-spacing:1px;background:transparent;border:none;}"
        )
        root.addWidget(title)
        root.addWidget(subtitle)

        # ── Status strip ──────────────────────────────────────────────────────
        self._status_strip = _StatusStrip()
        root.addWidget(self._status_strip)

        # ── Main body ─────────────────────────────────────────────────────────
        body = QHBoxLayout()
        body.setSpacing(12)

        # Left: transcript timeline
        transcript_panel = GlassPanel()
        transcript_panel.set_fill_color(QColor(10, 17, 19, 220))
        tp_lay = QVBoxLayout(transcript_panel)
        tp_lay.setContentsMargins(0, 0, 0, 0)
        tp_lay.setSpacing(0)

        thdr, tsep = _panel_header("VOICE TRANSCRIPT")
        tp_lay.addWidget(thdr)
        tp_lay.addWidget(tsep)

        self._timeline = _TranscriptTimeline()
        tp_lay.addWidget(self._timeline, 1)
        body.addWidget(transcript_panel, 3)

        # Right: command inspector
        self._inspector = _CommandInspector()
        # The inspector hosts the page mic button. Re-broadcast its press
        # through the existing mic_toggled signal so main.py keeps a single
        # connection point regardless of where the user actually clicked.
        self._inspector.mic_clicked.connect(self.mic_toggled.emit)
        body.addWidget(self._inspector, 2)

        # Body : log = 3 : 1 vertical stretch. Body still dominates, but the
        # execution log gets ~25% of the free vertical space (~12-15 lines on
        # a 900px window) instead of being capped at the old 110px (~5 lines).
        root.addLayout(body, 3)

        # ── Execution log ─────────────────────────────────────────────────────
        log_panel = GlassPanel()
        log_panel.set_fill_color(QColor(10, 17, 19, 220))
        # Floor of 170px so the log stays usable on small windows; no fixed
        # ceiling so it can grow with the window via the stretch factor below.
        log_panel.setMinimumHeight(170)
        lp_lay = QVBoxLayout(log_panel)
        lp_lay.setContentsMargins(0, 0, 0, 0)
        lp_lay.setSpacing(0)

        lhdr, lsep = _panel_header("EXECUTION LOG")
        lp_lay.addWidget(lhdr)
        lp_lay.addWidget(lsep)

        self._exec_log = TerminalLog()
        self._exec_log.set_lines([
            "[SYSTEM] Voice core initialized.",
            "[SYSTEM] Intent router connected. Ready.",
        ])
        lp_lay.addWidget(self._exec_log, 1)

        root.addWidget(log_panel, 1)

    # ── Public API — signatures unchanged from Phase 0 ────────────────────────

    def set_state(self, state: str):
        self._state = state
        self._status_strip.set_state(state)
        self._inspector.set_state(state)
        now = datetime.now().strftime("%H:%M:%S")
        if state == "listening":
            self._exec_log.append_line(f"[{now}] Mic activated. Listening...")
        elif state == "thinking":
            self._exec_log.append_line(f"[{now}] Parsing command sequence...")
        elif state == "speaking":
            self._exec_log.append_line(f"[{now}] Voice output engaged.")

    def update_transcript(self, cmd: str, resp: str, intent: str, conf: float):
        now = datetime.now().strftime("%H:%M:%S")
        self._timeline.add_user(now, cmd)
        self._timeline.add_jarvis(now, resp, intent, conf)
        self._exec_log.append_line(
            f"[{now}] Intent: {intent}  Conf: {int(conf * 100)}%"
        )
        self._inspector.set_last_result(intent, conf)
        self._status_strip.set_conf(conf)

    # ── Phase 2: live executor wiring ─────────────────────────────────────────

    def set_execution(self, intent: str, action: str, conf: float,
                      success: bool, error: str | None = None):
        """Reflect the executor result on the inspector and exec log."""
        self._inspector.set_last_result(intent, conf)
        self._inspector.set_action(action)
        if success:
            self._inspector.set_status("EXECUTED", kind="ok")
        else:
            short = (error or "Failed").strip()
            if len(short) > 60:
                short = short[:57] + "…"
            self._inspector.set_status(f"FAILED — {short}", kind="fail")
        now = datetime.now().strftime("%H:%M:%S")
        outcome = "OK" if success else f"FAIL ({error or 'unknown'})"
        self._exec_log.append_line(
            f"[{now}] Action: {action or '—'}  →  {outcome}"
        )

    # ── Confirmation pending state ────────────────────────────────────────────

    def set_pending(self, intent: str, action: str, conf: float, message: str):
        """Brain returned requires_confirmation — show holding state.

        Note: main.py calls _set_state("idle") before set_pending, which puts
        both the inspector and status strip into the idle look. We override
        both here so the user sees a unified amber "awaiting" visual.
        """
        self._inspector.set_state("awaiting")
        self._status_strip.set_state("awaiting")
        self._inspector.set_last_result(intent, conf)
        self._inspector.set_action(action)
        self._inspector.set_status("AWAITING USER CONFIRMATION", kind="pending")
        now = datetime.now().strftime("%H:%M:%S")
        self._timeline.add_system(
            f"Confirmation required for {intent}·{action} — {message}"
        )
        self._exec_log.append_line(
            f"[{now}] Hold: {intent}·{action} pending confirmation."
        )

    def clear_pending(self):
        """User cancelled or confirmation completed."""
        self._inspector.set_state(self._state)
        self._inspector.set_status("CANCELLED", kind="fail")
        now = datetime.now().strftime("%H:%M:%S")
        self._exec_log.append_line(f"[{now}] Pending command cancelled.")

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        p.setPen(QPen(QColor(59, 73, 76, 28), 1))
        for x in range(0, self.width(), 50):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 50):
            p.drawLine(0, y, self.width(), y)
