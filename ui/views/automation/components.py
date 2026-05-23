"""Workflow row and breakdown components for AutomationView.

Redesigned 2026-05 to match the HTML mockup:
  WorkflowRow — name + "N steps · schedule" + ON/PAUSED label, cyan left
                accent on active. Inline buttons (play/delete/toggle) are
                gone — those moved to StepBreakdown's action bar where
                they have room to breathe.
  StepBreakdown — big workflow name + summary + 4 action buttons
                  (RUN NOW · PAUSE/RESUME · EDIT · DELETE), schedule +
                  trigger + enabled fields, then the step pipeline with
                  intent badges.
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ui.components.design import (
    AMBER,
    BG_PANEL,
    CYAN_FAINT,
    CYAN_SOFT,
    GREEN,
    INK,
    INK_DIM,
    INK_FAINT,
    RED,
    IntentBadge,
    PanelCard,
)
from ui.theme import CYAN, FM


# ── Helpers ──────────────────────────────────────────────────────────────────


def step_label(step) -> str:
    """Display name for a step. Keep the old free function — used by dialogs."""
    if isinstance(step, str):
        return step
    action = step.get("action", step.get("intent", "unknown"))
    return action.replace("_", " ").title()


def _step_intent(step) -> str:
    """Pull the intent string from a step dict, or heuristically guess one
    for a plain-string step.

    Why guess: workflow steps stored as natural-language strings (the
    NewWorkflowDialog format) carry no intent metadata until the brain
    resolves them at run-time. We still want to show a coloured badge in
    the UI immediately. The guesser uses a tiny keyword map keyed on the
    leading verb / phrase — it's lossy but useful, and it never affects
    actual execution (the brain still resolves at run-time).
    """
    if isinstance(step, dict):
        return step.get("intent") or "unknown"
    return _guess_intent_from_text(str(step))


def _guess_intent_from_text(text: str) -> str:
    """Best-effort intent classifier for natural-language step strings."""
    t = text.lower().strip()
    if not t:
        return "unknown"
    # Order matters — more specific phrases first.
    keyword_map: tuple[tuple[tuple[str, ...], str], ...] = (
        (("take a screenshot", "screenshot", "screen capture"), "system_control"),
        (("volume up", "volume down", "mute", "unmute", "brightness",
          "lock screen", "shutdown", "restart", "sleep", "wifi", "bluetooth"),
         "system_control"),
        (("search ", "google ", "youtube search", "wikipedia", "look up"), "search_web"),
        (("open ", "launch ", "start "), "open_app"),
        (("close ", "quit ", "kill "), "close_app"),
        (("read screen", "what's on", "describe", "look at", "vision",
          "analyze image", "what do you see"), "vision_analysis"),
        (("ocr", "read text from"), "read_screen"),
        (("create file", "create folder", "new file", "make a file",
          "delete file", "rename", "move file", "copy file", "list files",
          "find files", "find in files", "search files", "edit file",
          "replace in", "append "), "file_operation"),
        (("type ", "press "), "type_text"),
        (("click ", "double click", "right click", "scroll", "drag "), "control_mouse"),
        (("navigate", "go to", "browse", "switch tab", "close tab",
          "click element", "fill form", "read page"), "browser_automation"),
        (("run ", "git ", "npm ", "pip ", "python ", "powershell", "cmd ",
          "execute"), "code_execution"),
        (("remind", "set a reminder", "remind me"), "reminder_task"),
        (("weather",), "weather"),
        (("create a doc", "create document", "create a report", "write a memo",
          "build a deck", "make slides", "compile a pdf", "create spreadsheet"),
         "document_creation"),
    )
    for triggers, intent in keyword_map:
        for kw in triggers:
            if kw in t:
                return intent
    return "unknown"


def _step_summary(step) -> str:
    """One-line summary shown in the right pane's step pipeline."""
    if isinstance(step, str):
        return step
    action = step.get("action") or step.get("intent") or "unknown"
    params = step.get("parameters") or {}
    # Compact: action · key1=val1, key2=val2  (cap at 80 chars)
    if params:
        bits = []
        for k, v in list(params.items())[:3]:
            sv = str(v)
            if len(sv) > 30:
                sv = sv[:27] + "…"
            bits.append(f"{k}={sv}")
        return f"{action} · {', '.join(bits)}"
    return action


# Map intent → short human label for the row's badge.
_INTENT_KEY_FALLBACK = "automation"


