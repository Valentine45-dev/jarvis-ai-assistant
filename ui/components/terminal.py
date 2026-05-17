"""
TerminalPanel — JARVIS HUD terminal view.

Consumes signals.terminal_line_ready (per-line streaming output) and
signals.terminal_done (exit code badge). Emits command_submitted(str)
when the user presses Enter so main.py can route it through _process_cmd.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, QEvent, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QKeySequence, QTextCursor
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QShortcut,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.theme import BG, CYAN, PRIMARY
from core.signals import signals

# ── Terminal-specific color constants ─────────────────────────────────────────
_COL_STDOUT  = CYAN          # normal output lines
_COL_STDERR  = "#FF4444"     # lines containing error keywords
_COL_SUCCESS = "#00FF88"     # [OK] exit badge
_COL_FAIL    = "#FF4444"     # [ERR] exit badge
_COL_WARNING = "#FFB347"     # system messages / JARVIS explanations
_COL_MUTED   = "#2D3748"     # separators, step headers
_COL_CMD     = "#E2E8F0"     # echoed command text
_COL_HEADER  = "#4A5568"     # header label text

_ERROR_WORDS = frozenset(["error", "exception", "failed", "traceback", "denied"])


class TerminalPanel(QWidget):
    """Real-time terminal output panel with a command input and history."""

    command_submitted = pyqtSignal(str)   # emitted as "@code <text>" for intent routing

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cmd_history: list[str] = []
        self._hist_idx: int = -1
        self._setup_ui()
        self._connect_signals()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # Header bar
        header = QHBoxLayout()
        title = QLabel("[ TERMINAL ]")
        title.setStyleSheet(
            f"color:{CYAN};font-family:'Roboto Mono';font-size:11px;"
            f"font-weight:700;letter-spacing:3px;"
        )
        subtitle = QLabel("JARVIS SHELL v2")
        subtitle.setStyleSheet(
            f"color:{_COL_HEADER};font-family:'Roboto Mono';"
            f"font-size:10px;letter-spacing:1.5px;"
        )
        header.addWidget(title)
        header.addStretch()
        header.addWidget(subtitle)
        layout.addLayout(header)

        # Glow underline
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(
            f"background:rgba(0,229,255,0.20);max-height:1px;border:none;"
        )
        layout.addWidget(sep)

        # Output area
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFont("Roboto Mono", 11))
        self._output.setStyleSheet(
            f"QTextEdit{{"
            f"background:{BG};"
            f"color:{CYAN};"
            f"border:1px solid rgba(0,229,255,0.12);"
            f"border-radius:4px;"
            f"padding:10px;"
            f"selection-background-color:rgba(0,229,255,0.20);"
            f"}}"
        )
        layout.addWidget(self._output, 1)

        # Input row
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        prompt = QLabel("❯")
        prompt.setStyleSheet(
            f"color:{CYAN};font-family:'Roboto Mono';font-size:13px;"
            f"font-weight:700;padding-right:4px;"
        )

        self._input = QLineEdit()
        self._input.setPlaceholderText("enter command or describe what you want…")
        self._input.setFont(QFont("Roboto Mono", 11))
        self._input.setStyleSheet(
            f"QLineEdit{{"
            f"background:rgba(0,229,255,0.05);"
            f"color:{PRIMARY};"
            f"border:1px solid rgba(0,229,255,0.20);"
            f"border-radius:4px;"
            f"padding:8px 12px;"
            f"}}"
            f"QLineEdit:focus{{"
            f"border:1px solid rgba(0,229,255,0.55);"
            f"background:rgba(0,229,255,0.07);"
            f"}}"
        )
        self._input.returnPressed.connect(self._on_submit)
        self._input.installEventFilter(self)

        input_row.addWidget(prompt)
        input_row.addWidget(self._input, 1)
        layout.addLayout(input_row)

        # Ctrl+L → clear
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.clear_output)

        # Welcome
        self._append_system(
            "JARVIS terminal ready — type a command or describe what you want in plain English."
        )

    def _connect_signals(self):
        signals.terminal_line_ready.connect(self._on_line)
        signals.terminal_done.connect(self._on_done)

    # ── Event filter (Up/Down history navigation) ─────────────────────────────

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Up:
                self._hist_up()
                return True
            if key == Qt.Key_Down:
                self._hist_down()
                return True
        return super().eventFilter(obj, event)

    def _hist_up(self):
        if not self._cmd_history:
            return
        self._hist_idx = max(0, self._hist_idx - 1)
        self._input.setText(self._cmd_history[self._hist_idx])

    def _hist_down(self):
        if not self._cmd_history:
            return
        self._hist_idx = min(len(self._cmd_history), self._hist_idx + 1)
        if self._hist_idx == len(self._cmd_history):
            self._input.clear()
        else:
            self._input.setText(self._cmd_history[self._hist_idx])

    # ── Input submission ──────────────────────────────────────────────────────

    def _on_submit(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        # History: max 50, no consecutive duplicates
        if not self._cmd_history or self._cmd_history[-1] != text:
            self._cmd_history.append(text)
            if len(self._cmd_history) > 50:
                self._cmd_history.pop(0)
        self._hist_idx = len(self._cmd_history)
        # Echo command
        self._append_colored(f"❯ {text}", _COL_CMD)
        # Route through code_execution intent via @code tag
        self.command_submitted.emit(f"@code {text}")

    # ── Signal handlers ───────────────────────────────────────────────────────

    def _on_line(self, line: str):
        """Append a single stdout/stderr line with smart error colouring."""
        lower = line.lower()
        is_cmd = line.startswith("❯ ")
        is_step = line.startswith("── Step") or line.startswith("──")
        if is_cmd:
            self._append_colored(line, _COL_CMD)
        elif is_step:
            self._append_colored(line, _COL_MUTED)
        elif any(w in lower for w in _ERROR_WORDS):
            self._append_colored(line, _COL_STDERR)
        else:
            self._append_colored(line, _COL_STDOUT)

    def _on_done(self, exit_code: int):
        """Show exit badge and separator when process finishes."""
        if exit_code == 0:
            self._append_colored(f"[OK] exit 0", _COL_SUCCESS)
        else:
            self._append_colored(f"[ERR {exit_code}]", _COL_FAIL)
        self._append_colored("─" * 64, _COL_MUTED)

    # ── Public helpers ────────────────────────────────────────────────────────

    def append_jarvis_response(self, text: str):
        """Show JARVIS's spoken explanation in the terminal output."""
        self._append_colored(f"◈ {text}", _COL_WARNING)
        self._append_colored("─" * 64, _COL_MUTED)

    def clear_output(self):
        self._output.clear()
        self._append_system("Terminal cleared.")

    # ── Internal rendering ────────────────────────────────────────────────────

    def _append_system(self, msg: str):
        self._append_colored(f"⬡  {msg}", _COL_WARNING)

    def _append_colored(self, text: str, color: str):
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = cursor.charFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(text + "\n")
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()
