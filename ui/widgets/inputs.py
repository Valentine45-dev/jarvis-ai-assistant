"""Interactive controls (R2-17e split).

Part of the ``ui/widgets`` package. Houses the user-input widgets:
``ToggleSwitch``, ``MicButton``, the ``_TagHighlighter`` + ``_TagLineEdit``
pair, and the ``CommandBar`` shell. No sibling imports — moved verbatim from
the former monolithic ``ui/widgets.py``.
"""

from __future__ import annotations

import re

from PyQt5.QtCore import (
    QRectF,
    Qt,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QWidget,
)
import qtawesome as qta

from ui.theme import ACCENT_RGB, CYAN, PRIMARY


class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 22)
        self._checked = checked
        self._hovered = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        self._checked = bool(checked)
        self.update()

    def enterEvent(self, _):
        self._hovered = True
        self.update()

    def leaveEvent(self, _):
        self._hovered = False
        self.update()

    def mousePressEvent(self, _):
        self._checked = not self._checked
        self.toggled.emit(self._checked)
        self.update()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self._checked = not self._checked
            self.toggled.emit(self._checked)
            self.update()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track = QRectF(1, 1, 42, 20)
        hover_boost = 20 if self._hovered else 0
        p.setPen(QPen(QColor(CYAN if self._checked else "#3b494c"), 1))
        p.setBrush(QColor(*ACCENT_RGB, (40 if self._checked else 20) + hover_boost))
        p.drawRoundedRect(track, 10, 10)
        knob_x = 24 if self._checked else 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(CYAN if self._checked else "#849396"))
        p.drawEllipse(knob_x, 2, 18, 18)
        if self.hasFocus():
            p.setPen(QPen(QColor(*ACCENT_RGB, 180), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(0.5, 0.5, 43, 21), 11, 11)


class MicButton(QPushButton):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._listening = False
        self._hovered = False
        self.setFixedSize(42, 38)
        self.setCursor(Qt.PointingHandCursor)
        self.setText("")
        self.setFocusPolicy(Qt.StrongFocus)

    def set_listening(self, listening: bool):
        self._listening = listening
        self.update()

    def enterEvent(self, _):
        self._hovered = True
        self.update()

    def leaveEvent(self, _):
        self._hovered = False
        self.update()

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        focused = self.hasFocus()
        bg_alpha = 180 if self._hovered else 120
        p.fillRect(self.rect(), QColor(8, 15, 17, bg_alpha))
        border_alpha = 200 if (self._hovered or focused) else 120
        p.setPen(QPen(QColor(*ACCENT_RGB, border_alpha), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        if focused:
            p.setPen(QPen(QColor(*ACCENT_RGB, 140), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.rect().adjusted(2, 2, -3, -3))
        icon_color = CYAN if (self._listening or self._hovered or focused) else PRIMARY
        icon = qta.icon("fa5s.microphone", color=icon_color)
        p.drawPixmap((self.width() - 14) // 2, (self.height() - 14) // 2, icon.pixmap(14, 14))


class _TagHighlighter(QSyntaxHighlighter):
    """Colors the leading @tag token in the command input in real time.

    Valid tag   → cyan + bold  (confirms the shortcut is active)
    Invalid tag → gold         (warns the user before they submit)
    """
    _CYAN = QColor(*ACCENT_RGB)   # valid-@tag highlight = accent (== #00E5FF on cyan)
    _GOLD = QColor("#FFE16D")     # invalid-@tag = SEMANTIC warning, fixed across themes

    def __init__(self, document, valid_tags: frozenset):
        super().__init__(document)
        self._valid_tags = valid_tags

        self._fmt_valid = QTextCharFormat()
        self._fmt_valid.setForeground(self._CYAN)
        self._fmt_valid.setFontWeight(QFont.Bold)

        self._fmt_warn = QTextCharFormat()
        self._fmt_warn.setForeground(self._GOLD)

    def highlightBlock(self, text: str):
        m = re.match(r'^(@\w+)', text)
        if not m:
            return
        tag = m.group(1)[1:].lower()
        fmt = self._fmt_valid if tag in self._valid_tags else self._fmt_warn
        self.setFormat(0, len(m.group(1)), fmt)


class _TagLineEdit(QTextEdit):
    """Directive field: @tag highlighting; **Enter** submits, **Shift+Enter** inserts newline.

    Exposes the same surface as QLineEdit so CommandBar callers need
    no changes: text(), setText(), setCursorPosition(), setFocus(), clear().
    """
    returnPressed = pyqtSignal()
    contentHeightChanged = pyqtSignal(int)  # desired editor height in px (for parent layout)

    # Locked editor height — overflow scrolls vertically inside the
    # fixed viewport instead of growing the editor. UX call (2026-05): the
    # input bar must NEVER push or overlap the central reactor / right
    # metrics; if the user types or pastes more than fits, they scroll.
    # Set _H_MAX == _H_MIN so _reflow_height's scrollbar branch kicks in
    # the moment content exceeds the viewport. 48px ≈ comfortable two-line
    # field at 13px mono with a bit of vertical padding.
    _H_MIN = 48
    _H_MAX = 48

    def __init__(self, valid_tags: frozenset = frozenset(), parent=None):
        super().__init__(parent)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(0)
        self._vtop = -1  # cached top viewport margin (vertical-centering)
        self.setFixedHeight(self._H_MIN)
        self.setPlaceholderText("Awaiting directive...")
        self._valid_tags = tuple(sorted(t.lower() for t in valid_tags))
        self._highlighter = _TagHighlighter(self.document(), valid_tags)
        self.document().contentsChanged.connect(self._reflow_height)
        self.textChanged.connect(self._refresh_tag_suggestions)
        self.cursorPositionChanged.connect(self._refresh_tag_suggestions)
        self._tag_popup = QListWidget()
        self._tag_popup.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self._tag_popup.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._tag_popup.setFocusPolicy(Qt.NoFocus)
        self._tag_popup.setSelectionMode(QAbstractItemView.SingleSelection)
        self._tag_popup.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tag_popup.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._tag_popup.setStyleSheet(
            "QListWidget{"
            "background:rgba(8,15,17,0.98);"
            "border:1px solid rgba(0,229,255,0.45);"
            "color:#c3f5ff;"
            "font-family:'Roboto Mono';"
            "font-size:11px;"
            "padding:4px;"
            "}"
            "QListWidget::item{padding:6px 8px;}"
            "QListWidget::item:selected{"
            "background:rgba(0,229,255,0.20);"
            "color:#00e5ff;"
            "}"
            "QListWidget::item:hover{background:rgba(0,229,255,0.12);}"
        )
        self._tag_popup.itemClicked.connect(lambda *_: self._accept_tag_suggestion())
        self._popup_tag_range: tuple[int, int] | None = None
        self._popup_token_prefix: str = ""
        # Center the placeholder right away (contentsChanged won't fire for the
        # initial empty document).
        self._reflow_height()

    # ── QLineEdit-compatible API ──────────────────────────────────────────

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, s: str):
        self.setPlainText(s)
        c = self.textCursor()
        c.movePosition(QTextCursor.End)
        self.setTextCursor(c)
        self._reflow_height()

    def setCursorPosition(self, pos: int):
        c = self.textCursor()
        c.setPosition(min(pos, len(self.toPlainText())))
        self.setTextCursor(c)

    def _apply_vcenter(self):
        """Vertically center the text while it's a single line (the usual state —
        placeholder + short commands) so it lines up with the ">_" prompt and
        mic; top-align once it wraps so a 2-line field still shows both lines."""
        doc_h = int(self.document().size().height())
        single_line = doc_h <= int(self.fontMetrics().height() * 1.6)
        top = max(0, (self.height() - doc_h) // 2) if single_line else 0
        if top != self._vtop:
            self._vtop = top
            self.setViewportMargins(0, top, 0, 0)

    def resizeEvent(self, e):
        # Recompute centering once the widget gets its real height on screen
        # (the __init__ pass runs before layout, so the placeholder would
        # otherwise keep a stale margin until the first keystroke).
        super().resizeEvent(e)
        self._apply_vcenter()

    def _reflow_height(self):
        """Grow/shrink with line count; cap height then scroll. Notify parent card."""
        doc_h = int(self.document().size().height())
        pad = 12
        content_h = doc_h + pad
        h = max(self._H_MIN, min(content_h, self._H_MAX))
        if h != self.height():
            self.setFixedHeight(h)
        self._apply_vcenter()
        # Show vertical scroll only when content exceeds the fixed viewport
        if content_h > self._H_MAX - 1:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        else:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.contentHeightChanged.emit(self.height())
        self._reposition_tag_popup()

    def _current_tag_context(self) -> tuple[int, int, str] | None:
        """Return (start_pos, end_pos, typed_fragment) for the @token near cursor."""
        c = self.textCursor()
        block = c.block()
        block_pos = block.position()
        in_block = c.position() - block_pos
        left = block.text()[:in_block]
        m = re.search(r'(^|\s)@([A-Za-z0-9_]*)$', left)
        if not m:
            return None
        at_idx = m.start(2) - 1  # include '@' before capture group 2
        start = block_pos + at_idx
        end = c.position()
        typed = m.group(2).lower()
        return start, end, typed

    def _refresh_tag_suggestions(self):
        ctx = self._current_tag_context()
        if not ctx or not self._valid_tags:
            self._hide_tag_popup()
            return

        start, end, typed = ctx
        if typed:
            choices = [t for t in self._valid_tags if t.startswith(typed)]
        else:
            choices = list(self._valid_tags)
        if not choices:
            self._hide_tag_popup()
            return

        self._popup_tag_range = (start, end)
        self._popup_token_prefix = typed
        self._tag_popup.clear()
        for t in choices[:12]:
            QListWidgetItem(f"@{t}", self._tag_popup)
        self._tag_popup.setCurrentRow(0)
        self._reposition_tag_popup()
        if not self._tag_popup.isVisible():
            self._tag_popup.show()

    def _reposition_tag_popup(self):
        if not self._tag_popup.isVisible():
            return
        cr = self.cursorRect()
        anchor = self.mapToGlobal(cr.topLeft())
        width = max(220, min(self.width() - 4, 360))
        rows = min(max(self._tag_popup.count(), 1), 8)
        row_h = self._tag_popup.sizeHintForRow(0) if self._tag_popup.count() else 24
        height = max(80, rows * row_h + 10)
        x = anchor.x()
        y = anchor.y() - height - 6  # default: open above the input

        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            if y < avail.top() + 4:
                # Fallback below when there is not enough room above.
                y = self.mapToGlobal(cr.bottomLeft()).y() + 4
            if x + width > avail.right() - 4:
                x = max(avail.left() + 4, avail.right() - width - 4)
            if x < avail.left() + 4:
                x = avail.left() + 4
            if y + height > avail.bottom() - 4:
                y = max(avail.top() + 4, avail.bottom() - height - 4)

        self._tag_popup.setGeometry(x, y, width, height)

    def _hide_tag_popup(self):
        self._popup_tag_range = None
        self._popup_token_prefix = ""
        self._tag_popup.hide()

    def _accept_tag_suggestion(self) -> bool:
        if not self._tag_popup.isVisible():
            return False
        item = self._tag_popup.currentItem()
        if item is None or self._popup_tag_range is None:
            self._hide_tag_popup()
            return False
        start, end = self._popup_tag_range
        tc = self.textCursor()
        tc.setPosition(start)
        tc.setPosition(end, QTextCursor.KeepAnchor)
        tc.insertText(item.text() + " ")
        self.setTextCursor(tc)
        self._hide_tag_popup()
        return True

    # ── Behaviour overrides ───────────────────────────────────────────────

    def keyPressEvent(self, event):
        if self._tag_popup.isVisible():
            if event.key() == Qt.Key_Down:
                row = min(self._tag_popup.currentRow() + 1, self._tag_popup.count() - 1)
                self._tag_popup.setCurrentRow(row)
                return
            if event.key() == Qt.Key_Up:
                row = max(self._tag_popup.currentRow() - 1, 0)
                self._tag_popup.setCurrentRow(row)
                return
            if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
                if self._accept_tag_suggestion():
                    return
            if event.key() == Qt.Key_Escape:
                self._hide_tag_popup()
                return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)
                return
            # If tag suggestions are open, Enter accepts suggestion before submit.
            if self._accept_tag_suggestion():
                return
            self.returnPressed.emit()
            return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source):
        """Allow pasting multiple lines (Shift+Enter / paste); normalise CR only."""
        t = source.text()
        if not t:
            return
        self.insertPlainText(t.replace("\r\n", "\n").replace("\r", "\n"))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Word wrap reflows line count when width changes
        self._reflow_height()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        # Keep suggestions visible while typing in the same field; they will
        # hide automatically when context no longer matches or on explicit Esc.


class CommandBar(QWidget):
    command_sent = pyqtSignal(str)

    def __init__(self, valid_tags: frozenset = frozenset(), parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._input = _TagLineEdit(valid_tags)
        self._input.returnPressed.connect(self._emit)
        self._send = QPushButton("EXECUTE")
        self._send.clicked.connect(self._emit)
        lay.addWidget(self._input, 1)
        lay.addWidget(self._send)

    def get_input(self) -> "_TagLineEdit":
        return self._input

    def _emit(self):
        text = self._input.text().strip()
        if not text:
            return
        self.command_sent.emit(text)
        self._input.clear()
