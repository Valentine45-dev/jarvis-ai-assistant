from __future__ import annotations

from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QWidget


class GlassPanel(QWidget):
    """Semi-transparent panel with corner brackets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._show_brackets = True
        self._fill = True
        self._fill_color = QColor(21, 29, 30, 100)

    def set_show_brackets(self, show: bool):
        self._show_brackets = show
        self.update()

    def set_fill(self, fill: bool):
        self._fill = fill
        self.update()

    def set_fill_color(self, color):
        """Override panel fill color (QColor or RGBA tuple)."""
        if isinstance(color, QColor):
            self._fill_color = color
        else:
            try:
                r, g, b, *rest = color
                a = rest[0] if rest else 255
                self._fill_color = QColor(int(r), int(g), int(b), int(a))
            except Exception:
                return
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        w, h = self.width(), self.height()
        if self._fill:
            p.fillRect(0, 0, w, h, self._fill_color)
        if self._show_brackets:
            # subtle full-rect border, alpha 35 cyan
            p.setPen(QPen(QColor(0, 229, 255, 35), 1))
            p.drawRect(0, 0, w - 1, h - 1)
            # corner brackets, alpha 180 cyan, 10px
            p.setPen(QPen(QColor(0, 229, 255, 180), 1))
            b = 10
            p.drawLine(0, 0, b, 0)
            p.drawLine(0, 0, 0, b)
            p.drawLine(w - 1 - b, 0, w - 1, 0)
            p.drawLine(w - 1, 0, w - 1, b)
            p.drawLine(0, h - 1, b, h - 1)
            p.drawLine(0, h - 1 - b, 0, h - 1)
            p.drawLine(w - 1 - b, h - 1, w - 1, h - 1)
            p.drawLine(w - 1, h - 1 - b, w - 1, h - 1)
