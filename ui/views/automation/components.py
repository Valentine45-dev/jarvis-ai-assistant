"""Workflow row and breakdown components for AutomationView."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ui.theme import CYAN, FM
from ui.widgets import GlassPanel, StatusPip, _mono


def step_label(step) -> str:
    if isinstance(step, str):
        return step
    action = step.get("action", step.get("intent", "unknown"))
    return action.replace("_", " ").title()


class WorkflowRow(QWidget):
    selected = pyqtSignal(int)
    run_requested = pyqtSignal(str)
    toggle_requested = pyqtSignal(str, bool)
    delete_requested = pyqtSignal(str, str)

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
        name.setStyleSheet(f"color:{CYAN};letter-spacing:1px;background:transparent;border:none;")
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

        toggle = QPushButton("ON" if self._enabled else "OFF")
        toggle.setFixedSize(36, 22)
        toggle.setCursor(Qt.PointingHandCursor)
        toggle.setToolTip("Disable workflow" if self._enabled else "Enable workflow")
        toggle.setStyleSheet(self._toggle_style(self._enabled))
        toggle.clicked.connect(self._on_toggle)
        lay.addWidget(toggle)

        has_steps = bool(wf.get("steps"))
        play = QPushButton("▶")
        play.setFixedSize(26, 26)
        can_run = self._enabled and has_steps
        play.setEnabled(can_run)
        play.setCursor(Qt.PointingHandCursor if can_run else Qt.ForbiddenCursor)
        if not self._enabled:
            play.setToolTip(f"{wf['name']} is disabled")
        elif not has_steps:
            play.setToolTip(f"{wf['name']} has no steps yet")
        else:
            play.setToolTip(f"Run {wf['name']}")
        if can_run:
            play.setStyleSheet(
                f"QPushButton{{color:{CYAN};background:rgba(0,229,255,0.08);"
                "border:1px solid rgba(0,229,255,0.30);font-size:10px;}"
                "QPushButton:hover{background:rgba(0,229,255,0.20);}"
            )
            play.clicked.connect(
                lambda checked=False, wid=self._wf_id: self.run_requested.emit(f"__run_workflow_id__:{wid}")
            )
        else:
            play.setStyleSheet(
                "QPushButton{color:rgba(132,147,150,0.35);background:transparent;"
                "border:1px solid rgba(132,147,150,0.15);font-size:10px;}"
            )
        lay.addWidget(play)

        delete = QPushButton("✕")
        delete.setFixedSize(22, 22)
        delete.setCursor(Qt.PointingHandCursor)
        delete.setToolTip(f"Delete {wf['name']}")
        delete.setStyleSheet(
            "QPushButton{color:rgba(255,80,80,0.55);background:transparent;"
            "border:1px solid rgba(255,80,80,0.20);font-size:10px;}"
            "QPushButton:hover{color:rgba(255,80,80,0.9);background:rgba(255,80,80,0.10);"
            "border:1px solid rgba(255,80,80,0.45);}"
        )
        delete.clicked.connect(lambda: self.delete_requested.emit(self._wf_id, wf["name"]))
        lay.addWidget(delete)

        self._set_style(False)

    @staticmethod
    def _toggle_style(enabled: bool) -> str:
        if enabled:
            return (
                "QPushButton{color:#00c853;background:rgba(0,200,83,0.10);"
                "border:1px solid rgba(0,200,83,0.35);"
                "font-family:'Roboto Mono';font-size:9px;font-weight:700;}"
                "QPushButton:hover{background:rgba(0,200,83,0.22);}"
            )
        return (
            "QPushButton{color:rgba(132,147,150,0.55);background:transparent;"
            "border:1px solid rgba(132,147,150,0.20);"
            "font-family:'Roboto Mono';font-size:9px;font-weight:700;}"
            "QPushButton:hover{background:rgba(132,147,150,0.10);}"
        )

    def _on_toggle(self):
        self.toggle_requested.emit(self._wf_id, not self._enabled)

    def set_active(self, v: bool):
        self._set_style(v)

    def _set_style(self, active: bool):
        if active:
            self.setStyleSheet("background:rgba(0,229,255,0.07);border-radius:4px;")
        else:
            self.setStyleSheet("background:transparent;")

    def mousePressEvent(self, _):
        self.selected.emit(self._idx)


class StepBreakdown(GlassPanel):
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
            lbl = QLabel(step_label(step))
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