# ── WorkflowRow ──────────────────────────────────────────────────────────────


class WorkflowRow(QWidget):
    """One row in the WORKFLOW LIBRARY list.

    Signal: ``selected(idx)`` fires when the row is clicked. Inline action
    buttons (play / pause / delete) intentionally don't live here anymore —
    they're in the StepBreakdown action bar where the user has more room.
    """

    selected = pyqtSignal(int)

    # Legacy signals kept on the class for source-compat with any external
    # caller — the new view wires actions through StepBreakdown instead so
    # these never fire in practice.
    run_requested = pyqtSignal(str)
    toggle_requested = pyqtSignal(str, bool)
    delete_requested = pyqtSignal(str, str)

    def __init__(self, idx: int, wf: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._idx = idx
        self._wf_id = str(wf.get("id", ""))
        self._enabled = bool(wf.get("enabled", True))
        self._active = False

        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(58)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 14, 10)
        lay.setSpacing(10)

        # ── Left column: name + sub line ────────────────────────────────────
        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(3)

        # Name color is driven by _set_style(): INK when inactive, CYAN when
        # active — matches the mockup where only the selected row's name
        # lights up cyan.
        self._name_lbl = QLabel(str(wf.get("name", wf.get("id", "—"))))
        info.addWidget(self._name_lbl)

        sub_row = QHBoxLayout()
        sub_row.setContentsMargins(0, 0, 0, 0)
        sub_row.setSpacing(8)

        steps_n = len(wf.get("steps", []))
        self._steps_lbl = QLabel(f"{steps_n} step{'s' if steps_n != 1 else ''}")
        self._steps_lbl.setStyleSheet(
            "QLabel {"
            f"color: {INK_DIM};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 11px;"
            "}"
        )
        sub_row.addWidget(self._steps_lbl)

        # Schedule badge OR "manual"
        schedule = str(wf.get("schedule", "") or "").strip()
        if schedule:
            sep = QLabel("·")
            sep.setStyleSheet(
                f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
                f"font-family: '{FM}'; font-size: 11px; }}"
            )
            sub_row.addWidget(sep)

            sched_badge = QLabel(schedule)
            sched_badge.setStyleSheet(
                "QLabel {"
                f"color: {AMBER};"
                f"border: 1px solid {AMBER};"
                "border-radius: 3px;"
                "padding: 1px 6px;"
                f"font-family: '{FM}';"
                "font-size: 10px;"
                "font-weight: 700;"
                "letter-spacing: 0.5px;"
                "background: transparent;"
                "}"
            )
            sched_badge.setToolTip(f"Cron schedule: {schedule}")
            sub_row.addWidget(sched_badge)
        else:
            sep = QLabel("·")
            sep.setStyleSheet(
                f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
                f"font-family: '{FM}'; font-size: 11px; }}"
            )
            sub_row.addWidget(sep)
            manual_lbl = QLabel("manual")
            manual_lbl.setStyleSheet(
                f"QLabel {{ color: {INK_DIM}; background: transparent; border: none;"
                f"font-family: '{FM}'; font-size: 11px; letter-spacing: 0.5px; }}"
            )
            sub_row.addWidget(manual_lbl)

        sub_row.addStretch(1)
        sub_wrap = QWidget()
        sub_wrap.setStyleSheet("QWidget { background: transparent; }")
        sub_wrap.setLayout(sub_row)
        info.addWidget(sub_wrap)
        lay.addLayout(info, 1)

        # ── Right column: ON / PAUSED status text ──────────────────────────
        self._status_lbl = QLabel("ON" if self._enabled else "PAUSED")
        self._status_lbl.setStyleSheet(self._status_style(self._enabled))
        lay.addWidget(self._status_lbl, 0, Qt.AlignVCenter)

        self._set_style(False)

    # ── Public API ───────────────────────────────────────────────────────────

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        self._set_style(active)

    # ── Style helpers ────────────────────────────────────────────────────────

    def _set_style(self, active: bool) -> None:
        # Bottom divider runs on every row (matches mockup), regardless of
        # active state. The 0.07 alpha is intentionally thinner than
        # CYAN_FAINT so the list reads as a quiet ladder, not a grid.
        divider = "rgba(0,229,255,0.07)"
        if active:
            self.setStyleSheet(
                "QWidget {"
                "background: rgba(0,229,255,0.04);"
                f"border-left: 2px solid {CYAN};"
                "border-top: 1px solid transparent;"
                "border-right: 1px solid transparent;"
                f"border-bottom: 1px solid {divider};"
                "}"
            )
        else:
            self.setStyleSheet(
                "QWidget {"
                "background: transparent;"
                "border-left: 2px solid transparent;"
                "border-top: 1px solid transparent;"
                "border-right: 1px solid transparent;"
                f"border-bottom: 1px solid {divider};"
                "}"
            )
        # Name color flip: cyan when selected, plain ink otherwise.
        name_color = CYAN if active else INK
        self._name_lbl.setStyleSheet(
            "QLabel {"
            f"color: {name_color};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 13px;"
            "font-weight: 700;"
            "letter-spacing: 0.5px;"
            "}"
        )

    @staticmethod
    def _status_style(enabled: bool) -> str:
        color = GREEN if enabled else INK_FAINT
        return (
            "QLabel {"
            f"color: {color};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "font-weight: 700;"
            "letter-spacing: 1.5px;"
            "}"
        )

    # ── Mouse ────────────────────────────────────────────────────────────────

    def mousePressEvent(self, _event) -> None:
        self.selected.emit(self._idx)


