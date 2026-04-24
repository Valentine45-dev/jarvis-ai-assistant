"""DashboardView — Screen 1 (jarvis_main_hud.png), reference-faithful rebuild.

Mirrors the canonical jarvis_main_hud.py structure (SysLogPanel, CenterPanel,
RightTelemetryPanel, CommandBar) while exposing the attribute surface that
main.py relies on:

    view.left.{mic, cmd_bar, command_sent, transcript, hud_status, last_action,
               typing, confirm_bar, waveform, orb, status_lbl, state_pill}
    view.right.{cpu_val, sparkline, mem_card.val, mem_card.set_bar,
                uptime_card.val, uptime_card.set_bar, gauge, conf_label,
                greeting, command_requested}
    view.toast.show_toast(text, kind)
"""

from __future__ import annotations

import psutil
from PyQt5.QtCore import QEasingCurve, QObject, QPropertyAnimation, QTimer, Qt, pyqtProperty, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPen, QRadialGradient
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.brain import TAG_INTENT_MAP
from ui.theme import BG, CYAN, FM
from ui.widgets import (
    ArcReactorWidget,
    CommandBar as _MainCommandBar,
    ConfidenceGauge,
    ConfirmationBar,
    GlassPanel,
    GreetingCard,
    HudStatusLabel,
    LastActionStrip,
    LineChartWidget,
    MicButton,
    SegmentedBar,
    StatusPip,
    ToastNotification,
    TranscriptPanel,
    TypingIndicator,
    WaveformStrip,
)


# ─── reference color tokens (kept local so the module reads like the reference) ──
SURFACE_LOW = "#151d1e"
SURFACE = "#192122"
OUTLINE = "#849396"
OUTLINE_VAR = "#3b494c"
ON_SURFACE = "#dce4e5"
ON_SURFACE_VAR = "#bac9cc"
GOLD = "#ffe16d"
GOLD_DIM = "#e9c400"
EMERALD = "#83fba5"
EMERALD_DIM = "#66dd8b"


def _mono(size: int, bold: bool = False) -> QFont:
    f = QFont(FM, size)
    f.setBold(bold)
    return f


STATES = {
    "idle": ("STANDBY", "#ffe16d"),
    "listening": ("LISTENING", "#00e5ff"),
    "thinking": ("PROCESSING", "#00e5ff"),
    "speaking": ("RESPONDING", "#83fba5"),
    "error": ("SYS ERROR", "#ffb4ab"),
    "wake": ("WAKE DETECTED", "#00e5ff"),
}


