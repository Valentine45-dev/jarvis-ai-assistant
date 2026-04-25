"""Top and bottom HUD status bars — reference-faithful (jarvis_main_hud.png)."""

from __future__ import annotations

from datetime import datetime

import psutil
import qtawesome as qta
from PyQt5.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QPen
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStyle, QStyleOption, QWidget

from ui.theme import CYAN, FM, TOPBAR_H, BOTBAR_H


# Topbar height matches the sidebar's brand zone so the two horizontal
# divider lines (topbar bottom-border and sidebar brand bottom-border)
# meet at the same y, producing one continuous line across the screen.
TOPBAR_HEIGHT = 64

# (icon_name, tooltip, attribute_name) — attribute_name is used to expose the
# button as self._btn_<attr> so callers can anchor popovers to its geometry.
_TOPBAR_ICONS = (
    ("ph.sliders-horizontal", "Quick settings",  "settings"),
    ("ph.terminal-window",    "Command palette", "terminal"),
    ("ph.broadcast",          "Wake-word listener", "broadcast"),
)


def _qicon(name: str, color: str):
    """Build a qtawesome icon, swallowing missing-glyph errors."""
    try:
        return qta.icon(name, color=color)
    except Exception:
        return None


def draw_glow_underline(widget: QWidget, painter: QPainter,
                         line_alpha: int = 140, glow_alpha: int = 28,
                         glow_height: int = 8):
    """Draw a 1px cyan line at the widget's bottom edge with a soft upward glow.

    Mirrors the reference HTML's
    `border-b border-cyan-500/30 shadow-[0_1px_10px_rgba(0,229,255,0.1)]`.
    QSS can't render that shadow, so we paint it manually.
    """
    w, h = widget.width(), widget.height()
    # Glow halo: gradient from transparent (top) to soft cyan (bottom).
    grad = QLinearGradient(0, h - glow_height, 0, h)
    grad.setColorAt(0.0, QColor(0, 229, 255, 0))
    grad.setColorAt(1.0, QColor(0, 229, 255, glow_alpha))
    painter.fillRect(0, h - glow_height, w, glow_height, grad)
    # Sharp 1px line at the bottom edge.
    painter.setPen(QPen(QColor(0, 229, 255, line_alpha), 1))
    painter.drawLine(0, h - 1, w, h - 1)


def draw_glow_right_edge(widget: QWidget, painter: QPainter,
                          line_alpha: int = 140, glow_alpha: int = 28,
                          glow_width: int = 8):
    """Draw a 1px cyan line on the widget's right edge with a soft leftward
    glow. Vertical sibling of `draw_glow_underline` — same colors and falloff
    so the two read as one continuous glowing border."""
    w, h = widget.width(), widget.height()
    grad = QLinearGradient(w - glow_width, 0, w, 0)
    grad.setColorAt(0.0, QColor(0, 229, 255, 0))
    grad.setColorAt(1.0, QColor(0, 229, 255, glow_alpha))
    painter.fillRect(w - glow_width, 0, glow_width, h, grad)
    painter.setPen(QPen(QColor(0, 229, 255, line_alpha), 1))
    painter.drawLine(w - 1, 0, w - 1, h)


