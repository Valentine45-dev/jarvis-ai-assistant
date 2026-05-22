"""Shared HUD design primitives.

Components defined here are used across multiple views (History, Settings,
Voice, Automation, Terminal). Keeping them in one place means a typography
or border-treatment change propagates to every view in one commit.

Convention: every widget here paints transparently and exposes its own
border via QSS — never use setAutoFillBackground or stylesheet background
unless you absolutely mean it (clashes with the dotted DashboardView bg).
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.theme import CYAN, FM


# ── Token shortcuts ──────────────────────────────────────────────────────────
# Centralised here so a re-theme is one edit per token. The .py side mirrors
# the CSS custom properties used in assets/reference/views_redesign_proposals.html.

INK         = "#c3f5ff"
INK_DIM     = "rgba(195, 245, 255, 0.62)"
INK_FAINT   = "rgba(195, 245, 255, 0.38)"
CYAN_SOFT   = "rgba(0, 229, 255, 0.45)"
CYAN_FAINT  = "rgba(0, 229, 255, 0.18)"
BG_PANEL    = "rgba(10, 17, 19, 0.92)"
GREEN       = "#83fba5"
GREEN_DIM   = "rgba(131, 251, 165, 0.78)"
AMBER       = "#ffd166"
RED         = "#ff6b6b"

# Intent badge colours (also used by transcript / log rows).
INTENT_COLOR: dict[str, str] = {
    "file":               "#66dd8b",
    "browser":            CYAN,
    "vision":             "#c792ea",
    "system":             AMBER,
    "code":               "#6cc6ff",
    "automation":         "#ff9bd6",
    "meta":               "rgba(195, 245, 255, 0.62)",
    "weather":            "#9bd0ff",
    "reminder":           "#ffd166",
    "document":           "#ff9bd6",
    "search":             CYAN,
    "fail":               RED,
}

# Short label shown on the badge. Keys mirror the brain's `intent` strings so
# a single lookup per row covers everything.
INTENT_LABEL: dict[str, str] = {
    "file_operation":     "file",
    "browser_automation": "browser",
    "vision_analysis":    "vision",
    "system_control":     "system",
    "code_execution":     "code",
    "automation_task":    "auto",
    "jarvis_meta":        "meta",
    "weather":            "weather",
    "reminder_task":      "remind",
    "document_creation":  "doc",
    "search_web":         "search",
    "open_app":           "app",
    "close_app":          "close",
    "type_text":          "type",
    "control_mouse":      "mouse",
    "read_screen":        "ocr",
    "unknown":            "unknown",
}


def _mono(size: int, *, bold: bool = False, tracking: float = 0.0) -> QFont:
    """Project monospace font helper. ``tracking`` is in em-fractions (multiplied
    to 1000 for QFont.setLetterSpacing(PercentageSpacing))."""
    font = QFont(FM)
    font.setPointSize(size)
    font.setBold(bold)
    if tracking:
        font.setLetterSpacing(QFont.AbsoluteSpacing, tracking)
    return font


# ── IntentBadge ──────────────────────────────────────────────────────────────


class IntentBadge(QLabel):
    """Compact coloured tag indicating an intent / outcome category.

    Drives off the brain's raw intent string (``file_operation`` →  ``file``)
    or a status keyword (``fail``, ``ok``). Caller can pass either form.
    """

    def __init__(self, intent_or_status: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.set_intent(intent_or_status)

    def set_intent(self, intent_or_status: str) -> None:
        key = (intent_or_status or "unknown").strip().lower()
        # Map full intent name → short label, else use the input directly.
        label = INTENT_LABEL.get(key, key)
        # Color: try the short label first (most badges use that key), then
        # the raw intent as a fallback.
        color = INTENT_COLOR.get(label) or INTENT_COLOR.get(key) or INK_DIM
        self.setText(label.upper())
        self.setStyleSheet(
            "QLabel {"
            f"color: {color};"
            f"border: 1px solid {color};"
            "border-radius: 2px;"
            "padding: 1px 6px;"
            f"font-family: '{FM}';"
            "font-size: 9px;"
            "font-weight: 700;"
            "letter-spacing: 1.5px;"
            "background: transparent;"
            "}"
        )
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)


# ── StatusPip ────────────────────────────────────────────────────────────────


class StatusPip(QWidget):
    """Small filled circle indicating health/status.

    States:
      - ``"on"`` (default green with glow)
      - ``"warn"`` (amber)
      - ``"err"`` (red)
      - ``"off"`` (faint grey)
    """

    _COLORS = {
        "on":   GREEN,
        "warn": AMBER,
        "err":  RED,
        "off":  "rgba(195, 245, 255, 0.38)",
    }

    def __init__(self, state: str = "off", *, size: int = 8, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = state
        self._size = size
        self.setFixedSize(size + 4, size + 4)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        color_str = self._COLORS.get(self._state, self._COLORS["off"])
        # rgba() parsing — Qt expects QColor("#hex") OR named.
        if color_str.startswith("rgba"):
            # crude parse: rgba(r, g, b, a-float)
            inner = color_str[color_str.index("(") + 1:color_str.rindex(")")]
            r, g, b, a = [x.strip() for x in inner.split(",")]
            color = QColor(int(r), int(g), int(b), int(float(a) * 255))
        else:
            color = QColor(color_str)
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        cx = self.width() // 2
        cy = self.height() // 2
        p.drawEllipse(cx - self._size // 2, cy - self._size // 2, self._size, self._size)
        if self._state == "on":
            # Soft outer glow ring at 30% alpha.
            color.setAlpha(80)
            p.setBrush(color)
            p.drawEllipse(cx - self._size // 2 - 2, cy - self._size // 2 - 2,
                          self._size + 4, self._size + 4)


# ── HeroMetric ───────────────────────────────────────────────────────────────


class HeroMetric(QWidget):
    """Big-number/small-label metric tile used in the header strips of every view.

    Layout::

        LABEL  (9px tracking-wide cyan, opaque 78%)
        VALUE  (28-32px bold ink, hero number)
        UNIT   (10px ink-faint inline with value)
        SUB    (10px ink-dim, optional supporting detail)
    """

    def __init__(
        self,
        label: str,
        value: str = "—",
        *,
        unit: str = "",
        sub: str = "",
        value_color: str = INK,
        value_size: int = 16,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._value_color = value_color
        self._value_size = value_size

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        self._label = QLabel(label.upper())
        # NOTE: `border: none` is mandatory on every inner QLabel — QLabel
        # subclasses QFrame, so a parent's `QFrame { border-right: ... }`
        # stylesheet selector cascades and paints a border on the label
        # itself. The explicit `border: none` blocks that.
        self._label.setStyleSheet(
            "QLabel {"
            "color: rgba(0,229,255,0.78);"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 9px;"
            "font-weight: 700;"
            "letter-spacing: 2.2px;"
            "}"
        )
        lay.addWidget(self._label)

        # Value row: large number + optional small inline unit
        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(4)
        self._value = QLabel(value)
        self._value.setStyleSheet(
            "QLabel {"
            f"color: {value_color};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            f"font-size: {value_size}px;"
            "font-weight: 700;"
            "letter-spacing: -0.3px;"
            "}"
        )
        value_row.addWidget(self._value, 0)

        self._unit = QLabel(unit)
        self._unit.setStyleSheet(
            "QLabel {"
            f"color: {INK_FAINT};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "letter-spacing: 1px;"
            "}"
        )
        value_row.addWidget(self._unit, 0, Qt.AlignBottom)
        value_row.addStretch(1)
        lay.addLayout(value_row)

        self._sub = QLabel(sub)
        self._sub.setStyleSheet(
            "QLabel {"
            f"color: {INK_DIM};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "}"
        )
        if not sub:
            self._sub.setVisible(False)
        lay.addWidget(self._sub)
        lay.addStretch(1)

    # ── Public ───────────────────────────────────────────────────────────────

    def set_value(self, value: str, *, color: Optional[str] = None) -> None:
        self._value.setText(value)
        if color and color != self._value_color:
            self._value_color = color
            self._value.setStyleSheet(
                "QLabel {"
                f"color: {color};"
                "background: transparent;"
                "border: none;"
                f"font-family: '{FM}';"
                f"font-size: {self._value_size}px;"
                "font-weight: 700;"
                "letter-spacing: -0.3px;"
                "}"
            )

    def set_sub(self, sub: str) -> None:
        self._sub.setText(sub)
        self._sub.setVisible(bool(sub))


# ── DivideRow ────────────────────────────────────────────────────────────────


class DivideRow(QFrame):
    """Horizontal row with a hairline divider underneath. Use as the building
    block for transcript timelines, history lists, log buffers.

    Caller assembles whatever inner widgets they want via ``row.layout()``.
    Set ``last=True`` on the final row to suppress the divider.
    """

    def __init__(self, *, last: bool = False, padding_y: int = 8, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame {"
            "background: transparent;"
            + ("" if last else
               "border-bottom: 1px solid rgba(0,229,255,0.07);")
            + "}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, padding_y, 0, padding_y)
        lay.setSpacing(12)
        self._lay = lay

    def add(self, widget: QWidget, *, stretch: int = 0, align: Optional[Qt.AlignmentFlag] = None) -> None:
        if align is not None:
            self._lay.addWidget(widget, stretch, align)
        else:
            self._lay.addWidget(widget, stretch)

    def add_stretch(self, stretch: int = 1) -> None:
        self._lay.addStretch(stretch)


# ── ChipFilter ───────────────────────────────────────────────────────────────


class ChipFilter(QPushButton):
    """Pill-style toggle chip with active/inactive states. Used in filter rows."""

    def __init__(self, text: str, *, active: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(text.upper(), parent)
        self.setCheckable(True)
        self.setChecked(active)
        self.setCursor(Qt.PointingHandCursor)
        self._refresh_style()
        self.toggled.connect(lambda _: self._refresh_style())

    def _refresh_style(self) -> None:
        if self.isChecked():
            border = CYAN
            color = CYAN
            bg = "rgba(0,229,255,0.08)"
        else:
            border = CYAN_FAINT
            color = INK_DIM
            bg = "transparent"
        self.setStyleSheet(
            "QPushButton {"
            f"background: {bg};"
            f"color: {color};"
            f"border: 1px solid {border};"
            "padding: 2px 10px;"
            f"font-family: '{FM}';"
            "font-size: 9.5px;"
            "font-weight: 700;"
            "letter-spacing: 1.4px;"
            "text-align: center;"
            "}"
            "QPushButton:hover { background: rgba(0,229,255,0.10); }"
        )


# ── PanelCard ────────────────────────────────────────────────────────────────


class PanelCard(QFrame):
    """Bordered panel with an optional title label and an active accent border.

    ``active=True`` adds a 2px cyan left border (per the shared design grammar).
    Pass ``title`` to render a label row at the top automatically; otherwise
    use ``layout()`` directly.
    """

    def __init__(
        self,
        title: str = "",
        *,
        active: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        left_border = (
            f"border-left: 2px solid {CYAN};"
            if active else
            f"border-left: 1px solid {CYAN_FAINT};"
        )
        self.setStyleSheet(
            "QFrame {"
            f"background: {BG_PANEL};"
            f"border: 1px solid {CYAN_FAINT};"
            f"{left_border}"
            "}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 14, 12)
        lay.setSpacing(10)
        self._lay = lay

        if title:
            title_lbl = QLabel(title.upper())
            title_lbl.setStyleSheet(
                "QLabel {"
                f"color: {CYAN};"
                "background: transparent;"
                "border: none;"
                f"font-family: '{FM}';"
                "font-size: 9.5px;"
                "font-weight: 700;"
                "letter-spacing: 2.2px;"
                "}"
            )
            lay.addWidget(title_lbl)

    def body(self) -> QVBoxLayout:
        """Convenience accessor for callers who want to keep adding widgets
        without needing to know the layout's name."""
        return self._lay

    def add(self, widget: QWidget, *, stretch: int = 0) -> None:
        self._lay.addWidget(widget, stretch)


__all__ = [
    "INK", "INK_DIM", "INK_FAINT", "CYAN_SOFT", "CYAN_FAINT", "BG_PANEL",
    "GREEN", "GREEN_DIM", "AMBER", "RED",
    "INTENT_COLOR", "INTENT_LABEL",
    "IntentBadge", "StatusPip", "HeroMetric", "DivideRow", "ChipFilter",
    "PanelCard",
]
