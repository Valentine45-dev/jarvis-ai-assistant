"""TerminalPanel — JARVIS HUD terminal view.

Consumes signals.terminal_line_ready (per-line streaming output) and
signals.terminal_done (exit code badge). Emits command_submitted(str)
when the user presses Enter so main.py can route it through _process_cmd.

Redesigned 2026-05 to match the shared HUD grammar:
  - Top breadcrumb: JARVIS SHELL · V2 + session info + clear/save buttons
  - Output (main, left): scrollable colored stream with subtle top fade
  - Sidebar (right, 220px): Quick actions · Recent commands · Shortcuts cheat
  - Input row spans both columns at the bottom (cyan prompt + edit + hint)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from PyQt5.QtCore import Qt, QEvent, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QKeySequence, QTextCursor
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QShortcut,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.signals import signals
from ui.components.design import (
    BG_PANEL,
    ChipFilter,
    CYAN_FAINT,
    CYAN_SOFT,
    INK,
    INK_DIM,
    INK_FAINT,
    PanelCard,
)
from ui.theme import BG, CYAN, FM, PRIMARY


# ── Output block model (used by the @tag filter) ─────────────────────────────
#
# The terminal output stream is rendered into a single QTextEdit, but the
# @ALL/@CODE/@FILES/@BROWSER chip filter needs to hide/show whole COMMANDS
# (one user prompt + its echoed response lines together). We solve that by
# keeping an in-memory ordered list of blocks: every block is either a
# system message (always visible) or a command (filterable by its tag).
# On every chip switch we clear the QTextEdit and re-paint from the
# filtered block list. Mild flicker on filter change — fine in practice.


@dataclass
class _Block:
    kind: str                              # "system" | "command"
    tag: str = "other"                     # "code" | "files" | "browser" | "other" — for command blocks only
    lines: list[tuple[str, str]] = field(default_factory=list)  # (text, color)


# ── Stream colour constants ──────────────────────────────────────────────────


_COL_STDOUT  = CYAN
_COL_STDERR  = "#FF6B6B"
_COL_SUCCESS = "#83fba5"
_COL_FAIL    = "#FF6B6B"
_COL_WARNING = "#FFB347"
_COL_MUTED   = "#3a4753"
_COL_CMD     = "#E2E8F0"

_ERROR_WORDS = frozenset(["error", "exception", "failed", "traceback", "denied"])


# ── Sidebar quick-action presets ─────────────────────────────────────────────

# Each entry: (display, pre-filled command). Display ≤ 22 chars to fit the
# sidebar comfortably. The pre-fill includes the @tag where appropriate so
# the brain routes correctly.
_QUICK_ACTIONS: tuple[tuple[str, str], ...] = (
    ("GIT STATUS",   "@code git status"),
    ("GIT LOG -5",   "@code git log --oneline -5"),
    ("NPM RUN DEV",  "@code npm run dev"),
    ("PYTEST",       "@code uv run pytest -q"),
    ("SCREENSHOT",   "take a screenshot"),
    ("READ SCREEN",  "what's on my screen"),
    ("LIST WORKFLOWS", "list my workflows"),
)


# Keys wrapped in mini cyan-bordered chips ('<kbd>' style) per the HTML
# mockup. QLabel rich-text doesn't honor every CSS property, but border /
# padding / background on inline spans render fine.
def _kbd(key: str) -> str:
    return (
        f"<span style=\"color:{CYAN};"
        f"border:1px solid {CYAN_FAINT};"
        f"background:rgba(0,229,255,0.05);"
        f"padding:1px 6px;font-weight:700;"
        f"font-family:'{FM}';font-size:9.5px;\">{key}</span>"
    )


_SHORTCUTS_HTML = (
    "<table cellspacing='0' cellpadding='3' style='font-family: \"" + FM + "\";'>"
    "<tr><td style='padding-right:10px;'>" + _kbd("Ctrl+L") + "</td>"
    "<td style='color:" + INK_DIM + ";'>clear</td></tr>"
    "<tr><td style='padding-right:10px;'>" + _kbd("↑/↓") + "</td>"
    "<td style='color:" + INK_DIM + ";'>history</td></tr>"
    "<tr><td style='padding-right:10px;'>" + _kbd("Tab") + "</td>"
    "<td style='color:" + INK_DIM + ";'>@tag complete</td></tr>"
    "<tr><td style='padding-right:10px;'>" + _kbd("Ctrl+K") + "</td>"
    "<td style='color:" + INK_DIM + ";'>palette</td></tr>"
    "<tr><td style='padding-right:10px;'>" + _kbd("Ctrl+/") + "</td>"
    "<td style='color:" + INK_DIM + ";'>help</td></tr>"
    "</table>"
)


# ── Main view ────────────────────────────────────────────────────────────────


class TerminalPanel(QWidget):
    """Real-time terminal output panel with a command input and history."""

    command_submitted = pyqtSignal(str)   # emitted as "@code <text>" for intent routing

    _MAX_RECENT_SIDEBAR = 8
    _MAX_HISTORY        = 50

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cmd_history: list[str] = []
        self._hist_idx: int = -1
        self._start_time = datetime.now()
        self._cmd_count = 0
        self._recent_btns: list[QPushButton] = []
        # Output block model (see _Block docstring above).
        self._blocks: list[_Block] = []
        self._cur_block: Optional[_Block] = None
        # @tag filter state — "all" shows everything, otherwise filters
        # command blocks whose .tag matches.
        self._active_tag_filter: str = "all"
        self._tag_chips: dict[str, ChipFilter] = {}

        self._setup_ui()
        self._connect_signals()

        # Tick the session uptime label once a second so the 'MM:SS' part
        # stays live without waiting for the next command to land.
        self._uptime_timer = QTimer(self)
        self._uptime_timer.setInterval(1000)
        self._uptime_timer.timeout.connect(self._refresh_session_label)
        self._uptime_timer.start()
        self._refresh_session_label()

        # Welcome
        self._append_system(
            "JARVIS terminal ready — type a command or describe what you want in plain English."
        )

    # ── UI ───────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # ── Header ──────────────────────────────────────────────────────────
        root.addLayout(self._build_header())

        # ── Middle: output (left) + sidebar (right) ─────────────────────────
        middle = QHBoxLayout()
        middle.setSpacing(12)
        middle.addWidget(self._build_output(), 1)
        middle.addWidget(self._build_sidebar(), 0)
        root.addLayout(middle, 1)

        # ── Input row ───────────────────────────────────────────────────────
        root.addLayout(self._build_input_row())

        # Ctrl+L → clear
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.clear_output)
        # Ctrl+Shift+D → seed fake history for UI testing without API calls.
        # Undocumented in the cheat sheet on purpose (dev affordance).
        QShortcut(QKeySequence("Ctrl+Shift+D"), self, activated=self.seed_demo)

    def _build_header(self) -> QHBoxLayout:
        head = QHBoxLayout()
        head.setSpacing(14)

        title = QLabel("JARVIS SHELL · V2")
        title.setStyleSheet(
            "QLabel {"
            f"color: {CYAN};"
            f"font-family: '{FM}';"
            "font-size: 14px;"
            "font-weight: 700;"
            "letter-spacing: 3px;"
            "background: transparent;"
            "border: none;"
            "}"
        )
        head.addWidget(title)

        self._session_lbl = QLabel("session · 0 commands")
        self._session_lbl.setStyleSheet(
            "QLabel {"
            f"color: {INK_DIM};"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "letter-spacing: 1.2px;"
            "background: transparent;"
            "border: none;"
            "}"
        )
        head.addWidget(self._session_lbl)
        head.addStretch(1)

        # @tag filter chips — ALL / CODE / FILES / BROWSER. Click filters
        # the visible command blocks by their tag. ALL is the no-filter case.
        for key, label in (
            ("all",     "@ALL"),
            ("code",    "@CODE"),
            ("files",   "@FILES"),
            ("browser", "@BROWSER"),
        ):
            chip = ChipFilter(label, active=(key == "all"))
            chip.clicked.connect(lambda _checked, k=key: self._on_tag_chip_clicked(k))
            self._tag_chips[key] = chip
            head.addWidget(chip)

        self._btn_clear = self._mini_btn("⌫ CLEAR")
        self._btn_clear.clicked.connect(self.clear_output)
        head.addWidget(self._btn_clear)

        self._btn_save = self._mini_btn("↓ SAVE")
        self._btn_save.clicked.connect(self._on_save)
        head.addWidget(self._btn_save)
        return head

    def _build_output(self) -> QWidget:
        wrap = QFrame()
        wrap.setStyleSheet(
            "QFrame {"
            f"background: {BG_PANEL};"
            f"border: 1px solid {CYAN_FAINT};"
            f"border-left: 2px solid {CYAN};"
            "}"
        )
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFont(FM, 11))
        self._output.setStyleSheet(
            "QTextEdit {"
            "background: transparent;"
            f"color: {CYAN};"
            "border: none;"
            "padding: 12px 14px;"
            f"selection-background-color: rgba(0,229,255,0.20);"
            "}"
            "QScrollBar:vertical { background: transparent; width: 6px; }"
            "QScrollBar::handle:vertical {"
            "background: rgba(0,229,255,0.30); border-radius: 3px; min-height: 20px;"
            "}"
            "QScrollBar::handle:vertical:hover { background: rgba(0,229,255,0.55); }"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height: 0; }"
        )
        lay.addWidget(self._output)
        return wrap

    def _build_sidebar(self) -> QWidget:
        col = QWidget()
        col.setFixedWidth(220)
        col.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(10)

        # ── Quick actions ──────────────────────────────────────────────────
        qa = PanelCard("Quick actions")
        for label, prefill in _QUICK_ACTIONS:
            qa.add(self._sidebar_btn(label, prefill))
        qa.body().addStretch(1)
        cl.addWidget(qa)

        # ── Recent commands ────────────────────────────────────────────────
        self._recent_panel = PanelCard("Recent · ↑↓")
        # We'll lazily populate this; start with an empty-state hint.
        self._recent_empty = QLabel("Run a command — recent history appears here.")
        self._recent_empty.setWordWrap(True)
        self._recent_empty.setStyleSheet(
            f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 9.5px; }}"
        )
        self._recent_panel.add(self._recent_empty)
        self._recent_panel.body().addStretch(1)
        cl.addWidget(self._recent_panel)

        # ── Shortcuts cheat ────────────────────────────────────────────────
        sc = PanelCard("Shortcuts")
        sc_body = QLabel(_SHORTCUTS_HTML)
        sc_body.setStyleSheet(
            f"QLabel {{ background: transparent; border: none; font-size: 10px; }}"
        )
        sc_body.setTextFormat(Qt.RichText)
        sc.add(sc_body)
        sc.body().addStretch(1)
        cl.addWidget(sc)

        cl.addStretch(1)
        return col

    def _build_input_row(self) -> QHBoxLayout:
        lay = QHBoxLayout()
        lay.setSpacing(10)

        prompt = QLabel("❯")
        prompt.setStyleSheet(
            "QLabel {"
            f"color: {CYAN};"
            f"font-family: '{FM}';"
            "font-size: 14px;"
            "font-weight: 700;"
            "padding-right: 4px;"
            "background: transparent;"
            "border: none;"
            "}"
        )
        lay.addWidget(prompt)

        self._input = QLineEdit()
        self._input.setPlaceholderText("enter command or describe what you want…")
        self._input.setFont(QFont(FM, 11))
        self._input.setStyleSheet(
            "QLineEdit {"
            f"background: {BG_PANEL};"
            f"color: {INK};"
            f"border: 1px solid {CYAN_FAINT};"
            "padding: 7px 12px;"
            "}"
            "QLineEdit:focus {"
            f"border: 1px solid {CYAN_SOFT};"
            "background: rgba(0,229,255,0.05);"
            "}"
        )
        self._input.returnPressed.connect(self._on_submit)
        self._input.installEventFilter(self)
        lay.addWidget(self._input, 1)

        hint = QLabel("Enter · send  ·  Shift+Enter · newline")
        hint.setStyleSheet(
            f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 9.5px; letter-spacing: 1px; }}"
        )
        lay.addWidget(hint)
        return lay

    # ── Component helpers ────────────────────────────────────────────────────

    def _mini_btn(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton {"
            "background: transparent;"
            f"color: {CYAN};"
            f"border: 1px solid {CYAN_FAINT};"
            f"font-family: '{FM}';"
            "font-size: 9.5px;"
            "font-weight: 700;"
            "padding: 4px 10px;"
            "letter-spacing: 1.5px;"
            "}"
            "QPushButton:hover { background: rgba(0,229,255,0.10); }"
        )
        return btn

    def _sidebar_btn(self, label: str, prefill: str, *, active: bool = False) -> QPushButton:
        # ``active=True`` is used by the Recent sidebar to mark the most-
        # recent command — cursor prefix '▸ ' + cyan bold text. Quick Action
        # buttons always pass active=False (the default).
        display = f"▸ {label}" if active else label
        btn = QPushButton(display)
        btn.setCursor(Qt.PointingHandCursor)
        if active:
            btn.setStyleSheet(
                "QPushButton {"
                "background: transparent;"
                f"color: {CYAN};"
                "border: none;"
                f"font-family: '{FM}';"
                "font-size: 10px;"
                "font-weight: 700;"
                "padding: 5px 8px;"
                "text-align: left;"
                "}"
                "QPushButton:hover { background: rgba(0,229,255,0.08); }"
            )
        else:
            btn.setStyleSheet(
                "QPushButton {"
                "background: transparent;"
                f"color: {INK_DIM};"
                f"border: 1px solid {CYAN_FAINT};"
                f"font-family: '{FM}';"
                "font-size: 10px;"
                "padding: 5px 8px;"
                "text-align: left;"
                "}"
                f"QPushButton:hover {{ background: rgba(0,229,255,0.08); color: {CYAN}; }}"
            )
        btn.clicked.connect(lambda _checked, p=prefill: self._fill_input(p))
        return btn

    def _fill_input(self, text: str) -> None:
        self._input.setText(text)
        self._input.setFocus()
        self._input.setCursorPosition(len(text))

    # ── Signal wiring ────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        signals.terminal_line_ready.connect(self._on_line)
        signals.terminal_done.connect(self._on_done)

    # ── Event filter (Up/Down history navigation) ────────────────────────────

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

    def _hist_up(self) -> None:
        if not self._cmd_history:
            return
        self._hist_idx = max(0, self._hist_idx - 1)
        self._input.setText(self._cmd_history[self._hist_idx])

    def _hist_down(self) -> None:
        if not self._cmd_history:
            return
        self._hist_idx = min(len(self._cmd_history), self._hist_idx + 1)
        if self._hist_idx == len(self._cmd_history):
            self._input.clear()
        else:
            self._input.setText(self._cmd_history[self._hist_idx])

    # ── Input submission ─────────────────────────────────────────────────────

    def _on_submit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        if not self._cmd_history or self._cmd_history[-1] != text:
            self._cmd_history.append(text)
            if len(self._cmd_history) > self._MAX_HISTORY:
                self._cmd_history.pop(0)
        self._hist_idx = len(self._cmd_history)
        self._cmd_count += 1
        self._refresh_session_label()
        self._refresh_recent_sidebar()

        # Echo + dispatch. If the user typed a @tag prefix themselves, pass
        # verbatim. Otherwise default to the @code routing so the executor
        # picks the right intent for shell-style inputs.
        # Open a fresh command block so subsequent streamed lines belong
        # to this command (and the @tag filter can hide it as a unit).
        self._begin_command_block(self._classify_tag(text))
        self._record_into_current(f"❯ {text}", _COL_CMD)
        if text.startswith("@"):
            self.command_submitted.emit(text)
        else:
            self.command_submitted.emit(f"@code {text}")

    def _on_save(self) -> None:
        """Best-effort dump of the current buffer to logs/terminal_dump.txt."""
        from pathlib import Path
        try:
            out_path = Path(__file__).parent.parent.parent / "logs" / "terminal_dump.txt"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(self._output.toPlainText(), encoding="utf-8")
            self._append_system(f"Saved to {out_path.name}.")
        except OSError as exc:
            self._append_colored(f"[save failed] {exc}", _COL_FAIL)

    # ── Signal handlers ──────────────────────────────────────────────────────

    def _on_line(self, line: str) -> None:
        lower = line.lower()
        is_cmd = line.startswith("❯ ")
        is_step = line.startswith("── Step") or line.startswith("──")
        if is_cmd:
            self._record_into_current(line, _COL_CMD)
        elif is_step:
            self._record_into_current(line, _COL_MUTED)
        elif any(w in lower for w in _ERROR_WORDS):
            self._record_into_current(line, _COL_STDERR)
        else:
            self._record_into_current(line, _COL_STDOUT)

    def _on_done(self, exit_code: int) -> None:
        if exit_code == 0:
            self._record_into_current(f"[OK] exit 0", _COL_SUCCESS)
        else:
            self._record_into_current(f"[ERR {exit_code}]", _COL_FAIL)
        self._record_into_current("─" * 64, _COL_MUTED)

    # ── Public helpers ───────────────────────────────────────────────────────

    def append_jarvis_response(self, text: str) -> None:
        """Show JARVIS's spoken explanation in the terminal output."""
        self._record_into_current(f"◈ {text}", _COL_WARNING)
        self._record_into_current("─" * 64, _COL_MUTED)

    def clear_output(self) -> None:
        self._output.clear()
        self._blocks.clear()
        self._cur_block = None
        self._append_system("Terminal cleared.")

    # ── Dev helper (Ctrl+Shift+D) ────────────────────────────────────────────
    #
    # Pushes a handful of fake commands into the output stream + recent
    # sidebar so the UI can be visually verified without burning Anthropic
    # API credits. Triggered via Ctrl+Shift+D (wired in _setup_ui).
    # Intentionally undocumented in the Shortcuts cheat sheet — it's a dev
    # affordance, not a user feature. Safe to leave behind because it has
    # no side-effects beyond writing to the local QTextEdit + sidebar list.

    _DEMO_ROWS: tuple[tuple[str, str, str, str, str, str], ...] = (
        # (HH:MM:SS, prompt, intent_label, response, color_kind, tag)
        # 'tag' drives the @CODE/@FILES/@BROWSER chip filter — picked here
        # explicitly so the demo covers each bucket cleanly.
        ("03:31:05", "create a file called notes.txt in Downloads",
         "FILE",    "Created notes.txt in Downloads.",          "ok",   "files"),
        ("03:32:22", "switch to the youtube tab",
         "BROWSER", "Switching to YouTube.",                    "ok",   "browser"),
        ("03:33:48", "what's on my screen",
         "VISION",  "Taking a look — JARVIS HUD with the reactor visible.",
         "ok",   "other"),
        ("03:34:01", "open spotify",
         "FAIL",    "Couldn't open Spotify — file not found.",  "fail", "other"),
        ("03:35:12", "tell me a joke",
         "META",    "Why do programmers prefer dark mode? Because light attracts bugs.",
         "ok",   "other"),
        ("03:36:30", "@code git status",
         "CODE",    "On branch main · clean working tree.",     "ok",   "code"),
    )

    def seed_demo(self) -> None:
        """Inject fake commands so the terminal looks 'used' for UI tests.

        Each row is recorded as its own command block with an explicit tag,
        so the @CODE/@FILES/@BROWSER chips actually filter the seeded data.
        """
        self._append_system("DEMO MODE — seeded 6 fake commands. No API calls were made.")
        for ts, prompt, intent, response, kind, tag in self._DEMO_ROWS:
            self._begin_command_block(tag)
            self._record_into_current(f"[{ts}] ❯ {prompt}", _COL_MUTED)
            color = _COL_FAIL if kind == "fail" else _COL_STDOUT
            self._record_into_current(f"   [{intent}] {response}", color)
            # Mirror what _on_submit does so the sidebar + counter stay in sync.
            self._cmd_history.append(prompt)
            self._cmd_count += 1
        self._cmd_history = self._cmd_history[-self._MAX_HISTORY:]
        self._refresh_recent_sidebar()
        self._refresh_session_label()

    # ── Tag classification + filter wiring ───────────────────────────────────

    @staticmethod
    def _classify_tag(text: str) -> str:
        """Map a user-typed command to one of the chip buckets. Drives both
        the per-command tag attribute and the filter predicate."""
        t = text.strip().lower()
        if t.startswith("@code"):
            return "code"
        if t.startswith("@files") or t.startswith("@file"):
            return "files"
        if t.startswith("@browser"):
            return "browser"
        # Untagged commands default-route through @code (see _on_submit),
        # so treat them as code for the filter too.
        return "code"

    def _on_tag_chip_clicked(self, key: str) -> None:
        for k, chip in self._tag_chips.items():
            chip.setChecked(k == key)
            chip._refresh_style()  # noqa: SLF001 — internal helper, ok here
        self._active_tag_filter = key
        self._rerender()

    def _block_visible(self, block: _Block) -> bool:
        """Filter predicate. System blocks are always visible; command blocks
        are visible when the active filter is 'all' or matches their tag."""
        if block.kind == "system":
            return True
        return self._active_tag_filter == "all" or block.tag == self._active_tag_filter

    def _rerender(self) -> None:
        """Clear the QTextEdit and re-paint from the filtered block list."""
        self._output.clear()
        for block in self._blocks:
            if not self._block_visible(block):
                continue
            for text, color in block.lines:
                self._paint(text, color)

    # ── Internal rendering ───────────────────────────────────────────────────

    def _append_system(self, msg: str) -> None:
        # System messages are their own one-line block — always visible
        # regardless of filter. Use this for app banners, save errors,
        # "terminal cleared", and the welcome line.
        block = _Block(kind="system")
        text = f"⬡  {msg}"
        block.lines.append((text, _COL_WARNING))
        self._blocks.append(block)
        # System block doesn't become _cur_block — it's standalone.
        self._paint(text, _COL_WARNING)

    def _begin_command_block(self, tag: str) -> _Block:
        """Open a new command block. Subsequent _record_into_current() calls
        accumulate into it until the next call to this method."""
        block = _Block(kind="command", tag=tag)
        self._blocks.append(block)
        self._cur_block = block
        return block

    def _record_into_current(self, text: str, color: str) -> None:
        """Append a colored line to the current command block (if any) AND
        paint it. Used by streaming handlers (_on_line / _on_done) and the
        public ``append_jarvis_response``."""
        if self._cur_block is not None:
            self._cur_block.lines.append((text, color))
        self._paint(text, color)

    def _append_colored(self, text: str, color: str) -> None:
        """Back-compat shim — most callers now route through
        _record_into_current or _append_system. Anything that still calls
        this raw method paints without going into the block list (i.e.
        won't survive a filter rerender). Kept for any future caller that
        genuinely wants unfilterable raw text."""
        self._paint(text, color)

    def _paint(self, text: str, color: str) -> None:
        """Pure QTextEdit write — no block bookkeeping."""
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = cursor.charFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(text + "\n")
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    def _refresh_session_label(self) -> None:
        # 'session · MM:SS · N commands' (HH:MM:SS once we cross an hour).
        # Mockup shows '03:31' style — that's MM:SS on a fresh session and
        # H:MM once you've been running long enough.
        elapsed = datetime.now() - self._start_time
        secs = max(0, int(elapsed.total_seconds()))
        if secs >= 3600:
            uptime = f"{secs // 3600}:{(secs % 3600) // 60:02d}:{secs % 60:02d}"
        else:
            uptime = f"{secs // 60:02d}:{secs % 60:02d}"
        self._session_lbl.setText(
            f"session · {uptime} · {self._cmd_count} "
            f"command{'s' if self._cmd_count != 1 else ''}"
        )

    def _refresh_recent_sidebar(self) -> None:
        """Re-render the right-sidebar 'Recent' panel from _cmd_history."""
        body = self._recent_panel.body()
        # Remove old buttons / empty hint
        for btn in self._recent_btns:
            btn.deleteLater()
        self._recent_btns.clear()
        if self._recent_empty.isVisible():
            self._recent_empty.setVisible(False)

        # Build buttons for the last N (newest first). The first entry is
        # the most recent — gets the ▸ cursor + cyan bold styling.
        recent = list(reversed(self._cmd_history))[: self._MAX_RECENT_SIDEBAR]
        for i, cmd in enumerate(recent):
            shown = cmd if len(cmd) <= 26 else cmd[:23] + "…"
            btn = self._sidebar_btn(shown, cmd, active=(i == 0))
            # Tighter spacing than action buttons
            btn.setStyleSheet(btn.styleSheet().replace("padding: 5px 8px", "padding: 3px 8px"))
            body.insertWidget(body.count() - 1, btn)
            self._recent_btns.append(btn)
