"""AutomationView — AUTOMATION_CORE.

Redesigned 2026-05 to match the shared HUD grammar:
  - Top 5-tile hero strip (Workflows · Scheduled · Total runs · Last fired · Avg latency)
  - Chip filter row (All · Scheduled · Paused)
  - 2-column body: library list (left, active panel) + step breakdown (right)
  - Drops the legacy execution log — the History view + transcript now own
    "what just ran" so a parallel log here is dead weight.

Public API preserved (main.py wires `run_command` to dispatch routine runs).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.automation import workflow_library
from ui.components.design import (
    AMBER,
    BG_PANEL,
    CYAN_FAINT,
    CYAN_SOFT,
    GREEN,
    INK,
    INK_DIM,
    INK_FAINT,
    ChipFilter,
    HeroMetric,
    PanelCard,
)
from ui.theme import BG, CYAN, FM
from ui.views.automation.components import StepBreakdown, WorkflowRow
from ui.views.automation.dialogs import ConfirmDeleteDialog, NewWorkflowDialog


class AutomationView(QWidget):
    """AUTOMATION_CORE. See module docstring."""

    run_command = pyqtSignal(str)

    # Chip definitions: (key, label). 'all' is the no-filter case.
    _CHIPS: tuple[tuple[str, str], ...] = (
        ("all",       "All"),
        ("scheduled", "Scheduled"),
        ("manual",    "Manual"),
        ("paused",    "Paused"),
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: list[WorkflowRow] = []
        self._selected_workflow_id: str = ""
        self._active_filter: str = "all"

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # ── Header ──────────────────────────────────────────────────────────
        head = QHBoxLayout()
        head.setSpacing(12)
        title = QLabel("AUTOMATION_CORE")
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

        subtitle = QLabel("WORKFLOW ORCHESTRATOR · ROUTINE MANAGEMENT")
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

        self._new_btn = QPushButton("+ NEW WORKFLOW")
        self._new_btn.setCursor(Qt.PointingHandCursor)
        self._new_btn.setStyleSheet(
            "QPushButton {"
            f"background: {CYAN};"
            "color: #001a1f;"
            f"border: 1px solid {CYAN};"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "font-weight: 700;"
            "padding: 6px 14px;"
            "letter-spacing: 2px;"
            "}"
            "QPushButton:hover { background: #5ff2ff; }"
        )
        self._new_btn.clicked.connect(self._create_workflow)
        head.addWidget(self._new_btn)

        self._edit_btn = QPushButton("EDIT")
        self._edit_btn.setCursor(Qt.PointingHandCursor)
        self._edit_btn.setEnabled(False)
        self._edit_btn.setStyleSheet(
            "QPushButton {"
            "background: transparent;"
            f"color: {CYAN};"
            f"border: 1px solid {CYAN_SOFT};"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "font-weight: 700;"
            "padding: 6px 14px;"
            "letter-spacing: 2px;"
            "}"
            "QPushButton:hover { background: rgba(0,229,255,0.10); }"
            "QPushButton:disabled {"
            f"color: {INK_FAINT};"
            f"border-color: {CYAN_FAINT};"
            "}"
        )
        self._edit_btn.clicked.connect(self._edit_selected_workflow)
        head.addWidget(self._edit_btn)
        root.addLayout(head)

        # ── Top stats strip ────────────────────────────────────────────────
        self._stats_wrap = self._build_stats_strip()
        root.addWidget(self._stats_wrap)

        # ── Chip filter row ────────────────────────────────────────────────
        chip_row = QHBoxLayout()
        chip_row.setSpacing(6)
        self._chip_widgets: dict[str, ChipFilter] = {}
        for key, label in self._CHIPS:
            chip = ChipFilter(label, active=(key == "all"))
            chip.clicked.connect(lambda _checked, k=key: self._on_chip_clicked(k))
            self._chip_widgets[key] = chip
            chip_row.addWidget(chip)
        chip_row.addStretch(1)

        self._wf_count_lbl = QLabel("")
        self._wf_count_lbl.setStyleSheet(
            f"QLabel {{ color: {INK_DIM}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 10px; letter-spacing: 1px; }}"
        )
        chip_row.addWidget(self._wf_count_lbl)
        root.addLayout(chip_row)

        # ── 2-column body ──────────────────────────────────────────────────
        body = QHBoxLayout()
        body.setSpacing(14)

        # LEFT: library list (active panel)
        self._lib_panel = PanelCard("Workflow library", active=True)
        self._lib_scroll = QScrollArea()
        self._lib_scroll.setWidgetResizable(True)
        self._lib_scroll.setFrameShape(QScrollArea.NoFrame)
        self._lib_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._lib_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 6px; }"
            "QScrollBar::handle:vertical {"
            "background: rgba(0,229,255,0.30); border-radius: 3px; min-height: 20px;"
            "}"
            "QScrollBar::handle:vertical:hover { background: rgba(0,229,255,0.55); }"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height: 0; }"
        )
        self._row_container = QWidget()
        self._row_container.setStyleSheet("background: transparent;")
        self._row_container_lay = QVBoxLayout(self._row_container)
        self._row_container_lay.setContentsMargins(0, 0, 0, 0)
        self._row_container_lay.setSpacing(0)
        self._row_container_lay.addStretch(1)
        self._lib_scroll.setWidget(self._row_container)
        self._lib_panel.add(self._lib_scroll, stretch=1)
        # Mockup width — library is a narrow column (~310px), detail pane takes
        # the rest. Min/max keeps the ratio stable across window sizes instead
        # of stretching 50/50 with the breakdown.
        self._lib_panel.setMinimumWidth(340)
        self._lib_panel.setMaximumWidth(420)
        body.addWidget(self._lib_panel, 0)

        # RIGHT: step breakdown — action buttons live here now (run / pause /
        # edit / delete + add step). The library rows on the left are
        # click-to-select only; mutation goes through this pane.
        self._breakdown = StepBreakdown()
        self._breakdown.run_requested.connect(self.run_command.emit)
        self._breakdown.toggle_requested.connect(self._toggle_workflow)
        self._breakdown.edit_requested.connect(self._edit_selected_workflow)
        self._breakdown.delete_requested.connect(self._delete_workflow)
        body.addWidget(self._breakdown, 1)

        root.addLayout(body, 1)

        # ── Initial population + live-reload subscription ──────────────────
        self._build_rows()

        from core.signals import signals
        signals.workflow_library_changed.connect(self.refresh)

    # ── Builders ─────────────────────────────────────────────────────────────

    def _build_stats_strip(self) -> QFrame:
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

        self._hm_total      = HeroMetric("Workflows", "0", sub="0 enabled · 0 paused", value_size=30)
        self._hm_scheduled  = HeroMetric("Scheduled", "0", sub="manual triggers only",
                                          value_color=GREEN, value_size=30)
        self._hm_runs       = HeroMetric("Total runs", "—", sub="last run history",
                                          value_size=30)
        self._hm_last_fired = HeroMetric("Last fired", "—", sub="never",
                                          value_color=CYAN, value_size=14)
        self._hm_avg        = HeroMetric("Avg steps", "—", sub="per workflow",
                                          value_size=30)

        lay.addWidget(_cell(self._hm_total), 1)
        lay.addWidget(_cell(self._hm_scheduled), 1)
        lay.addWidget(_cell(self._hm_runs), 1)
        lay.addWidget(_cell(self._hm_last_fired), 1)
        lay.addWidget(_cell(self._hm_avg, last=True), 1)
        return wrap

    # ── Workflow rendering ───────────────────────────────────────────────────

    def _build_rows(self) -> None:
        workflows = workflow_library.list_all()
        self._refresh_stats(workflows)
        visible = self._filter_workflows(workflows)
        self._refresh_count_label(visible, workflows)
        self._render_rows(visible)
        # Restore selection if possible
        if visible:
            target_idx = 0
            if self._selected_workflow_id:
                for i, wf in enumerate(visible):
                    if wf.get("id") == self._selected_workflow_id:
                        target_idx = i
                        break
            self._select(target_idx)
        else:
            self._selected_workflow_id = ""
            self._edit_btn.setEnabled(False)

    def _refresh_stats(self, workflows: list) -> None:
        n = len(workflows)
        enabled = sum(1 for w in workflows if w.get("enabled", True))
        paused = n - enabled
        self._hm_total.set_value(str(n))
        self._hm_total.set_sub(f"{enabled} enabled · {paused} paused")

        scheduled = [w for w in workflows if (w.get("schedule") or "").strip()]
        self._hm_scheduled.set_value(str(len(scheduled)))
        if scheduled:
            first = scheduled[0].get("schedule", "")
            self._hm_scheduled.set_sub(f"e.g. {first}")
        else:
            self._hm_scheduled.set_sub("manual triggers only")

        # Total runs and last fired — derived from workflow last_run timestamps
        # if present. We don't track run counts today; show "—" until we do.
        self._hm_runs.set_value("—")
        self._hm_runs.set_sub("not tracked yet")

        # Find the most recent last_run
        most_recent: tuple[Optional[str], Optional[str]] = (None, None)
        for w in workflows:
            ts = (w.get("last_run") or "").strip()
            if ts:
                if most_recent[0] is None or ts > most_recent[0]:
                    most_recent = (ts, w.get("name", w.get("id", "")))
        if most_recent[0]:
            self._hm_last_fired.set_value(str(most_recent[1] or "—"), color=CYAN)
            # last_run is an ISO string from automation.mark_run
            self._hm_last_fired.set_sub(most_recent[0][:19].replace("T", " "))
        else:
            self._hm_last_fired.set_value("—", color=INK_DIM)
            self._hm_last_fired.set_sub("never")

        if workflows:
            avg = sum(len(w.get("steps", [])) for w in workflows) / max(n, 1)
            self._hm_avg.set_value(f"{avg:.1f}")
            self._hm_avg.set_sub("per workflow")
        else:
            self._hm_avg.set_value("—")
            self._hm_avg.set_sub("no workflows")

    def _refresh_count_label(self, visible: list, all_wfs: list) -> None:
        n = len(visible)
        total = len(all_wfs)
        if self._active_filter == "all" or n == total:
            self._wf_count_lbl.setText(
                f"{n} workflow{'s' if n != 1 else ''}"
            )
        else:
            self._wf_count_lbl.setText(
                f"{n} of {total} shown"
            )

    def _filter_workflows(self, workflows: list) -> list:
        flt = self._active_filter
        if flt == "all":
            return workflows
        if flt == "scheduled":
            return [w for w in workflows if (w.get("schedule") or "").strip()]
        if flt == "manual":
            return [w for w in workflows if not (w.get("schedule") or "").strip()]
        if flt == "paused":
            return [w for w in workflows if not w.get("enabled", True)]
        return workflows

    def _render_rows(self, workflows: list) -> None:
        # Clear existing rows except the trailing stretch
        while self._row_container_lay.count() > 1:
            item = self._row_container_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows.clear()

        if not workflows:
            empty = QLabel("NO WORKFLOWS MATCH" if self._active_filter != "all"
                           else "NO WORKFLOWS YET — CLICK + NEW")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                "QLabel {"
                "color: rgba(0,229,255,0.22);"
                f"font-family: '{FM}';"
                "font-size: 10px;"
                "font-weight: 700;"
                "letter-spacing: 2.4px;"
                "background: transparent;"
                "border: none;"
                "padding: 30px 0;"
                "}"
            )
            self._row_container_lay.insertWidget(0, empty)
            return

        for i, wf in enumerate(workflows):
            row = WorkflowRow(i, wf)
            row.selected.connect(self._select)
            row.run_requested.connect(self.run_command.emit)
            row.toggle_requested.connect(self._toggle_workflow)
            row.delete_requested.connect(self._delete_workflow)
            self._row_container_lay.insertWidget(i, row)
            self._rows.append(row)

    # ── Event handlers ───────────────────────────────────────────────────────

    def _on_chip_clicked(self, key: str) -> None:
        for k, chip in self._chip_widgets.items():
            chip.setChecked(k == key)
            chip._refresh_style()  # noqa: SLF001
        self._active_filter = key
        self._build_rows()

    def refresh(self) -> None:
        """Called by signals.workflow_library_changed when the disk file changes
        or programmatic edits happen."""
        self._build_rows()

    def _create_workflow(self) -> None:
        dlg = NewWorkflowDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        name, trigger, steps = dlg.get_values()
        schedule = dlg.get_schedule()
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
        wf: dict = {
            "id": wf_id,
            "name": name,
            "trigger": trigger,
            "steps": steps,
            "enabled": True,
            "last_run": None,
        }
        if schedule:
            wf["schedule"] = schedule
        workflow_library.add(wf)

    def _edit_selected_workflow(self) -> None:
        if not self._selected_workflow_id:
            return
        wf = workflow_library.get(self._selected_workflow_id)
        if not wf:
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
                return
            if not workflow_library.rename(old_id, name):
                return
            wf = workflow_library.get(new_id) or {}
            old_id = new_id

        updated = dict(wf)
        updated["id"] = old_id
        updated["name"] = name
        updated["trigger"] = trigger
        updated["steps"] = steps
        schedule = dlg.get_schedule()
        if schedule:
            updated["schedule"] = schedule
        else:
            updated.pop("schedule", None)
        workflow_library.add(updated)
        self._selected_workflow_id = old_id

    def _delete_workflow(self, wf_id: str, display_name: str) -> None:
        dlg = ConfirmDeleteDialog(display_name, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        workflow_library.remove(wf_id)

    def _toggle_workflow(self, wf_id: str, enabled: bool) -> None:
        workflow_library.set_enabled(wf_id, enabled)

    def _select(self, idx: int) -> None:
        for i, row in enumerate(self._rows):
            row.set_active(i == idx)
        visible = self._filter_workflows(workflow_library.list_all())
        if 0 <= idx < len(visible):
            self._selected_workflow_id = str(visible[idx].get("id", ""))
            self._edit_btn.setEnabled(True)
            self._breakdown.show_workflow(visible[idx])
        else:
            self._selected_workflow_id = ""
            self._edit_btn.setEnabled(False)

    # ── Paint (dotted backdrop) ──────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 229, 255, 18))
        for x in range(0, self.width() + 28, 28):
            for y in range(0, self.height() + 28, 28):
                p.drawEllipse(x - 1, y - 1, 2, 2)
