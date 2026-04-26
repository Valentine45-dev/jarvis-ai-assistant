"""HistoryView — COMMAND_LOG: session stats and scrollable command history."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from data.mock import MOCK_HISTORY_FULL
from ui.theme import BG, CYAN, FM, GREEN, PRIMARY, RED, WARNING
from ui.widgets import GlassPanel, SegmentedBar, StatusPip


def _mono(size: int, bold: bool = False):
    from PyQt5.QtGui import QFont
    f = QFont(FM, size)
    f.setBold(bold)
    return f


# ── Stat card ──────────────────────────────────────────────────────────────

class _StatCard(GlassPanel):
    def __init__(self, label: str, value: str, bar_value: float = 0.0, parent=None):
        super().__init__(parent)
        self.set_fill_color(QColor(10, 17, 19, 220))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        lbl = QLabel(label)
        lbl.setFont(_mono(8, bold=True))
        lbl.setStyleSheet(
            "color:rgba(186,201,204,0.55);letter-spacing:2px;"
            "background:transparent;border:none;"
        )
        lay.addWidget(lbl)

        self._val = QLabel(value)
        self._val.setFont(_mono(22))
        self._val.setStyleSheet(
            f"color:{CYAN};letter-spacing:2px;background:transparent;border:none;"
        )
        lay.addWidget(self._val)

        lay.addStretch(1)

        self._bar = SegmentedBar(segments=8, value=bar_value, color=CYAN)
        self._bar.setFixedHeight(10)
        lay.addWidget(self._bar)

    def set_metrics(self, value: str, bar_value: float = 0.0):
        self._val.setText(value)
        self._bar.set_value(max(0.0, min(1.0, bar_value)))


# ── Command log row ────────────────────────────────────────────────────────

_STATUS_STATE = {"success": "active", "warning": "standby", "error": "error"}


class _LogRow(QWidget):
    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)

        conf   = float(entry.get("confidence", entry.get("conf", 0.0)))
        status = entry.get("status", "success")
        intent = entry.get("intent", "unknown")
        cmd    = entry.get("you", "")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(12)

        pip = StatusPip(_STATUS_STATE.get(status, "active"))
        pip.setFixedSize(8, 8)
        lay.addWidget(pip, 0, Qt.AlignVCenter)

        time_lbl = QLabel(str(entry.get("time", "--:--"))[:8])
        time_lbl.setFixedWidth(64)
        time_lbl.setFont(_mono(10))
        time_lbl.setStyleSheet(
            "color:rgba(132,147,150,0.7);background:transparent;border:none;"
        )
        lay.addWidget(time_lbl)

        cmd_lbl = QLabel(cmd[:46] + "…" if len(cmd) > 46 else cmd)
        cmd_lbl.setFont(_mono(11))
        cmd_lbl.setStyleSheet(
            "color:rgba(195,245,255,0.88);background:transparent;border:none;"
        )
        lay.addWidget(cmd_lbl, 1)

        intent_lbl = QLabel(intent.replace("_", "·"))
        intent_lbl.setFixedWidth(106)
        intent_lbl.setFont(_mono(10))
        intent_lbl.setStyleSheet(f"color:{CYAN};background:transparent;border:none;")
        lay.addWidget(intent_lbl)

        conf_color = CYAN if conf >= 0.9 else WARNING if conf >= 0.7 else RED
        conf_lbl = QLabel(f"{int(conf * 100)}%")
        conf_lbl.setFixedWidth(34)
        conf_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        conf_lbl.setFont(_mono(10, bold=True))
        conf_lbl.setStyleSheet(
            f"color:{conf_color};background:transparent;border:none;"
        )
        lay.addWidget(conf_lbl)

    def enterEvent(self, _):
        self.setStyleSheet("background:rgba(0,229,255,0.05);")

    def leaveEvent(self, _):
        self.setStyleSheet("background:transparent;")


class _LogTable(QWidget):
    """Scrollable list of _LogRow widgets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        col_hdr = QWidget()
        col_hdr.setFixedHeight(26)
        col_hdr.setStyleSheet("background:rgba(0,229,255,0.04);")
        ch = QHBoxLayout(col_hdr)
        ch.setContentsMargins(34, 0, 12, 0)
        ch.setSpacing(12)
        for txt, w in (("TIME", 64), ("COMMAND", 0), ("INTENT", 106), ("CONF", 34)):
            lbl = QLabel(txt)
            lbl.setFont(_mono(8, bold=True))
            lbl.setStyleSheet(
                "color:rgba(132,147,150,0.55);letter-spacing:2px;"
                "background:transparent;border:none;"
            )
            if w:
                lbl.setFixedWidth(w)
                ch.addWidget(lbl)
            else:
                ch.addWidget(lbl, 1)
        outer.addWidget(col_hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(
            "color:rgba(0,229,255,0.12);background:rgba(0,229,255,0.12);"
        )
        sep.setFixedHeight(1)
        outer.addWidget(sep)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{background:rgba(0,0,0,0);width:6px;}"
            "QScrollBar::handle:vertical{"
            "background:rgba(0,229,255,0.25);border-radius:3px;min-height:20px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0px;}"
        )

        self._container = QWidget()
        self._container.setStyleSheet("background:transparent;")
        self._rows_lay = QVBoxLayout(self._container)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(0)
        self._rows_lay.addStretch(1)

        scroll.setWidget(self._container)
        outer.addWidget(scroll, 1)

    def set_entries(self, entries: list):
        for i in reversed(range(self._rows_lay.count())):
            item = self._rows_lay.takeAt(i)
            if item.widget():
                item.widget().deleteLater()

        if not entries:
            empty = QLabel("NO HISTORY YET")
            empty.setAlignment(Qt.AlignCenter)
            empty.setFont(_mono(11, bold=True))
            empty.setStyleSheet(
                "color:rgba(0,229,255,0.20);letter-spacing:3px;"
                "background:transparent;border:none;"
            )
            self._rows_lay.addStretch(1)
            self._rows_lay.addWidget(empty, 0, Qt.AlignCenter)
            self._rows_lay.addStretch(1)
            return

        for entry in entries:
            self._rows_lay.addWidget(_LogRow(entry))
        self._rows_lay.addStretch(1)


