"""HistoryView — session command log + analytics.

Redesigned 2026-05 to match the shared HUD grammar:
  - Top 4 hero metric tiles (total / success rate / avg confidence / top intent)
  - Sparkline strip showing per-hour activity for the last 24 h
  - Filter chip row (All / per-intent) with optional search input
  - Dense log rows (divide-y, intent badge + user query + JARVIS response +
    outcome pip), the same row shape used elsewhere across the app.

Public API preserved so main.py needs no changes:
  - HistoryView.history_cleared signal
  - HistoryView.refresh_history(entries, uptime_str="") method
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import List, Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.components.design import (
    AMBER,
    BG_PANEL,
    CYAN_FAINT,
    CYAN_SOFT,
    GREEN,
    GREEN_DIM,
    INK,
    INK_DIM,
    INK_FAINT,
    INTENT_LABEL,
    RED,
    ChipFilter,
    DivideRow,
    HeroMetric,
    IntentBadge,
    PanelCard,
    StatusPip,
)
from ui.theme import BG, CYAN, FM


# ── Sparkline ────────────────────────────────────────────────────────────────


class _Sparkline(QWidget):
    """24-bin activity sparkline. Each bin = one hour. Bins fade left → right
    based on age; today's most recent hour is brightest on the far right.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._bins: List[int] = [0] * 24
        self._peak_hours: list[int] = []
        self.setMinimumHeight(50)

    # ── Data ─────────────────────────────────────────────────────────────────

    def set_entries(self, entries: list) -> None:
        """Rebuild bins from ``entries``. Times are read from ``entry["jTime"]``
        when available (HH:MM string from main.py), else from "time" (legacy)."""
        bins = [0] * 24
        for e in entries:
            t = str(e.get("jTime") or e.get("time") or "").strip()
            if len(t) < 2 or ":" not in t:
                continue
            try:
                hour = int(t.split(":", 1)[0])
            except ValueError:
                continue
            if 0 <= hour < 24:
                bins[hour] += 1
        self._bins = bins

        # Identify top 3 peak hours (by count) for the summary line.
        if any(self._bins):
            sorted_hours = sorted(range(24), key=lambda h: self._bins[h], reverse=True)
            self._peak_hours = [h for h in sorted_hours[:3] if self._bins[h] > 0]
        else:
            self._peak_hours = []
        self.update()

    def peak_summary(self) -> str:
        """Short text describing where activity concentrated — for the
        sparkline's adjacent caption."""
        total = sum(self._bins)
        if not total:
            return "no activity yet"
        if not self._peak_hours:
            return f"{total} commands"
        hh = " / ".join(f"{h:02d}:00" for h in self._peak_hours)
        return f"{total} commands · peaks at {hh}"

    # ── Paint ────────────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        w, h = self.width(), self.height()
        if w <= 4 or h <= 4:
            return
        if not any(self._bins):
            # Faint baseline + "no data" hint
            pen = QPen(QColor(0, 229, 255, 40))
            pen.setWidthF(1.0)
            p.setPen(pen)
            p.drawLine(0, h - 4, w, h - 4)
            return

        max_count = max(self._bins) or 1
        step = w / 23.0  # 24 points, 23 gaps
        baseline = h - 2
        amplitude = h - 8

        # Build the polyline path
        path = QPainterPath()
        first = True
        for i, c in enumerate(self._bins):
            x = i * step
            y = baseline - (c / max_count) * amplitude
            if first:
                path.moveTo(x, y)
                first = False
            else:
                path.lineTo(x, y)

        # Fill under the curve at low alpha
        fill_path = QPainterPath(path)
        fill_path.lineTo(w, baseline)
        fill_path.lineTo(0, baseline)
        fill_path.closeSubpath()
        p.fillPath(fill_path, QColor(0, 229, 255, 22))

        # Stroke the line
        pen = QPen(QColor(CYAN))
        pen.setWidthF(1.2)
        p.setPen(pen)
        p.drawPath(path)


# ── Empty-state helper ──────────────────────────────────────────────────────


def _empty_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setStyleSheet(
        "QLabel {"
        f"color: rgba(0,229,255,0.22);"
        "background: transparent;"
        "border: none;"
        f"font-family: '{FM}';"
        "font-size: 11px;"
        "font-weight: 700;"
        "letter-spacing: 3px;"
        "}"
    )
    return lbl


