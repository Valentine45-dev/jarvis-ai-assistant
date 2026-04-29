"""Dialog components for AutomationView."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.theme import CYAN
from ui.widgets import _mono


def _dialog_step_label(step) -> str:
    if isinstance(step, str):
        return step
    action = step.get("action", step.get("intent", "unknown"))
    return action.replace("_", " ").title()


class GlassDialog(QDialog):
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


class NewWorkflowDialog(GlassDialog):
    def __init__(self, parent=None, workflow: dict | None = None):
        super().__init__(parent)
        self.setMinimumWidth(460)
        is_edit = workflow is not None

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
            step_lines = [_dialog_step_label(s) for s in workflow.get("steps", [])]
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


class ConfirmDeleteDialog(GlassDialog):
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
        btn_row.addStretch(1)
        btn_row.setSpacing(8)
        cancel = QPushButton("CANCEL")
        cancel.setFixedHeight(30)
        cancel.clicked.connect(self.reject)
        cancel.setStyleSheet(
            "QPushButton{color:rgba(132,147,150,0.7);background:transparent;"
            "border:1px solid rgba(132,147,150,0.25);border-radius:4px;"
            "font-family:'Roboto Mono';font-size:10px;font-weight:700;padding:0 18px;}"
        )
        del_btn = QPushButton("DELETE")
        del_btn.setFixedHeight(30)
        del_btn.clicked.connect(self.accept)
        del_btn.setStyleSheet(
            "QPushButton{color:rgba(255,80,80,0.9);background:rgba(255,80,80,0.08);"
            "border:1px solid rgba(255,80,80,0.35);border-radius:4px;"
            "font-family:'Roboto Mono';font-size:10px;font-weight:700;padding:0 18px;}"
        )
        btn_row.addWidget(cancel)
        btn_row.addWidget(del_btn)
        bl.addLayout(btn_row)
        self._body.addWidget(bw)
