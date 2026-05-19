"""
Reusable UI factory helpers — panels, labels, buttons, metric cards.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
)
from PyQt5.QtCore import Qt, QRectF, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QPainter, QPen, QFont, QFontMetrics, QBrush, QLinearGradient, QColor,
)
import qtawesome as qta

from ui.theme import (
    PRIMARY, PRIMARY_DIM, CARD_CLR, BORDER_A,
    FN, FM, RADIUS_SM, RADIUS_MD,
    _c, _primary,
)


class PanelFrame(QWidget):
    """Titled card container — accent header bar + painted glass border."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)

        # Header row
        hdr_w = QWidget()
        hdr_w.setFixedHeight(38)
        hdr_lay = QHBoxLayout(hdr_w)
        hdr_lay.setContentsMargins(14, 0, 14, 0)
        hdr_lay.setSpacing(8)

        # Accent dot
        accent = QLabel("▎")
        accent.setFont(QFont(FN, 10))
        accent.setStyleSheet(f"color:{PRIMARY};background:transparent;border:none;")
        hdr_lay.addWidget(accent, 0, Qt.AlignVCenter)

        title_lbl = QLabel(title)
        title_lbl.setFont(QFont(FN, 9, QFont.DemiBold))
        title_lbl.setStyleSheet(
            "color:rgba(200,215,245,0.55);letter-spacing:0.8px;"
            "background:transparent;border:none;")
        hdr_lay.addWidget(title_lbl)
        hdr_lay.addStretch()

        hdr_w.setStyleSheet("border-bottom:1px solid rgba(0,102,255,0.14);")
        self._lay.addWidget(hdr_w)

        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(14, 12, 14, 14)
        self._body_lay.setSpacing(8)
        self._lay.addWidget(self._body)

    @property
    def body(self):
        return self._body_lay

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Card background
        p.setPen(Qt.NoPen)
        p.setBrush(_c(*CARD_CLR))
        p.drawRoundedRect(QRectF(0, 0, w, h), RADIUS_MD, RADIUS_MD)

        # Border
        p.setPen(QPen(_c(*BORDER_A), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), RADIUS_MD, RADIUS_MD)

        # Top edge accent glow
        tg = QLinearGradient(0, 0, w, 0)
        tg.setColorAt(0.0, _primary(0))
        tg.setColorAt(0.3, _primary(45))
        tg.setColorAt(0.7, _primary(45))
        tg.setColorAt(1.0, _primary(0))
        p.setPen(QPen(QBrush(tg), 1))
        p.drawLine(int(RADIUS_MD), 0, int(w - RADIUS_MD), 0)

        p.end()


