"""Global command palette — centered modal overlay with command input.

Opened via the TopBar terminal icon or the global Ctrl+K shortcut. Routes the
submitted command through the same pipeline as the Dashboard command bar so
the user can issue commands from any page (or even with no view focused).

Architecture:
    CommandPalette is a child widget of the main window. On show_palette() it
    resizes to fill the parent window, paints a semi-transparent dim
    backdrop, and centers an inner glass frame containing:
        - input field (with @tag highlighting)
        - recent commands row (click to re-fill)
        - hint footer

    Closing happens on Esc, click on backdrop (outside the inner frame), or
    after a successful submit. Behaves like a modal but is not blocking —
    the rest of the UI keeps running underneath.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPalette
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ui.theme import ACCENT_RGB, CYAN, FM, PRIMARY
from ui.widgets import _TagLineEdit, _mono


_FRAME_WIDTH = 640
_FRAME_TOP_OFFSET = 110          # distance from window top to frame top
_BACKDROP_ALPHA = 165            # 0..255 — how dark the dim layer is


class _RecentChip(QPushButton):
    """Compact pill button representing a recent command. Click → re-fill."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        # Truncate visually but keep full text accessible via tooltip + data
        display = text if len(text) <= 28 else text[:25] + "…"
        self.setText(display)
        self.setToolTip(text)
        self._full_text = text
        self.setStyleSheet(
            "QPushButton{"
            "color:rgba(195,245,255,0.78);"
            f"font-family:'{FM}';font-size:11px;"
            "background:rgba(0,229,255,0.06);"
            "border:1px solid rgba(0,229,255,0.18);"
            "padding:6px 12px;border-radius:2px;text-align:left;"
            "}"
            "QPushButton:hover{"
            f"color:{CYAN};border-color:rgba(0,229,255,0.55);"
            "background:rgba(0,229,255,0.12);"
            "}"
        )

    def full_text(self) -> str:
        return self._full_text