# ── Intent breakdown panel ─────────────────────────────────────────────────

class _IntentBreakdown(GlassPanel):
    """Right panel: top intents by frequency with labeled bars."""

    MAX_SHOWN = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.set_fill_color(QColor(10, 17, 19, 220))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        hdr = QWidget()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet("background:transparent;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 0, 14, 0)
        t = QLabel("INTENT BREAKDOWN")
        t.setFont(_mono(10, bold=True))
        t.setStyleSheet(
            f"color:{CYAN};letter-spacing:2px;background:transparent;border:none;"
        )
        hl.addWidget(t)
        outer.addWidget(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(
            "color:rgba(0,229,255,0.15);background:rgba(0,229,255,0.15);"
        )
        sep.setFixedHeight(1)
        outer.addWidget(sep)

        self._body = QWidget()
        self._body.setStyleSheet("background:transparent;")
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(14, 14, 14, 14)
        self._body_lay.setSpacing(12)
        outer.addWidget(self._body, 1)

    def update_breakdown(self, entries: list):
        while self._body_lay.count():
            item = self._body_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not entries:
            lbl = QLabel("NO DATA")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(
                "color:rgba(0,229,255,0.20);letter-spacing:3px;"
                "background:transparent;border:none;"
            )
            self._body_lay.addStretch(1)
            self._body_lay.addWidget(lbl, 0, Qt.AlignCenter)
            self._body_lay.addStretch(1)
            return

        counts = Counter(
            e.get("intent", "unknown") for e in entries if e.get("intent")
        )
        total = sum(counts.values()) or 1

        for intent, count in counts.most_common(self.MAX_SHOWN):
            w = QWidget()
            w.setStyleSheet("background:transparent;")
            wl = QVBoxLayout(w)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.setSpacing(3)

            label_row = QHBoxLayout()
            name_lbl = QLabel(intent.replace("_", "·"))
            name_lbl.setFont(_mono(9))
            name_lbl.setStyleSheet(
                f"color:{CYAN};background:transparent;border:none;"
            )
            cnt_lbl = QLabel(str(count))
            cnt_lbl.setFont(_mono(9, bold=True))
            cnt_lbl.setStyleSheet(
                "color:rgba(132,147,150,0.70);background:transparent;border:none;"
            )
            label_row.addWidget(name_lbl, 1)
            label_row.addWidget(cnt_lbl)
            wl.addLayout(label_row)

            bar = SegmentedBar(segments=8, value=count / total, color=CYAN)
            bar.setFixedHeight(5)
            wl.addWidget(bar)

            self._body_lay.addWidget(w)

        self._body_lay.addStretch(1)


# ── Filter bar ─────────────────────────────────────────────────────────────

class _FilterBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setStyleSheet(
            "background:rgba(8,15,17,0.55);"
            "border:1px solid rgba(0,229,255,0.09);"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(10)

        lbl = QLabel("FILTER")
        lbl.setFont(_mono(8, bold=True))
        lbl.setStyleSheet(
            "color:rgba(0,229,255,0.45);letter-spacing:2px;"
            "background:transparent;border:none;"
        )
        lay.addWidget(lbl)

        div = QFrame()
        div.setFrameShape(QFrame.VLine)
        div.setStyleSheet(
            "color:rgba(0,229,255,0.15);background:rgba(0,229,255,0.15);"
        )
        div.setFixedWidth(1)
        lay.addWidget(div)

        self.input = QLineEdit()
        self.input.setPlaceholderText("type to filter commands…")
        self.input.setStyleSheet(
            "QLineEdit{background:transparent;border:none;"
            f"color:{CYAN};font-family:'{FM}';font-size:11px;letter-spacing:1px;}"
        )
        lay.addWidget(self.input, 1)

        clr = QPushButton("✕")
        clr.setCursor(Qt.PointingHandCursor)
        clr.setFixedSize(20, 20)
        clr.setStyleSheet(
            "QPushButton{color:rgba(0,229,255,0.35);background:transparent;"
            "border:none;font-size:11px;}"
            "QPushButton:hover{color:rgba(0,229,255,0.85);}"
        )
        clr.clicked.connect(self.input.clear)
        lay.addWidget(clr)


# ── Main view ──────────────────────────────────────────────────────────────

class HistoryView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._start_time = datetime.now()
        self._all_entries: list = []   # newest-first, full unfiltered list

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── Header ──────────────────────────────────────────────────────────
        head = QHBoxLayout()
        title = QLabel("COMMAND_LOG")
        title.setStyleSheet(
            "QLabel{"
            f"color:{PRIMARY};"
            "font-family:'Space Grotesk';font-size:40px;font-weight:700;"
            "background:transparent;border:none;"
            "}"
        )
        head.addWidget(title, 1)

        self._clear_btn = QPushButton("CLEAR HISTORY")
        self._clear_btn.setCursor(Qt.PointingHandCursor)
        self._clear_btn.setToolTip("Clear session command history")
        self._clear_btn.setStyleSheet(
            "QPushButton{"
            f"color:{CYAN};border:1px solid rgba(0,229,255,0.6);"
            "font-family:'Roboto Mono';font-size:11px;font-weight:700;"
            "padding:6px 14px;background:transparent;"
            "}"
            "QPushButton:hover{background:rgba(0,229,255,0.08);}"
        )
        head.addWidget(self._clear_btn, 0, Qt.AlignVCenter)
        root.addLayout(head)

        subtitle = QLabel("SESSION INTERACTION LOG  //  INTENT ANALYTICS")
        subtitle.setStyleSheet(
            "QLabel{color:rgba(132,147,150,0.9);font-family:'Roboto Mono';"
            "font-size:11px;letter-spacing:1px;background:transparent;border:none;}"
        )
        root.addWidget(subtitle)

        # ── Stat cards ───────────────────────────────────────────────────────
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self._card_total  = _StatCard("TOTAL COMMANDS", "0",      0.0)
        self._card_conf   = _StatCard("AVG CONFIDENCE", "0%",     0.0)
        self._card_uptime = _StatCard("SESSION UPTIME", "0h 00m", 0.0)
        for card in (self._card_total, self._card_conf, self._card_uptime):
            card.setFixedHeight(110)
            stats_row.addWidget(card, 1)
        root.addLayout(stats_row)

        # ── Filter bar ───────────────────────────────────────────────────────
        self._filter_bar = _FilterBar()
        root.addWidget(self._filter_bar)

        # Restarts on each keystroke; fires _apply_filter 250ms after last key
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(250)
        self._filter_timer.timeout.connect(self._apply_filter)
        self._filter_bar.input.textChanged.connect(
            lambda _: self._filter_timer.start()
        )

        # ── Body: log (left 70%) + intent breakdown (right 30%) ─────────────
        body = QHBoxLayout()
        body.setSpacing(12)

        log_panel = GlassPanel()
        log_panel.set_fill_color(QColor(10, 17, 19, 220))
        lp_lay = QVBoxLayout(log_panel)
        lp_lay.setContentsMargins(0, 0, 0, 0)
        lp_lay.setSpacing(0)

        log_hdr = QWidget()
        log_hdr.setFixedHeight(36)
        log_hdr.setStyleSheet("background:transparent;")
        lh = QHBoxLayout(log_hdr)
        lh.setContentsMargins(14, 0, 14, 0)
        lh.setSpacing(0)

        log_title = QLabel("INTERACTION HISTORY")
        log_title.setFont(_mono(10, bold=True))
        log_title.setStyleSheet(
            f"color:{CYAN};letter-spacing:2px;background:transparent;border:none;"
        )
        self._entry_count = QLabel("0 ENTRIES")
        self._entry_count.setFont(_mono(10))
        self._entry_count.setStyleSheet(
            "color:rgba(132,147,150,0.7);background:transparent;border:none;"
        )
        lh.addWidget(log_title, 1)
        lh.addWidget(self._entry_count)
        lp_lay.addWidget(log_hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(
            "color:rgba(0,229,255,0.15);background:rgba(0,229,255,0.15);"
        )
        sep.setFixedHeight(1)
        lp_lay.addWidget(sep)

        self._table = _LogTable()
        lp_lay.addWidget(self._table, 1)
        body.addWidget(log_panel, 7)

        self._breakdown = _IntentBreakdown()
        body.addWidget(self._breakdown, 3)

        root.addLayout(body, 1)

        # Self-updating uptime — fires every 60s, no dependency on main.py
        self._uptime_timer = QTimer(self)
        self._uptime_timer.setInterval(60_000)
        self._uptime_timer.timeout.connect(self._tick_uptime)
        self._uptime_timer.start()
        self._tick_uptime()  # populate immediately at "0h 00m"

        self.refresh_history(MOCK_HISTORY_FULL)
        self._clear_btn.clicked.connect(self._on_clear)

    # ── Internal helpers ────────────────────────────────────────────────────

    def _tick_uptime(self):
        secs = int((datetime.now() - self._start_time).total_seconds())
        h, m = divmod(secs // 60, 60)
        self._card_uptime.set_metrics(f"{h}h {m:02d}m", min(1.0, secs / 14400))

    def _apply_filter(self):
        q = self._filter_bar.input.text().strip().lower()
        visible = (
            [e for e in self._all_entries if q in e.get("you", "").lower()]
            if q else self._all_entries
        )
        n = len(visible)
        self._entry_count.setText(f"{n} {'ENTRY' if n == 1 else 'ENTRIES'}")
        self._table.set_entries(visible[:50])

    # ── Public API ──────────────────────────────────────────────────────────

    def refresh_history(self, entries: list, uptime_str: str = ""):
        """Called from main.py after each command completes.

        uptime_str is accepted for API compatibility but session uptime is
        computed internally via _tick_uptime so the card never shows '--'.
        """
        total = len(entries)
        avg_conf = (
            sum(float(e.get("confidence", e.get("conf", 0.0))) for e in entries) / total
            if total else 0.0
        )
        self._card_total.set_metrics(str(total), min(1.0, total / 50.0))
        self._card_conf.set_metrics(f"{int(avg_conf * 100)}%", avg_conf)

        # Store newest-first; filter and table read from this
        self._all_entries = list(reversed(entries))
        self._apply_filter()

        # Breakdown always reflects the full unfiltered history
        self._breakdown.update_breakdown(entries)

    def _on_clear(self):
        self.refresh_history([])

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        p.setPen(QPen(QColor(59, 73, 76, 28), 1))
        for x in range(0, self.width(), 50):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 50):
            p.drawLine(0, y, self.width(), y)
