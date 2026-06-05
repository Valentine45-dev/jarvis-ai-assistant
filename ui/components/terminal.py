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
from PyQt5.QtGui import QColor, QFont, QKeySequence, QPainter, QTextCursor
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
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
    GREEN,
    GREEN_DIM,
    INK,
    INK_DIM,
    INK_FAINT,
    IntentBadge,
    PanelCard,
)
from ui.theme import BG, CYAN, FM, PRIMARY


# ── Output block model ───────────────────────────────────────────────────────
#
# Each block is a self-contained unit in the terminal output:
#   * ``system`` blocks are app notices (welcome line, "terminal cleared",
#     DEMO MODE banner, save errors). Always visible regardless of filter.
#   * ``command`` blocks are one user prompt + its echoed response. Filtered
#     as a unit by the @ALL/@CODE/@FILES/@BROWSER chip row.
#
# Blocks are rendered into a scrollable QWidget container — one widget per
# block — so the chip styling, multi-line indent, and per-command spacing
# can be done properly with real QLabels instead of fighting QTextEdit's
# limited HTML support.


@dataclass
class _Block:
    kind: str                          # "system" | "command"
    tag: str = "other"                 # "code" | "files" | "browser" | "other" (command blocks)
    # ── command-block fields ──
    ts: str = ""                       # "HH:MM:SS" timestamp (or "")
    prompt: str = ""                   # user-typed command
    intent: str = ""                   # short intent label for the badge ("file" / "vision" / …)
                                       # — empty means no badge rendered (e.g. mid-stream real cmds)
    response: str = ""                 # one-line JARVIS reply that pairs with the badge
    response_color: str = INK          # color used for ``response`` (RED for failures)
    awaiting_response: bool = False    # True between submit and reply for a block the
                                       # user typed HERE — gates append_jarvis_response so
                                       # a dashboard/mic command can't fill a stale block
    extras: list[tuple[str, str]] = field(default_factory=list)
                                       # additional lines under the response: (text, color)
    # ── system-block fields ──
    system_text: str = ""              # message body for ``system`` blocks


# ── Row widgets ──────────────────────────────────────────────────────────────


# Bumped from 11/12/11 to match the rest of the redesigned views (transcript,
# history rows, automation StepBreakdown all sit at 13px body text). Qt mono
# renders smaller per-px than browser mono so the mockup's "looks like 13px"
# actually wants ~14px to read equivalently.
_TS_FONT_SIZE     = 12
_PROMPT_FONT_SIZE = 14
_BODY_FONT_SIZE   = 13
_BODY_INDENT      = 28    # px of left padding under the prompt for body lines


class _SystemRow(QLabel):
    """Single-line app notice with the ⬡ glyph."""

    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(f"⬡  {text}", parent)
        self.setWordWrap(True)
        self.setStyleSheet(
            "QLabel {"
            f"color: {CYAN};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            f"font-size: {_BODY_FONT_SIZE}px;"
            "padding: 2px 0;"
            "letter-spacing: 0.5px;"
            "}"
        )