class StateLabel(QWidget):
    """Animated reactor-state label rendered below the orb."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "idle"
        self._text = STATES["idle"][0]
        self._color = QColor(STATES["idle"][1])
        self._pulse_opacity = 1.0
        self._font = _mono(9, bold=True)
        self.setFixedHeight(28)

        self._pulse_anim = QPropertyAnimation(self, b"pulse_opacity", self)
        self._pulse_anim.setStartValue(0.4)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.setEasingCurve(QEasingCurve.InOutSine)

        self.set_state("idle")

    def get_pulse_opacity(self) -> float:
        return self._pulse_opacity

    def set_pulse_opacity(self, value: float):
        self._pulse_opacity = max(0.0, min(1.0, float(value)))
        self.update()

    pulse_opacity = pyqtProperty(float, fget=get_pulse_opacity, fset=set_pulse_opacity)

    def set_state(self, state: str):
        normalized = str(state).strip().lower()
        if normalized not in STATES:
            normalized = "idle"
        self._state = normalized
        text, color_hex = STATES[normalized]
        self._text = text
        self._color = QColor(color_hex)

        metrics = QFontMetrics(self._font)
        self.setFixedWidth(max(150, metrics.horizontalAdvance(self._text) + 40))

        self._pulse_anim.stop()
        if normalized in ("listening", "thinking"):
            self._pulse_anim.setDuration(600)
            self._pulse_anim.start()
        elif normalized == "error":
            self._pulse_anim.setDuration(300)
            self._pulse_anim.start()
        else:
            self._pulse_opacity = 1.0

        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        r = self.rect().adjusted(0, 0, -1, -1)

        border = QColor(self._color)
        border.setAlpha(int(255 * self._pulse_opacity))
        fill = QColor(self._color)
        fill.setAlpha(int(30 * self._pulse_opacity))
        text = QColor(self._color)
        text.setAlpha(245)

        p.fillRect(r, fill)
        p.setPen(QPen(border, 1))
        p.drawRect(r)

        f = QFont(self._font)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        p.setFont(f)
        p.setPen(text)
        p.drawText(r, Qt.AlignCenter, self._text)


# ─────────────────────────────────────────────────────────────────────────────
# LEFT: SYS_LOG_BUFFER
# ─────────────────────────────────────────────────────────────────────────────


class _SysLogPanel(GlassPanel):
    """Boot-log style panel; hosts a TranscriptPanel for live exchanges."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Reference panel is visually solid; prevent background grid bleed-through.
        self.set_fill_color(QColor(10, 17, 19, 236))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(32)
        header.setStyleSheet("background:transparent;")
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(14, 0, 14, 0)
        title = QLabel("SYS_LOG_BUFFER")
        title.setFont(_mono(9, bold=True))
        title.setStyleSheet(
            f"color:{CYAN};letter-spacing:3px;background:transparent;border:none;"
        )
        self._pip = StatusPip("active")
        hlay.addWidget(title)
        hlay.addStretch(1)
        hlay.addWidget(self._pip)
        outer.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{OUTLINE_VAR};background:{OUTLINE_VAR};")
        sep.setFixedHeight(1)
        outer.addWidget(sep)

        # Transcript lives here. Strip its own chrome because the outer
        # GlassPanel already provides the border + brackets.
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        blay = QVBoxLayout(body)
        blay.setContentsMargins(12, 10, 12, 12)
        blay.setSpacing(0)
        self.transcript = TranscriptPanel()
        self.transcript.set_show_brackets(False)
        self.transcript.set_fill(False)
        self.transcript._view.setStyleSheet(
            "QTextEdit{"
            "background:transparent;"
            "border:none;"
            f"color:{ON_SURFACE};"
            f"font-family:'{FM}';"
            "font-size:14px;"
            "line-height:1.6;"
            "}"
        )
        self.transcript._view.setPlainText(
            "[14:02:44] INITIALIZING SEQUENCE...\n"
            "[14:02:44] LOADING KERNEL MODULES [OK]\n"
            "[14:02:45] MOUNTING VFS...       [OK]\n"
            "[14:02:46] ESTABLISHING UPLINK... [OK]\n"
            "[14:02:47] SYNCING TELEMETRY...\n"
            "\n"
            "> GET /api/v1/core/status\n"
            "{\n"
            "  \"status\": \"OPERATIONAL\",\n"
            "  \"temperature\": 42.4,\n"
            "  \"load\": [0.14, 0.22, 0.18],\n"
            "  \"power_draw\": \"1.21 GW\",\n"
            "  \"threat_level\": \"ALPHA_ZERO\"\n"
            "}\n"
            "\n"
            "> AWAITING DIRECTIVE...\n"
            "▌"
        )
        blay.addWidget(self.transcript, 1)
        outer.addWidget(body, 1)


# ─────────────────────────────────────────────────────────────────────────────
# CENTER: ARC REACTOR + CORE_ONLINE
# ─────────────────────────────────────────────────────────────────────────────


class _CenterPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(0)

        cluster = QWidget()
        cluster_lay = QVBoxLayout(cluster)
        cluster_lay.setContentsMargins(0, 0, 0, 0)
        cluster_lay.setSpacing(8)
        cluster_lay.setAlignment(Qt.AlignHCenter)

        self.reactor = ArcReactorWidget()
        self.reactor.setMinimumSize(300, 300)
        self.reactor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cluster_lay.addWidget(self.reactor, 0, Qt.AlignCenter)

        self.core_label = StateLabel()
        self.reactor.state_changed.connect(self.core_label.set_state)
        self.core_label.set_state("idle")
        cluster_lay.addWidget(self.core_label, 0, Qt.AlignCenter)

        lay.addStretch(1)
        lay.addWidget(cluster, 0, Qt.AlignCenter)
        lay.addStretch(1)


