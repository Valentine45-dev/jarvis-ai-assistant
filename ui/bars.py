"""Top and bottom HUD status bars — reference-faithful (jarvis_main_hud.png)."""

from __future__ import annotations

import re
import socket
import subprocess
import sys
from datetime import datetime

import psutil
import qtawesome as qta
from PyQt5.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen
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


def _subprocess_kw() -> dict:
    """Windows: hide console window for status probes."""
    if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _battery_state() -> tuple[int | None, bool]:
    """Return (percent 0–100, power_plugged) or (None, False) if no battery sensor."""
    try:
        bat = psutil.sensors_battery()
    except Exception:
        return None, False
    if bat is None:
        return None, False
    pct = bat.percent
    if pct is None:
        return None, False
    return int(round(float(pct))), bool(bat.power_plugged)


def _wifi_data_connected() -> bool:
    """True when a wireless-like interface is up with a routable IPv4, or Windows Wi‑Fi reports connected."""
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    keywords = (
        "wi-fi",
        "wi fi",
        "wlan",
        "wireless",
        "802.11",
        "wifi",
        "wlp",
        "wlo",
        "wlx",
    )
    for name, st in stats.items():
        if not st.isup:
            continue
        nl = name.lower()
        if not any(k in nl for k in keywords):
            continue
        for snic in addrs.get(name, []):
            if snic.family != socket.AF_INET or not snic.address:
                continue
            a = str(snic.address)
            if a.startswith("127."):
                continue
            if a.startswith("169.254."):
                continue
            return True

    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True,
                text=True,
                timeout=2.5,
                **_subprocess_kw(),
            )
            s = r.stdout or ""
            if re.search(r"State\s*:\s*connected", s, re.IGNORECASE):
                return True
        except Exception:
            pass
    return False


class _BatteryGlyph(QWidget):
    """Phone-style battery outline, terminal nub, and left-to-right fill."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pct = 100
        self._plugged = False
        self.setFixedSize(32, 16)

    def set_state(self, pct: int, plugged: bool) -> None:
        self._pct = max(0, min(100, int(pct)))
        self._plugged = bool(plugged)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        body = QRectF(1.0, 2.0, 22.0, h - 4.0)
        nub = QRectF(body.right() + 0.5, h / 2.0 - 2.0, 2.0, 4.0)

        low = self._pct < 20
        if low:
            fill = QColor(255, 149, 60)
        elif self._plugged:
            fill = QColor(0x83, 0xFB, 0xA5)
        else:
            fill = QColor(CYAN)

        border = QColor(255, 255, 255, 200)
        p.setPen(QPen(border, 1.1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(body, 2.2, 2.2)
        p.setPen(Qt.NoPen)
        p.setBrush(border)
        p.drawRoundedRect(nub, 0.5, 0.5)

        inner = body.adjusted(2.0, 2.0, -2.0, -2.0)
        fill_w = max(0.0, inner.width() * (self._pct / 100.0))
        if fill_w > 0.5:
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(fill))
            p.drawRoundedRect(QRectF(inner.left(), inner.top(), fill_w, inner.height()), 0.8, 0.8)

        if self._plugged:
            cx = body.center().x()
            t = body.top() - 2.2
            bolt = QPainterPath()
            bolt.moveTo(cx - 0.4, t)
            bolt.lineTo(cx + 2.2, t + 2.4)
            bolt.lineTo(cx + 0.35, t + 2.4)
            bolt.lineTo(cx + 1.9, t + 7.2)
            bolt.lineTo(cx - 1.3, t + 3.6)
            bolt.lineTo(cx + 0.9, t + 3.6)
            bolt.closeSubpath()
            p.setPen(QPen(QColor(255, 255, 255, 230), 0.35))
            p.setBrush(QColor(255, 255, 255, 252))
            p.drawPath(bolt)


class _BatteryStatusBlock(QWidget):
    """Glyph + percentage, hidden when `sensors_battery` is unavailable (e.g. some desktops)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._glyph = _BatteryGlyph()
        self._label = QLabel("—%")
        self._label.setStyleSheet(
            f"QLabel{{color:{CYAN};"
            f"font-family:'{FM}';"
            "font-size:11px;font-weight:700;letter-spacing:0px;"
            "background:transparent;}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self._glyph, 0, Qt.AlignVCenter)
        lay.addWidget(self._label, 0, Qt.AlignVCenter)
        self.setVisible(False)

    def set_state(self, pct: int | None, plugged: bool) -> None:
        if pct is None:
            self.setVisible(False)
            return
        self.setVisible(True)
        self._glyph.set_state(pct, plugged)
        self._label.setText(f"{pct}%")


class _WifiIcon(QWidget):
    """Wi‑Fi arcs + dot; matches cyan HUD. Visibility controlled by parent."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 16)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        c = QColor(CYAN)
        p.setPen(QPen(c, 1.15, Qt.SolidLine, Qt.FlatCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        cx = self.width() / 2.0
        base_y = float(self.height() - 1.0)
        for r in (8.0, 5.5, 3.0):
            rect = QRectF(cx - r, base_y - 2.0 * r, 2.0 * r, 2.0 * r)
            p.drawArc(rect, 30 * 16, 120 * 16)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QPointF(cx, base_y - 0.5), 1.4, 1.4)


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

        self._wifi = _WifiIcon()
        self._wifi.setToolTip("Wi‑Fi: connected")
        self._wifi.setVisible(False)
        stats_lay.addWidget(self._wifi, 0, Qt.AlignVCenter)

        self._battery = _BatteryStatusBlock()
        self._battery.setToolTip("Battery (system sensor)")
        stats_lay.addWidget(self._battery, 0, Qt.AlignVCenter)
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

        try:
            b_pct, b_plug = _battery_state()
            self._battery.set_state(b_pct, b_plug)
        except Exception:
            self._battery.set_state(None, False)

        try:
            has_wifi = _wifi_data_connected()
            self._wifi.setVisible(has_wifi)
            self._wifi.setToolTip("Wi‑Fi: connected" if has_wifi else "")
        except Exception:
            self._wifi.setVisible(False)

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
