"""AutomationView — AUTOMATION_CORE: workflow library and execution log."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from core.automation import workflow_library
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
    toggle_requested = pyqtSignal(str, bool)   # (workflow_id, new_enabled_state)
    delete_requested = pyqtSignal(str, str)    # (workflow_id, display_name)

    def __init__(self, idx: int, wf: dict, parent=None):
        super().__init__(parent)
        self._idx = idx
        self._wf_id = wf["id"]
        self._enabled = bool(wf.get("enabled", True))
        self.setFixedHeight(52)
        self.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(8)

        pip = StatusPip("active" if self._enabled else "standby")
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

        # Toggle button — ON/OFF
        toggle = QPushButton("ON" if self._enabled else "OFF")
        toggle.setFixedSize(36, 22)
        toggle.setCursor(Qt.PointingHandCursor)
        toggle.setToolTip("Disable workflow" if self._enabled else "Enable workflow")
        toggle.setStyleSheet(self._toggle_style(self._enabled))
        toggle.clicked.connect(self._on_toggle)
        lay.addWidget(toggle)
        self._toggle_btn = toggle

        # Play button
        play = QPushButton("▶")
        play.setFixedSize(26, 26)
        play.setEnabled(self._enabled)
        play.setCursor(Qt.PointingHandCursor if self._enabled else Qt.ForbiddenCursor)
        play.setToolTip(f"Run {wf['name']}" if self._enabled else f"{wf['name']} is disabled")
        if self._enabled:
            play.setStyleSheet(
                "QPushButton{"
                f"color:{CYAN};background:rgba(0,229,255,0.08);"
                "border:1px solid rgba(0,229,255,0.30);font-size:10px;"
                "}"
                "QPushButton:hover{background:rgba(0,229,255,0.20);}"
            )
            play.clicked.connect(lambda: self.run_requested.emit(f"Run {wf['name']}"))
        else:
            play.setStyleSheet(
                "QPushButton{"
                "color:rgba(132,147,150,0.35);background:transparent;"
                "border:1px solid rgba(132,147,150,0.15);font-size:10px;"
                "}"
            )
        lay.addWidget(play)

        # Delete button
        delete = QPushButton("✕")
        delete.setFixedSize(22, 22)
        delete.setCursor(Qt.PointingHandCursor)
        delete.setToolTip(f"Delete {wf['name']}")
        delete.setStyleSheet(
            "QPushButton{"
            "color:rgba(255,80,80,0.55);background:transparent;"
            "border:1px solid rgba(255,80,80,0.20);font-size:10px;"
            "}"
            "QPushButton:hover{"
            "color:rgba(255,80,80,0.9);background:rgba(255,80,80,0.10);"
            "border:1px solid rgba(255,80,80,0.45);"
            "}"
        )
        delete.clicked.connect(lambda: self.delete_requested.emit(self._wf_id, wf["name"]))
        lay.addWidget(delete)

        self._set_style(False)

    # ── Toggle ────────────────────────────────────────────────────────────────

    @staticmethod
    def _toggle_style(enabled: bool) -> str:
        if enabled:
            return (
                "QPushButton{"
                "color:#00c853;background:rgba(0,200,83,0.10);"
                "border:1px solid rgba(0,200,83,0.35);"
                "font-family:'Roboto Mono';font-size:9px;font-weight:700;"
                "}"
                "QPushButton:hover{background:rgba(0,200,83,0.22);}"
            )
        return (
            "QPushButton{"
            "color:rgba(132,147,150,0.55);background:transparent;"
            "border:1px solid rgba(132,147,150,0.20);"
            "font-family:'Roboto Mono';font-size:9px;font-weight:700;"
            "}"
            "QPushButton:hover{background:rgba(132,147,150,0.10);}"
        )

    def _on_toggle(self):
        self.toggle_requested.emit(self._wf_id, not self._enabled)

    # ── Row highlight ─────────────────────────────────────────────────────────

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

        for i in reversed(range(self._body_lay.count())):
            item = self._body_lay.takeAt(i)
            if item.widget():
                item.widget().deleteLater()

        meta_row = QHBoxLayout()
        last_run = wf.get("last_run") or wf.get("lastRun") or "Never"
        last = QLabel(f"LAST RUN: {last_run}")
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

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:rgba(0,229,255,0.10);background:rgba(0,229,255,0.10);")
        sep.setFixedHeight(1)
        self._body_lay.addWidget(sep)

        for i, step in enumerate(wf.get("steps", [])):
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
            lbl = QLabel(_step_label(step))
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


def _step_label(step) -> str:
    """Convert a step dict or plain string to a human-readable label."""
    if isinstance(step, str):
        return step
    action = step.get("action", step.get("intent", "unknown"))
    return action.replace("_", " ").title()


class AutomationView(QWidget):
    run_command = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
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
        self._lib = GlassPanel()
        self._lib.set_fill_color(QColor(10, 17, 19, 220))
        lib_lay = QVBoxLayout(self._lib)
        lib_lay.setContentsMargins(0, 0, 0, 0)
        lib_lay.setSpacing(0)

        # Header with mutable count label
        lib_hdr = QWidget()
        lib_hdr.setFixedHeight(36)
        lib_hdr.setStyleSheet("background:transparent;")
        lib_hdr_lay = QHBoxLayout(lib_hdr)
        lib_hdr_lay.setContentsMargins(14, 0, 14, 0)
        lib_title = QLabel("WORKFLOW LIBRARY")
        lib_title.setStyleSheet(
            f"color:{CYAN};font-family:'{FM}';font-size:10px;"
            "font-weight:700;letter-spacing:2px;background:transparent;border:none;"
        )
        self._wf_count_lbl = QLabel("")
        self._wf_count_lbl.setStyleSheet(
            "color:rgba(132,147,150,0.7);font-family:'Roboto Mono';"
            "font-size:10px;background:transparent;border:none;"
        )
        lib_hdr_lay.addWidget(lib_title, 1)
        lib_hdr_lay.addWidget(self._wf_count_lbl)

        lib_sep = QFrame()
        lib_sep.setFrameShape(QFrame.HLine)
        lib_sep.setStyleSheet("color:rgba(0,229,255,0.15);background:rgba(0,229,255,0.15);")
        lib_sep.setFixedHeight(1)

        lib_lay.addWidget(lib_hdr)
        lib_lay.addWidget(lib_sep)

        # Row container — clear-and-rebuild target for refresh()
        self._row_container = QWidget()
        self._row_container.setStyleSheet("background:transparent;")
        self._row_container_lay = QVBoxLayout(self._row_container)
        self._row_container_lay.setContentsMargins(0, 0, 0, 0)
        self._row_container_lay.setSpacing(0)
        lib_lay.addWidget(self._row_container, 1)

        body.addWidget(self._lib, 1)

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
        log_lay.addWidget(self._exec_log, 1)

        root.addWidget(log_panel)

        # ── Populate rows and connect live-update signal ───────────────────────
        self._build_rows(log_init=True)

        from core.signals import signals
        signals.workflow_library_changed.connect(self.refresh)

    # ── Row management ────────────────────────────────────────────────────────

    def _build_rows(self, log_init: bool = False):
        workflows = workflow_library.list_all()
        n = len(workflows)
        self._wf_count_lbl.setText(f"{n} ROUTINE{'S' if n != 1 else ''}")
        if log_init:
            self._exec_log.append_line("[SYSTEM] Automation core initialized.")
            self._exec_log.append_line(
                f"[SYSTEM] {n} workflow{'s' if n != 1 else ''} loaded. Awaiting directive."
            )
        self._rows = []
        for i, wf in enumerate(workflows):
            row = _WorkflowRow(i, wf)
            row.selected.connect(self._select)
            row.run_requested.connect(self.run_command.emit)
            row.toggle_requested.connect(self._toggle_workflow)
            row.delete_requested.connect(self._delete_workflow)
            self._row_container_lay.addWidget(row)
            self._rows.append(row)
        self._row_container_lay.addStretch(1)
        if self._rows:
            self._select(0)

    def refresh(self):
        """Rebuild the workflow list — called when workflow_library_changed fires."""
        while self._row_container_lay.count():
            item = self._row_container_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows.clear()
        self._build_rows(log_init=False)

    def _delete_workflow(self, wf_id: str, display_name: str):
        reply = QMessageBox.question(
            self,
            "Delete Workflow",
            f"Delete '{display_name}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        ok = workflow_library.remove(wf_id)
        if ok:
            self._exec_log.append_line(f"[SYSTEM] Workflow '{display_name}' deleted.")
        else:
            self._exec_log.append_line(f"[WARN] Delete failed — workflow '{wf_id}' not found.")
        # workflow_library_changed signal triggers refresh() automatically

    def _toggle_workflow(self, wf_id: str, enabled: bool):
        ok = workflow_library.set_enabled(wf_id, enabled)
        if ok:
            state = "enabled" if enabled else "disabled"
            self._exec_log.append_line(f"[SYSTEM] Workflow '{wf_id}' {state}.")
        else:
            self._exec_log.append_line(f"[WARN] Toggle ignored — workflow '{wf_id}' not found.")
        # workflow_library_changed signal triggers refresh() automatically

    # ── Selection ─────────────────────────────────────────────────────────────

    def _select(self, idx: int):
        for i, row in enumerate(self._rows):
            row.set_active(i == idx)
        workflows = workflow_library.list_all()
        if 0 <= idx < len(workflows):
            self._breakdown.show_workflow(workflows[idx])

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        p.setPen(QPen(QColor(59, 73, 76, 28), 1))
        for x in range(0, self.width(), 50):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 50):
            p.drawLine(0, y, self.width(), y)
