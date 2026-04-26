from __future__ import annotations

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QTextEdit, QVBoxLayout

from ui.components.panels import GlassPanel
from ui.theme import FM, PRIMARY


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
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(self._view)

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
