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
from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt, pyqtProperty, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap, QRadialGradient
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.brain import TAG_INTENT_MAP
from ui.components.typewriter import _TypewriterProxy
from ui.theme import ACCENT_RGB, BG, CYAN, FM, TEXT_MUTED
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
    _mono,
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


STATES = {
    "idle": ("STANDBY", "#00e5ff"),
    "listening": ("LISTENING", "#00e5ff"),
    "thinking": ("PROCESSING", "#00e5ff"),
    "speaking": ("SPEAKING", "#83fba5"),
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
        self.set_fill_color(QColor(10, 12, 12, 236))

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
        # Empty until a real user ↔ JARVIS exchange is added (no fake boot / API log).
        self.transcript._view.setPlainText("")
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
        self.set_fill_color(QColor(10, 12, 12, 236))
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
            f"color:{TEXT_MUTED};background:transparent;border:none;"
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
        self._tx = QLabel("0.00")
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
        self._rx = QLabel("0.00")
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
        self._chart.set_data([0] * 10)
        self.add_widget(self._chart)

        # Expose the primary uplink value so main.py .val.setText still works.
        self.val = self._tx

        # Real throughput sampling via psutil
        self._net_history: list[float] = [0.0] * 10
        try:
            _c = psutil.net_io_counters()
            self._last_sent = _c.bytes_sent
            self._last_recv = _c.bytes_recv
        except Exception:
            self._last_sent = 0
            self._last_recv = 0

        self._net_timer = QTimer(self)
        self._net_timer.timeout.connect(self._tick_net)
        self._net_timer.start(2000)

    def _tick_net(self) -> None:
        try:
            c = psutil.net_io_counters()
            sent = c.bytes_sent
            recv = c.bytes_recv
        except Exception:
            return
        tx_mb = (sent - self._last_sent) / 2 / 1_000_000 * 8  # Mb/s over 2 s
        rx_mb = (recv - self._last_recv) / 2 / 1_000_000 * 8
        self._last_sent = sent
        self._last_recv = recv

        self._tx.setText(f"{tx_mb:.2f}")
        self._rx.setText(f"{rx_mb:.2f}")

        self._net_history = self._net_history[1:] + [tx_mb]
        self._chart.set_data(self._net_history)

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

    # Card height: 70 gives the locked-48 editor + prompt/mic/send chrome
    # comfortable vertical breathing room (was 50, felt squashed at the
    # one-line editor height). The strip's layout slot is intentionally
    # NOT computed from this — see _CommandStrip._SLOT_HEIGHT — so growing
    # this constant makes the input card visually taller without shifting
    # the reactor or right metrics.
    INPUT_H = 70
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
            "background:rgba(8,10,10,0.92);"
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
        # Style both the editor body AND its vertical scrollbar — the scrollbar
        # becomes visible when content overflows the locked one-line height
        # (_TagLineEdit._H_MAX == _H_MIN), so we don't want a stock Windows
        # control showing up next to the cyan/teal HUD aesthetic.
        self.cmd_bar._input.setStyleSheet(
            "QTextEdit{"
            "background:transparent;"
            "border:none;"
            f"color:{CYAN};"
            f"font-family:'{FM}';"
            "font-size:13px;"
            "letter-spacing:2px;"
            "}"
            "QScrollBar:vertical{"
            "background:transparent;"
            "width:6px;"
            "margin:0;"
            "}"
            "QScrollBar::handle:vertical{"
            "background:rgba(0,229,255,0.45);"
            "min-height:14px;"
            "border-radius:3px;"
            "}"
            "QScrollBar::handle:vertical:hover{background:rgba(0,229,255,0.75);}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}"
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
        self.cmd_bar._input.setToolTip("Enter — send\nShift+Enter — new line")
        self.cmd_bar._input.contentHeightChanged.connect(self._on_input_editor_height)

    def _on_input_editor_height(self, editor_h: int):
        """Expand or shrink the input card when the directive field line count changes.

        Strip-overlay model (F-? UX fix): the block changes its OWN height but
        does NOT push the parent strip height anymore — the strip stays at a
        fixed minimum slot so the central reactor + right metrics never shift
        upward when the user types a multi-line command. The block grows
        UPWARD via reposition (`_CommandStrip._reposition_block`), keeping
        its bottom edge anchored to the strip's bottom.
        """
        # Match _TagLineEdit._H_MAX (~108) + row padding; do not let the card exceed ~160px
        # before the editor itself scrolls (see widgets._TagLineEdit).
        need = max(50, min(int(editor_h) + 14, 160))
        if need == self.INPUT_H:
            return
        self.INPUT_H = need
        self.setFixedHeight(self.INPUT_H + self.GLOW_H)
        self.input_card.setGeometry(0, 0, self.width(), self.INPUT_H)
        self.update()
        # Trigger the parent strip's reposition so the block's bottom stays
        # anchored to the strip's bottom and the extra height extends UPWARD
        # into the central area (no layout shift on cols / right panels).
        p = self.parent()
        if p is not None and hasattr(p, "_reposition_block"):
            p._reposition_block()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.input_card.setGeometry(0, 0, self.width(), self.INPUT_H)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        cx = self.width() / 2.0
        radius = max(self.width() * 0.45, 200.0)

        grad = QRadialGradient(cx, self.INPUT_H, radius)
        grad.setColorAt(0.00, QColor(*ACCENT_RGB, 110))
        grad.setColorAt(0.35, QColor(*ACCENT_RGB, 45))
        grad.setColorAt(1.00, QColor(*ACCENT_RGB, 0))
        p.fillRect(0, self.INPUT_H, self.width(), self.GLOW_H, grad)


class _CommandStrip(QWidget):
    """Outer strip — bottom layout slot for the input bar.

    Architecture (overlay model):
        The strip itself is a FIXED-HEIGHT slot in DashboardView's vertical
        layout — it never grows. The actual _InputBlock is a manually-
        positioned child of the strip, anchored bottom-center. When the
        block expands vertically (multi-line input), it grows UPWARD by
        moving its top edge into negative-y coordinates relative to the
        strip — Qt doesn't clip children to parent bounds by default, so
        the visual block extends above the strip's top.

        Net effect: the central reactor + right metrics never shift when
        the input grows, because the strip's layout-reported size stays
        constant. The expanding input simply overlaps the empty space
        above the strip — at worst clipping into the lower edge of the
        reactor's bloom, which is invisible cyan anyway.
    """

    command_sent = pyqtSignal(str)

    # Reserved height in the QVBoxLayout. Sized to fit the full collapsed
    # block (INPUT_H + GLOW_H) so the block never overflows upward into
    # cols — that overflow was visibly clipping the input's top edge.
    # Net effect: the strip is ~20px taller than the pre-bump version, so
    # the reactor + right metrics shift up by ~20px (acceptable; the user
    # asked for the input to sit closer to the footer). When the user
    # types multiple lines, the internal scrollbar handles overflow within
    # the locked editor viewport — the block still doesn't grow.
    _SLOT_HEIGHT = _InputBlock.INPUT_H + _InputBlock.GLOW_H

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        self.setFixedHeight(self._SLOT_HEIGHT)

        # Block is a child of the strip, but positioned manually — NOT in a
        # layout. _reposition_block() centers it horizontally and anchors
        # its bottom to the strip's bottom on every resize / growth event.
        self._block = _InputBlock(self)
        self._block.command_sent.connect(self.command_sent.emit)

        # Forward block's signal + expose the contracts main.py / LeftColumn use.
        self.mic = self._block.mic
        self.waveform = self._block.waveform
        self.cmd_bar = self._block.cmd_bar

        self._reposition_block()

    def _reposition_block(self) -> None:
        """Center horizontally, anchor bottom to the strip's bottom edge.

        When the block is taller than the strip's _SLOT_HEIGHT (i.e. user
        typed a multi-line command), the block's top y becomes negative —
        Qt renders the overflow above the strip's top edge, overlapping
        the central panel without disturbing its layout.
        """
        block_w = self._block.width()
        if block_w <= 0:
            # Block hasn't received a size yet — fall back to its preferred
            # width so the first paint isn't anchored to (0, ...).
            block_w = self._block.sizeHint().width() or self._block.minimumWidth()
        # Width: respect block's own min/max bounds, but clamp to the strip
        # so a very narrow window doesn't push the input off-screen.
        avail = self.width()
        target_w = max(self._block.minimumWidth(), min(avail, self._block.maximumWidth()))
        x = max(0, (avail - target_w) // 2)
        y = self._SLOT_HEIGHT - self._block.height()  # may be negative; intentional
        self._block.setGeometry(x, y, target_w, self._block.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_block()


# ─────────────────────────────────────────────────────────────────────────────
# Column wrappers that main.py expects (view.left, view.right)
# ─────────────────────────────────────────────────────────────────────────────


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
        self._bg_px: "QPixmap | None" = None
        self._bg_sz = (-1, -1)

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

    def _rebuild_bg(self) -> None:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            self._bg_px = None
            return
        px = QPixmap(w, h)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing, False)

        p.fillRect(0, 0, w, h, QColor(8, 10, 10, 255))

        cx = w * 0.52
        cy = h * 0.56
        grad = QRadialGradient(cx, cy, max(w, h) * 0.58)
        grad.setColorAt(0.00, QColor(*ACCENT_RGB, 22))
        grad.setColorAt(0.38, QColor(*ACCENT_RGB, 8))
        grad.setColorAt(1.00, QColor(*ACCENT_RGB, 0))
        p.fillRect(0, 0, w, h, QBrush(grad))

        dot_step = 18
        for y in range(0, h + dot_step, dot_step):
            x_offset = (dot_step // 2) if ((y // dot_step) % 2) else 0
            for x in range(-x_offset, w + dot_step, dot_step):
                dx = abs(x - cx) / max(w, 1)
                dy = abs(y - cy) / max(h, 1)
                fade = min(1.0, (dx + dy) * 0.9)
                alpha = int(28 - (fade * 14))
                p.fillRect(int(x), int(y), 2, 2, QColor(*ACCENT_RGB, max(10, alpha)))

        vignette = QRadialGradient(w * 0.5, h * 0.55, w * 0.95)
        vignette.setColorAt(0.65, QColor(8, 10, 10, 0))
        vignette.setColorAt(1.00, QColor(8, 10, 10, 130))
        p.fillRect(0, 0, w, h, QBrush(vignette))

        p.end()
        self._bg_px = px
        self._bg_sz = (w, h)

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        if self._bg_px is None or self._bg_sz != (w, h):
            self._rebuild_bg()
        p = QPainter(self)
        if self._bg_px is not None:
            p.drawPixmap(0, 0, self._bg_px)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._bg_px = None  # invalidate; rebuilt lazily in paintEvent
        self.toast._reposition()
