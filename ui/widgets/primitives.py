"""Primitive labels, helpers, and the canonical font/header factories (R2-17e split).

Part of the ``ui/widgets`` package. Houses ``_mono`` (the cached Roboto-Mono
QFont factory used everywhere) and ``_panel_header`` (the canonical GlassPanel
header row + separator). The simple QLabel-based widgets — ``ModuleIDLabel``,
``StatusPip``, ``AnimatedLabel``, ``HudStatusLabel``, ``LastActionStrip`` —
also live here.

``_mono`` is defined exactly once so the ``@functools.lru_cache`` is shared
across every caller (sibling sub-modules + external importers via the package
``__init__.py`` re-export).
"""

from __future__ import annotations

import functools

from PyQt5.QtCore import (
    QEasingCurve,
    Qt,
    QPropertyAnimation,
    pyqtProperty,
)
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from ui.theme import CYAN, FM, GREEN, RED, TEXT_MUTED, WARNING


# ---------------------------------------------------------------------------
# Canonical font/layout helpers — import these; do NOT redefine per-file
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=32)
def _mono(size: int, bold: bool = False) -> QFont:
    """Create a Roboto Mono QFont. Canonical — replaces 6 per-file copies."""
    f = QFont(FM, size)
    f.setBold(bold)
    return f


def _panel_header(title: str, right_text: str = "") -> "tuple[QWidget, QFrame]":
    """Standard GlassPanel header row + separator. Canonical — replaces 3 per-file copies."""
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
    if right_text:
        r = QLabel(right_text)
        r.setFont(_mono(8))
        r.setStyleSheet(f"color:{TEXT_MUTED};background:transparent;border:none;")
        hl.addStretch(1)
        hl.addWidget(r)
    sep = QFrame()
    sep.setFrameShape(QFrame.HLine)
    sep.setStyleSheet("color:rgba(0,229,255,0.15);background:rgba(0,229,255,0.15);")
    sep.setFixedHeight(1)
    return header, sep


class ModuleIDLabel(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text.upper(), parent)
        self.setFixedHeight(20)
        self.setStyleSheet(
            "QLabel{"
            "background:rgba(0,229,255,0.15);"
            "border-right:1px solid rgba(0,229,255,0.8);"
            "border-bottom:1px solid rgba(0,229,255,0.8);"
            f"color:{CYAN};"
            f"font-family:'{FM}';"
            "font-size:10px;"
            "padding:2px 8px;"
            "}"
        )


class StatusPip(QWidget):
    """Animated status pip: active/standby/error."""

    def __init__(self, status: str = "active", parent=None):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self._status = status
        self._opacity = 1.0
        self._anim = QPropertyAnimation(self, b"opacity")
        self._anim.setLoopCount(-1)
        self.set_status(status)

    def get_opacity(self):
        return self._opacity

    def set_opacity(self, value):
        self._opacity = float(value)
        self.update()

    opacity = pyqtProperty(float, fget=get_opacity, fset=set_opacity)

    def set_status(self, status: str):
        self._status = status
        self._anim.stop()
        if status == "active":
            self._anim.setDuration(2000)
            self._anim.setStartValue(0.6)
            self._anim.setEndValue(1.0)
            self._anim.setEasingCurve(QEasingCurve.InOutSine)
            self._anim.start()
        elif status == "error":
            self._anim.setDuration(800)
            self._anim.setStartValue(0.4)
            self._anim.setEndValue(1.0)
            self._anim.setEasingCurve(QEasingCurve.InOutSine)
            self._anim.start()
        else:
            self._opacity = 1.0
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._status == "active":
            color = QColor(GREEN)
        elif self._status == "error":
            color = QColor(RED)
        else:
            color = QColor(WARNING)
        color.setAlphaF(max(0.0, min(1.0, self._opacity)))
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(1, 1, 8, 8)


# ---------------- Compatibility / chrome labels used by main.py ----------------


class AnimatedLabel(QLabel):
    def __init__(self, text="0", fmt="{:.0f}%", suffix="", parent=None):
        super().__init__(text, parent)
        self._fmt = fmt
        self._suffix = suffix
        self._value = 0.0

    def setText(self, text):
        raw = str(text)
        try:
            self._value = float("".join(c for c in raw if c.isdigit() or c == "."))
            super().setText(self._fmt.format(self._value) + self._suffix)
        except ValueError:
            super().setText(raw)


class HudStatusLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__("STANDBY", parent)
        self.setStyleSheet(f"QLabel{{color:{CYAN};font-family:'{FM}';font-size:10px;letter-spacing:1px;}}")

    def set_status(self, text):
        self.setText(str(text).upper())


class LastActionStrip(QLabel):
    def __init__(self, parent=None):
        super().__init__("LAST ACTION: --", parent)
        self.setStyleSheet("QLabel{color:rgba(186,201,204,0.8);font-size:10px;}")

    def set_action(self, intent, conf):
        self.setText(f"LAST ACTION: {str(intent).upper()} ({int(float(conf) * 100)}%)")