# ─────────────────────────────────────────────────────────────────────────────
# RIGHT: TELEMETRY CARDS
# ─────────────────────────────────────────────────────────────────────────────


class _TelemetryCard(GlassPanel):
    """Glass-bordered card with a header row (title + value)."""

    def __init__(self, title: str, value: str, value_color: str = CYAN, parent=None):
        super().__init__(parent)
        # Right-side cards should read as solid glass blocks, not transparent.
        self.set_fill_color(QColor(10, 17, 19, 236))
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(12, 10, 12, 10)
        self._lay.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        t = QLabel(title)
        t.setFont(_mono(8, bold=True))
        t.setStyleSheet(
            f"color:{ON_SURFACE_VAR};letter-spacing:2px;background:transparent;border:none;"
        )
        self.val = QLabel(value)
        self.val.setFont(_mono(12))
        self.val.setStyleSheet(
            f"color:{value_color};letter-spacing:2px;background:transparent;border:none;"
        )
        head.addWidget(t)
        head.addStretch(1)
        head.addWidget(self.val)
        self._lay.addLayout(head)

    def add_widget(self, w: QWidget):
        self._lay.addWidget(w)

    def add_stretch(self):
        self._lay.addStretch(1)

    def add_layout(self, l):
        self._lay.addLayout(l)


class _CpuCard(_TelemetryCard):
    cpu_updated = pyqtSignal(int)   # emits integer % after each poll

    def __init__(self, parent=None):
        super().__init__("CPU_USAGE", "0%", CYAN, parent)

        self._history = [0.0] * 28

        self._chart = LineChartWidget()
        self._chart.setFixedHeight(70)
        self._chart.set_threshold(75.0)
        self._chart.set_data(self._history)
        self.add_widget(self._chart)

        self.add_stretch()
        self._bar = SegmentedBar(segments=8, value=0.0, color=CYAN)
        self._bar.setFixedHeight(12)
        self.add_widget(self._bar)

        # Prime psutil's delta calculator, then stream real CPU usage.
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_cpu)
        self._timer.start(1000)
        self._poll_cpu()

    def _poll_cpu(self):
        try:
            usage = float(psutil.cpu_percent(interval=None))
        except Exception:
            usage = self._history[-1] if self._history else 0.0
        self._push_sample(usage)

    def _push_sample(self, usage: float):
        usage = max(0.0, min(100.0, float(usage)))
        self._history.append(usage)
        if len(self._history) > 40:
            self._history = self._history[-40:]
        pct = int(round(usage))
        self.val.setText(f"{pct}%")
        self._bar.set_value(usage / 100.0)
        self._chart.set_data(self._history)
        self.cpu_updated.emit(pct)

    def set_series(self, values):
        """Compatibility helper for external CPU history feeds."""
        seq = [max(0.0, min(100.0, float(v))) for v in values] if values else []
        if not seq:
            return
        self._history = seq[-40:]
        latest = self._history[-1]
        self.val.setText(f"{int(round(latest))}%")
        self._bar.set_value(latest / 100.0)
        self._chart.set_data(self._history)

    def set_bar(self, pct: float):
        # Preserve old contract while keeping chart + label in sync.
        self._push_sample(pct)


