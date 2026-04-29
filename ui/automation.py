"""AutomationView — AUTOMATION_CORE: workflow library and execution log."""

from __future__ import annotations

import re

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import (
    QDialog,
    QFrame, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from core.automation import workflow_library
from ui.automation_components import StepBreakdown, WorkflowRow
from ui.automation_dialogs import ConfirmDeleteDialog, NewWorkflowDialog
from ui.theme import BG, CYAN, FM, PRIMARY
from ui.widgets import GlassPanel, TerminalLog, _panel_header


class AutomationView(QWidget):
    run_command = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[WorkflowRow] = []
        self._selected_workflow_id: str = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        title = QLabel("AUTOMATION_CORE")
        title.setStyleSheet(
            f"QLabel{{color:{PRIMARY};font-family:'Space Grotesk';"
            "font-size:40px;font-weight:700;background:transparent;border:none;}"
        )
        subtitle = QLabel("WORKFLOW ORCHESTRATOR  //  ROUTINE MANAGEMENT")
        subtitle.setStyleSheet(
            "QLabel{color:rgba(132,147,150,0.9);font-family:'Roboto Mono';"
            "font-size:11px;letter-spacing:1px;background:transparent;border:none;}"
        )
        root.addWidget(title)
        root.addWidget(subtitle)

        body = QHBoxLayout()
        body.setSpacing(12)

        self._lib = GlassPanel()
        self._lib.set_fill_color(QColor(10, 17, 19, 220))
        lib_lay = QVBoxLayout(self._lib)
        lib_lay.setContentsMargins(0, 0, 0, 0)
        lib_lay.setSpacing(0)

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
        new_btn = QPushButton("+ NEW")
        new_btn.setFixedHeight(22)
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.setStyleSheet(
            f"QPushButton{{color:{CYAN};background:rgba(0,229,255,0.08);"
            "border:1px solid rgba(0,229,255,0.30);border-radius:3px;"
            "font-family:'Roboto Mono';font-size:9px;font-weight:700;"
            "padding:0 8px;letter-spacing:1px;}"
            "QPushButton:hover{background:rgba(0,229,255,0.20);}"
        )
        new_btn.clicked.connect(self._create_workflow)
        self._edit_btn = QPushButton("EDIT")
        self._edit_btn.setFixedHeight(22)
        self._edit_btn.setCursor(Qt.PointingHandCursor)
        self._edit_btn.setEnabled(False)
        self._edit_btn.setStyleSheet(
            f"QPushButton{{color:{CYAN};background:rgba(0,229,255,0.06);"
            "border:1px solid rgba(0,229,255,0.24);border-radius:3px;"
            "font-family:'Roboto Mono';font-size:9px;font-weight:700;"
            "padding:0 8px;letter-spacing:1px;}"
            "QPushButton:hover{background:rgba(0,229,255,0.16);}"
            "QPushButton:disabled{color:rgba(132,147,150,0.45);"
            "background:transparent;border:1px solid rgba(132,147,150,0.16);}"
        )
        self._edit_btn.clicked.connect(self._edit_selected_workflow)

        lib_hdr_lay.addWidget(lib_title, 1)
        lib_hdr_lay.addWidget(self._wf_count_lbl)
        lib_hdr_lay.addWidget(self._edit_btn)
        lib_hdr_lay.addWidget(new_btn)

        lib_sep = QFrame()
        lib_sep.setFrameShape(QFrame.HLine)
        lib_sep.setStyleSheet("color:rgba(0,229,255,0.15);background:rgba(0,229,255,0.15);")
        lib_sep.setFixedHeight(1)

        lib_lay.addWidget(lib_hdr)
        lib_lay.addWidget(lib_sep)

        self._row_container = QWidget()
        self._row_container.setStyleSheet("background:transparent;")
        self._row_container_lay = QVBoxLayout(self._row_container)
        self._row_container_lay.setContentsMargins(0, 0, 0, 0)
        self._row_container_lay.setSpacing(0)
        lib_lay.addWidget(self._row_container, 1)

        body.addWidget(self._lib, 1)

        self._breakdown = StepBreakdown()
        body.addWidget(self._breakdown, 1)

        # Give more space to the execution log: top panels are shorter.
        root.addLayout(body, 3)

        log_panel = GlassPanel()
        log_panel.set_fill_color(QColor(10, 17, 19, 220))
        log_panel.setMinimumHeight(170)
        log_lay = QVBoxLayout(log_panel)
        log_lay.setContentsMargins(0, 0, 0, 0)
        log_lay.setSpacing(0)

        log_hdr, log_sep = _panel_header("EXECUTION LOG")
        log_lay.addWidget(log_hdr)
        log_lay.addWidget(log_sep)

        self._exec_log = TerminalLog()
        log_lay.addWidget(self._exec_log, 1)

        root.addWidget(log_panel, 2)

        self._build_rows(log_init=True)

        from core.signals import signals
        signals.workflow_library_changed.connect(self.refresh)

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
            row = WorkflowRow(i, wf)
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
        while self._row_container_lay.count():
            item = self._row_container_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows.clear()
        self._build_rows(log_init=False)

    def _create_workflow(self):
        dlg = NewWorkflowDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        name, trigger, steps = dlg.get_values()
        if not name:
            return
        if not trigger:
            trigger = f"run {name.lower()}"
        wf_id = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")
        if not wf_id:
            return
        base_id = wf_id
        existing = {w["id"] for w in workflow_library.list_all()}
        n = 1
        while wf_id in existing:
            wf_id = f"{base_id}_{n}"
            n += 1
        workflow_library.add({
            "id": wf_id,
            "name": name,
            "trigger": trigger,
            "steps": steps,
            "enabled": True,
            "last_run": None,
        })
        self._exec_log.append_line(f"[SYSTEM] Workflow '{name}' created with {len(steps)} step(s).")

    def _edit_selected_workflow(self):
        if not self._selected_workflow_id:
            return
        wf = workflow_library.get(self._selected_workflow_id)
        if not wf:
            self._exec_log.append_line("[WARN] Edit failed — selected workflow no longer exists.")
            return
        dlg = NewWorkflowDialog(self, workflow=wf)
        if dlg.exec_() != QDialog.Accepted:
            return
        name, trigger, steps = dlg.get_values()
        if not name:
            return
        if not trigger:
            trigger = f"run {name.lower()}"

        old_id = str(wf.get("id") or self._selected_workflow_id).strip()
        new_id = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")
        if not new_id:
            return

        if new_id != old_id:
            existing = workflow_library.get(new_id)
            if existing is not None:
                self._exec_log.append_line(
                    f"[WARN] Edit blocked — another workflow already uses id '{new_id}'."
                )
                return
            if not workflow_library.rename(old_id, name):
                self._exec_log.append_line(f"[WARN] Edit failed — could not rename '{old_id}'.")
                return
            wf = workflow_library.get(new_id) or {}
            old_id = new_id

        updated = dict(wf)
        updated["id"] = old_id
        updated["name"] = name
        updated["trigger"] = trigger
        updated["steps"] = steps
        workflow_library.add(updated)
        self._selected_workflow_id = old_id
        self._exec_log.append_line(f"[SYSTEM] Workflow '{name}' updated ({len(steps)} step(s)).")

    def _delete_workflow(self, wf_id: str, display_name: str):
        dlg = ConfirmDeleteDialog(display_name, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        ok = workflow_library.remove(wf_id)
        if ok:
            self._exec_log.append_line(f"[SYSTEM] Workflow '{display_name}' deleted.")
        else:
            self._exec_log.append_line(f"[WARN] Delete failed — workflow '{wf_id}' not found.")

    def _toggle_workflow(self, wf_id: str, enabled: bool):
        ok = workflow_library.set_enabled(wf_id, enabled)
        if ok:
            self._exec_log.append_line(f"[SYSTEM] Workflow '{wf_id}' {'enabled' if enabled else 'disabled'}.")
        else:
            self._exec_log.append_line(f"[WARN] Toggle ignored — workflow '{wf_id}' not found.")

    def _select(self, idx: int):
        for i, row in enumerate(self._rows):
            row.set_active(i == idx)
        workflows = workflow_library.list_all()
        if 0 <= idx < len(workflows):
            self._selected_workflow_id = str(workflows[idx].get("id", ""))
            self._edit_btn.setEnabled(True)
            self._breakdown.show_workflow(workflows[idx])
        else:
            self._selected_workflow_id = ""
            self._edit_btn.setEnabled(False)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 229, 255, 20))
        for x in range(0, self.width() + 28, 28):
            for y in range(0, self.height() + 28, 28):
                p.drawEllipse(x - 1, y - 1, 2, 2)