class _HoverGlowWidget(QWidget):
    """Base widget — animated hover glow + rounded background. Subclass and
    override paintEvent if extra layers are needed (call _paint_glow_background
    first)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(95)
        self._hover = False
        self._glow_alpha = 0.0
        self._glow_t = QTimer(self)
        self._glow_t.setInterval(16)
        self._glow_t.timeout.connect(self._animate_glow)

    def enterEvent(self, _):
        self._hover = True
        if not self._glow_t.isActive():
            self._glow_t.start()

    def leaveEvent(self, _):
        self._hover = False
        if not self._glow_t.isActive():
            self._glow_t.start()

    def _animate_glow(self):
        target = 1.0 if self._hover else 0.0
        diff = target - self._glow_alpha
        if abs(diff) < 0.02:
            self._glow_alpha = target
            self._glow_t.stop()
        else:
            self._glow_alpha += diff * 0.15
        self.update()

    def _paint_glow_background(self, p: QPainter) -> None:
        w, h = self.width(), self.height()
        g = self._glow_alpha

        border_a = int(18 + 32 * g)
        p.setPen(QPen(_primary(border_a), 1))
        p.setBrush(_c(11, 15, 25, 140))
        p.drawRoundedRect(QRectF(0, 0, w, h), RADIUS_SM, RADIUS_SM)

        if g > 0.01:
            from PyQt5.QtGui import QRadialGradient
            glow = QRadialGradient(w / 2, h / 2, max(w, h) * 0.6)
            glow.setColorAt(0, _primary(int(12 * g)))
            glow.setColorAt(1, _primary(0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(glow))
            p.drawRoundedRect(QRectF(0, 0, w, h), RADIUS_SM, RADIUS_SM)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._paint_glow_background(p)
        p.end()


class MetricCard(_HoverGlowWidget):
    """Single stat card with label, large value, progress bar, and hover glow."""

    def __init__(self, label, value, bar_pct=0, bar_color=PRIMARY, parent=None):
        super().__init__(parent)
        self._bar_pct = bar_pct
        self._bar_color = bar_color

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(4)

        lbl = QLabel(label)
        lbl.setFont(QFont(FM, 8))
        lbl.setStyleSheet(
            "color:rgba(200,215,245,0.32);letter-spacing:0.8px;background:transparent;")
        lay.addWidget(lbl)

        self.val = QLabel(value)
        self.val.setFont(QFont(FN, 21, QFont.Bold))
        self.val.setStyleSheet("color:rgba(210,220,245,0.92);background:transparent;")
        lay.addWidget(self.val)
        lay.addStretch()

    def set_bar(self, pct, color=None):
        self._bar_pct = pct
        if color:
            self._bar_color = color
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._paint_glow_background(p)

        if self._bar_pct > 0:
            w, h = self.width(), self.height()
            bh, by = 3, h - 10
            bw = w - 20
            p.setPen(Qt.NoPen)
            p.setBrush(_primary(22))
            p.drawRoundedRect(QRectF(10, by, bw, bh), 1.5, 1.5)
            p.setBrush(QColor(self._bar_color))
            p.drawRoundedRect(QRectF(10, by, bw * self._bar_pct / 100, bh), 1.5, 1.5)

        p.end()


class MetricCell(_HoverGlowWidget):
    """Grid cell matching MetricCard style with hover glow."""
    # Inherits glow + background paint from _HoverGlowWidget unchanged.


class QuickActionBtn(QWidget):
    """Icon + label tile for quick-action grid."""
    clicked = pyqtSignal(str)

    def __init__(self, icon_name, label, parent=None):
        super().__init__(parent)
        self.setMinimumSize(88, 76)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self._label = label
        self._hover = False
        self._pressed = False
        self._pm       = qta.icon(icon_name, color='#3366CC').pixmap(20, 20)
        self._pm_hover = qta.icon(icon_name, color='#66AAFF').pixmap(20, 20)

    def enterEvent(self, _):
        self._hover = True
        self.update()

    def leaveEvent(self, _):
        self._hover = False
        self._pressed = False
        self.update()

    def mousePressEvent(self, _):
        self._pressed = True
        self.update()

    def mouseReleaseEvent(self, e):
        if self._pressed:
            self._pressed = False
            self.update()
            if self.rect().contains(e.pos()):
                self.clicked.emit(self._label)

    def paintEvent(self, _):
        from PyQt5.QtGui import QRadialGradient
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = QRectF(0.5, 0.5, w - 1, h - 1)

        if self._pressed:
            p.setPen(QPen(_primary(70), 1))
            p.setBrush(_primary(30))
        elif self._hover:
            p.setPen(QPen(_primary(50), 1))
            bg = QRadialGradient(w / 2, h / 2, w * 0.65)
            bg.setColorAt(0, _primary(22))
            bg.setColorAt(1, _primary(7))
            p.setBrush(QBrush(bg))
        else:
            p.setPen(QPen(_primary(18), 1))
            p.setBrush(_c(11, 15, 25, 90))
        p.drawRoundedRect(r, RADIUS_MD, RADIUS_MD)

        # Icon area bg on hover
        icon_y = int(h * 0.18)
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(_primary(20))
            p.drawRoundedRect(QRectF(w / 2 - 18, icon_y - 2, 36, 30), 8, 8)

        pm = self._pm_hover if self._hover else self._pm
        p.setOpacity(0.95 if self._hover else 0.55)
        p.drawPixmap(int(w / 2 - 10), icon_y + 4, pm)
        p.setOpacity(1.0)

        # Label
        p.setPen(_primary(230 if self._hover else 110))
        f = QFont(FN, 8, QFont.DemiBold if self._hover else QFont.Normal)
        p.setFont(f)
        fm = QFontMetrics(f)
        label = fm.elidedText(self._label, Qt.ElideRight, max(1, w - 10))
        p.drawText(QRectF(4, icon_y + 36, w - 8, h - icon_y - 36),
                   Qt.AlignHCenter | Qt.AlignTop, label)
        p.end()
