from __future__ import annotations

import random

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from ui.components.panels import GlassPanel
from ui.theme import FM, PRIMARY


def _a255(x: float) -> int:
    """Qt QSS `rgba(r,g,b,a)` uses alpha 0-255, not CSS 0-1 (see Qt style sheet ref)."""
    return max(0, min(255, int(round(x * 255))))


class InlineConfirmCard(QWidget):
    """Inline confirmation card that embeds below the transcript text.

    Shows two HUD-styled buttons: [CONFIRM] (cyan) and [CANCEL] (muted red).
    The card border pulses while waiting for user input.
    """

    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    _WAIT_LINES = [
        "Waiting for your call, sir.",
        "Your move, sir.",
        "Just say the word.",
        "Standing by for your decision, sir.",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)

        self._pulse_step = 0
        self._pulse_up   = True

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 4)
        lay.setSpacing(8)

        # Prompt label
        self._label = QLabel("Confirm?")
        self._label.setWordWrap(True)
        self._label.setStyleSheet(
            f"color:{PRIMARY};font-family:'{FM}';font-size:12px;"
            "letter-spacing:0.5px;background:transparent;"
        )
        self._label.setAlignment(Qt.AlignLeft)
        lay.addWidget(self._label)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(10)

        self._confirm_btn = QPushButton("[ CONFIRM ]")
        self._cancel_btn  = QPushButton("[ CANCEL ]")

        for btn, r, g, b in (
            (self._confirm_btn, 0, 212, 255),
            (self._cancel_btn, 255, 80, 80),
        ):
            btn.setFixedHeight(28)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton{{color:rgba({r},{g},{b},{_a255(0.70)});"
                f"border:1px solid rgba({r},{g},{b},{_a255(0.35)});"
                f"background:rgba({r},{g},{b},{_a255(0.06)});"
                f"font-family:'{FM}';font-size:11px;letter-spacing:1.5px;"
                "padding:0 14px;}}"
                f"QPushButton:hover{{background:rgba({r},{g},{b},{_a255(0.14)});"
                f"border:1px solid rgba({r},{g},{b},{_a255(0.60)});}}"
            )

        self._confirm_btn.clicked.connect(self._on_confirm)
        self._cancel_btn.clicked.connect(self._on_cancel)

        btn_row.addWidget(self._confirm_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        # Card container styling (will be pulsed)
        self.setStyleSheet(
            "InlineConfirmCard{"
            f"border:1px solid rgba(0,212,255,{_a255(0.25)});"
            "border-radius:4px;"
            f"background:rgba(0,212,255,{_a255(0.04)});"
            "padding:6px 10px;}"
        )

        # Pulse timer — alternates border brightness while card is visible
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._pulse)

    def show_confirm(self, prompt: str) -> None:
        self._label.setText(prompt)
        self._pulse_step = 0
        self._pulse_up   = True
        self._pulse_timer.start(60)
        self.setVisible(True)

    def hide_confirm(self) -> None:
        self._pulse_timer.stop()
        self.setVisible(False)

    def wait_line(self) -> str:
        return random.choice(self._WAIT_LINES)

    def _on_confirm(self) -> None:
        self.hide_confirm()
        self.confirmed.emit()

    def _on_cancel(self) -> None:
        self.hide_confirm()
        self.cancelled.emit()

    def _pulse(self) -> None:
        if self._pulse_up:
            self._pulse_step += 1
            if self._pulse_step >= 12:
                self._pulse_up = False
        else:
            self._pulse_step -= 1
            if self._pulse_step <= 0:
                self._pulse_up = True

        a_border = 0.20 + self._pulse_step * 0.04   # 0.20 – 0.68
        a_bg     = 0.03 + self._pulse_step * 0.005  # 0.03 – 0.09
        self.setStyleSheet(
            "InlineConfirmCard{"
            f"border:1px solid rgba(0,212,255,{_a255(a_border)});"
            "border-radius:4px;"
            f"background:rgba(0,212,255,{_a255(a_bg)});"
            "padding:6px 10px;}"
        )


class TerminalLog(QTextEdit):
    """Read-only terminal log with a blinking block cursor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self._show_cursor = True
        self._base_lines = []
        self.setStyleSheet(
            "QTextEdit{"
            "background:transparent;"
            "border:none;"
            f"color:{PRIMARY};"
            f"font-family:'{FM}';"
            "font-size:12px;"
            "}"
        )
        self._cursor_timer = QTimer(self)
        self._cursor_timer.timeout.connect(self._toggle_cursor)
        self._cursor_timer.start(500)

    def set_lines(self, lines):
        self._base_lines = list(lines)
        self._render()

    def append_line(self, line: str):
        self._base_lines.append(line)
        self._render()

    def _toggle_cursor(self):
        self._show_cursor = not self._show_cursor
        self._render()

    def _render(self):
        cursor = "\n█" if self._show_cursor else "\n "
        self.setPlainText("\n".join(self._base_lines) + cursor)
        self.moveCursor(self.textCursor().End)


class TranscriptPanel(GlassPanel):
    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._view = QTextEdit(self)
        self._view.setReadOnly(True)
        self._view.setStyleSheet(
            "QTextEdit{background:transparent;border:none;"
            f"color:{PRIMARY};font-family:'{FM}';font-size:14px;"
            "line-height:1.6;}"
        )
        self._confirm_card = InlineConfirmCard(self)
        self._confirm_card.confirmed.connect(self.confirmed)
        self._confirm_card.cancelled.connect(self.cancelled)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        lay.addWidget(self._view)
        lay.addWidget(self._confirm_card)

    def show_confirm(self, prompt: str) -> str:
        """Show the inline confirm card and return the wait line for TTS."""
        self._confirm_card.show_confirm(prompt)
        return self._confirm_card.wait_line()

    def hide_confirm(self) -> None:
        self._confirm_card.hide_confirm()

    def add_exchange(self, you, y_time, jarvis="", j_time="", intent="", conf=None):
        self._rows.append((you, y_time, jarvis, j_time, intent, conf))
        self._render()

    def update_last_you(self, text, y_time=""):
        if not self._rows:
            return
        _, _, jarvis, j_time, intent, conf = self._rows[-1]
        self._rows[-1] = (text, y_time, jarvis, j_time, intent, conf)
        self._render()

    def update_last_jarvis(self, text, j_time="", intent="", conf=None):
        if not self._rows:
            return
        you, y_time, _, _, old_intent, old_conf = self._rows[-1]
        self._rows[-1] = (
            you,
            y_time,
            text,
            j_time,
            intent or old_intent,
            conf if conf is not None else old_conf,
        )
        self._render()

    def _render(self):
        lines = []
        for you, y_time, jarvis, j_time, intent, conf in self._rows:
            lines.append(f"[{y_time}] YOU: {you}")
            if jarvis:
                suffix = f" ({intent}, {int(conf * 100)}%)" if intent and conf is not None else ""
                lines.append(f"[{j_time}] JARVIS: {jarvis}{suffix}")
            lines.append("")
        self._view.setPlainText("\n".join(lines))
        self._view.moveCursor(self._view.textCursor().End)
