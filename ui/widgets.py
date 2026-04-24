"""Reusable HUD widgets for the JARVIS UI rebuild."""

from __future__ import annotations

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
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
import qtawesome as qta

from ui.theme import BG, CYAN, FM, FN, GREEN, PRIMARY, RED, WARNING, _c, _primary


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
        cursor = "\n\u2588" if self._show_cursor else "\n "
        self.setPlainText("\n".join(self._base_lines) + cursor)
        self.moveCursor(self.textCursor().End)


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
            "idle": QColor("#ffe16d"),
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

        # ── 2. Outermost dashed ring (slow rotation) ────────────────────────
        r_dash = base * 0.96
        p.save()
        p.translate(center)
        p.rotate(self._angle)
        pen = QPen(QColor(0, 229, 255, 120), 1)
        pen.setDashPattern([3, 6])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(0, 0), r_dash, r_dash)
        p.restore()

        # ── 3. Bright outer ring (the dominant cyan circle) ─────────────────
        r_outer = base * 0.80
        p.setPen(QPen(QColor(0, 229, 255, 235), 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(center, r_outer, r_outer)

        # subtle inner shadow line just inside the bright outer ring
        p.setPen(QPen(QColor(0, 229, 255, 70), 1))
        p.drawEllipse(center, r_outer - 4, r_outer - 4)

        # ── 4. Eight radial spokes between inner and outer bright rings ─────
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

        # ── 5. Bright inner ring ────────────────────────────────────────────
        p.setPen(QPen(QColor(0, 229, 255, 235), 2.0))
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

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        self._checked = bool(checked)
        self.update()

    def mousePressEvent(self, _):
        self._checked = not self._checked
        self.toggled.emit(self._checked)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track = QRectF(1, 1, 42, 20)
        p.setPen(QPen(QColor(CYAN if self._checked else "#3b494c"), 1))
        p.setBrush(QColor(0, 229, 255, 40 if self._checked else 20))
        p.drawRoundedRect(track, 10, 10)
        knob_x = 24 if self._checked else 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(CYAN if self._checked else "#849396"))
        p.drawEllipse(knob_x, 2, 18, 18)


class MicButton(QPushButton):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._listening = False
        self.setFixedSize(42, 38)
        self.setCursor(Qt.PointingHandCursor)
        self.setText("")

    def set_listening(self, listening: bool):
        self._listening = listening
        self.update()

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(8, 15, 17, 120))
        p.setPen(QPen(QColor(0, 229, 255, 120), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        icon = qta.icon("fa5s.microphone", color=CYAN if self._listening else PRIMARY)
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


class TranscriptPanel(GlassPanel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._view = QTextEdit(self)
        self._view.setReadOnly(True)
        self._view.setStyleSheet(
            "QTextEdit{background:transparent;border:none;"
            f"color:{PRIMARY};font-family:'{FM}';font-size:14px;"
            "line-height:1.6;}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(self._view)

    def add_exchange(self, you, y_time, jarvis="", j_time="", intent="", conf=None):
        self._rows.append((you, y_time, jarvis, j_time, intent, conf))
        self._render()

    def update_last_jarvis(self, text, j_time="", intent="", conf=None):
        if not self._rows:
            return
        you, y_time, _, _, old_intent, old_conf = self._rows[-1]
        self._rows[-1] = (
            you,
            y_time,
            text,
            j_time,
            intent or old_intent,
            conf if conf is not None else old_conf,
        )
        self._render()

    def _render(self):
        lines = []
        for you, y_time, jarvis, j_time, intent, conf in self._rows:
            lines.append(f"[{y_time}] YOU: {you}")
            if jarvis:
                suffix = f" ({intent}, {int(conf * 100)}%)" if intent and conf is not None else ""
                lines.append(f"[{j_time}] JARVIS: {jarvis}{suffix}")
            lines.append("")
        self._view.setPlainText("\n".join(lines))
        self._view.moveCursor(self._view.textCursor().End)


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
    """Single-line QTextEdit with live @tag syntax highlighting.

    Exposes the same surface as QLineEdit so CommandBar callers need
    no changes: text(), setText(), setCursorPosition(), setFocus(), clear().
    """
    returnPressed = pyqtSignal()

    def __init__(self, valid_tags: frozenset = frozenset(), parent=None):
        super().__init__(parent)
        self.setLineWrapMode(QTextEdit.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(0)
        self.setFixedHeight(36)
        self.setPlaceholderText("Awaiting directive...")
        self._highlighter = _TagHighlighter(self.document(), valid_tags)

    # ── QLineEdit-compatible API ──────────────────────────────────────────

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, s: str):
        self.setPlainText(s)
        c = self.textCursor()
        c.movePosition(QTextCursor.End)
        self.setTextCursor(c)

    def setCursorPosition(self, pos: int):
        c = self.textCursor()
        c.setPosition(min(pos, len(self.toPlainText())))
        self.setTextCursor(c)

    # ── Behaviour overrides ───────────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.returnPressed.emit()
            return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source):
        """Strip newlines from pasted content to enforce single-line."""
        self.insertPlainText(
            source.text().replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
        )


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
        self.setGeometry(self.parent().width() - 300, 10, 280, 36)
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._msg = QLabel("Confirm command?")
        self._ok = QPushButton("CONFIRM")
        self._no = QPushButton("CANCEL")
        self._ok.clicked.connect(self.confirmed.emit)
        self._no.clicked.connect(self.cancelled.emit)
        lay.addWidget(self._msg, 1)
        lay.addWidget(self._ok)
        lay.addWidget(self._no)