class TopBar(QWidget):
    # Per-icon signals — main.py wires these to popovers / palettes.
    settings_clicked  = pyqtSignal()
    terminal_clicked  = pyqtSignal()
    broadcast_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(TOPBAR_HEIGHT)
        # Background only; the glowing bottom line is drawn in paintEvent
        # because QSS can't reproduce the soft cyan halo from the reference.
        self.setStyleSheet("background:rgba(8,15,17,0.85);")
        self._view_name = "Dashboard"
        # Icon buttons are stored as attributes so callers can read their
        # global geometry (mapToGlobal) when anchoring popovers.
        self._btn_settings:  QPushButton | None = None
        self._btn_terminal:  QPushButton | None = None
        self._btn_broadcast: QPushButton | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 0, 18, 0)
        lay.setSpacing(0)

        # ── Brand: HUD_STATUS_V4.2 (transparent — header background reads through) ──
        self._brand = QLabel("HUD_STATUS_V4.2")
        self._brand.setStyleSheet(
            "QLabel{"
            f"color:{CYAN};"
            f"font-family:'{FM}';"
            "font-size:13px;"
            "font-weight:700;"
            "letter-spacing:3px;"
            "background:transparent;"
            "border:none;"
            "padding:6px 0;"
            "}"
        )
        lay.addWidget(self._brand)
        lay.addStretch(1)

        # ── Center: CPU / MEM / UPTIME with generous gaps ──
        stats_wrap = QWidget()
        stats_wrap.setStyleSheet("background:transparent;")
        stats_lay = QHBoxLayout(stats_wrap)
        stats_lay.setContentsMargins(0, 0, 0, 0)
        stats_lay.setSpacing(36)   # gap between each stat label

        self._cpu = QLabel("CPU: 14%")
        self._mem = QLabel("MEM: 32GB")
        self._uptime = QLabel("UPTIME: 72:12:04")
        for w in (self._cpu, self._mem, self._uptime):
            w.setStyleSheet(
                "QLabel{"
                "color:rgba(186,201,204,0.55);"
                f"font-family:'{FM}';"
                "font-size:11px;"
                "font-weight:700;"
                "letter-spacing:2px;"
                "background:transparent;"
                "}"
            )
            stats_lay.addWidget(w)
        lay.addWidget(stats_wrap)

        lay.addStretch(1)

        # ── Right: trailing icons (Phosphor, matches sidebar style) ──
        icons_wrap = QWidget()
        icons_wrap.setStyleSheet("background:transparent;")
        icons_lay = QHBoxLayout(icons_wrap)
        icons_lay.setContentsMargins(0, 0, 0, 0)
        icons_lay.setSpacing(8)

        # Map attribute name → outbound signal so each button has a
        # purpose-built emitter without a chain of if/elif inside the loop.
        signal_for = {
            "settings":  self.settings_clicked,
            "terminal":  self.terminal_clicked,
            "broadcast": self.broadcast_clicked,
        }

        for name, tip, attr in _TOPBAR_ICONS:
            btn = QPushButton()
            btn.setFixedSize(42, 42)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tip)
            icon = _qicon(name, CYAN)
            if icon is not None:
                btn.setIcon(icon)
                btn.setIconSize(QSize(22, 22))
            btn.setStyleSheet(
                "QPushButton{"
                "background:transparent;"
                "border:none;"
                "border-radius:4px;"
                "}"
                "QPushButton:hover{background:rgba(0,229,255,0.12);}"
            )
            sig = signal_for.get(attr)
            if sig is not None:
                btn.clicked.connect(sig.emit)
            setattr(self, f"_btn_{attr}", btn)
            icons_lay.addWidget(btn)
        lay.addWidget(icons_wrap)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    def set_view(self, name):
        self._view_name = name

    def set_cpu(self, pct: int):
        """Receive CPU % from _CpuCard's signal so both displays stay in sync."""
        self._cpu.setText(f"CPU: {pct}%")

    def icon_button(self, name: str) -> QPushButton | None:
        """Look up a top-right icon button by name (settings|terminal|broadcast).

        Returned button can be used by callers to anchor popovers via
        button.mapToGlobal(QPoint(0, button.height())).
        """
        return getattr(self, f"_btn_{name}", None)

    def _tick(self):
        try:
            mem = int(psutil.virtual_memory().total / (1024 ** 3))
            self._mem.setText(f"MEM: {mem}GB")
        except Exception:
            pass
        self._uptime.setText(f"UPTIME: {datetime.now().strftime('%H:%M:%S')}")

    def paintEvent(self, event):
        # Draw the QSS background (the rgba fill) first, then layer the
        # glowing cyan underline on top.
        opt = QStyleOption()
        opt.initFrom(self)
        p = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, p, self)
        p.setRenderHint(QPainter.Antialiasing, False)
        draw_glow_underline(self, p)


class BottomBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(BOTBAR_H)
        self._view = "DASHBOARD"
        self._cmd_count = 0

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(10)

        self._status = QLabel("SYSTEM ONLINE")
        self._status.setStyleSheet(
            "QLabel{"
            "color:rgba(131,251,165,0.95);"
            f"font-family:'{FM}';"
            "font-size:10px;"
            "font-weight:700;"
            "letter-spacing:1px;"
            "background:transparent;"
            "}"
        )
        lay.addWidget(self._status)
        lay.addStretch(1)

        self._cmd_lbl = QLabel("0 COMMANDS")
        self._cmd_lbl.setStyleSheet(
            "QLabel{"
            "color:rgba(195,245,255,0.85);"
            f"font-family:'{FM}';"
            "font-size:10px;"
            "font-weight:700;"
            "letter-spacing:1px;"
            "background:transparent;"
            "}"
        )
        lay.addWidget(self._cmd_lbl)

        self._view_lbl = QLabel("DASHBOARD")
        self._view_lbl.setStyleSheet(
            "QLabel{"
            "color:rgba(132,147,150,0.9);"
            f"font-family:'{FM}';"
            "font-size:10px;"
            "font-weight:700;"
            "letter-spacing:1px;"
            "background:transparent;"
            "padding-left:18px;"
            "}"
        )
        lay.addWidget(self._view_lbl)

    def set_view(self, v):
        self._view = str(v).upper()
        self._view_lbl.setText(self._view)

    def increment_commands(self):
        self._cmd_count += 1
        self._cmd_lbl.setText(f"{self._cmd_count} COMMANDS")

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(7, 16, 18, 240))
        p.setPen(QPen(QColor(0, 229, 255, 46), 1))
        p.drawLine(0, 0, self.width(), 0)