class CommandPalette(QWidget):
    """Full-window modal overlay with a centered command input."""

    command_submitted = pyqtSignal(str)

    def __init__(self, parent: QWidget, valid_tags: frozenset = frozenset()):
        super().__init__(parent)
        self._valid_tags = valid_tags
        self._recents: list[str] = []
        # Hidden by default; show_palette() resizes us to the parent and shows.
        self.hide()
        # Block mouse events under the palette frame (so clicks on the
        # backdrop are caught here, not propagated to the underlying view).
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._build_frame()

    # ── Construction ─────────────────────────────────────────────────────────

    def _build_frame(self):
        # The inner frame is a child of the overlay; we manually position it
        # in resizeEvent so it stays centered when the window resizes.
        self._frame = QFrame(self)
        self._frame.setFixedWidth(_FRAME_WIDTH)
        # Frame paints its own background + border via paintEvent below.
        self._frame.setAttribute(Qt.WA_StyledBackground, False)
        self._frame.paintEvent = self._frame_paint   # type: ignore[assignment]

        outer = QVBoxLayout(self._frame)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)

        # ── Header label ─────────────────────────────────────────────────────
        head_row = QHBoxLayout()
        head_row.setSpacing(10)
        title = QLabel("COMMAND PALETTE")
        title.setFont(_mono(11, bold=True))
        title.setStyleSheet(
            f"color:{CYAN};letter-spacing:3px;background:transparent;border:none;"
        )
        head_row.addWidget(title)
        head_row.addStretch(1)
        kbd = QLabel("CTRL+K  ·  ESC TO CLOSE")
        kbd.setStyleSheet(
            "color:rgba(132,147,150,0.55);font-family:'Roboto Mono';"
            "font-size:9px;letter-spacing:2px;background:transparent;border:none;"
        )
        head_row.addWidget(kbd)
        outer.addLayout(head_row)

        # ── Input field ──────────────────────────────────────────────────────
        self._input = _TagLineEdit(self._valid_tags)
        self._input.setFixedHeight(54)
        self._input.setPlaceholderText("Issue a directive  ·  open chrome  ·  @browser search today")
        self._input.setStyleSheet(
            "QTextEdit{"
            f"color:{PRIMARY};font-family:'{FM}';font-size:16px;"
            "background:rgba(8,15,17,0.85);"
            "border:1px solid rgba(0,229,255,0.32);"
            "padding:11px 14px;"
            "selection-background-color:rgba(0,229,255,0.30);"
            "}"
            "QTextEdit:focus{border:1px solid rgba(0,229,255,0.85);}"
        )
        # Must be set AFTER setStyleSheet — stylesheet rebuilds the palette and
        # would otherwise override this.
        _ph_pal = self._input.palette()
        _ph_pal.setColor(QPalette.PlaceholderText, QColor(*ACCENT_RGB, 150))
        self._input.setPalette(_ph_pal)
        self._input.returnPressed.connect(self._submit)
        outer.addWidget(self._input)

        # ── Recents row ──────────────────────────────────────────────────────
        self._recents_label = QLabel("RECENT")
        self._recents_label.setStyleSheet(
            "color:rgba(132,147,150,0.65);font-family:'Roboto Mono';"
            "font-size:10px;letter-spacing:2px;background:transparent;border:none;"
        )
        outer.addWidget(self._recents_label)

        self._recents_row = QWidget()
        self._recents_row.setStyleSheet("background:transparent;")
        self._recents_lay = QHBoxLayout(self._recents_row)
        self._recents_lay.setContentsMargins(0, 0, 0, 0)
        self._recents_lay.setSpacing(6)
        outer.addWidget(self._recents_row)

        # ── Footer hint ──────────────────────────────────────────────────────
        hint = QLabel(
            "Press ENTER to send  ·  Click outside or ESC to dismiss"
        )
        hint.setStyleSheet(
            "color:rgba(132,147,150,0.60);font-family:'Roboto Mono';"
            "font-size:10px;letter-spacing:0.5px;background:transparent;border:none;"
        )
        outer.addWidget(hint)

        self._refresh_recents_ui()
        self._frame.adjustSize()

    # ── Public API ───────────────────────────────────────────────────────────

    def show_palette(self):
        """Open the palette: resize to parent, focus the input, raise."""
        if self.parentWidget() is not None:
            self.resize(self.parentWidget().size())
        self._reposition_frame()
        self.show()
        self.raise_()
        self._input.clear()
        self._input.setFocus()

    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self.show_palette()

    def set_recents(self, commands: list[str]):
        """Refresh the recents row. Newest first; capped at 3."""
        self._recents = list(commands)[:3]
        self._refresh_recents_ui()

    # ── Submit / dismiss ─────────────────────────────────────────────────────

    def _submit(self):
        text = self._input.text().strip()
        if not text:
            return
        # Hide first so the dispatch doesn't render under a stale overlay.
        self.hide()
        self.command_submitted.emit(text)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        # Click outside the inner frame closes the palette; clicks on the
        # frame propagate normally (so input still gets focus, etc.).
        if not self._frame.geometry().contains(event.pos()):
            self.hide()
            return
        super().mousePressEvent(event)

    # ── Layout / paint ───────────────────────────────────────────────────────

    def resizeEvent(self, event):
        self._reposition_frame()
        super().resizeEvent(event)

    def _reposition_frame(self):
        if self.width() <= 0:
            return
        x = max(20, (self.width() - self._frame.width()) // 2)
        # If window is narrower than the frame, shrink the frame too
        if self.width() < _FRAME_WIDTH + 40:
            new_w = max(360, self.width() - 40)
            self._frame.setFixedWidth(new_w)
            x = (self.width() - new_w) // 2
        else:
            self._frame.setFixedWidth(_FRAME_WIDTH)
        self._frame.move(x, _FRAME_TOP_OFFSET)
        self._frame.adjustSize()

    def paintEvent(self, _):
        # Dim backdrop covering the entire parent window.
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, _BACKDROP_ALPHA))

    def _frame_paint(self, _):
        # Hand-painted glass surface for the inner frame to match other panels.
        f = self._frame
        p = QPainter(f)
        p.setRenderHint(QPainter.Antialiasing)
        rect = f.rect().adjusted(0, 0, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(10, 17, 19, 248))
        p.drawRect(rect)
        p.setPen(QPen(QColor(*ACCENT_RGB, 130), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(rect)
        # Top accent line — subtle "live surface" cue
        p.setPen(QPen(QColor(*ACCENT_RGB, 200), 1))
        p.drawLine(rect.left(), rect.top(), rect.right(), rect.top())

    # ── Recents UI ───────────────────────────────────────────────────────────

    def _refresh_recents_ui(self):
        # Remove old chips
        while self._recents_lay.count():
            item = self._recents_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not self._recents:
            empty = QLabel("No recent commands yet — type one above.")
            empty.setStyleSheet(
                "color:rgba(132,147,150,0.40);font-family:'Roboto Mono';"
                "font-size:10px;background:transparent;border:none;"
            )
            self._recents_lay.addWidget(empty)
            self._recents_lay.addStretch(1)
            self._recents_label.setVisible(True)
            return

        for cmd in self._recents:
            chip = _RecentChip(cmd)
            chip.clicked.connect(lambda _, c=chip: self._on_chip_clicked(c.full_text()))
            self._recents_lay.addWidget(chip)
        self._recents_lay.addStretch(1)

    def _on_chip_clicked(self, text: str):
        self._input.setText(text)
        self._input.setFocus()


__all__ = ["CommandPalette"]
