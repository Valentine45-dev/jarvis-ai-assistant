"""VoiceView — VOICE_CORE: live transcript, active command state, execution log."""

from __future__ import annotations

from datetime import datetime

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.theme import BG, CYAN, FM, PRIMARY, WARNING, RED
from ui.widgets import GlassPanel, TerminalLog, WaveformStrip


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
    "idle":      ("AWAITING INPUT",  "rgba(195,245,255,0.45)"),
    "listening": ("LISTENING",       CYAN),
    "thinking":  ("PROCESSING",      CYAN),
    "processing": ("PROCESSING",     CYAN),
    "speaking":  ("SPEAKING",        "#83fba5"),
}


# ─────────────────────────────────────────────────────────────────────────────


class _ActiveCommandCard(GlassPanel):
    """Right panel — shows current state, waveform, last intent + confidence."""

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
        bl.setContentsMargins(16, 16, 16, 16)
        bl.setSpacing(12)

        # State label
        self._state_lbl = QLabel("AWAITING INPUT")
        self._state_lbl.setFont(_mono(16, bold=True))
        self._state_lbl.setAlignment(Qt.AlignCenter)
        self._state_lbl.setStyleSheet(
            "color:rgba(195,245,255,0.45);letter-spacing:3px;"
            "background:transparent;border:none;"
        )
        bl.addWidget(self._state_lbl)

        # Waveform (hidden when idle)
        self._waveform = WaveformStrip()
        self._waveform.setFixedHeight(40)
        self._waveform.set_active(False)
        self._waveform.setVisible(False)
        bl.addWidget(self._waveform)

        bl.addStretch(1)

        # Intent / confidence readout
        self._intent_sep = QFrame()
        self._intent_sep.setFrameShape(QFrame.HLine)
        self._intent_sep.setStyleSheet(
            "color:rgba(0,229,255,0.10);background:rgba(0,229,255,0.10);"
        )
        self._intent_sep.setFixedHeight(1)
        bl.addWidget(self._intent_sep)

        intent_row = QHBoxLayout()
        intent_row.setSpacing(8)
        intent_lbl_head = QLabel("LAST INTENT")
        intent_lbl_head.setFont(_mono(8, bold=True))
        intent_lbl_head.setStyleSheet(
            "color:rgba(132,147,150,0.55);letter-spacing:2px;"
            "background:transparent;border:none;"
        )
        intent_row.addWidget(intent_lbl_head, 1)
        bl.addLayout(intent_row)

        self._intent_lbl = QLabel("—")
        self._intent_lbl.setFont(_mono(13))
        self._intent_lbl.setStyleSheet(
            f"color:{CYAN};letter-spacing:1px;background:transparent;border:none;"
        )
        bl.addWidget(self._intent_lbl)

        self._conf_lbl = QLabel("CONFIDENCE: —")
        self._conf_lbl.setFont(_mono(10))
        self._conf_lbl.setStyleSheet(
            "color:rgba(132,147,150,0.7);background:transparent;border:none;"
        )
        bl.addWidget(self._conf_lbl)

        outer.addWidget(body, 1)

    def set_state(self, state: str):
        text, color = _STATE_LABELS.get(state, ("AWAITING INPUT", "rgba(195,245,255,0.45)"))
        self._state_lbl.setText(text)
        self._state_lbl.setStyleSheet(
            f"color:{color};letter-spacing:3px;"
            "background:transparent;border:none;"
        )
        audio_active = state in ("listening", "speaking")
        self._waveform.setVisible(audio_active)
        self._waveform.set_active(audio_active)

    def set_last_result(self, intent: str, conf: float):
        self._intent_lbl.setText(intent.replace("_", "·"))
        conf_color = CYAN if conf >= 0.9 else WARNING if conf >= 0.7 else RED
        self._conf_lbl.setText(f"CONFIDENCE: {int(conf * 100)}%")
        self._conf_lbl.setStyleSheet(
            f"color:{conf_color};background:transparent;border:none;"
        )


# ─────────────────────────────────────────────────────────────────────────────


class VoiceView(QWidget):
    mic_toggled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "idle"

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── Header ────────────────────────────────────────────────────────────
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

        # ── Main body ─────────────────────────────────────────────────────────
        body = QHBoxLayout()
        body.setSpacing(12)

        # Left: voice transcript log
        transcript_panel = GlassPanel()
        transcript_panel.set_fill_color(QColor(10, 17, 19, 220))
        tp_lay = QVBoxLayout(transcript_panel)
        tp_lay.setContentsMargins(0, 0, 0, 0)
        tp_lay.setSpacing(0)

        thdr, tsep = _panel_header("VOICE TRANSCRIPT")
        tp_lay.addWidget(thdr)
        tp_lay.addWidget(tsep)

        self._transcript = TerminalLog()
        self._transcript.set_lines([
            "[SYSTEM] Voice pipeline ready.",
            "[SYSTEM] Microphone standby. Awaiting activation.",
        ])
        tp_lay.addWidget(self._transcript, 1)
        body.addWidget(transcript_panel, 3)

        # Right: active command card
        self._cmd_card = _ActiveCommandCard()
        body.addWidget(self._cmd_card, 2)

        root.addLayout(body, 1)

        # ── Execution log ─────────────────────────────────────────────────────
        log_panel = GlassPanel()
        log_panel.set_fill_color(QColor(10, 17, 19, 220))
        log_panel.setFixedHeight(110)
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

        root.addWidget(log_panel)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_state(self, state: str):
        self._state = state
        self._cmd_card.set_state(state)
        now = datetime.now().strftime("%H:%M:%S")
        if state == "listening":
            self._exec_log.append_line(f"[{now}] Mic activated. Listening...")
        elif state == "thinking":
            self._exec_log.append_line(f"[{now}] Parsing command sequence...")
        elif state == "speaking":
            self._exec_log.append_line(f"[{now}] Voice output engaged.")
        elif state == "idle":
            pass  # no log noise on every idle transition

    def update_transcript(self, cmd: str, resp: str, intent: str, conf: float):
        """Called from main.py after each command/response cycle."""
        now = datetime.now().strftime("%H:%M:%S")
        self._transcript.append_line(f"[{now}] > {cmd}")
        conf_tag = f"{int(conf * 100)}%"
        self._transcript.append_line(
            f"[{now}] » {resp}  [{intent.replace('_', '·')} / {conf_tag}]"
        )
        self._exec_log.append_line(
            f"[{now}] Intent: {intent}  Conf: {conf_tag}"
        )
        self._cmd_card.set_last_result(intent, conf)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        p.setPen(QPen(QColor(59, 73, 76, 28), 1))
        for x in range(0, self.width(), 50):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 50):
            p.drawLine(0, y, self.width(), y)
