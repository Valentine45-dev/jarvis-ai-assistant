"""Painted indicator + chart widgets (R2-17e split).

Part of the ``ui/widgets`` package. Houses every paint-heavy widget that
visualises state: segmented bars, scan-line overlay, line chart, the Mark-LXXXV
arc reactor, the waveform strip, the confidence gauge, plus the two
compatibility shims (``OrbWidget``, ``SparklineWidget``).

These classes have no sibling dependencies — they're moved verbatim from the
former monolithic ``ui/widgets.py``.
"""

from __future__ import annotations

import math
import random

from PyQt5.QtCore import (
    QPointF,
    QRectF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PyQt5.QtWidgets import QWidget

from ui.theme import ACCENT_RGB, CYAN, FM, GREEN, PRIMARY, WARNING


class SegmentedBar(QWidget):
    def __init__(self, segments: int = 12, value: float = 0.0, color: str = CYAN, parent=None):
        super().__init__(parent)
        self.segments = max(1, segments)
        self.value = max(0.0, min(1.0, value))
        self.color = QColor(color)
        self.setMinimumHeight(10)

    def set_value(self, value: float):
        self.value = max(0.0, min(1.0, float(value)))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        w, h = self.width(), self.height()
        gap = 2
        block_w = max(2, (w - (self.segments - 1) * gap) // self.segments)
        filled = int(round(self.value * self.segments))
        for i in range(self.segments):
            x = i * (block_w + gap)
            c = QColor(self.color)
            c.setAlpha(205 if i < filled else 50)
            p.fillRect(x, 0, block_w, h, c)


class ScanLineOverlay(QWidget):
    """Thin horizontal scanline animation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._y = 0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _tick(self):
        self._y += 2
        if self._y > self.height():
            self._y = 0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        grad = QLinearGradient(0, self._y - 1, 0, self._y + 1)
        grad.setColorAt(0, QColor(*ACCENT_RGB, 0))
        grad.setColorAt(0.5, QColor(*ACCENT_RGB, 76))
        grad.setColorAt(1, QColor(*ACCENT_RGB, 0))
        p.fillRect(0, self._y - 1, self.width(), 2, grad)


class LineChartWidget(QWidget):
    """Wireframe chart with primary/secondary lines and threshold."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._series = [0.0] * 24
        self._secondary = []
        self._threshold = None
        self.setMinimumHeight(90)

    def set_data(self, values):
        self._series = list(values) if values else [0.0]
        self.update()

    def set_secondary(self, values):
        self._secondary = list(values) if values else []
        self.update()

    def set_threshold(self, value):
        self._threshold = value
        self.update()

    def _draw_series(self, p: QPainter, data, color: QColor, area: QRectF, dashed=False):
        if not data or len(data) < 2:
            return
        max_val = max(max(data), 1.0)
        points = []
        for i, v in enumerate(data):
            x = area.left() + (i / (len(data) - 1)) * area.width()
            y = area.bottom() - (v / max_val) * area.height()
            points.append(QPointF(x, y))
        pen = QPen(color, 1)
        if dashed:
            pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.drawPolyline(QPolygonF(points))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.fillRect(r, QColor(8, 15, 17, 80))
        p.setPen(QPen(QColor(59, 73, 76, 76), 1))
        for i in range(1, 5):
            y = int(r.top() + i * r.height() / 5)
            p.drawLine(r.left(), y, r.right(), y)
        for i in range(1, 8):
            x = int(r.left() + i * r.width() / 8)
            p.drawLine(x, r.top(), x, r.bottom())
        chart = QRectF(r.left() + 2, r.top() + 2, r.width() - 4, r.height() - 4)
        self._draw_series(p, self._series, QColor(CYAN), chart)
        if self._secondary:
            c = QColor(WARNING)
            c.setAlpha(150)
            self._draw_series(p, self._secondary, c, chart)
        if self._threshold is not None:
            max_val = max(max(self._series), 1.0)
            y = chart.bottom() - (self._threshold / max_val) * chart.height()
            p.setPen(QPen(QColor(GREEN), 1, Qt.DashLine))
            p.drawLine(int(chart.left()), int(y), int(chart.right()), int(y))


class ArcReactorWidget(QWidget):
    """Mark LXXXV-style arc reactor.

    Faithful to `assets/reference/jarvis_main_hud.png`:
      - Outer dashed ring slowly rotating
      - Bright cyan ring at ~80% radius (the dominant ring)
      - 8 radial spokes (N, NE, E, SE, S, SW, W, NW) connecting the two rings
      - Bright cyan ring at ~50% radius
      - White-cyan glowing core with a starburst pattern inside
    Ambient halo + slow pulse on the core sell the "powered" look.
    """

    state_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 240)
        self._angle = 0.0
        self._pulse = 0.0
        self._state = "idle"
        self._state_colors = {
            "idle": QColor(*ACCENT_RGB, 89),   # IDLE_CYAN — unified with Voice mic idle
            "listening": QColor("#00e5ff"),
            "thinking": QColor("#00e5ff"),
            "speaking": QColor("#83fba5"),
            "error": QColor("#ffb4ab"),
            "wake": QColor("#00e5ff"),
        }
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _tick(self):
        self._angle = (self._angle + 0.45) % 360
        self._pulse += 0.045
        self.update()

    def _normalize_state(self, state) -> str:
        if isinstance(state, int):
            return {0: "idle", 1: "listening", 2: "thinking", 3: "speaking"}.get(state, "idle")
        s = str(state).strip().lower()
        if s in ("standby", "idle"):
            return "idle"
        if s in self._state_colors:
            return s
        return "idle"

    def set_state(self, state):
        self._state = self._normalize_state(state)
        self.state_changed.emit(self._state)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        center = QPointF(cx, cy)
        base = min(w, h) * 0.42  # outermost reachable radius

        cyan = QColor(*ACCENT_RGB)
        state_color = QColor(self._state_colors.get(self._state, cyan))

        # ── 1. Ambient halo (soft cyan bloom behind the rings) ──────────────
        halo = QRadialGradient(center, base * 1.35)
        halo.setColorAt(0.00, QColor(*ACCENT_RGB, 70))
        halo.setColorAt(0.55, QColor(*ACCENT_RGB, 22))
        halo.setColorAt(1.00, QColor(*ACCENT_RGB, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(center, base * 1.35, base * 1.35)

        # ── 2. Outermost dashed ring + triangle markers ──────────────────────
        r_dash = base * 0.96
        p.save()
        p.translate(center)
        p.rotate(self._angle)
        pen = QPen(QColor(*ACCENT_RGB, 130), 1)
        pen.setDashPattern([4, 5])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(0, 0), r_dash, r_dash)
        p.restore()

        # Triangle markers at 12, 3, 6, 9 o'clock (fixed, not rotating)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(*ACCENT_RGB, 200))
        tri_r  = r_dash          # radius where tip sits
        tri_sz = base * 0.045    # triangle half-base
        for deg in (270, 0, 90, 180):   # 12, 3, 6, 9 o'clock
            rad = math.radians(deg)
            tip_x = cx + math.cos(rad) * tri_r
            tip_y = cy + math.sin(rad) * tri_r
            # inward-pointing filled triangle
            in_x  = cx + math.cos(rad) * (tri_r - tri_sz * 2.2)
            in_y  = cy + math.sin(rad) * (tri_r - tri_sz * 2.2)
            perp  = math.radians(deg + 90)
            lx = in_x + math.cos(perp) * tri_sz
            ly = in_y + math.sin(perp) * tri_sz
            rx = in_x - math.cos(perp) * tri_sz
            ry = in_y - math.sin(perp) * tri_sz
            p.drawPolygon(QPolygonF([QPointF(tip_x, tip_y), QPointF(lx, ly), QPointF(rx, ry)]))

        # ── 3. Armor panel ring — 12 segmented plates between two rings ──────
        r_outer = base * 0.80
        r_mid_o = base * 0.88   # outer edge of armor band
        r_mid_i = base * 0.82   # inner edge of armor band
        N_SEG   = 12
        gap_deg = 3.0            # gap between panels in degrees
        p.setPen(QPen(QColor(*ACCENT_RGB, 160), 1.0))
        for i in range(N_SEG):
            start_deg = i * (360 / N_SEG) + gap_deg / 2
            span_deg  = (360 / N_SEG) - gap_deg
            start_rad = math.radians(start_deg)
            end_rad   = math.radians(start_deg + span_deg)
            # Build panel polygon from 4 arc-edge points
            steps = 6
            pts = []
            for s in range(steps + 1):
                a = start_rad + (end_rad - start_rad) * s / steps
                pts.append(QPointF(cx + math.cos(a) * r_mid_o, cy + math.sin(a) * r_mid_o))
            for s in range(steps, -1, -1):
                a = start_rad + (end_rad - start_rad) * s / steps
                pts.append(QPointF(cx + math.cos(a) * r_mid_i, cy + math.sin(a) * r_mid_i))
            poly = QPolygonF(pts)
            p.setBrush(QColor(4, 18, 22, 210))   # dark armor fill
            p.drawPolygon(poly)

        # Bright outer ring border over the armor band
        p.setPen(QPen(QColor(*ACCENT_RGB, 235), 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(center, r_outer, r_outer)
        p.setPen(QPen(QColor(*ACCENT_RGB, 60), 1))
        p.drawEllipse(center, r_outer - 4, r_outer - 4)

        # ── 4. Eight radial spokes between inner and outer bright rings ──────
        r_inner = base * 0.50
        spoke_pen = QPen(QColor(*ACCENT_RGB, 175), 1.2)
        p.setPen(spoke_pen)
        for i in range(8):
            ang = math.radians(i * 45)
            x1 = cx + math.cos(ang) * r_inner
            y1 = cy + math.sin(ang) * r_inner
            x2 = cx + math.cos(ang) * (r_outer - 1)
            y2 = cy + math.sin(ang) * (r_outer - 1)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # ── 5. Bright inner ring ─────────────────────────────────────────────
        p.setPen(QPen(QColor(*ACCENT_RGB, 235), 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(center, r_inner, r_inner)

        # ── 6. Glowing core (white-cyan with soft pulse) ────────────────────
        pulse = 1.0 + math.sin(self._pulse) * 0.08
        r_core = base * 0.22 * pulse

        core_glow = QRadialGradient(center, r_core * 1.6)
        glow_mid = QColor(state_color)
        glow_mid.setAlpha(130)
        glow_outer = QColor(state_color)
        glow_outer.setAlpha(0)
        core_glow.setColorAt(0.0, QColor(255, 255, 255, 235))
        core_glow.setColorAt(0.5, glow_mid)
        core_glow.setColorAt(1.0, glow_outer)
        p.setPen(Qt.NoPen)
        p.setBrush(core_glow)
        p.drawEllipse(center, r_core * 1.6, r_core * 1.6)

        core = QRadialGradient(center, r_core)
        edge = QColor(state_color)
        edge.setAlpha(210)
        core.setColorAt(0.0, QColor(255, 255, 255, 250))
        core.setColorAt(0.55, QColor(195, 245, 255, 230))
        core.setColorAt(1.0, edge)
        p.setBrush(core)
        p.drawEllipse(center, r_core, r_core)

        # ── 7. Core starburst — 8 thin wedges over the bright core ──────────
        burst = QColor(state_color)
        burst.setAlpha(110)
        p.setPen(QPen(burst, 1))
        for i in range(8):
            ang = math.radians(i * 45)
            x = cx + math.cos(ang) * r_core * 0.95
            y = cy + math.sin(ang) * r_core * 0.95
            p.drawLine(center, QPointF(x, y))


# ---------------- Compatibility layer used by main.py ----------------


class OrbWidget(ArcReactorWidget):
    pass


class WaveformStrip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = False
        self._bars = [3] * 30
        self.setFixedHeight(24)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(80)

    def set_active(self, active):
        self._active = bool(active)

    def _tick(self):
        hi = 18 if self._active else 5
        self._bars = [random.randint(2, hi) for _ in self._bars]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        w = self.width()
        h = self.height()
        bw = max(1, w // (len(self._bars) * 2))
        for i, v in enumerate(self._bars):
            x = i * bw * 2
            p.fillRect(x, h - v, bw, v, QColor(CYAN if self._active else PRIMARY))


class SparklineWidget(LineChartWidget):
    pass


class ConfidenceGauge(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self.setFixedSize(96, 96)

    def set_value(self, value):
        self._value = max(0, min(100, int(value)))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(6, 6, -6, -6)
        p.setPen(QPen(QColor(59, 73, 76, 180), 2))
        p.drawEllipse(r)
        p.setPen(QPen(QColor(CYAN), 3))
        p.drawArc(r, 90 * 16, int(-360 * 16 * (self._value / 100)))
        p.setPen(QColor(PRIMARY))
        p.setFont(QFont(FM, 10, QFont.Bold))
        p.drawText(self.rect(), Qt.AlignCenter, f"{self._value}%")