class _CommandRow(QFrame):
    """One command block rendered as a real widget tree.

    Layout (matches the HTML mockup):

        [HH:MM:SS]  ❯ user prompt text                       ← header row
                    [BADGE]  one-line JARVIS reply           ← response row
                    additional dim detail line 1             ← extras
                    additional dim detail line 2

    The badge is reused from the design system's ``IntentBadge``, so colors
    track the rest of the app (cyan FILE/BROWSER/CODE/META, purple VISION,
    red FAIL, amber SYSTEM, etc.).
    """

    def __init__(self, block: _Block, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("QFrame { background: transparent; border: none; }")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        # Inner spacing between header / response / extras within ONE command
        # block. 3 was too tight — header + response read as one mashed
        # paragraph. 5 gives them visual separation without becoming airy.
        outer.setSpacing(5)

        # ── Header row: [ts] ❯ prompt ───────────────────────────────────────
        header = QHBoxLayout()
        header.setSpacing(8)
        header.setContentsMargins(0, 0, 0, 0)

        if block.ts:
            ts_lbl = QLabel(f"[{block.ts}]")
            ts_lbl.setStyleSheet(
                "QLabel {"
                f"color: {INK_FAINT};"
                "background: transparent;"
                "border: none;"
                f"font-family: '{FM}';"
                f"font-size: {_TS_FONT_SIZE}px;"
                "}"
            )
            header.addWidget(ts_lbl)

        arrow = QLabel("❯")
        arrow.setStyleSheet(
            "QLabel {"
            f"color: {GREEN_DIM};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            f"font-size: {_PROMPT_FONT_SIZE}px;"
            "font-weight: 700;"
            "}"
        )
        header.addWidget(arrow)

        prompt_lbl = QLabel(block.prompt or "")
        prompt_lbl.setWordWrap(True)
        prompt_lbl.setStyleSheet(
            "QLabel {"
            f"color: {GREEN};"   # mockup uses lime green for the user input
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            f"font-size: {_BODY_FONT_SIZE}px;"
            "}"
        )
        header.addWidget(prompt_lbl, 1)
        outer.addLayout(header)

        # ── Response row: [badge] response text ─────────────────────────────
        if block.response or block.intent:
            body = QHBoxLayout()
            body.setSpacing(8)
            body.setContentsMargins(_BODY_INDENT, 0, 0, 0)

            if block.intent:
                body.addWidget(IntentBadge(block.intent), 0, Qt.AlignTop)

            if block.response:
                resp = QLabel(block.response)
                resp.setWordWrap(True)
                resp.setStyleSheet(
                    "QLabel {"
                    f"color: {block.response_color or INK};"
                    "background: transparent;"
                    "border: none;"
                    f"font-family: '{FM}';"
                    f"font-size: {_BODY_FONT_SIZE}px;"
                    "}"
                )
                body.addWidget(resp, 1, Qt.AlignTop)
            else:
                body.addStretch(1)
            outer.addLayout(body)

        # ── Extra lines (dim by default, color-tagged when caller cares) ───
        for text, color in block.extras:
            extra = QLabel(text)
            extra.setWordWrap(True)
            extra.setStyleSheet(
                "QLabel {"
                f"color: {color or INK_DIM};"
                "background: transparent;"
                "border: none;"
                f"font-family: '{FM}';"
                f"font-size: {_BODY_FONT_SIZE}px;"
                f"padding-left: {_BODY_INDENT}px;"
                "}"
            )
            outer.addWidget(extra)


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
    ("SCREENSHOT",   "take a screenshot"),
    ("READ SCREEN",  "what's on my screen"),
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
        # block_id → widget mapping so we can replace one block's row in
        # place when its data changes (e.g. a streamed line arrives) without
        # flickering the whole panel.
        self._block_widgets: dict[int, QWidget] = {}
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
        root.addWidget(self._build_input_row())

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

        # @tag filter chips. Click filters the visible command blocks by their
        # tag (derived from the resolved intent). ALL is the no-filter case.
        # Buckets without a chip (weather/reminder/doc/meta/…) show under @ALL.
        for key, label in (
            ("all",     "@ALL"),
            ("app",     "@APP"),
            ("search",  "@SEARCH"),
            ("files",   "@FILES"),
            ("code",    "@CODE"),
            ("browser", "@BROWSER"),
            ("system",  "@SYSTEM"),
            ("auto",    "@AUTO"),
            ("vision",  "@VISION"),
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
        wrap_lay = QVBoxLayout(wrap)
        wrap_lay.setContentsMargins(0, 0, 0, 0)
        wrap_lay.setSpacing(0)

        # Scrollable container of block widgets (one widget per _Block).
        # 14px spacing between blocks gives the per-command breathing room
        # the mockup shows; 16/14 outer padding mirrors the other panels.
        self._output_scroll = QScrollArea()
        self._output_scroll.setWidgetResizable(True)
        self._output_scroll.setFrameShape(QScrollArea.NoFrame)
        self._output_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 6px; }"
            "QScrollBar::handle:vertical {"
            "background: rgba(0,229,255,0.30); border-radius: 3px; min-height: 20px;"
            "}"
            "QScrollBar::handle:vertical:hover { background: rgba(0,229,255,0.55); }"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height: 0; }"
        )

        self._output_container = QWidget()
        self._output_container.setStyleSheet("QWidget { background: transparent; }")
        self._output_lay = QVBoxLayout(self._output_container)
        # Roomier than 16/14 + 14: matches the mockup's per-command breathing
        # room. 22px gap between blocks reads as a real visual separator
        # instead of just "tight newline".
        self._output_lay.setContentsMargins(20, 18, 20, 18)
        self._output_lay.setSpacing(22)
        self._output_lay.addStretch(1)   # push rows to the top

        self._output_scroll.setWidget(self._output_container)
        wrap_lay.addWidget(self._output_scroll)
        return wrap

    def _build_sidebar(self) -> QWidget:
        col = QWidget()
        # Wider sidebar (220 → 240) so the action button labels + recent
        # command text breathe; we were clipping mid-label on longer entries.
        col.setFixedWidth(240)
        col.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        # 14 between panels (was 10) — matches the gap between command blocks
        # in the output panel and pulls each panel down into the empty zone.
        cl.setSpacing(14)

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

    def _build_input_row(self) -> QWidget:
        """Bordered transparent shell wrapping ❯ + QLineEdit + hint.

        Mockup look: thin cyan border, transparent interior so the panel's
        dotted backdrop shows through. The QLineEdit itself has no border
        and no background — the wrapper QFrame owns the chrome.
        """
        wrap = QFrame()
        wrap.setStyleSheet(
            "QFrame {"
            "background: transparent;"
            f"border: 1px solid {CYAN_FAINT};"
            "}"
            "QFrame:focus-within {"
            f"border: 1px solid {CYAN_SOFT};"
            "}"
        )
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(14, 10, 14, 10)
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
        # Transparent + borderless — chrome lives on the wrapper QFrame
        # above so the input row looks like ONE bordered box, not a
        # padded button-style field nested inside a row.
        self._input.setStyleSheet(
            "QLineEdit {"
            "background: transparent;"
            f"color: {INK};"
            "border: none;"
            "padding: 0;"
            "}"
        )
        self._input.returnPressed.connect(self._on_submit)
        self._input.installEventFilter(self)
        lay.addWidget(self._input, 1)

        # Mockup phrasing: two compact phrases ("Enter to send" / "Shift+Enter
        # newline") separated by a single dot — reads less like a checklist
        # than the four-word-three-dots version we had.
        hint = QLabel("Enter to send  ·  Shift+Enter newline")
        hint.setStyleSheet(
            f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 9.5px; letter-spacing: 1px; }}"
        )
        lay.addWidget(hint)
        return wrap

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
        # Roomier than the old 5x8 — gives the sidebar panels real height
        # so they fill more of the right column naturally rather than
        # leaving a giant dead zone at the bottom. Font 10 → 11 too.
        if active:
            btn.setStyleSheet(
                "QPushButton {"
                "background: transparent;"
                f"color: {CYAN};"
                "border: none;"
                f"font-family: '{FM}';"
                "font-size: 11px;"
                "font-weight: 700;"
                "padding: 7px 10px;"
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
                "font-size: 11px;"
                "padding: 7px 10px;"
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
        # Open a fresh command block so subsequent streamed lines belong
        # to this command (and the @tag filter can hide it as a unit).
        block = self._begin_command_block(self._classify_tag(text))
        block.ts = datetime.now().strftime("%H:%M:%S")
        block.prompt = text
        block.awaiting_response = True   # this block expects JARVIS's reply inline
        self._rebuild_block_widget(block)
        # Route raw so the brain picks the intent exactly like the dashboard
        # command bar ("open chrome" → open_app, "navigate youtube" → browser).
        # An explicit @tag the user typed is preserved. Bare shell commands can
        # still be forced with an explicit "@code <cmd>".
        self.command_submitted.emit(text)

    def begin_external_command(self, text: str) -> None:
        """Open a command block for a command issued OUTSIDE the terminal box
        (dashboard, mic, palette) so the terminal mirrors ALL JARVIS activity.

        Unlike _on_submit this does NOT re-dispatch — main.py already routed the
        command; the reply lands via append_jarvis_response and any streamed
        output via _record_extra, exactly like a terminal-typed command.
        """
        self._cmd_count += 1
        self._refresh_session_label()
        block = self._begin_command_block(self._classify_tag(text))
        block.ts = datetime.now().strftime("%H:%M:%S")
        block.prompt = text
        block.awaiting_response = True
        self._rebuild_block_widget(block)
        self._scroll_to_bottom()

    def _on_save(self) -> None:
        """Best-effort dump of the current buffer to logs/terminal_dump.txt."""
        from pathlib import Path
        try:
            out_path = Path(__file__).parent.parent.parent / "logs" / "terminal_dump.txt"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(self._serialize_buffer(), encoding="utf-8")
            self._append_system(f"Saved to {out_path.name}.")
        except OSError as exc:
            self._append_system(f"save failed — {exc}")

    def _serialize_buffer(self) -> str:
        """Flatten the block model into plain text for the SAVE button."""
        out: list[str] = []
        for block in self._blocks:
            if block.kind == "system":
                out.append(f"⬡  {block.system_text}")
            else:
                header = ""
                if block.ts:
                    header += f"[{block.ts}] "
                header += f"❯ {block.prompt}"
                out.append(header)
                if block.intent or block.response:
                    bits = []
                    if block.intent:
                        bits.append(f"[{block.intent.upper()}]")
                    if block.response:
                        bits.append(block.response)
                    out.append("    " + " ".join(bits))
                for txt, _color in block.extras:
                    out.append("    " + txt)
            out.append("")  # blank line between blocks
        return "\n".join(out)

    # ── Signal handlers ──────────────────────────────────────────────────────

    def _on_line(self, line: str) -> None:
        # Streamed lines from a running handler land in the current command
        # block's ``extras`` so they appear under the prompt + (optional)
        # response. Color heuristics match the old QTextEdit path so terminal
        # output, errors, and step dividers stay visually distinct.
        lower = line.lower()
        is_step = line.startswith("── Step") or line.startswith("──")
        if is_step:
            color = _COL_MUTED
        elif any(w in lower for w in _ERROR_WORDS):
            color = _COL_STDERR
        else:
            color = _COL_STDOUT
        self._record_extra(line, color)

    def _on_done(self, exit_code: int) -> None:
        if exit_code == 0:
            self._record_extra("[OK] exit 0", _COL_SUCCESS)
        else:
            self._record_extra(f"[ERR {exit_code}]", _COL_FAIL)

    # ── Public helpers ───────────────────────────────────────────────────────

    def append_jarvis_response(self, text: str, *, intent: str = "", final: bool = True) -> None:
        """Show JARVIS's spoken reply in the current command block.

        ``intent`` is optional but recommended — when provided, it drives
        the colored chip next to the response (FILE / BROWSER / VISION /
        etc.). Without it the response shows without a badge.
        """
        block = self._cur_block
        # Only fill a command block that is still WAITING for its reply — i.e.
        # one the user just typed in this terminal. A command issued from the
        # dashboard / mic / palette leaves no awaiting block here, so its reply
        # is ignored rather than overwriting the last terminal command's block.
        if block is None or block.kind != "command" or not block.awaiting_response:
            return
        block.response = text
        if intent:
            block.intent = intent
            # Refine the filter bucket from the REAL resolved intent so the
            # @CODE/@FILES/@BROWSER chips match the badge shown on the block.
            # Only overwrite for a concrete bucket — the final reply of a
            # confirmed command carries intent "confirmation" (→ 'other') and
            # must not wipe the code/browser tag set by the prompt.
            tag = self._intent_to_tag(intent)
            if tag != "other":
                block.tag = tag
        # Keep the block "awaiting" while this is only a confirmation PROMPT
        # (final=False) so the eventual result still lands in the same block.
        # Clear it on the real reply so a later dashboard/mic command can't
        # overwrite this block.
        if final:
            block.awaiting_response = False
            # The command that owns this block is done — drop the current-block
            # pointer so streamed lines (terminal_line_ready) from a LATER
            # dashboard/mic command don't leak into this finished block via
            # _record_extra.
            self._cur_block = None
        self._rebuild_block_widget(block)

    def clear_output(self) -> None:
        # Drop every spawned widget AND the underlying block model so the
        # filter / rerender path starts from a clean slate.
        for w in list(self._block_widgets.values()):
            w.deleteLater()
        self._block_widgets.clear()
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
            block = self._begin_command_block(tag)
            block.ts = ts
            block.prompt = prompt
            # Map our short label → IntentBadge's intent key. The chip
            # constructor accepts either the short label or the full intent
            # name; we already use short labels here.
            block.intent = intent.lower()
            block.response = response
            block.response_color = _COL_FAIL if kind == "fail" else INK
            # One demo extra to show what multi-line responses look like.
            if intent == "FILE":
                block.extras.append(
                    ("Path: C:\\Users\\Lenovo\\Downloads\\notes.txt", INK_DIM)
                )
            elif intent == "BROWSER":
                block.extras.append(
                    ("Active tab: YouTube · Music · Lofi Hip Hop Radio", INK_DIM)
                )
            elif intent == "FAIL":
                block.extras.append(
                    ("WinError 2: The system cannot find the file specified: 'Spotify'",
                     _COL_FAIL),
                )
            self._rebuild_block_widget(block)
            # Mirror what _on_submit does so the sidebar + counter stay in sync.
            self._cmd_history.append(prompt)
            self._cmd_count += 1
        self._cmd_history = self._cmd_history[-self._MAX_HISTORY:]
        self._refresh_recent_sidebar()
        self._refresh_session_label()

    # ── Tag classification + filter wiring ───────────────────────────────────

    # Resolved intent → filter-chip key. Keeps the chip filter aligned with the
    # badge on each block. Intents not listed fall to 'other' (only @ALL shows).
    _INTENT_FILTER: dict[str, str] = {
        "open_app": "app", "close_app": "app",
        "search_web": "search",
        "file_operation": "files",
        "code_execution": "code",
        "browser_automation": "browser",
        "system_control": "system",
        "automation_task": "auto",
        "vision_analysis": "vision", "read_screen": "vision",
    }
    # Typed @tag → chip key (initial guess; refined from the intent on reply).
    _TAG_ALIAS: dict[str, str] = {
        "code": "code", "files": "files", "file": "files",
        "browser": "browser", "system": "system", "app": "app",
        "search": "search", "vision": "vision", "screen": "vision",
        "automate": "auto", "auto": "auto",
    }

    @classmethod
    def _classify_tag(cls, text: str) -> str:
        """Initial bucket from a typed @tag (refined from the resolved intent on
        reply — see _intent_to_tag). Plain/untagged text → 'other'."""
        t = text.strip().lower()
        if not t.startswith("@"):
            return "other"
        word = t[1:].split(maxsplit=1)[0] if len(t) > 1 else ""
        return cls._TAG_ALIAS.get(word, "other")

    @classmethod
    def _intent_to_tag(cls, intent: str) -> str:
        """Map a resolved intent to its filter chip key. Anything unlisted
        (incl. 'confirmation') → 'other', so it never wipes a real tag."""
        return cls._INTENT_FILTER.get((intent or "").lower(), "other")

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

    # ── Widget-based rendering ───────────────────────────────────────────────
    #
    # The output panel is a QScrollArea wrapping a QVBoxLayout of one widget
    # per block. Three operations matter:
    #   * append_block — block created, spawn its widget at the end
    #   * rebuild_block — block data changed, swap widget in place
    #   * rerender — filter changed, clear + respawn visible blocks
    # The block_id → widget dict makes the swap O(1).

    def _spawn_widget(self, block: _Block) -> QWidget:
        if block.kind == "system":
            return _SystemRow(block.system_text)
        return _CommandRow(block)

    def _append_block_widget(self, block: _Block) -> None:
        if not self._block_visible(block):
            return
        widget = self._spawn_widget(block)
        self._block_widgets[id(block)] = widget
        # Insert above the trailing stretch (always the last item).
        self._output_lay.insertWidget(self._output_lay.count() - 1, widget)
        self._scroll_to_bottom()

    def _rebuild_block_widget(self, block: _Block) -> None:
        """Replace this block's widget in place. Called after the block's
        data changes (streamed line, response set, etc.)."""
        old = self._block_widgets.get(id(block))
        if old is None:
            # Block isn't currently rendered (e.g. filter is hiding it OR
            # the widget hasn't been spawned yet). Append if visible.
            if self._block_visible(block):
                self._append_block_widget(block)
            return
        # Find the index of the old widget and replace it.
        idx = self._output_lay.indexOf(old)
        if idx < 0:
            return
        old.deleteLater()
        if self._block_visible(block):
            new = self._spawn_widget(block)
            self._block_widgets[id(block)] = new
            self._output_lay.insertWidget(idx, new)
        else:
            del self._block_widgets[id(block)]
        self._scroll_to_bottom()

    def _rerender(self) -> None:
        """Full clear + respawn from filtered _blocks. Used on filter switch."""
        for w in list(self._block_widgets.values()):
            w.deleteLater()
        self._block_widgets.clear()
        for block in self._blocks:
            if self._block_visible(block):
                widget = self._spawn_widget(block)
                self._block_widgets[id(block)] = widget
                self._output_lay.insertWidget(self._output_lay.count() - 1, widget)

    def _scroll_to_bottom(self) -> None:
        # Defer to give Qt time to lay the new widget out before we ask
        # the scrollbar for its new max value.
        QTimer.singleShot(0, lambda: (
            self._output_scroll.verticalScrollBar().setValue(
                self._output_scroll.verticalScrollBar().maximum()
            )
        ))

    # ── Block lifecycle ──────────────────────────────────────────────────────

    def _append_system(self, msg: str) -> None:
        """System notice — its own one-line block, always visible."""
        block = _Block(kind="system", system_text=msg)
        self._blocks.append(block)
        self._append_block_widget(block)
        # System blocks don't take over _cur_block — they're standalone, so
        # subsequent streamed lines still belong to whichever command was
        # mid-flight (none in practice when system messages fire).

    def _begin_command_block(self, tag: str) -> _Block:
        """Open a new command block. Caller fills in ts/prompt/intent/etc.,
        then calls _rebuild_block_widget(block) to render it."""
        block = _Block(kind="command", tag=tag)
        self._blocks.append(block)
        self._cur_block = block
        # Spawn an empty widget shell; caller is expected to populate the
        # block and call _rebuild_block_widget once data lands.
        self._append_block_widget(block)
        return block

    def _record_extra(self, text: str, color: str) -> None:
        """Append a colored extra line to the current command block AND
        re-render it. Used by streaming handlers (_on_line / _on_done)."""
        if self._cur_block is None or self._cur_block.kind != "command":
            return
        self._cur_block.extras.append((text, color))
        self._rebuild_block_widget(self._cur_block)

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
        # Roomier label cap too — was 26, bumped to 32 to use the wider
        # sidebar column (240px) without truncating common command lengths.
        recent = list(reversed(self._cmd_history))[: self._MAX_RECENT_SIDEBAR]
        for i, cmd in enumerate(recent):
            shown = cmd if len(cmd) <= 32 else cmd[:29] + "…"
            btn = self._sidebar_btn(shown, cmd, active=(i == 0))
            # Tighter spacing than action buttons but still roomier than
            # before. Recent list reads as a quiet column, not a button bar.
            btn.setStyleSheet(btn.styleSheet().replace("padding: 7px 10px", "padding: 5px 10px"))
            body.insertWidget(body.count() - 1, btn)
            self._recent_btns.append(btn)

    # ── Paint (dotted backdrop) ──────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        """Same cyan-dot grid the other top-level views use (History, Voice,
        Settings). Child panels with semi-transparent BG_PANEL let the dots
        show faintly through; gaps between panels show them clearly."""
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 229, 255, 18))
        for x in range(0, self.width() + 28, 28):
            for y in range(0, self.height() + 28, 28):
                p.drawEllipse(x - 1, y - 1, 2, 2)