# ── StepBreakdown ────────────────────────────────────────────────────────────


class StepBreakdown(PanelCard):
    """Right pane: detail view of the selected workflow."""

    # Signals fired by the action buttons. The view connects them to its
    # workflow-mutating slots.
    run_requested    = pyqtSignal(str)            # workflow_id
    toggle_requested = pyqtSignal(str, bool)      # workflow_id, enabled
    edit_requested   = pyqtSignal()               # current selection (view tracks it)
    delete_requested = pyqtSignal(str, str)       # workflow_id, display_name
    add_step_requested = pyqtSignal()             # opens edit dialog (alias of edit_requested)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent=parent)
        self._wf: dict = {}

        body = self.body()
        body.setContentsMargins(16, 14, 16, 14)
        body.setSpacing(12)

        # ── Empty state ─────────────────────────────────────────────────────
        self._empty_lbl = QLabel("SELECT A WORKFLOW")
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setStyleSheet(
            "QLabel {"
            "color: rgba(0,229,255,0.22);"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 11px;"
            "font-weight: 700;"
            "letter-spacing: 3px;"
            "padding: 60px 0;"
            "}"
        )
        body.addWidget(self._empty_lbl, 0, Qt.AlignCenter)

        # ── Filled state (built lazily, hidden initially) ──────────────────
        self._filled = QWidget()
        self._filled.setStyleSheet("QWidget { background: transparent; }")
        self._filled_lay = QVBoxLayout(self._filled)
        self._filled_lay.setContentsMargins(0, 0, 0, 0)
        self._filled_lay.setSpacing(14)

        # Title + summary row
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        self._wf_name_lbl = QLabel("—")
        self._wf_name_lbl.setStyleSheet(
            "QLabel {"
            f"color: {CYAN};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 18px;"
            "font-weight: 700;"
            "letter-spacing: 1.5px;"
            "}"
        )
        title_col.addWidget(self._wf_name_lbl)

        self._wf_summary_lbl = QLabel("")
        self._wf_summary_lbl.setStyleSheet(
            "QLabel {"
            f"color: {INK_DIM};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "letter-spacing: 0.5px;"
            "}"
        )
        title_col.addWidget(self._wf_summary_lbl)
        title_row.addLayout(title_col, 1)

        # Action buttons
        self._btn_run = self._mk_btn("▶ RUN NOW", primary=True)
        self._btn_run.clicked.connect(self._on_run_clicked)
        self._btn_pause = self._mk_btn("PAUSE")
        self._btn_pause.clicked.connect(self._on_pause_clicked)
        self._btn_edit = self._mk_btn("EDIT")
        self._btn_edit.clicked.connect(lambda: self.edit_requested.emit())
        self._btn_delete = self._mk_btn("DELETE", danger=True)
        self._btn_delete.clicked.connect(self._on_delete_clicked)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(6)
        actions_row.addStretch(1)
        actions_row.addWidget(self._btn_run)
        actions_row.addWidget(self._btn_pause)
        actions_row.addWidget(self._btn_edit)
        actions_row.addWidget(self._btn_delete)
        title_row.addLayout(actions_row)
        self._filled_lay.addLayout(title_row)

        # ── Meta block (Schedule / Trigger / Enabled) ──────────────────────
        meta = QFrame()
        meta.setStyleSheet(
            "QFrame {"
            "background: transparent;"
            "border: none;"
            "}"
        )
        meta_lay = QVBoxLayout(meta)
        meta_lay.setContentsMargins(0, 0, 0, 0)
        meta_lay.setSpacing(8)
        self._row_schedule = self._mk_meta_row("SCHEDULE", "—")
        self._row_trigger  = self._mk_meta_row("TRIGGER", "—")
        self._row_enabled  = self._mk_meta_row("ENABLED", "—",
                                                value_color=GREEN)
        meta_lay.addWidget(self._row_schedule["wrap"])
        meta_lay.addWidget(self._row_trigger["wrap"])
        meta_lay.addWidget(self._row_enabled["wrap"])
        self._filled_lay.addWidget(meta)

        # ── Steps section header ───────────────────────────────────────────
        self._steps_header_lbl = QLabel("STEPS · 0")
        self._steps_header_lbl.setStyleSheet(
            "QLabel {"
            f"color: {CYAN};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "font-weight: 700;"
            "letter-spacing: 2.2px;"
            "}"
        )
        self._filled_lay.addWidget(self._steps_header_lbl)

        # ── Steps container (rebuilt per workflow) ─────────────────────────
        self._steps_container = QWidget()
        self._steps_container.setStyleSheet("QWidget { background: transparent; }")
        self._steps_lay = QVBoxLayout(self._steps_container)
        self._steps_lay.setContentsMargins(0, 0, 0, 0)
        self._steps_lay.setSpacing(6)
        self._filled_lay.addWidget(self._steps_container)

        # ── Add Step button ────────────────────────────────────────────────
        self._btn_add_step = QPushButton("+ ADD STEP")
        self._btn_add_step.setCursor(Qt.PointingHandCursor)
        self._btn_add_step.setStyleSheet(
            "QPushButton {"
            "background: transparent;"
            f"color: {INK_DIM};"
            f"border: 1px solid {CYAN_FAINT};"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "font-weight: 700;"
            "padding: 8px 12px;"
            "letter-spacing: 2px;"
            "text-align: left;"
            "}"
            f"QPushButton:hover {{ background: rgba(0,229,255,0.08); color: {CYAN}; }}"
        )
        self._btn_add_step.clicked.connect(lambda: self.edit_requested.emit())
        self._filled_lay.addWidget(self._btn_add_step)

        self._filled_lay.addStretch(1)
        body.addWidget(self._filled, 1)
        self._filled.setVisible(False)

    # ── Builders ─────────────────────────────────────────────────────────────

    def _mk_btn(self, text: str, *, primary: bool = False, danger: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        if primary:
            bg = CYAN
            color = "#001a1f"
            border = CYAN
            hover = "background: #5ff2ff;"
        elif danger:
            bg = "transparent"
            color = RED
            border = RED
            hover = "background: rgba(255,107,107,0.10);"
        else:
            bg = "transparent"
            color = CYAN
            border = CYAN_SOFT
            hover = "background: rgba(0,229,255,0.10);"
        btn.setStyleSheet(
            "QPushButton {"
            f"background: {bg};"
            f"color: {color};"
            f"border: 1px solid {border};"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "font-weight: 700;"
            "padding: 7px 14px;"
            "letter-spacing: 1.6px;"
            "}"
            "QPushButton:hover {" + hover + "}"
        )
        return btn

    def _mk_meta_row(self, label: str, value: str, *,
                     value_color: str = INK) -> dict:
        wrap = QFrame()
        wrap.setStyleSheet("QFrame { background: transparent; border: none; }")
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(14)

        lbl = QLabel(label)
        lbl.setFixedWidth(82)
        lbl.setStyleSheet(
            "QLabel {"
            f"color: {CYAN};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 9.5px;"
            "font-weight: 700;"
            "letter-spacing: 2px;"
            "}"
        )
        wl.addWidget(lbl)

        val = QLabel(value)
        val.setStyleSheet(
            "QLabel {"
            f"color: {value_color};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 11.5px;"
            "}"
        )
        val.setWordWrap(True)
        wl.addWidget(val, 1)
        return {"wrap": wrap, "label": lbl, "value": val}

    # ── Public API ───────────────────────────────────────────────────────────

    def show_workflow(self, wf: dict) -> None:
        self._wf = wf or {}
        if not self._wf:
            self._filled.setVisible(False)
            self._empty_lbl.setVisible(True)
            return

        self._empty_lbl.setVisible(False)
        self._filled.setVisible(True)

        name = str(self._wf.get("name", self._wf.get("id", "—")))
        self._wf_name_lbl.setText(name)

        steps = self._wf.get("steps") or []
        runs = self._wf.get("runs") or self._wf.get("run_count") or 0
        last_run = self._wf.get("last_run") or ""
        summary_bits = []
        if last_run:
            summary_bits.append(f"last fired {last_run[:19].replace('T', ' ')}")
        summary_bits.append(f"{len(steps)} step{'s' if len(steps) != 1 else ''}")
        if runs:
            summary_bits.append(f"{runs} run{'s' if runs != 1 else ''}")
        self._wf_summary_lbl.setText(" · ".join(summary_bits))

        # Pause button label tracks enabled state
        enabled = bool(self._wf.get("enabled", True))
        self._btn_pause.setText("PAUSE" if enabled else "RESUME")

        # Meta rows
        schedule = str(self._wf.get("schedule", "") or "").strip()
        if schedule:
            self._row_schedule["value"].setText(schedule)
            self._row_schedule["value"].setStyleSheet(
                "QLabel {"
                f"color: {AMBER};"
                "background: transparent;"
                "border: none;"
                f"font-family: '{FM}';"
                "font-size: 11.5px;"
                "letter-spacing: 0.5px;"
                "}"
            )
        else:
            self._row_schedule["value"].setText("manual only")
            self._row_schedule["value"].setStyleSheet(
                "QLabel {"
                f"color: {INK_DIM};"
                "background: transparent;"
                "border: none;"
                f"font-family: '{FM}';"
                "font-size: 11.5px;"
                "}"
            )

        trigger = str(self._wf.get("trigger", "") or "").strip()
        self._row_trigger["value"].setText(trigger or "—")

        self._row_enabled["value"].setText("ON" if enabled else "PAUSED")
        self._row_enabled["value"].setStyleSheet(
            "QLabel {"
            f"color: {GREEN if enabled else INK_FAINT};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 11.5px;"
            "font-weight: 700;"
            "letter-spacing: 1px;"
            "}"
        )

        # Steps header + list
        self._steps_header_lbl.setText(f"STEPS · {len(steps)}")
        # Clear and rebuild
        while self._steps_lay.count():
            item = self._steps_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for i, step in enumerate(steps):
            self._steps_lay.addWidget(self._build_step_row(i, step))

    # ── Step row builder ─────────────────────────────────────────────────────

    def _build_step_row(self, idx: int, step) -> QFrame:
        row = QFrame()
        row.setStyleSheet(
            "QFrame {"
            f"background: {BG_PANEL};"
            f"border: 1px solid {CYAN_FAINT};"
            "}"
        )
        rl = QHBoxLayout(row)
        rl.setContentsMargins(10, 7, 12, 7)
        rl.setSpacing(10)

        num = QLabel(f"{idx + 1}")
        num.setFixedWidth(18)
        num.setStyleSheet(
            "QLabel {"
            f"color: {INK_FAINT};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "}"
        )
        rl.addWidget(num)

        intent = _step_intent(step)
        if intent and intent != "unknown":
            rl.addWidget(IntentBadge(intent))

        summary = QLabel(_step_summary(step))
        summary.setStyleSheet(
            "QLabel {"
            f"color: {INK};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 11.5px;"
            "}"
        )
        summary.setToolTip(_step_summary(step))
        rl.addWidget(summary, 1)
        return row

    # ── Action handlers ──────────────────────────────────────────────────────

    def _on_run_clicked(self) -> None:
        wid = str(self._wf.get("id", ""))
        if wid:
            # AutomationView listens on `run_command(str)` and recognises
            # the `__run_workflow_id__:{wid}` prefix as a direct run.
            self.run_requested.emit(f"__run_workflow_id__:{wid}")

    def _on_pause_clicked(self) -> None:
        wid = str(self._wf.get("id", ""))
        if not wid:
            return
        new_enabled = not bool(self._wf.get("enabled", True))
        self.toggle_requested.emit(wid, new_enabled)

    def _on_delete_clicked(self) -> None:
        wid = str(self._wf.get("id", ""))
        name = str(self._wf.get("name", wid))
        if wid:
            self.delete_requested.emit(wid, name)