class _MemCard(_TelemetryCard):
    def __init__(self, parent=None):
        super().__init__("MEM_ALLOC", "-- GB", CYAN, parent)

        self._pct_lbl = QLabel("0%")
        self._pct_lbl.setFont(_mono(22))
        self._pct_lbl.setAlignment(Qt.AlignCenter)
        self._pct_lbl.setStyleSheet(
            f"color:{CYAN};letter-spacing:2px;background:transparent;border:none;"
        )
        self.add_widget(self._pct_lbl)

        self._detail_lbl = QLabel("-- / -- GB")
        self._detail_lbl.setFont(_mono(9))
        self._detail_lbl.setAlignment(Qt.AlignCenter)
        self._detail_lbl.setStyleSheet(
            "color:rgba(132,147,150,0.65);background:transparent;border:none;"
        )
        self.add_widget(self._detail_lbl)

        self.add_stretch()
        self._bar = SegmentedBar(segments=8, value=0.0, color=CYAN)
        self._bar.setFixedHeight(12)
        self.add_widget(self._bar)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_mem)
        self._timer.start(2000)
        self._poll_mem()

    def _poll_mem(self):
        try:
            mem = psutil.virtual_memory()
            used_gb = mem.used / (1024 ** 3)
            total_gb = mem.total / (1024 ** 3)
            pct = mem.percent
            self.val.setText(f"{used_gb:.1f} GB")
            self._pct_lbl.setText(f"{int(pct)}%")
            self._detail_lbl.setText(f"{used_gb:.1f} / {total_gb:.1f} GB")
            self._bar.set_value(pct / 100.0)
        except Exception:
            pass

    def set_bar(self, pct: float):
        self._bar.set_value(max(0.0, min(100.0, float(pct))) / 100.0)


class _UplinkCard(_TelemetryCard):
    def __init__(self, parent=None):
        super().__init__("UPLINK_STATUS", "", CYAN, parent)
        # Remove the (empty) right-side value from the header to keep spacing clean.
        self.val.setText("")
        self.val.setMaximumWidth(0)

        txrx = QHBoxLayout()
        txrx.setContentsMargins(0, 0, 0, 0)
        txrx.setSpacing(0)

        tx_col = QVBoxLayout()
        tx_col.setSpacing(2)
        tx_lbl = QLabel("TX (Mb/s)")
        tx_lbl.setFont(_mono(7))
        tx_lbl.setStyleSheet(
            f"color:{OUTLINE};background:transparent;border:none;letter-spacing:1px;"
        )
        self._tx = QLabel("452.1")
        self._tx.setFont(_mono(14))
        self._tx.setStyleSheet(
            f"color:{EMERALD_DIM};letter-spacing:1px;background:transparent;border:none;"
        )
        tx_col.addWidget(tx_lbl)
        tx_col.addWidget(self._tx)

        div = QFrame()
        div.setFrameShape(QFrame.VLine)
        div.setFixedWidth(1)
        div.setStyleSheet(f"color:{OUTLINE_VAR};background:{OUTLINE_VAR};")

        rx_col = QVBoxLayout()
        rx_col.setContentsMargins(12, 0, 0, 0)
        rx_col.setSpacing(2)
        rx_lbl = QLabel("RX (Mb/s)")
        rx_lbl.setFont(_mono(7))
        rx_lbl.setStyleSheet(
            f"color:{OUTLINE};background:transparent;border:none;letter-spacing:1px;"
        )
        self._rx = QLabel("1208.4")
        self._rx.setFont(_mono(14))
        self._rx.setStyleSheet(
            f"color:{EMERALD_DIM};letter-spacing:1px;background:transparent;border:none;"
        )
        rx_col.addWidget(rx_lbl)
        rx_col.addWidget(self._rx)

        txrx.addLayout(tx_col)
        txrx.addWidget(div)
        txrx.addLayout(rx_col)
        txrx.addStretch(1)

        self.add_layout(txrx)
        self.add_stretch()

        self._chart = LineChartWidget()
        self._chart.setFixedHeight(32)
        self._chart.set_data([60, 50, 70, 40, 80, 30, 90, 50, 60, 40])
        self.add_widget(self._chart)

        # Expose the primary uplink value so main.py .val.setText still works.
        self.val = self._tx

    def set_bar(self, _pct: float):
        pass


class _CpuSparklineBridge:
    """Compatibility bridge so main.py's sparkline feed updates the visible CPU chart."""

    def __init__(self, cpu_card: _CpuCard):
        self._cpu_card = cpu_card

    def set_data(self, values):
        self._cpu_card.set_series(values)