# ── Main view ───────────────────────────────────────────────────────────────


class HistoryView(QWidget):
    """Session command log + analytics. See module docstring."""

    history_cleared = pyqtSignal()   # main.py listens to wipe its own _history

    # Intent filter chips shown above the log. "all" is the no-filter case.
    _CHIPS: tuple[tuple[str, str], ...] = (
        ("all",                  "All"),
        ("browser_automation",   "Browser"),
        ("file_operation",       "File"),
        ("vision_analysis",      "Vision"),
        ("system_control",       "System"),
        ("jarvis_meta",          "Meta"),
        ("automation_task",      "Workflow"),
        ("fail",                 "Failures"),
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._start_time = datetime.now()
        self._all_entries: list = []
        self._active_filter: str = "all"

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # ── Header row ──────────────────────────────────────────────────────
        head = QHBoxLayout()
        head.setSpacing(12)
        title = QLabel("COMMAND_LOG")
        title.setStyleSheet(
            "QLabel {"
            f"color: {CYAN};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 32px;"
            "font-weight: 700;"
            "letter-spacing: 5px;"
            "}"
        )
        head.addWidget(title, 0, Qt.AlignBottom)

        subtitle = QLabel("SESSION INTERACTION LOG · INTENT ANALYTICS")
        subtitle.setStyleSheet(
            "QLabel {"
            f"color: {INK_DIM};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "letter-spacing: 2px;"
            "padding-bottom: 6px;"
            "}"
        )
        head.addWidget(subtitle, 0, Qt.AlignBottom)
        head.addStretch(1)

        self._clear_btn = QPushButton("CLEAR HISTORY")
        self._clear_btn.setCursor(Qt.PointingHandCursor)
        self._clear_btn.setToolTip("Clear session command history")
        self._clear_btn.setStyleSheet(
            "QPushButton {"
            "background: transparent;"
            f"color: {CYAN};"
            f"border: 1px solid {CYAN_SOFT};"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "font-weight: 700;"
            "padding: 5px 14px;"
            "letter-spacing: 2px;"
            "}"
            "QPushButton:hover { background: rgba(0,229,255,0.10); }"
        )
        self._clear_btn.clicked.connect(self._on_clear)
        head.addWidget(self._clear_btn)
        root.addLayout(head)

        # ── Hero stats strip (4 tiles in a bordered horizontal container) ───
        stats_row = self._build_stats_strip()
        root.addWidget(stats_row)

        # ── Sparkline strip ─────────────────────────────────────────────────
        spark_panel = self._build_sparkline_panel()
        root.addWidget(spark_panel)

        # ── Filter chip row + search ────────────────────────────────────────
        filter_row = self._build_filter_row()
        root.addLayout(filter_row)

        # ── Log panel (scrollable, divide-y rows) ───────────────────────────
        self._log_panel = PanelCard("Sessions · today", active=True)
        self._log_panel.setMinimumHeight(280)
        self._log_scroll = QScrollArea()
        self._log_scroll.setWidgetResizable(True)
        self._log_scroll.setFrameShape(QScrollArea.NoFrame)
        self._log_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._log_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 6px; }"
            "QScrollBar::handle:vertical {"
            "background: rgba(0,229,255,0.30); border-radius: 3px; min-height: 20px;"
            "}"
            "QScrollBar::handle:vertical:hover { background: rgba(0,229,255,0.55); }"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical { background: transparent; }"
        )
        self._rows_container = QWidget()
        self._rows_container.setStyleSheet("background: transparent;")
        self._rows_lay = QVBoxLayout(self._rows_container)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(0)
        self._rows_lay.addStretch(1)
        self._log_scroll.setWidget(self._rows_container)
        self._log_panel.add(self._log_scroll, stretch=1)
        root.addWidget(self._log_panel, 1)

        # Search-debounce timer
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(250)
        self._filter_timer.timeout.connect(self._apply_filter)
        self._search_input.textChanged.connect(lambda _: self._filter_timer.start())

        # Initial empty render
        self.refresh_history([])

    # ── Builders ─────────────────────────────────────────────────────────────

    def _build_stats_strip(self) -> QWidget:
        """Four hero metric tiles in a divide-by-vertical-rule row."""
        wrap = QFrame()
        wrap.setStyleSheet(
            "QFrame {"
            f"background: {BG_PANEL};"
            f"border: 1px solid {CYAN_FAINT};"
            "}"
        )
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        def _cell(metric: HeroMetric, *, last: bool = False) -> QWidget:
            cell = QFrame()
            cell.setStyleSheet(
                "QFrame {"
                "background: transparent;"
                + ("border: none;" if last else f"border-right: 1px solid {CYAN_FAINT};")
                + "}"
            )
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(16, 12, 16, 12)
            cl.addWidget(metric)
            return cell

        self._stat_total      = HeroMetric("Total commands", "0", sub="all-time", value_size=30)
        self._stat_success    = HeroMetric("Success rate",  "—", sub="today",
                                           value_color=GREEN, value_size=30)
        self._stat_confidence = HeroMetric("Avg confidence", "0%", sub="routing certainty", value_size=30)
        self._stat_top_intent = HeroMetric("Top intent", "—", sub="0 calls", value_size=16)

        lay.addWidget(_cell(self._stat_total), 1)
        lay.addWidget(_cell(self._stat_success), 1)
        lay.addWidget(_cell(self._stat_confidence), 1)
        lay.addWidget(_cell(self._stat_top_intent, last=True), 1)
        return wrap

    def _build_sparkline_panel(self) -> QWidget:
        panel = PanelCard()
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("ACTIVITY · LAST 24H")
        title.setStyleSheet(
            "QLabel {"
            f"color: {CYAN};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 9.5px;"
            "font-weight: 700;"
            "letter-spacing: 2.2px;"
            "}"
        )
        header.addWidget(title)
        header.addStretch(1)
        self._spark_caption = QLabel("no activity yet")
        self._spark_caption.setStyleSheet(
            "QLabel {"
            f"color: {INK_DIM};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "}"
        )
        header.addWidget(self._spark_caption)
        panel.body().addLayout(header)

        self._spark = _Sparkline()
        panel.add(self._spark, stretch=0)
        return panel

    def _build_filter_row(self) -> QHBoxLayout:
        lay = QHBoxLayout()
        lay.setSpacing(6)
        self._chip_widgets: dict[str, ChipFilter] = {}
        for key, label in self._CHIPS:
            chip = ChipFilter(label, active=(key == "all"))
            chip.clicked.connect(lambda _checked, k=key: self._on_chip_clicked(k))
            self._chip_widgets[key] = chip
            lay.addWidget(chip)
        lay.addStretch(1)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("search history…")
        self._search_input.setFixedWidth(220)
        self._search_input.setStyleSheet(
            "QLineEdit {"
            f"background: {BG_PANEL};"
            f"color: {INK};"
            f"border: 1px solid {CYAN_FAINT};"
            f"font-family: '{FM}';"
            "font-size: 11px;"
            "padding: 4px 10px;"
            "}"
            f"QLineEdit:focus {{ border-color: {CYAN}; }}"
        )
        lay.addWidget(self._search_input)
        return lay

    # ── Event handlers ───────────────────────────────────────────────────────

    def _on_chip_clicked(self, key: str) -> None:
        # Chips behave as a single-select group. Toggle off others, ensure this
        # one stays checked. ChipFilter is a QPushButton with .setCheckable;
        # we want exclusive behaviour so manage state by hand here.
        for k, chip in self._chip_widgets.items():
            chip.setChecked(k == key)
            chip._refresh_style()  # noqa: SLF001 — internal helper, ok here
        self._active_filter = key
        self._apply_filter()

    def _on_clear(self) -> None:
        self.refresh_history([])
        self.history_cleared.emit()

    # ── Filtering / rendering ────────────────────────────────────────────────

    def _apply_filter(self) -> None:
        q = self._search_input.text().strip().lower()
        flt = self._active_filter

        def keep(e: dict) -> bool:
            if q and q not in (e.get("you", "") + " " + e.get("jarvis", "")).lower():
                return False
            if flt == "all":
                return True
            if flt == "fail":
                return (e.get("status") == "error")
            return e.get("intent") == flt

        visible = [e for e in self._all_entries if keep(e)]
        self._render_rows(visible[:80])

    def _render_rows(self, entries: List[dict]) -> None:
        # Clear existing rows (everything except the trailing stretch)
        while self._rows_lay.count():
            item = self._rows_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not entries:
            self._rows_lay.addStretch(1)
            self._rows_lay.addWidget(_empty_label("NO ENTRIES"), 0, Qt.AlignCenter)
            self._rows_lay.addStretch(1)
            return

        last_idx = len(entries) - 1
        for i, entry in enumerate(entries):
            self._rows_lay.addWidget(self._build_row(entry, last=(i == last_idx)))
        self._rows_lay.addStretch(1)

    def _build_row(self, entry: dict, *, last: bool) -> DivideRow:
        you  = (entry.get("you") or "").strip()
        resp = (entry.get("jarvis") or "").strip()
        intent = entry.get("intent") or "unknown"
        status = entry.get("status") or "success"
        t = str(entry.get("jTime") or entry.get("time") or "--:--")[:8]

        row = DivideRow(last=last, padding_y=8)

        time_lbl = QLabel(t)
        time_lbl.setFixedWidth(48)
        time_lbl.setStyleSheet(
            f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 10px; }}"
        )
        row.add(time_lbl)

        # Badge: failures get the dedicated FAIL badge regardless of intent
        badge_key = "fail" if status == "error" else intent
        row.add(IntentBadge(badge_key))

        you_lbl = QLabel(f'"{you}"' if you else "")
        you_lbl.setMinimumWidth(160)
        you_lbl.setStyleSheet(
            f"QLabel {{ color: {GREEN_DIM}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 11px; }}"
        )
        you_lbl.setToolTip(you)
        row.add(you_lbl, stretch=1)

        arrow = QLabel("→")
        arrow.setStyleSheet(
            f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 11px; }}"
        )
        row.add(arrow)

        resp_lbl = QLabel(resp[:120] + ("…" if len(resp) > 120 else ""))
        resp_color = RED if status == "error" else INK
        resp_lbl.setStyleSheet(
            f"QLabel {{ color: {resp_color}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 11px; }}"
        )
        resp_lbl.setToolTip(resp)
        row.add(resp_lbl, stretch=2)

        # Outcome pip
        pip = StatusPip("on" if status == "success" else "err")
        row.add(pip)

        return row

    # ── Public API (preserved) ───────────────────────────────────────────────

    def refresh_history(self, entries: list, uptime_str: str = "") -> None:
        """Called by main.py after each command. ``uptime_str`` accepted for API
        compatibility — we recompute internally if needed."""
        # Store newest-first
        self._all_entries = list(reversed(entries))
        total = len(entries)

        # Total commands
        self._stat_total.set_value(f"{total:,}")
        self._stat_total.set_sub("all-time" if total else "no commands yet")

        # Success rate
        if total:
            ok_count = sum(1 for e in entries if (e.get("status") != "error"))
            rate = ok_count / total
            self._stat_success.set_value(
                f"{int(rate * 100)}%",
                color=GREEN if rate >= 0.9 else AMBER if rate >= 0.7 else RED,
            )
            self._stat_success.set_sub(f"{ok_count} of {total} succeeded")
        else:
            self._stat_success.set_value("—", color=INK_DIM)
            self._stat_success.set_sub("no commands yet")

        # Average confidence
        if total:
            avg_conf = sum(
                float(e.get("confidence", e.get("conf", 0.0)) or 0.0) for e in entries
            ) / total
            self._stat_confidence.set_value(f"{int(avg_conf * 100)}%")
            self._stat_confidence.set_sub("routing certainty")
        else:
            self._stat_confidence.set_value("0%")
            self._stat_confidence.set_sub("routing certainty")

        # Top intent
        if total:
            counts = Counter(
                e.get("intent") or "unknown" for e in entries
            )
            top_intent, top_count = counts.most_common(1)[0]
            label = INTENT_LABEL.get(top_intent, top_intent)
            self._stat_top_intent.set_value(label, color=CYAN)
            pct = int((top_count / total) * 100)
            self._stat_top_intent.set_sub(f"{top_count} calls · {pct}% of all")
        else:
            self._stat_top_intent.set_value("—", color=INK_DIM)
            self._stat_top_intent.set_sub("0 calls")

        # Sparkline
        self._spark.set_entries(entries)
        self._spark_caption.setText(self._spark.peak_summary())

        # Re-render visible rows under the current filter
        self._apply_filter()

    # ── Paint (dotted backdrop) ──────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 229, 255, 18))
        for x in range(0, self.width() + 28, 28):
            for y in range(0, self.height() + 28, 28):
                p.drawEllipse(x - 1, y - 1, 2, 2)
