"""Reusable HUD widgets for the JARVIS UI rebuild."""

from __future__ import annotations

import functools
import math
import random
import re

from PyQt5.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    Qt,
    QPropertyAnimation,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPen, QPolygonF, QRadialGradient,
    QSyntaxHighlighter, QTextCharFormat, QTextCursor,
)
from PyQt5.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QWidget,
)
import qtawesome as qta

from ui.components.panels import GlassPanel
from ui.components.transcript import TerminalLog, TranscriptPanel
from ui.theme import BG, CYAN, FM, FN, GREEN, IDLE_CYAN, PRIMARY, RED, TEXT_MUTED, WARNING, _c, _primary


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
        grad.setColorAt(0, QColor(0, 229, 255, 0))
        grad.setColorAt(0.5, QColor(0, 229, 255, 76))
        grad.setColorAt(1, QColor(0, 229, 255, 0))
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
            "idle": QColor(0, 229, 255, 89),   # IDLE_CYAN — unified with Voice mic idle
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

        cyan = QColor(0, 229, 255)
        state_color = QColor(self._state_colors.get(self._state, cyan))

        # ── 1. Ambient halo (soft cyan bloom behind the rings) ──────────────
        halo = QRadialGradient(center, base * 1.35)
        halo.setColorAt(0.00, QColor(0, 229, 255, 70))
        halo.setColorAt(0.55, QColor(0, 229, 255, 22))
        halo.setColorAt(1.00, QColor(0, 229, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(center, base * 1.35, base * 1.35)

        # ── 2. Outermost dashed ring + triangle markers ──────────────────────
        r_dash = base * 0.96
        p.save()
        p.translate(center)
        p.rotate(self._angle)
        pen = QPen(QColor(0, 229, 255, 130), 1)
        pen.setDashPattern([4, 5])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(0, 0), r_dash, r_dash)
        p.restore()

        # Triangle markers at 12, 3, 6, 9 o'clock (fixed, not rotating)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 229, 255, 200))
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
        p.setPen(QPen(QColor(0, 229, 255, 160), 1.0))
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
        p.setPen(QPen(QColor(0, 229, 255, 235), 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(center, r_outer, r_outer)
        p.setPen(QPen(QColor(0, 229, 255, 60), 1))
        p.drawEllipse(center, r_outer - 4, r_outer - 4)

        # ── 4. Eight radial spokes between inner and outer bright rings ──────
        r_inner = base * 0.50
        spoke_pen = QPen(QColor(0, 229, 255, 175), 1.2)
        p.setPen(spoke_pen)
        for i in range(8):
            ang = math.radians(i * 45)
            x1 = cx + math.cos(ang) * r_inner
            y1 = cy + math.sin(ang) * r_inner
            x2 = cx + math.cos(ang) * (r_outer - 1)
            y2 = cy + math.sin(ang) * (r_outer - 1)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # ── 5. Bright inner ring ─────────────────────────────────────────────
        p.setPen(QPen(QColor(0, 229, 255, 235), 2.0))
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
        p.setBrush(QColor(0, 229, 255, (40 if self._checked else 20) + hover_boost))
        p.drawRoundedRect(track, 10, 10)
        knob_x = 24 if self._checked else 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(CYAN if self._checked else "#849396"))
        p.drawEllipse(knob_x, 2, 18, 18)
        if self.hasFocus():
            p.setPen(QPen(QColor(0, 229, 255, 180), 1, Qt.DashLine))
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
        p.setPen(QPen(QColor(0, 229, 255, border_alpha), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        if focused:
            p.setPen(QPen(QColor(0, 229, 255, 140), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.rect().adjusted(2, 2, -3, -3))
        icon_color = CYAN if (self._listening or self._hovered or focused) else PRIMARY
        icon = qta.icon("fa5s.microphone", color=icon_color)
        p.drawPixmap((self.width() - 14) // 2, (self.height() - 14) // 2, icon.pixmap(14, 14))


class GreetingCard(GlassPanel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._commands = 0
        self._uptime_s = 0
        self.setMinimumHeight(86)

    def set_stats(self, commands, uptime_s):
        self._commands = int(commands)
        self._uptime_s = int(uptime_s)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setPen(QColor(PRIMARY))
        p.setFont(QFont(FM, 9, QFont.Bold))
        p.drawText(10, 18, "SESSION")
        p.setFont(QFont(FN, 10))
        p.drawText(10, 40, f"Commands: {self._commands}")
        p.drawText(10, 58, f"Uptime: {self._uptime_s // 60}m")


class TypingIndicator(QLabel):
    def __init__(self, parent=None):
        super().__init__("JARVIS typing...", parent)
        self.setVisible(False)
        self.setStyleSheet(f"QLabel{{color:{PRIMARY};font-family:'{FM}';font-size:10px;}}")

    def show_typing(self):
        self.setVisible(True)

    def hide_typing(self):
        self.setVisible(False)


class _TagHighlighter(QSyntaxHighlighter):
    """Colors the leading @tag token in the command input in real time.

    Valid tag   → cyan + bold  (confirms the shortcut is active)
    Invalid tag → gold         (warns the user before they submit)
    """
    _CYAN = QColor("#00E5FF")
    _GOLD = QColor("#FFE16D")

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

    # Grow a few lines, then cap — overflow scrolls (avoids driving the bar off-screen).
    _H_MIN = 28
    _H_MAX = 108

    def __init__(self, valid_tags: frozenset = frozenset(), parent=None):
        super().__init__(parent)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(0)
        self.setFixedHeight(36)
        self.setPlaceholderText("Awaiting directive...")
        self._highlighter = _TagHighlighter(self.document(), valid_tags)
        self.document().contentsChanged.connect(self._reflow_height)

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

    def _reflow_height(self):
        """Grow/shrink with line count; cap height then scroll. Notify parent card."""
        doc_h = int(self.document().size().height())
        pad = 12
        content_h = doc_h + pad
        h = max(self._H_MIN, min(content_h, self._H_MAX))
        if h != self.height():
            self.setFixedHeight(h)
        # Show vertical scroll only when content exceeds the fixed viewport
        if content_h > self._H_MAX - 1:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        else:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.contentHeightChanged.emit(self.height())

    # ── Behaviour overrides ───────────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)
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


class ToastNotification(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._label = QLabel("", self)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity")
        self._fade.setDuration(350)
        self._label.setStyleSheet(
            f"QLabel{{background:rgba(8,15,17,0.95);border:1px solid {CYAN};"
            f"color:{PRIMARY};font-family:'{FM}';padding:6px 10px;}}"
        )
        self.hide()

    def _reposition(self):
        if not self.parent():
            return
        toast_w = 280
        right_column_w = 260
        margin = 24
        gap = 16
        x = self.parent().width() - margin - right_column_w - gap - toast_w
        self.setGeometry(max(margin, x), 10, toast_w, 36)
        self._label.setGeometry(0, 0, 280, 36)

    def show_toast(self, text, _kind="info"):
        self._label.setText(str(text))
        self._reposition()
        self.show()
        self._effect.setOpacity(1.0)
        QTimer.singleShot(1400, self._fade_out)

    def _fade_out(self):
        self._fade.stop()
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.hide)
        self._fade.start()


class ConfirmationBar(QWidget):
    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    _AMBER = "rgba(255,219,60,0.92)"
    _BORDER = "rgba(255,219,60,0.45)"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self.setFixedHeight(46)
        self.setStyleSheet(
            "background:rgba(22,18,8,0.97);"
            "border-top:1px solid rgba(255,219,60,0.30);"
            "border-bottom:1px solid rgba(255,219,60,0.30);"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 10, 0)
        lay.setSpacing(10)

        warn = QLabel("⚠")
        warn.setFixedWidth(18)
        warn.setStyleSheet(
            "color:rgba(255,219,60,0.80);font-size:13px;"
            "background:transparent;border:none;"
        )
        lay.addWidget(warn)

        self._msg = QLabel("Confirm command?")
        self._msg.setFont(_mono(10))
        self._msg.setStyleSheet(
            f"color:{self._AMBER};background:transparent;border:none;"
        )
        lay.addWidget(self._msg, 1)

        self._ok = QPushButton("CONFIRM")
        self._ok.setFixedSize(86, 28)
        self._ok.setCursor(Qt.PointingHandCursor)
        self._ok.setStyleSheet(
            "QPushButton{"
            f"color:{self._AMBER};border:1px solid {self._BORDER};"
            f"font-family:'Roboto Mono';font-size:10px;font-weight:700;"
            "letter-spacing:1px;background:rgba(255,219,60,0.07);"
            "}"
            "QPushButton:hover{background:rgba(255,219,60,0.18);}"
            "QPushButton:pressed{background:rgba(255,219,60,0.30);}"
            "QPushButton:focus{border:1px solid rgba(255,219,60,0.85);}"
        )
        self._ok.clicked.connect(self.confirmed.emit)
        lay.addWidget(self._ok)

        self._no = QPushButton("CANCEL")
        self._no.setFixedSize(72, 28)
        self._no.setCursor(Qt.PointingHandCursor)
        self._no.setStyleSheet(
            "QPushButton{"
            "color:rgba(132,147,150,0.75);border:1px solid rgba(132,147,150,0.25);"
            "font-family:'Roboto Mono';font-size:10px;letter-spacing:1px;"
            "background:transparent;"
            "}"
            "QPushButton:hover{color:rgba(195,245,255,0.90);border-color:rgba(132,147,150,0.50);}"
            "QPushButton:pressed{background:rgba(132,147,150,0.10);}"
        )
        self._no.clicked.connect(self.cancelled.emit)
        lay.addWidget(self._no)

    def show_confirmation(self, message: str = "") -> None:
        """Set message text and make the bar visible."""
        if message:
            self._msg.setText(message)
        self.setVisible(True)