class _RightTelemetry(QWidget):
    command_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self._cpu = _CpuCard()
        self.cpu_val = self._cpu.val
        lay.addWidget(self._cpu, 1)

        self.mem_card = _MemCard()
        lay.addWidget(self.mem_card, 1)

        self.uptime_card = _UplinkCard()
        lay.addWidget(self.uptime_card, 1)

        # Hidden compatibility surfaces for main.py.
        self.sparkline = _CpuSparklineBridge(self._cpu)
        self.greeting = GreetingCard()
        self.greeting.setVisible(False)
        lay.addWidget(self.greeting)
        self.gauge = ConfidenceGauge()
        self.gauge.setVisible(False)
        lay.addWidget(self.gauge)
        self.conf_label = QLabel("HIGH")
        self.conf_label.setVisible(False)
        lay.addWidget(self.conf_label)


# ─────────────────────────────────────────────────────────────────────────────
# BOTTOM: COMMAND BAR
#   - Width-constrained, centered input panel (~max 820px wide)
#   - STANDBY badge rendered as a small bordered tab that overlaps the top-left
#     corner of the input panel (its opaque fill masks the input border behind)
#   - Radial cyan bloom painted underneath the panel (mirrors the soft
#     `shadow-[0_0_60px_rgba(0,229,255,0.18)]` glow in the HTML reference)
# ─────────────────────────────────────────────────────────────────────────────


