"""AutomationView — AUTOMATION_CORE: workflow library and execution log."""

from __future__ import annotations

import re

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import (
    QDialog,
    QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from core.automation import workflow_library
from ui.theme import BG, CYAN, FM, PRIMARY
from ui.widgets import GlassPanel, StatusPip, TerminalLog, _mono, _panel_header


# ─────────────────────────────────────────────────────────────────────────────


class _GlassDialog(QDialog):
    """Frameless JARVIS-themed modal base."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag_pos = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._card = QWidget(self)
        self._card.setObjectName("_card")
        self._card.setStyleSheet(
            "#_card{background:#0d1618;"
            "border:1px solid rgba(0,229,255,0.22);border-radius:6px;}"
        )
        root.addWidget(self._card)

        self._body = QVBoxLayout(self._card)
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(0)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, _):
        self._drag_pos = None


# ─────────────────────────────────────────────────────────────────────────────


class _NewWorkflowDialog(_GlassDialog):

    def __init__(self, parent=None, workflow: dict | None = None):
        super().__init__(parent)
        self.setMinimumWidth(460)
        is_edit = workflow is not None

        # Title bar
        title_bar = QWidget()
        title_bar.setFixedHeight(40)
        title_bar.setStyleSheet("background:transparent;")
        tb = QHBoxLayout(title_bar)
        tb.setContentsMargins(16, 0, 12, 0)
        lbl = QLabel("EDIT WORKFLOW" if is_edit else "NEW WORKFLOW")
        lbl.setFont(_mono(11, bold=True))
        lbl.setStyleSheet(f"color:{CYAN};letter-spacing:2px;background:transparent;border:none;")
        x_btn = QPushButton("✕")
        x_btn.setFixedSize(20, 20)
        x_btn.setCursor(Qt.PointingHandCursor)
        x_btn.setStyleSheet(
            "QPushButton{color:rgba(255,80,80,0.6);background:transparent;border:none;font-size:11px;}"
            "QPushButton:hover{color:rgba(255,80,80,1.0);}"
        )
        x_btn.clicked.connect(self.reject)
        tb.addWidget(lbl, 1)
        tb.addWidget(x_btn)
        self._body.addWidget(title_bar)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:rgba(0,229,255,0.15);background:rgba(0,229,255,0.15);")
        sep.setFixedHeight(1)
        self._body.addWidget(sep)

        form = QWidget()
        form.setStyleSheet("background:transparent;")
        fl = QVBoxLayout(form)
        fl.setContentsMargins(16, 14, 16, 16)
        fl.setSpacing(10)

        self._name_inp = self._field(fl, "WORKFLOW NAME", "Morning Routine")
        self._trigger_inp = self._field(fl, "TRIGGER PHRASE", "run morning routine")

        steps_lbl = QLabel("STEPS  —  one command per line")
        steps_lbl.setStyleSheet(
            f"color:{CYAN};font-size:10px;letter-spacing:1.5px;background:transparent;border:none;"
        )
        fl.addWidget(steps_lbl)

        self._steps_edit = QTextEdit()
        self._steps_edit.setAcceptRichText(False)
        self._steps_edit.setMinimumHeight(110)
        self._steps_edit.setPlaceholderText(
            "open chrome\nsearch youtube for lofi beats\ntake a screenshot"
        )
        self._steps_edit.setStyleSheet(
            "QTextEdit{background:#121a1b;color:#dce4e5;"
            "border:1px solid rgba(0,229,255,0.22);border-radius:4px;"
            "padding:8px 10px;font-family:'Roboto Mono';font-size:11px;}"
            "QTextEdit:focus{border:1px solid rgba(0,229,255,0.55);}"
        )
        self._steps_edit.textChanged.connect(self._update_counter)
        fl.addWidget(self._steps_edit)

        self._counter_lbl = QLabel("0 STEPS")
        self._counter_lbl.setStyleSheet(
            "color:rgba(132,147,150,0.6);font-family:'Roboto Mono';"
            "font-size:10px;background:transparent;border:none;"
        )
        fl.addWidget(self._counter_lbl, 0, Qt.AlignRight)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)

        cancel = QPushButton("CANCEL")
        cancel.setFixedHeight(30)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(
            "QPushButton{color:rgba(132,147,150,0.7);background:transparent;"
            "border:1px solid rgba(132,147,150,0.25);border-radius:4px;"
            "font-family:'Roboto Mono';font-size:10px;font-weight:700;padding:0 18px;}"
            "QPushButton:hover{color:rgba(195,245,255,0.8);}"
        )
        cancel.clicked.connect(self.reject)

        create = QPushButton("SAVE" if is_edit else "CREATE")
        create.setFixedHeight(30)
        create.setCursor(Qt.PointingHandCursor)
        create.setDefault(True)
        create.setStyleSheet(
            f"QPushButton{{color:{CYAN};background:rgba(0,229,255,0.08);"
            "border:1px solid rgba(0,229,255,0.35);border-radius:4px;"
            "font-family:'Roboto Mono';font-size:10px;font-weight:700;padding:0 18px;}"
            "QPushButton:hover{background:rgba(0,229,255,0.20);}"
        )
        create.clicked.connect(self.accept)

        btn_row.addWidget(cancel)
        btn_row.addWidget(create)
        fl.addLayout(btn_row)

        self._body.addWidget(form)
        if workflow:
            self._name_inp.setText(str(workflow.get("name", "")))
            self._trigger_inp.setText(str(workflow.get("trigger", "")))
            step_lines = [s if isinstance(s, str) else _step_label(s) for s in workflow.get("steps", [])]
            self._steps_edit.setPlainText("\n".join(step_lines))
            self._update_counter()

    @staticmethod
    def _field(layout: QVBoxLayout, label: str, placeholder: str) -> QLineEdit:
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color:{CYAN};font-size:10px;letter-spacing:1.5px;background:transparent;border:none;"
        )
        inp = QLineEdit()
        inp.setFixedHeight(32)
        inp.setPlaceholderText(placeholder)
        inp.setStyleSheet(
            "QLineEdit{background:#121a1b;color:#dce4e5;"
            "border:1px solid rgba(0,229,255,0.22);border-radius:4px;"
            "padding:0 10px;font-family:'Roboto Mono';font-size:12px;}"
            "QLineEdit:focus{border:1px solid rgba(0,229,255,0.55);}"
        )
        layout.addWidget(lbl)
        layout.addWidget(inp)
        return inp

    def _update_counter(self):
        n = len([s for s in self._steps_edit.toPlainText().splitlines() if s.strip()])
        self._counter_lbl.setText(f"{n} STEP{'S' if n != 1 else ''}")

    def get_values(self) -> tuple[str, str, list[str]]:
        name = self._name_inp.text().strip()
        trigger = self._trigger_inp.text().strip()
        steps = [s.strip() for s in self._steps_edit.toPlainText().splitlines() if s.strip()]
        return name, trigger, steps


# ─────────────────────────────────────────────────────────────────────────────


class _ConfirmDeleteDialog(_GlassDialog):

    def __init__(self, display_name: str, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(360)

        title_bar = QWidget()
        title_bar.setFixedHeight(40)
        title_bar.setStyleSheet("background:transparent;")
        tb = QHBoxLayout(title_bar)
        tb.setContentsMargins(16, 0, 12, 0)
        lbl = QLabel("⚠  CONFIRM DELETE")
        lbl.setFont(_mono(10, bold=True))
        lbl.setStyleSheet(
            "color:rgba(255,219,60,0.9);letter-spacing:1.5px;background:transparent;border:none;"
        )
        tb.addWidget(lbl, 1)
        self._body.addWidget(title_bar)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:rgba(255,219,60,0.18);background:rgba(255,219,60,0.18);")
        sep.setFixedHeight(1)
        self._body.addWidget(sep)

        bw = QWidget()
        bw.setStyleSheet("background:transparent;")
        bl = QVBoxLayout(bw)
        bl.setContentsMargins(16, 16, 16, 16)
        bl.setSpacing(14)

        msg = QLabel(f"Delete  <b>{display_name}</b>?<br>This cannot be undone.")
        msg.setStyleSheet(
            "color:rgba(195,245,255,0.80);font-family:'Roboto Mono';"
            "font-size:12px;background:transparent;border:none;"
        )
        msg.setWordWrap(True)
        bl.addWidget(msg)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)

        cancel = QPushButton("CANCEL")
        cancel.setFixedHeight(30)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(
            "QPushButton{color:rgba(132,147,150,0.7);background:transparent;"
            "border:1px solid rgba(132,147,150,0.25);border-radius:4px;"
            "font-family:'Roboto Mono';font-size:10px;font-weight:700;padding:0 18px;}"
            "QPushButton:hover{color:rgba(195,245,255,0.8);}"
        )
        cancel.clicked.connect(self.reject)

        del_btn = QPushButton("DELETE")
        del_btn.setFixedHeight(30)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setStyleSheet(
            "QPushButton{color:rgba(255,80,80,0.9);background:rgba(255,80,80,0.08);"
            "border:1px solid rgba(255,80,80,0.35);border-radius:4px;"
            "font-family:'Roboto Mono';font-size:10px;font-weight:700;padding:0 18px;}"
            "QPushButton:hover{background:rgba(255,80,80,0.18);}"
        )
        del_btn.clicked.connect(self.accept)

        btn_row.addWidget(cancel)
        btn_row.addWidget(del_btn)
        bl.addLayout(btn_row)

        self._body.addWidget(bw)


# ─────────────────────────────────────────────────────────────────────────────


class _WorkflowRow(QWidget):
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
        self._toggle_btn = toggle

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
            # Bypass NLP for Play clicks so we always execute the selected
            # saved workflow, not a model-reconstructed approximation.
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
    if isinstance(step, str):
        return step
    action = step.get("action", step.get("intent", "unknown"))
    return action.replace("_", " ").title()


class AutomationView(QWidget):
    run_command = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[_WorkflowRow] = []
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

        self._breakdown = _StepBreakdown()
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
        while self._row_container_lay.count():
            item = self._row_container_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows.clear()
        self._build_rows(log_init=False)

    def _create_workflow(self):
        dlg = _NewWorkflowDialog(self)
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
        dlg = _NewWorkflowDialog(self, workflow=wf)
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
        dlg = _ConfirmDeleteDialog(display_name, self)
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
