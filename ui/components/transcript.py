from __future__ import annotations

import html
import random

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

from ui.components.design import INTENT_LABEL, intent_label_color
from ui.components.panels import GlassPanel
from ui.theme import CYAN, FM, PRIMARY, TEXT_MUTED


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
        "Waiting for your call.",
        "Your move.",
        "Just say the word.",
        "Standing by.",
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
            (self._confirm_btn, 0, 229, 255),
            (self._cancel_btn, 255, 70, 70),
        ):
            btn.setFixedHeight(30)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton{{color:rgba({r},{g},{b},240);"
                f"border:1px solid rgba({r},{g},{b},160);"
                f"background:rgba({r},{g},{b},18);"
                f"font-family:'{FM}';font-size:11px;font-weight:700;"
                f"letter-spacing:2px;padding:0 16px;}}"
                f"QPushButton:hover{{color:rgb({r},{g},{b});"
                f"background:rgba({r},{g},{b},45);"
                f"border:1px solid rgba({r},{g},{b},230);}}"
                f"QPushButton:pressed{{background:rgba({r},{g},{b},70);}}"
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
            f"border:1px dashed rgba(0,229,255,{_a255(0.30)});"
            "border-radius:2px;"
            f"background:rgba(0,229,255,{_a255(0.04)});"
            "padding:10px 14px;}"
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

        a_border = 0.25 + self._pulse_step * 0.055   # 0.25 – 0.91
        a_bg     = 0.03 + self._pulse_step * 0.006   # 0.03 – 0.102
        self.setStyleSheet(
            "InlineConfirmCard{"
            f"border:1px dashed rgba(0,229,255,{_a255(a_border)});"
            "border-radius:2px;"
            f"background:rgba(0,229,255,{_a255(a_bg)});"
            "padding:10px 14px;}"
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


# ── SYS_LOG renderer (Variant B: outcome rail + gutters + JARVIS-only chips) ──
#
# Pure, Qt-free HTML builder so it's unit-testable. QTextBrowser (Qt rich text)
# renders bordered/background <td> cells and cell bgcolor, but DROPS border-radius
# and inline-span borders — so the rail is a 4px bgcolor cell and chips are square
# bordered <td>s. info rail follows the theme (CYAN token); the rest are SEMANTIC
# fixed colours. Latency is intentionally NOT rendered (deferred; never faked).

_RAIL_OK        = "#83fba5"    # success — green (semantic, fixed)
_RAIL_FAIL      = "#ff6b6b"    # failure — red (semantic, fixed)
_RAIL_INTERRUPT = "#ffd166"    # aborted — amber (semantic, fixed)
_INTERRUPT_TEXT = "#ffb432"    # the ⛔ line text colour (preserved as-is)
_CONF_CHIP      = "#849396"    # confidence chip — muted/secondary (solid for td border)


def _rail_color(is_you: bool, intent: str, success) -> str:
    """Per-line left-rail colour: info (themed accent) / ok / fail / interrupt."""
    if intent == "interrupted":
        return _RAIL_INTERRUPT
    if is_you:
        return CYAN                       # info — themed
    if success is True:
        return _RAIL_OK
    if success is False:
        return _RAIL_FAIL
    return CYAN                           # info (no outcome) — themed


def _chip(text: str, color: str) -> str:
    """One square chip as a bordered <td> (QTextBrowser drops border-radius)."""
    return (
        f'<td style="border:1px solid {color}; color:{color};">'
        f"&nbsp;{html.escape(text)}&nbsp;</td>"
    )


def _chip_row(intent: str, conf) -> str:
    """JARVIS-only chip row: intent chip (+ a confidence chip when conf is known).
    No latency chip — deferred, never fabricated."""
    label, color = intent_label_color(intent)
    chips = [_chip(label.upper(), color)]
    if conf is not None:
        chips.append("<td>&nbsp;&nbsp;</td>")          # gap
        chips.append(_chip(f"{int(conf * 100)}%", _CONF_CHIP))
    return (
        '<table cellspacing="0" cellpadding="3" style="margin-top:4px;">'
        f"<tr>{''.join(chips)}</tr></table>"
    )


def _line_table(rail: str, inner: str) -> str:
    """One log line: a 4px colour-rail cell + the content cell."""
    return (
        '<table width="100%" cellspacing="0" cellpadding="0"><tr>'
        f'<td width="4" bgcolor="{rail}"></td>'
        f'<td style="padding-left:8px;">{inner}</td>'
        "</tr></table>"
    )


def _build_log_html(rows, expanded_rows, preview_chars: int) -> str:
    """Render SYS_LOG rows to QTextBrowser HTML. Per line: a left outcome rail +
    time|speaker|message; JARVIS lines also get a chip row (intent · confidence).
    YOU lines stay one dense line with no chips. Pure (no Qt) → unit-testable."""
    ts   = f"color:{TEXT_MUTED};"
    you_ = f"color:{TEXT_MUTED};"
    jar_ = f"color:{CYAN};"
    body = f"color:{PRIMARY};"
    spacer = '<div style="font-size:5px;">&nbsp;</div>'
    blocks: list[str] = []

    for idx, row in enumerate(rows):
        you, y_time, jarvis, j_time, intent, conf, success = row

        if you:
            inner = (
                f'<span style="{ts}">[{html.escape(str(y_time))}]</span> '
                f'<span style="{you_}">YOU:</span> '
                f'<span style="{body}">{html.escape(str(you))}</span>'
            )
            blocks.append(_line_table(_rail_color(True, "", None), inner))

        if jarvis and intent == "interrupted":
            line = html.escape(f"[{j_time}] ⛔ {jarvis}")
            blocks.append(_line_table(
                _RAIL_INTERRUPT, f'<span style="color:{_INTERRUPT_TEXT};">{line}</span>'))
            blocks.append(spacer)
            continue

        if jarvis:
            shown = jarvis
            toggle = ""
            if len(jarvis) > preview_chars:
                if idx in expanded_rows:
                    toggle = f' <a href="jarvis://collapse/{idx}">[show less]</a>'
                else:
                    shown = jarvis[:preview_chars].rstrip() + "…"
                    toggle = f' <a href="jarvis://expand/{idx}">[load more]</a>'
            shown_html = html.escape(shown).replace("\n", "<br>")
            inner = (
                f'<span style="{ts}">[{html.escape(str(j_time))}]</span> '
                f'<span style="{jar_}">JARVIS:</span> '
                f'<span style="{body}">{shown_html}</span>{toggle}'
                + _chip_row(intent, conf)
            )
            blocks.append(_line_table(_rail_color(False, intent, success), inner))

        blocks.append(spacer)

    return "".join(blocks)


class TranscriptPanel(GlassPanel):
    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        # Row-id model (Option B): every row gets a stable id at creation so the
        # typewriter and any concurrent appender (narration / follow / reminder /
        # scheduled) target their OWN row by id — never "the last row", which
        # crosses when a row appends mid-animation. Rows are APPEND-ONLY (never
        # removed/reordered), so id→index stays valid for the life of the panel;
        # _id_index is kept O(1) and consistent with _rows/_row_ids on every append.
        self._row_ids: list[int] = []
        self._id_index: dict[int, int] = {}
        self._next_row_id = 0
        # Expand/collapse is keyed by row INDEX — also safe under the append-only
        # assumption above (index == position never shifts).
        self._expanded_jarvis_rows: set[int] = set()
        self._preview_chars = 260
        self._view = QTextBrowser(self)
        self._view.setOpenLinks(False)
        self._view.setOpenExternalLinks(False)
        self._view.anchorClicked.connect(self._on_link_clicked)
        self._view.setStyleSheet(
            "QTextBrowser{background:transparent;border:none;"
            f"color:{PRIMARY};font-family:'{FM}';font-size:14px;"
            "line-height:1.6;}"
            "QTextBrowser a{color:#00e5ff;text-decoration:none;}"
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

    def _append_row(self, row: tuple) -> int:
        """Append a row, allocate its stable id, keep _row_ids/_id_index in lockstep
        with _rows, and return the id. The single place rows are born."""
        rid = self._next_row_id
        self._next_row_id += 1
        self._id_index[rid] = len(self._rows)
        self._rows.append(row)
        self._row_ids.append(rid)
        return rid

    def add_exchange(self, you, y_time, jarvis="", j_time="", intent="", conf=None,
                     success=None) -> int:
        # success: None = info/neutral rail, True = ok (green), False = fail (red).
        # Returns the new row's stable id (Option B: the typewriter binds to it).
        rid = self._append_row((you, y_time, jarvis, j_time, intent, conf, success))
        self._render()
        return rid

    def append_jarvis_scheduled(
        self, jarvis: str, j_time: str, intent: str = "", conf: float | None = None,
        success=None,
    ) -> int:
        """Log line for a background scheduled action (no matching YOU: line).
        Returns its own stable id; it is an INDEPENDENT row that never disturbs a
        typewriter animating a different (command) row."""
        rid = self._append_row(("", "", jarvis, j_time, intent, conf, success))
        self._render()
        return rid

    # ── by-id mutators (Option B — the live targeting path) ───────────────────

    def update_you(self, row_id: int, text, y_time=""):
        idx = self._id_index.get(row_id)
        if idx is None:
            return
        _, _, jarvis, j_time, intent, conf, success = self._rows[idx]
        self._rows[idx] = (text, y_time, jarvis, j_time, intent, conf, success)
        self._render()

    def update_jarvis(self, row_id: int, text, j_time="", intent="", conf=None,
                      success=None):
        idx = self._id_index.get(row_id)
        if idx is None:
            return
        you, y_time, _, _, old_intent, old_conf, old_success = self._rows[idx]
        self._rows[idx] = (
            you,
            y_time,
            text,
            j_time,
            intent or old_intent,
            conf if conf is not None else old_conf,
            success if success is not None else old_success,
        )
        self._render()

    # ── back-compat wrappers (resolve the LAST row's id) ──────────────────────
    # Kept for any caller/test still using "last row" semantics; the live proxy
    # path now targets a specific row id via update_you/update_jarvis above.

    def update_last_you(self, text, y_time=""):
        if not self._row_ids:
            return
        self.update_you(self._row_ids[-1], text, y_time)

    def update_last_jarvis(self, text, j_time="", intent="", conf=None, success=None):
        if not self._row_ids:
            return
        self.update_jarvis(self._row_ids[-1], text, j_time, intent, conf, success)

    def _render(self):
        self._view.setHtml(
            _build_log_html(self._rows, self._expanded_jarvis_rows, self._preview_chars)
        )
        sb = self._view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_link_clicked(self, url):
        token = url.toString()
        if token.startswith("jarvis://expand/"):
            try:
                idx = int(token.rsplit("/", 1)[-1])
                self._expanded_jarvis_rows.add(idx)
                self._render()
            except Exception:
                return
        elif token.startswith("jarvis://collapse/"):
            try:
                idx = int(token.rsplit("/", 1)[-1])
                self._expanded_jarvis_rows.discard(idx)
                self._render()
            except Exception:
                return