class _InputBlock(QWidget):
    """Width-constrained input card with a bottom cyan bloom."""

    command_sent = pyqtSignal(str)

    INPUT_H = 50
    GLOW_H = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(568)
        self.setMaximumWidth(853)
        self.setFixedHeight(self.INPUT_H + self.GLOW_H)
        self.setStyleSheet("background:transparent;")

        # ── Input card ────────────────────────────────────────────────────
        self.input_card = QWidget(self)
        self.input_card.setStyleSheet(
            "background:rgba(8,15,17,0.92);"
            "border:1px solid rgba(0,229,255,0.45);"
        )

        il = QHBoxLayout(self.input_card)
        il.setContentsMargins(18, 4, 8, 4)
        il.setSpacing(12)

        prompt = QLabel(">_")
        prompt.setFont(_mono(13, bold=True))
        prompt.setStyleSheet(
            "color:rgba(0,229,255,0.85);background:transparent;border:none;"
            "letter-spacing:1px;"
        )
        il.addWidget(prompt)

        # Voice mic button (main.py already connects this to `_toggle_mic`).
        self.mic = MicButton()
        self.mic.setFixedSize(30, 30)
        self.mic.setToolTip("Voice input")
        il.addWidget(self.mic)

        # Inline voice waveform lives with the mic/input cluster.
        self.waveform = WaveformStrip()
        self.waveform.setFixedWidth(86)
        self.waveform.setVisible(False)
        self.waveform.set_active(False)
        il.addWidget(self.waveform)

        # Reuse project CommandBar — pass valid @tag keys for live highlighting.
        self.cmd_bar = _MainCommandBar(frozenset(TAG_INTENT_MAP.keys()))
        self.cmd_bar._input.setPlaceholderText("AWAITING DIRECTIVE...")
        self.cmd_bar._input.setStyleSheet(
            "QTextEdit{"
            "background:transparent;"
            "border:none;"
            f"color:{CYAN};"
            f"font-family:'{FM}';"
            "font-size:13px;"
            "letter-spacing:2px;"
            "}"
        )
        self.cmd_bar._send.setText("↵")
        self.cmd_bar._send.setFixedSize(36, 36)
        self.cmd_bar._send.setStyleSheet(
            "QPushButton{"
            "background:rgba(0,229,255,0.10);"
            "border:1px solid rgba(0,229,255,0.45);"
            f"color:{CYAN};"
            f"font-family:'{FM}';"
            "font-size:14px;"
            "font-weight:700;"
            "}"
            "QPushButton:hover{background:rgba(0,229,255,0.22);}"
        )
        self.cmd_bar.command_sent.connect(self.command_sent.emit)
        il.addWidget(self.cmd_bar, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.input_card.setGeometry(0, 0, self.width(), self.INPUT_H)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        cx = self.width() / 2.0
        radius = max(self.width() * 0.45, 200.0)

        grad = QRadialGradient(cx, self.INPUT_H, radius)
        grad.setColorAt(0.00, QColor(0, 229, 255, 110))
        grad.setColorAt(0.35, QColor(0, 229, 255, 45))
        grad.setColorAt(1.00, QColor(0, 229, 255, 0))
        p.fillRect(0, self.INPUT_H, self.width(), self.GLOW_H, grad)


class _CommandStrip(QWidget):
    """Outer strip — centers the constrained input block within full width."""

    command_sent = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addStretch(1)
        self._block = _InputBlock(self)
        lay.addWidget(self._block)
        lay.addStretch(1)

        # Strip height = block height; the bloom lives inside the block bounds.
        self.setFixedHeight(self._block.height())

        # Forward block's signal + expose the contracts main.py / LeftColumn use.
        self._block.command_sent.connect(self.command_sent.emit)
        self.mic = self._block.mic
        self.waveform = self._block.waveform
        self.cmd_bar = self._block.cmd_bar


# ─────────────────────────────────────────────────────────────────────────────
# Column wrappers that main.py expects (view.left, view.right)
# ─────────────────────────────────────────────────────────────────────────────


class _TypewriterProxy(QObject):
    """Wraps TranscriptPanel so JARVIS responses type in character-by-character.

    Delegates every attribute except add_exchange() and update_last_jarvis() to the real panel,
    so main.py and widgets interact with it identically to a bare TranscriptPanel.
    """

    _INTERVAL_MS = 25
    _THINKING_INTERVAL_MS = 500

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self._panel = panel
        self._timer = QTimer(self)
        self._timer.setInterval(self._INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._pending = None  # (full_text, j_time, intent, conf)
        self._pos = 0
        self._thinking_timer = QTimer(self)
        self._thinking_timer.setInterval(self._THINKING_INTERVAL_MS)
        self._thinking_timer.timeout.connect(self._tick_thinking)
        self._thinking_dots = 1

    def __getattr__(self, name):
        if "_panel" not in self.__dict__:
            raise AttributeError(name)
        return getattr(self._panel, name)

    def add_exchange(self, you, time="", jarvis="", j_time="", intent="", conf=None):
        self._stop_thinking()
        self._timer.stop()
        self._pending = None

        # History/mock entries already have a JARVIS response; render them unchanged.
        if jarvis:
            self._panel.add_exchange(you, time, jarvis, j_time, intent, conf)
            return

        self._thinking_dots = 1
        self._panel.add_exchange(you, time, self._thinking_text(), "", None, None)
        self._thinking_timer.start()

    def update_last_jarvis(self, text, j_time="", intent="", conf=None):
        self._stop_thinking()
        self._timer.stop()
        if not text:
            self._panel.update_last_jarvis(text, j_time, intent, conf)
            return
        self._pending = (text, j_time, intent, conf)
        self._pos = 0
        # Seed the row with empty text and no suffix so _render() has a slot to update.
        self._panel.update_last_jarvis("", j_time, None, None)
        self._timer.start()

    def _tick(self):
        if not self._pending:
            self._timer.stop()
            return
        full_text, j_time, intent, conf = self._pending
        self._pos += 1
        if self._pos >= len(full_text):
            self._timer.stop()
            self._pending = None
            # Final call: full text + real intent/conf so the suffix appears.
            self._panel.update_last_jarvis(full_text, j_time, intent, conf)
        else:
            # Partial text, no suffix (None suppresses the " (intent, X%)" line).
            self._panel.update_last_jarvis(full_text[: self._pos], j_time, None, None)

    def _thinking_text(self):
        return f"Thinking{'.' * self._thinking_dots}"

    def _tick_thinking(self):
        self._thinking_dots = 1 if self._thinking_dots >= 3 else self._thinking_dots + 1
        self._panel.update_last_jarvis(self._thinking_text(), "", None, None)

    def _stop_thinking(self):
        if self._thinking_timer.isActive():
            self._thinking_timer.stop()


class LeftColumn(QWidget):
    """Logical aggregator: exposes left/center widgets + shared command strip."""

    command_sent = pyqtSignal(str)

    def __init__(self, center: _CenterPanel, log: _SysLogPanel, strip: _CommandStrip, parent=None):
        super().__init__(parent)
        self._center = center
        self._log = log
        self._strip = strip

        # Bindings to the real widgets (no layout here — DashboardView owns it).
        self.transcript = _TypewriterProxy(log.transcript, parent=log.transcript)
        self.orb = center.reactor

        strip.command_sent.connect(self.command_sent.emit)
        self.mic = strip.mic
        self.waveform = strip.waveform
        self.cmd_bar = strip.cmd_bar

        # Hidden compat widgets (parented to self so they're still in the tree).
        self.hud_status = HudStatusLabel(self)
        self.hud_status.setVisible(False)
        self.status_lbl = QLabel("Awaiting directive...", self)
        self.status_lbl.setVisible(False)
        self.state_pill = QLabel("IDLE", self)
        self.state_pill.setVisible(False)
        self.last_action = LastActionStrip(self)
        self.last_action.setVisible(False)
        self.typing = TypingIndicator(self)
        self.typing.setVisible(False)
        self.confirm_bar = ConfirmationBar(self)
        self.confirm_bar.setVisible(False)


class RightColumn(_RightTelemetry):
    """Alias for main.py access (`view.right.*`)."""


# ─────────────────────────────────────────────────────────────────────────────
# Root view — mirrors reference JarvisMainHUD content layout
# ─────────────────────────────────────────────────────────────────────────────


class DashboardView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{BG};")

        content_lay = QVBoxLayout(self)
        content_lay.setContentsMargins(24, 20, 24, 0)
        content_lay.setSpacing(16)

        # Three-column main area
        cols = QHBoxLayout()
        cols.setSpacing(16)

        log_panel = _SysLogPanel()
        log_panel.setFixedWidth(340)
        log_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        cols.addWidget(log_panel)

        center = _CenterPanel()
        center.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cols.addWidget(center, 1)

        self.right = RightColumn()
        self.right.setFixedWidth(260)
        self.right.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        cols.addWidget(self.right)

        content_lay.addLayout(cols, 1)

        # Command strip
        strip = _CommandStrip()
        content_lay.addWidget(strip)

        # Build left-column aggregator (no layout of its own)
        self.left = LeftColumn(center, log_panel, strip, parent=self)

        self.toast = ToastNotification(self)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)

        # Base canvas.
        p.fillRect(self.rect(), QColor(13, 21, 22, 255))

        # Large ambient cyan radial bloom behind the reactor zone.
        cx = self.width() * 0.52
        cy = self.height() * 0.56
        grad = QRadialGradient(cx, cy, max(self.width(), self.height()) * 0.58)
        grad.setColorAt(0.00, QColor(0, 229, 255, 36))
        grad.setColorAt(0.38, QColor(0, 229, 255, 14))
        grad.setColorAt(1.00, QColor(0, 229, 255, 0))
        p.fillRect(self.rect(), QBrush(grad))

        # Modern dotted texture (replaces hard grid lines).
        # Use 2x2 dots with stronger alpha so they remain visible at runtime.
        dot_step = 18
        for y in range(0, self.height() + dot_step, dot_step):
            x_offset = (dot_step // 2) if ((y // dot_step) % 2) else 0
            for x in range(-x_offset, self.width() + dot_step, dot_step):
                # Slight center emphasis so dots blend naturally with the glow.
                dx = abs(x - cx) / max(self.width(), 1)
                dy = abs(y - cy) / max(self.height(), 1)
                fade = min(1.0, (dx + dy) * 0.9)
                alpha = int(40 - (fade * 18))
                p.fillRect(int(x), int(y), 2, 2, QColor(0, 229, 255, max(16, alpha)))

        # Slight vertical vignetting, darkest at edges, to keep focus center.
        vignette = QRadialGradient(self.width() * 0.5, self.height() * 0.55, self.width() * 0.95)
        vignette.setColorAt(0.65, QColor(13, 21, 22, 0))
        vignette.setColorAt(1.00, QColor(13, 21, 22, 120))
        p.fillRect(self.rect(), QBrush(vignette))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.toast._reposition()
