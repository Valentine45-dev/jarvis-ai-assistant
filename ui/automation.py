"""AutomationView — AUTOMATION_CORE: workflow library and execution log."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from data.mock import MOCK_AUTOMATIONS
from ui.theme import BG, CYAN, FM, PRIMARY
from ui.widgets import GlassPanel, StatusPip, TerminalLog


def _mono(size: int, bold: bool = False):
    from PyQt5.QtGui import QFont
    f = QFont(FM, size)
    f.setBold(bold)
    return f


def _panel_header(title: str, right: str = "") -> tuple[QWidget, QFrame]:
    """Returns a (header_widget, separator) pair for GlassPanel headers."""
    header = QWidget()
    header.setFixedHeight(36)
    header.setStyleSheet("background:transparent;")
    hl = QHBoxLayout(header)
    hl.setContentsMargins(14, 0, 14, 0)
    t = QLabel(title)
    t.setStyleSheet(
        f"color:{CYAN};font-family:'{FM}';font-size:10px;"
        "font-weight:700;letter-spacing:2px;background:transparent;border:none;"
    )
    hl.addWidget(t, 1)
    if right:
        r = QLabel(right)
        r.setStyleSheet(
            "color:rgba(132,147,150,0.7);font-family:'Roboto Mono';"
            "font-size:10px;background:transparent;border:none;"
        )
        hl.addWidget(r)
    sep = QFrame()
    sep.setFrameShape(QFrame.HLine)
    sep.setStyleSheet("color:rgba(0,229,255,0.15);background:rgba(0,229,255,0.15);")
    sep.setFixedHeight(1)
    return header, sep


# ─────────────────────────────────────────────────────────────────────────────


class _WorkflowRow(QWidget):
    selected = pyqtSignal(int)
    run_requested = pyqtSignal(str)

    def __init__(self, idx: int, wf: dict, parent=None):
        super().__init__(parent)
        self._idx = idx
        self.setFixedHeight(52)
        self.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(10)

        pip = StatusPip("active" if wf["enabled"] else "standby")
        pip.setFixedSize(10, 10)
        lay.addWidget(pip, 0, Qt.AlignVCenter)

        info = QVBoxLayout()
        info.setSpacing(2)
        name = QLabel(wf["name"].upper())
        name.setFont(_mono(11, bold=True))
        name.setStyleSheet(
            f"color:{CYAN};letter-spacing:1px;background:transparent;border:none;"
        )
        trigger = QLabel(wf["trigger"])
        trigger.setStyleSheet(
            "color:rgba(132,147,150,0.75);font-family:'Roboto Mono';"
            "font-size:10px;background:transparent;border:none;"
        )
        info.addWidget(name)
        info.addWidget(trigger)
        lay.addLayout(info, 1)

        steps_lbl = QLabel(f"{len(wf['steps'])} STEPS")
        steps_lbl.setStyleSheet(
            "color:rgba(195,245,255,0.4);font-family:'Roboto Mono';"
            "font-size:10px;background:transparent;border:none;"
        )
        lay.addWidget(steps_lbl)

        play = QPushButton("▶")
        play.setFixedSize(26, 26)
        play.setCursor(Qt.PointingHandCursor)
        play.setToolTip(f"Run {wf['name']}")
        play.setStyleSheet(
            "QPushButton{"
            f"color:{CYAN};background:rgba(0,229,255,0.08);"
            "border:1px solid rgba(0,229,255,0.30);font-size:10px;"
            "}"
            "QPushButton:hover{background:rgba(0,229,255,0.20);}"
        )
        play.clicked.connect(lambda: self.run_requested.emit(f"Run {wf['name']}"))
        lay.addWidget(play)

        self._set_style(False)

    def set_active(self, v: bool):
        self._set_style(v)

    def _set_style(self, active: bool):
        if active:
            self.setStyleSheet(
                "background:rgba(0,229,255,0.07);"
                f"border-left:2px solid {CYAN};"
            )
        else:
            self.setStyleSheet(
                "background:transparent;"
                "border-left:2px solid transparent;"
            )

    def mousePressEvent(self, _):
        self.selected.emit(self._idx)


# ─────────────────────────────────────────────────────────────────────────────


class _StepBreakdown(GlassPanel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.set_fill_color(QColor(10, 17, 19, 220))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header_lbl = QLabel("SELECT A WORKFLOW")
        self._header_lbl.setStyleSheet(
            f"color:{CYAN};font-family:'{FM}';font-size:10px;"
            "font-weight:700;letter-spacing:2px;background:transparent;border:none;"
        )
        header = QWidget()
        header.setFixedHeight(36)
        header.setStyleSheet("background:transparent;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 0, 14, 0)
        hl.addWidget(self._header_lbl, 1)
        outer.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:rgba(0,229,255,0.15);background:rgba(0,229,255,0.15);")
        sep.setFixedHeight(1)
        outer.addWidget(sep)

        self._body = QWidget()
        self._body.setStyleSheet("background:transparent;")
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(14, 12, 14, 12)
        self._body_lay.setSpacing(8)
        self._body_lay.addStretch(1)
        outer.addWidget(self._body, 1)

    def show_workflow(self, wf: dict):
        self._header_lbl.setText(wf["name"].upper())

        # Clear existing step widgets
        for i in reversed(range(self._body_lay.count())):
            item = self._body_lay.takeAt(i)
            if item.widget():
                item.widget().deleteLater()

        # Last-run metadata row
        meta_row = QHBoxLayout()
        last = QLabel(f"LAST RUN: {wf['lastRun']}")
        last.setStyleSheet(
            "color:rgba(132,147,150,0.65);font-family:'Roboto Mono';"
            "font-size:10px;background:transparent;border:none;"
        )
        trigger = QLabel(f"TRIGGER: {wf['trigger']}")
        trigger.setStyleSheet(
            f"color:rgba(0,229,255,0.55);font-family:'Roboto Mono';"
            "font-size:10px;background:transparent;border:none;"
        )
        meta_row.addWidget(last, 1)
        meta_row.addWidget(trigger)
        meta_w = QWidget()
        meta_w.setStyleSheet("background:transparent;")
        meta_w.setLayout(meta_row)
        self._body_lay.addWidget(meta_w)

        # Divider
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:rgba(0,229,255,0.10);background:rgba(0,229,255,0.10);")
        sep.setFixedHeight(1)
        self._body_lay.addWidget(sep)

        # Step rows
        for i, step in enumerate(wf["steps"]):
            row_lay = QHBoxLayout()
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(8)

            num = QLabel(f"{i + 1:02d}")
            num.setFixedWidth(22)
            num.setStyleSheet(
                "color:rgba(0,229,255,0.4);font-family:'Roboto Mono';"
                "font-size:10px;background:transparent;border:none;"
            )
            arrow = QLabel("→")
            arrow.setFixedWidth(12)
            arrow.setStyleSheet(
                "color:rgba(0,229,255,0.30);font-family:'Roboto Mono';"
                "font-size:11px;background:transparent;border:none;"
            )
            lbl = QLabel(step)
            lbl.setStyleSheet(
                "color:rgba(195,245,255,0.85);font-family:'Roboto Mono';"
                "font-size:11px;background:transparent;border:none;"
            )
            row_lay.addWidget(num)
            row_lay.addWidget(arrow)
            row_lay.addWidget(lbl, 1)

            row_w = QWidget()
            row_w.setStyleSheet("background:transparent;")
            row_w.setLayout(row_lay)
            row_w.setFixedHeight(24)
            self._body_lay.addWidget(row_w)

        self._body_lay.addStretch(1)


# ─────────────────────────────────────────────────────────────────────────────


class AutomationView(QWidget):
    run_command = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workflows = MOCK_AUTOMATIONS
        self._rows: list[_WorkflowRow] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── Header ────────────────────────────────────────────────────────────
        title = QLabel("AUTOMATION_CORE")
        title.setStyleSheet(
            "QLabel{"
            f"color:{PRIMARY};"
            "font-family:'Space Grotesk';font-size:40px;font-weight:700;"
            "background:transparent;border:none;"
            "}"
        )
        subtitle = QLabel("WORKFLOW ORCHESTRATOR  //  ROUTINE MANAGEMENT")
        subtitle.setStyleSheet(
            "QLabel{color:rgba(132,147,150,0.9);font-family:'Roboto Mono';"
            "font-size:11px;letter-spacing:1px;background:transparent;border:none;}"
        )
        root.addWidget(title)
        root.addWidget(subtitle)

        # ── Main body ─────────────────────────────────────────────────────────
        body = QHBoxLayout()
        body.setSpacing(12)

        # Left: workflow library
        lib = GlassPanel()
        lib.set_fill_color(QColor(10, 17, 19, 220))
        lib_lay = QVBoxLayout(lib)
        lib_lay.setContentsMargins(0, 0, 0, 0)
        lib_lay.setSpacing(0)

        hdr, sep = _panel_header("WORKFLOW LIBRARY", f"{len(self._workflows)} ROUTINES")
        lib_lay.addWidget(hdr)
        lib_lay.addWidget(sep)

        for i, wf in enumerate(self._workflows):
            row = _WorkflowRow(i, wf)
            row.selected.connect(self._select)
            row.run_requested.connect(self.run_command.emit)
            lib_lay.addWidget(row)
            self._rows.append(row)

        lib_lay.addStretch(1)
        body.addWidget(lib, 1)

        # Right: step breakdown
        self._breakdown = _StepBreakdown()
        body.addWidget(self._breakdown, 1)

        root.addLayout(body, 1)

        # ── Execution log ─────────────────────────────────────────────────────
        log_panel = GlassPanel()
        log_panel.set_fill_color(QColor(10, 17, 19, 220))
        log_panel.setFixedHeight(110)
        log_lay = QVBoxLayout(log_panel)
        log_lay.setContentsMargins(0, 0, 0, 0)
        log_lay.setSpacing(0)

        log_hdr, log_sep = _panel_header("EXECUTION LOG")
        log_lay.addWidget(log_hdr)
        log_lay.addWidget(log_sep)

        self._exec_log = TerminalLog()
        self._exec_log.append_line("[SYSTEM] Automation core initialized.")
        self._exec_log.append_line("[SYSTEM] 4 workflows loaded. Awaiting directive.")
        log_lay.addWidget(self._exec_log, 1)

        root.addWidget(log_panel)

        # Select first workflow by default
        self._select(0)

    def _select(self, idx: int):
        for i, row in enumerate(self._rows):
            row.set_active(i == idx)
        if 0 <= idx < len(self._workflows):
            self._breakdown.show_workflow(self._workflows[idx])

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        p.setPen(QPen(QColor(59, 73, 76, 28), 1))
        for x in range(0, self.width(), 50):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 50):
            p.drawLine(0, y, self.width(), y)
