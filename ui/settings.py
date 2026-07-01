"""SettingsView — SYSTEM_CONFIG.

Redesigned 2026-05 to match the shared HUD grammar:
  - Top 6-tile health strip (Anthropic · ElevenLabs · Gemini · Mic · Wake · Browser)
  - Three sectioned columns:
        API & connectivity   ·  Voice & audio  ·  Behaviour & visuals
  - Each section: PanelCard + divide-y rows with inline labels + descriptions
  - Theme picker: 5 visual swatch tiles (Stark / Teal / Amber / Indigo / Matrix)
  - Bottom apply bar with an "unsaved" pip

Public API preserved so main.py needs no changes:
  - signals: scanline_toggled, mic_muted_changed, tts_muted_changed,
             auto_confirm_changed, dim_mode_changed, wake_word_changed
  - sync_state(mic_muted, tts_muted, auto_confirm, dim_mode, wake_word)
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from config.settings import config
from core.voice import _EL_VOICES
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
    HeroMetric,
    PanelCard,
    StatusPip,
)
from ui.theme import _THEME_PALETTES, ACCENT_RGB, BG, CYAN, FM
from ui.widgets import ToggleSwitch, _mono


# ── Stylesheet constants ────────────────────────────────────────────────────


_INPUT_SS = (
    "QLineEdit {"
    "background: rgba(8,15,17,0.85);"
    f"border: 1px solid {CYAN_FAINT};"
    f"color: {CYAN};"
    f"font-family: '{FM}';"
    "font-size: 11px;"
    "letter-spacing: 0.5px;"
    "padding: 5px 10px;"
    "}"
    "QLineEdit:focus { border: 1px solid rgba(0,229,255,0.65); }"
)

_COMBO_SS = (
    "QComboBox {"
    "background: rgba(8,15,17,0.85);"
    f"border: 1px solid {CYAN_FAINT};"
    f"color: {CYAN};"
    f"font-family: '{FM}';"
    "font-size: 11px;"
    "padding: 5px 10px;"
    "}"
    "QComboBox:focus { border: 1px solid rgba(0,229,255,0.65); }"
    "QComboBox::drop-down { border: none; width: 20px; }"
    "QComboBox QAbstractItemView {"
    "background: rgba(10,20,22,0.97);"
    f"color: {CYAN};"
    f"font-family: '{FM}';"
    "font-size: 11px;"
    "selection-background-color: rgba(0,229,255,0.15);"
    f"border: 1px solid {CYAN_FAINT};"
    "}"
)

_SLIDER_SS = (
    "QSlider::groove:horizontal {"
    "height: 4px; background: rgba(0,229,255,0.12); border-radius: 2px;"
    "}"
    "QSlider::sub-page:horizontal {"
    f"background: {CYAN_SOFT}; border-radius: 2px;"
    "}"
    "QSlider::handle:horizontal {"
    f"background: {CYAN};"
    "width: 12px; height: 12px;"
    "border-radius: 6px;"
    "margin: -4px 0;"
    "}"
)


# ── API key field (locked-by-default + edit toggle) ─────────────────────────


class ApiKeyField(QWidget):
    """Read-only key preview + EDIT button, swaps to editable input on demand.

    Why a custom widget instead of a bare QLineEdit: API keys shouldn't be
    casually clickable / typo-able. Default state shows a masked preview
    (e.g. ``sk-ant-•••••a3F2``) and an EDIT button; clicking EDIT swaps the
    preview for a password QLineEdit + SAVE/CANCEL.

    Quacks like QLineEdit for the call site: exposes ``text()``, ``setText()``,
    and a ``textChanged(str)`` signal so the dirty-marker wiring and the
    ``_apply_cfg`` read path keep working without touching them.
    """

    textChanged = pyqtSignal(str)

    def __init__(self, value: str = "", *, placeholder: str = "",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._value: str = value or ""
        self._placeholder: str = placeholder or ""
        # Snapshot used to revert on CANCEL.
        self._snapshot: str = self._value

        self._stack = QHBoxLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.setSpacing(8)

        # ── Locked view ─────────────────────────────────────────────────────
        self._preview_lbl = QLabel(self._format_preview())
        self._preview_lbl.setStyleSheet(
            "QLabel {"
            f"color: {INK_DIM};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 11px;"
            "letter-spacing: 0.5px;"
            "padding: 5px 4px;"
            "}"
        )
        self._preview_lbl.setMinimumWidth(180)
        self._preview_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._stack.addWidget(self._preview_lbl, 1)

        self._edit_btn = QPushButton("EDIT")
        self._edit_btn.setCursor(Qt.PointingHandCursor)
        self._edit_btn.setStyleSheet(self._btn_style(primary=False))
        self._edit_btn.clicked.connect(self._on_edit_clicked)
        self._stack.addWidget(self._edit_btn)

        # ── Edit view (hidden until EDIT clicked) ──────────────────────────
        self._input = QLineEdit(self._value)
        self._input.setEchoMode(QLineEdit.Password)
        self._input.setPlaceholderText(self._placeholder)
        self._input.setStyleSheet(_INPUT_SS)
        self._input.setMinimumWidth(180)
        self._input.hide()
        self._stack.addWidget(self._input, 1)

        self._save_btn = QPushButton("SAVE")
        self._save_btn.setCursor(Qt.PointingHandCursor)
        self._save_btn.setStyleSheet(self._btn_style(primary=True))
        self._save_btn.clicked.connect(self._on_save_clicked)
        self._save_btn.hide()
        self._stack.addWidget(self._save_btn)

        self._cancel_btn = QPushButton("CANCEL")
        self._cancel_btn.setCursor(Qt.PointingHandCursor)
        self._cancel_btn.setStyleSheet(self._btn_style(primary=False))
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        self._cancel_btn.hide()
        self._stack.addWidget(self._cancel_btn)

    # ── QLineEdit-compatible API ────────────────────────────────────────────

    def text(self) -> str:
        # When the user is mid-edit, the live input has the truth; otherwise
        # the committed _value is canonical.
        if self._input.isVisible():
            return self._input.text()
        return self._value

    def setText(self, value: str) -> None:
        self._value = value or ""
        self._snapshot = self._value
        self._input.setText(self._value)
        self._preview_lbl.setText(self._format_preview())

    # ── Internal ────────────────────────────────────────────────────────────

    def _format_preview(self) -> str:
        """Show '<prefix>•••<last4>' so users can fingerprint without exposing
        the key. Empty / very short keys collapse to a 'not set' hint."""
        v = self._value or ""
        if not v:
            return "not set"
        # Pick a small prefix — most keys announce their provider in the first
        # 6-8 chars (sk-ant-, el_, AIza, vapi-). Show that + bullets + last 4.
        if len(v) <= 8:
            return "•" * len(v)
        prefix_len = min(8, max(4, len(v) // 4))
        last4 = v[-4:]
        return f"{v[:prefix_len]}{'•' * 5}{last4}"

    def _enter_edit_mode(self) -> None:
        self._snapshot = self._value
        self._preview_lbl.hide()
        self._edit_btn.hide()
        self._input.setText(self._value)
        self._input.show()
        self._input.setFocus()
        self._save_btn.show()
        self._cancel_btn.show()

    def _leave_edit_mode(self) -> None:
        self._input.hide()
        self._save_btn.hide()
        self._cancel_btn.hide()
        self._preview_lbl.setText(self._format_preview())
        self._preview_lbl.show()
        self._edit_btn.show()

    def _on_edit_clicked(self) -> None:
        self._enter_edit_mode()

    def _on_save_clicked(self) -> None:
        new_value = self._input.text().strip()
        changed = (new_value != self._value)
        self._value = new_value
        self._leave_edit_mode()
        if changed:
            # Only emit when something actually changed — prevents the dirty
            # marker from flipping on for SAVE-with-no-edits.
            self.textChanged.emit(new_value)

    def _on_cancel_clicked(self) -> None:
        # Discard whatever was typed; restore the snapshot taken on entry.
        self._input.setText(self._snapshot)
        self._leave_edit_mode()

    @staticmethod
    def _btn_style(*, primary: bool) -> str:
        if primary:
            return (
                "QPushButton {"
                f"background: {CYAN};"
                "color: #001a1f;"
                f"border: 1px solid {CYAN};"
                f"font-family: '{FM}';"
                "font-size: 9.5px;"
                "font-weight: 700;"
                "padding: 5px 12px;"
                "letter-spacing: 1.5px;"
                "}"
                "QPushButton:hover { background: #5ff2ff; }"
            )
        return (
            "QPushButton {"
            "background: transparent;"
            f"color: {CYAN};"
            f"border: 1px solid {CYAN_FAINT};"
            f"font-family: '{FM}';"
            "font-size: 9.5px;"
            "font-weight: 700;"
            "padding: 5px 12px;"
            "letter-spacing: 1.5px;"
            "}"
            "QPushButton:hover { background: rgba(0,229,255,0.10); }"
        )


# ── Theme swatch picker ──────────────────────────────────────────────────────


class _SwatchBar(QWidget):
    """A solid colour preview, PAINTED directly (not via setStyleSheet) so the
    global accent-substitution hook can't recolour a swatch to the active theme.
    This is the fix for "STARK shows the active accent": its #00e5ff fill used to
    be rewritten by apply_accent; a painted QColor is immune."""

    def __init__(self, color: QColor, *, outline: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self._outline = outline
        self.setFixedHeight(16)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), self._color)
        if self._outline:
            p.setPen(QColor(255, 255, 255, 26))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))


class _ThemeSwatch(QFrame):
    """Single theme tile: accent + bg swatches and a label. Click to select."""

    clicked = pyqtSignal(str)  # theme key

    def __init__(self, key: str, name: str, accent: str, bg: str, *,
                 active: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._key = key
        self._active = active
        self._accent = accent
        self._bg = bg

        self.setFixedHeight(58)
        self.setCursor(Qt.PointingHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        # Swatch row: two coloured bars side by side. PAINTED (not setStyleSheet)
        # with THIS palette's OWN fixed colours, sourced from the canonical
        # _THEME_PALETTES — so the global accent hook can never recolour them to
        # the active theme (each swatch always shows its own colour).
        pal = _THEME_PALETTES.get(key, {})
        acc_rgb = pal.get("accent")
        acc_color = QColor(*acc_rgb) if acc_rgb else QColor(accent)
        bg_color = QColor(str(pal.get("bg", bg)))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(_SwatchBar(acc_color))
        row.addWidget(_SwatchBar(bg_color, outline=True))
        lay.addLayout(row)

        self._name_lbl = QLabel(name.upper())
        lay.addWidget(self._name_lbl)
        lay.addStretch(1)

        self._refresh_style()

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        self._refresh_style()

    def _refresh_style(self) -> None:
        if self._active:
            border = f"2px solid {self._accent}"
            bg = "rgba(0,229,255,0.06)"
            label_color = self._accent
        else:
            border = f"1px solid {CYAN_FAINT}"
            bg = "transparent"
            label_color = INK_DIM
        self.setStyleSheet(
            "QFrame {"
            f"background: {bg};"
            f"border: {border};"
            "}"
        )
        self._name_lbl.setStyleSheet(
            "QLabel {"
            f"color: {label_color};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 9.5px;"
            "font-weight: 700;"
            "letter-spacing: 1.8px;"
            "}"
        )

    def mousePressEvent(self, _event) -> None:
        self.clicked.emit(self._key)


# ── Health strip ─────────────────────────────────────────────────────────────


class _HealthStrip(QFrame):
    """Top 6-tile horizontal status row.

    Each tile: status pip + label + state text. Replaces the legacy
    3-pill compact strip with something the user can actually read.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame {"
            f"background: {BG_PANEL};"
            f"border: 1px solid {CYAN_FAINT};"
            "}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._tiles: dict[str, tuple[StatusPip, QLabel]] = {}
        self._add_tile(lay, "anthropic", "ANTHROPIC")
        self._add_tile(lay, "elevenlabs", "ELEVENLABS")
        self._add_tile(lay, "gemini",     "GEMINI TTS")
        self._add_tile(lay, "mic",        "MIC")
        self._add_tile(lay, "wake",       "WAKE WORD")
        self._add_tile(lay, "browser",    "BROWSER", last=True)

        self.refresh()

    def _add_tile(self, lay: QHBoxLayout, key: str, label_text: str, *, last: bool = False) -> None:
        cell = QFrame()
        cell.setStyleSheet(
            "QFrame {"
            "background: transparent;"
            + ("border: none;" if last else f"border-right: 1px solid {CYAN_FAINT};")
            + "}"
        )
        cl = QHBoxLayout(cell)
        cl.setContentsMargins(14, 10, 14, 10)
        cl.setSpacing(10)

        pip = StatusPip("off")
        cl.addWidget(pip, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        name = QLabel(label_text)
        name.setStyleSheet(
            "QLabel {"
            f"color: {INK_FAINT};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 9px;"
            "font-weight: 700;"
            "letter-spacing: 2px;"
            "}"
        )
        col.addWidget(name)
        val = QLabel("—")
        val.setStyleSheet(
            "QLabel {"
            f"color: {INK_DIM};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 11px;"
            "}"
        )
        col.addWidget(val)
        cl.addLayout(col, 1)

        lay.addWidget(cell, 1)
        self._tiles[key] = (pip, val)

    def _set_tile(self, key: str, pip_state: str, value: str, value_color: str) -> None:
        pip, val = self._tiles[key]
        pip.set_state(pip_state)
        val.setText(value)
        val.setStyleSheet(
            f"QLabel {{ color: {value_color}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 11px; }}"
        )

    def refresh(self) -> None:
        """Re-read config + best-effort detect the live state of each provider."""
        # Anthropic
        if config.anthropic_api_key:
            self._set_tile("anthropic", "on", "connected", GREEN)
        else:
            self._set_tile("anthropic", "err", "no key", RED)

        # ElevenLabs
        if config.elevenlabs_api_key:
            self._set_tile("elevenlabs", "on", "key set", GREEN)
        else:
            self._set_tile("elevenlabs", "off", "not configured", INK_DIM)

        # Gemini
        gemini_key = getattr(config, "gemini_api_key", "")
        if gemini_key:
            self._set_tile("gemini", "on", "free tier", GREEN)
        else:
            self._set_tile("gemini", "off", "not configured", INK_DIM)

        # Mic — best effort via sounddevice
        try:
            import sounddevice as _sd  # type: ignore
            inputs = [d for d in _sd.query_devices() if d.get("max_input_channels", 0) > 0]
            if inputs:
                self._set_tile("mic", "on", "detected", GREEN)
            else:
                self._set_tile("mic", "warn", "no inputs", AMBER)
        except Exception:
            self._set_tile("mic", "warn", "unavailable", AMBER)

        # Wake word
        if getattr(config, "wake_word_enabled", True):
            self._set_tile("wake", "on", "listening", GREEN)
        else:
            self._set_tile("wake", "off", "disabled", INK_DIM)

        # Browser — Playwright session: best-effort
        try:
            from core.browser import browser as _b
            if getattr(_b, "_context", None):
                self._set_tile("browser", "on", "running", GREEN)
            else:
                self._set_tile("browser", "off", "not started", INK_DIM)
        except Exception:
            self._set_tile("browser", "off", "not started", INK_DIM)


# ── Field-row helper used inside section panels ─────────────────────────────


def _section_row(
    label: str,
    control: QWidget,
    helper: str = "",
    *,
    parent: Optional[QWidget] = None,
) -> QWidget:
    """One divide-y row inside a section panel.

    Layout:
        ┌─────────────────────────────────────────┐
        │  LABEL                       [control]  │
        │  (optional helper text on a 2nd line)   │
        └─────────────────────────────────────────┘
    """
    w = QFrame(parent)
    # `border: none` before `border-bottom` so the parent PanelCard's
    # `QFrame { border: ... }` cascade doesn't paint top/left/right edges
    # on each row (same bug as DivideRow — see its docstring).
    w.setStyleSheet(
        "QFrame {"
        "background: transparent;"
        "border: none;"
        "border-bottom: 1px solid rgba(0,229,255,0.07);"
        "}"
    )
    outer = QVBoxLayout(w)
    outer.setContentsMargins(0, 8, 0, 8)
    outer.setSpacing(4)

    row = QHBoxLayout()
    row.setSpacing(12)
    lbl = QLabel(label.upper())
    lbl.setStyleSheet(
        "QLabel {"
        f"color: {INK};"
        "background: transparent;"
        "border: none;"
        f"font-family: '{FM}';"
        "font-size: 10.5px;"
        "letter-spacing: 1.5px;"
        "}"
    )
    row.addWidget(lbl, 1)
    row.addWidget(control, 0)
    outer.addLayout(row)

    if helper:
        hl = QLabel(helper)
        hl.setStyleSheet(
            "QLabel {"
            f"color: {INK_FAINT};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 9.5px;"
            "letter-spacing: 0.3px;"
            "}"
        )
        hl.setWordWrap(True)
        outer.addWidget(hl)
    return w


# ── Main view ───────────────────────────────────────────────────────────────


class SettingsView(QWidget):
    """SYSTEM_CONFIG. See module docstring."""

    scanline_toggled     = pyqtSignal(bool)
    mic_muted_changed    = pyqtSignal(bool)
    tts_muted_changed    = pyqtSignal(bool)
    auto_confirm_changed = pyqtSignal(bool)
    dim_mode_changed     = pyqtSignal(bool)
    wake_word_changed    = pyqtSignal(bool)

    # Theme catalogue: keys match config.theme; mockup constants reused.
    _THEMES: tuple[tuple[str, str, str, str], ...] = (
        # (key, display, accent, bg)
        ("cyan",     "Stark",   "#00e5ff", "#080A0A"),
        ("teal",     "Teal",    "#3dc7d6", "#0a1010"),
        ("amber",    "Amber",   "#ffaa00", "#0d0a04"),
        ("indigo",   "Indigo",  "#818cf8", "#060912"),
        ("matrix",   "Matrix",  "#00ff66", "#050a06"),
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._bg_px: Optional[QPixmap] = None
        self._bg_sz = (-1, -1)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # ── Header ──────────────────────────────────────────────────────────
        head = QHBoxLayout()
        head.setSpacing(12)
        title = QLabel("SYSTEM_CONFIG")
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

        subtitle = QLabel("RUNTIME CONFIGURATION · API · AUDIO · SESSION FLAGS")
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

        self._unsaved_lbl = QLabel("● UNSAVED")
        self._unsaved_lbl.setStyleSheet(
            "QLabel {"
            f"color: {AMBER};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 9px;"
            "font-weight: 700;"
            "letter-spacing: 2px;"
            "}"
        )
        self._unsaved_lbl.setVisible(False)
        head.addWidget(self._unsaved_lbl)
        root.addLayout(head)

        # ── Health strip ────────────────────────────────────────────────────
        self._health = _HealthStrip()
        root.addWidget(self._health)

        # ── 3-column body (scrollable, mirrors the HISTORY page) ────────────
        # Without a scroll area the columns are pinned to the window height, so
        # each new field shrinks every row below its intended size (labels then
        # collide with their inputs). Wrapping the columns in a QScrollArea gives
        # them unbounded height: rows render at full size and the page scrolls
        # when there are more fields than fit — future-proof as more are added.
        cols = QHBoxLayout()
        cols.setContentsMargins(0, 0, 8, 0)   # gutter so the scrollbar clears the panels
        cols.setSpacing(14)
        cols.setAlignment(Qt.AlignTop)
        cols.addWidget(self._build_api_panel(), 1)
        cols.addWidget(self._build_voice_panel(), 1)
        cols.addWidget(self._build_behaviour_panel(), 1)

        body_container = QWidget()
        body_container.setLayout(cols)

        body_scroll = QScrollArea()
        body_scroll.setWidgetResizable(True)
        body_scroll.setFrameShape(QScrollArea.NoFrame)
        body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 6px; }"
            "QScrollBar::handle:vertical {"
            "background: rgba(0,229,255,0.30); border-radius: 3px; min-height: 20px;"
            "}"
            "QScrollBar::handle:vertical:hover { background: rgba(0,229,255,0.55); }"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical { background: transparent; }"
        )
        body_scroll.setWidget(body_container)
        root.addWidget(body_scroll, 1)

        # ── Apply bar ───────────────────────────────────────────────────────
        apply_bar = QFrame()
        apply_bar.setStyleSheet(
            "QFrame {"
            f"background: {BG_PANEL};"
            f"border: 1px solid {CYAN_FAINT};"
            "}"
        )
        abl = QHBoxLayout(apply_bar)
        abl.setContentsMargins(14, 8, 14, 8)
        abl.setSpacing(12)

        hint = QLabel("Apply writes API keys to .env and other prefs to data/jarvis.json.")
        hint.setStyleSheet(
            f"QLabel {{ color: {INK_DIM}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 10px; }}"
        )
        abl.addWidget(hint, 1)

        self._apply_btn = QPushButton("APPLY_CFG")
        self._apply_btn.setCursor(Qt.PointingHandCursor)
        self._apply_btn.setToolTip("Save configuration")
        self._apply_btn.setStyleSheet(
            "QPushButton {"
            "background: transparent;"
            f"color: {CYAN};"
            f"border: 1px solid {CYAN_SOFT};"
            f"font-family: '{FM}';"
            "font-size: 11px;"
            "font-weight: 700;"
            "padding: 6px 18px;"
            "letter-spacing: 2px;"
            "}"
            "QPushButton:hover { background: rgba(0,229,255,0.10); }"
            "QPushButton:pressed { background: rgba(0,229,255,0.18); }"
        )
        self._apply_btn.clicked.connect(self._apply_cfg)
        abl.addWidget(self._apply_btn)
        root.addWidget(apply_bar)

        # Wire dirty markers on every field
        self._wire_dirty_indicators()

    # ── Panel builders ───────────────────────────────────────────────────────

    def _build_api_panel(self) -> PanelCard:
        panel = PanelCard("API & connectivity", active=True)

        # API key inputs use ApiKeyField — locked-by-default preview + EDIT
        # button. The field exposes text() / setText() / textChanged so the
        # apply path and dirty-marker wiring downstream don't need to care
        # whether they're talking to a QLineEdit or this wrapper.
        self._anthro_key = ApiKeyField(config.anthropic_api_key, placeholder="sk-ant-…")
        panel.add(_section_row(
            "Anthropic key", self._anthro_key,
            "Required. Routes every command through Claude.",
        ))

        self._eleven_key = ApiKeyField(config.elevenlabs_api_key, placeholder="el-…")
        panel.add(_section_row(
            "ElevenLabs key", self._eleven_key,
            "Primary TTS provider. Falls back to Gemini when quota-locked.",
        ))

        self._gemini_key = ApiKeyField(getattr(config, "gemini_api_key", ""), placeholder="AIza…")
        panel.add(_section_row(
            "Gemini key", self._gemini_key,
            "Fallback TTS. 10 calls/day on the free tier.",
        ))

        self._vapi_key = ApiKeyField(config.vapi_api_key, placeholder="vapi-…")
        panel.add(_section_row(
            "Vapi key", self._vapi_key,
            "Optional. Syncs the JARVIS assistant config for web/phone deployment.",
        ))

        self._model_combo = QComboBox()
        self._model_combo.setStyleSheet(_COMBO_SS)
        for display, model_id in (
            ("Claude Sonnet 4.6", "claude-sonnet-4-6"),
            ("Claude Opus 4.7",   "claude-opus-4-7"),
            ("Claude Haiku 4.5",  "claude-haiku-4-5-20251001"),
        ):
            self._model_combo.addItem(display, userData=model_id)
        current_idx = next(
            (i for i in range(self._model_combo.count())
             if self._model_combo.itemData(i) == config.claude_model), 0
        )
        self._model_combo.setCurrentIndex(current_idx)
        panel.add(_section_row(
            "Claude model", self._model_combo,
            "Sonnet 4.6 for routing. Opus available for heavier reasoning.",
        ))

        self._debug_toggle = ToggleSwitch(config.debug_mode)
        panel.add(_section_row(
            "Debug mode", self._debug_toggle,
            "Print raw brain JSON, FOLLOW lines, and per-handler traces to stderr.",
        ))

        panel.body().addStretch(1)
        return panel

    def _build_voice_panel(self) -> PanelCard:
        panel = PanelCard("Voice & audio")

        self._voice_combo = QComboBox()
        self._voice_combo.setStyleSheet(_COMBO_SS)
        for key in sorted(_EL_VOICES.keys()):
            self._voice_combo.addItem(key.replace("-", " ").title(), userData=key)
        voice_idx = next(
            (i for i in range(self._voice_combo.count())
             if self._voice_combo.itemData(i) == config.tts_voice), 0
        )
        self._voice_combo.setCurrentIndex(voice_idx)
        panel.add(_section_row(
            "Voice profile", self._voice_combo,
            "ElevenLabs voice ID. Falls back to pyttsx3 when no TTS provider available.",
        ))

        self._wake_input = QLineEdit(config.wake_word)
        self._wake_input.setStyleSheet(_INPUT_SS)
        self._wake_input.setFixedWidth(160)
        panel.add(_section_row(
            "Wake word", self._wake_input,
            "Phrase that activates voice input. Lowercase; one or two words works best.",
        ))

        self._mic_device_combo = QComboBox()
        self._mic_device_combo.setStyleSheet(_COMBO_SS)
        self._mic_device_combo.addItem("System Default", -1)
        try:
            import sounddevice as _sd  # type: ignore
            for idx, dev in enumerate(_sd.query_devices()):
                if dev["max_input_channels"] > 0:
                    self._mic_device_combo.addItem(
                        f"[{idx}] {dev['name'][:36]}", idx
                    )
                    if idx == config.mic_device:
                        self._mic_device_combo.setCurrentIndex(
                            self._mic_device_combo.count() - 1
                        )
        except Exception:
            pass
        panel.add(_section_row(
            "Mic device", self._mic_device_combo,
            "Input device for STT. System default works for most laptops.",
        ))

        # Sensitivity slider
        sens_row = QHBoxLayout()
        sens_row.setSpacing(10)
        self._mic_slider = QSlider(Qt.Horizontal)
        self._mic_slider.setRange(0, 100)
        self._mic_slider.setValue(config.mic_sensitivity)
        self._mic_slider.setStyleSheet(_SLIDER_SS)
        self._mic_slider.setFixedWidth(140)
        self._mic_val = QLabel(f"{config.mic_sensitivity}")
        self._mic_val.setFixedWidth(28)
        self._mic_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._mic_val.setStyleSheet(
            f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 10px; }}"
        )
        self._mic_slider.valueChanged.connect(lambda v: self._mic_val.setText(f"{v}"))
        sens_row.addWidget(self._mic_slider)
        sens_row.addWidget(self._mic_val)
        sens_wrap = QWidget()
        sens_wrap.setLayout(sens_row)
        panel.add(_section_row("Mic sensitivity", sens_wrap,
                               "Threshold for voice detection. Lower → more sensitive."))

        # TTS speed slider
        tts_row = QHBoxLayout()
        tts_row.setSpacing(10)
        self._tts_slider = QSlider(Qt.Horizontal)
        self._tts_slider.setRange(50, 200)
        self._tts_slider.setValue(config.tts_speed)
        self._tts_slider.setStyleSheet(_SLIDER_SS)
        self._tts_slider.setFixedWidth(140)
        self._tts_val = QLabel(f"{config.tts_speed}")
        self._tts_val.setFixedWidth(28)
        self._tts_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._tts_val.setStyleSheet(
            f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 10px; }}"
        )
        self._tts_slider.valueChanged.connect(lambda v: self._tts_val.setText(f"{v}"))
        tts_row.addWidget(self._tts_slider)
        tts_row.addWidget(self._tts_val)
        tts_wrap = QWidget()
        tts_wrap.setLayout(tts_row)
        panel.add(_section_row("TTS speed", tts_wrap,
                               "Speech rate of the TTS engine. 100 = default."))

        # STT pause-tolerance (settle window). 0 = off (snappiest); >0 waits that
        # long after you stop before committing, so a mid-command think-pause
        # doesn't cut you off. Takes effect on the next turn (no restart).
        settle_row = QHBoxLayout()
        settle_row.setSpacing(10)
        self._settle_slider = QSlider(Qt.Horizontal)
        self._settle_slider.setRange(0, 800)
        self._settle_slider.setSingleStep(50)
        self._settle_slider.setPageStep(100)
        self._settle_slider.setValue(int(getattr(config, "stt_settle_ms", 0)))
        self._settle_slider.setStyleSheet(_SLIDER_SS)
        self._settle_slider.setFixedWidth(140)
        self._settle_val = QLabel(self._fmt_settle(self._settle_slider.value()))
        self._settle_val.setFixedWidth(34)
        self._settle_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._settle_val.setStyleSheet(
            f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 10px; }}"
        )
        self._settle_slider.valueChanged.connect(
            lambda v: self._settle_val.setText(self._fmt_settle(v)))
        settle_row.addWidget(self._settle_slider)
        settle_row.addWidget(self._settle_val)
        settle_wrap = QWidget()
        settle_wrap.setLayout(settle_row)
        panel.add(_section_row(
            "Pause tolerance", settle_wrap,
            "Wait after you stop before committing, so a mid-command pause doesn't "
            "cut you off. 0 = off (snappiest). ~350-500ms suits natural pauses.",
        ))

        # STT engine + persistent connection (applied on save; STT reads them on
        # the next session). Deepgram streams (lower latency); Google is batch.
        self._stt_provider_combo = QComboBox()
        self._stt_provider_combo.setStyleSheet(_COMBO_SS)
        for display, key in (("Google (batch)", "google"), ("Deepgram (streaming)", "deepgram")):
            self._stt_provider_combo.addItem(display, userData=key)
        _stt_idx = next(
            (i for i in range(self._stt_provider_combo.count())
             if self._stt_provider_combo.itemData(i) == getattr(config, "stt_provider", "google")), 0
        )
        self._stt_provider_combo.setCurrentIndex(_stt_idx)
        panel.add(_section_row(
            "STT engine", self._stt_provider_combo,
            "Speech-to-text provider. Deepgram streams (lower latency); Google is batch.",
        ))

        self._flag_stt_persistent = ToggleSwitch(getattr(config, "stt_persistent", False))
        panel.add(_section_row(
            "Persistent STT", self._flag_stt_persistent,
            "Keep the STT connection open between turns for faster starts (Deepgram).",
        ))

        # Noise gate + wake word listener
        self._noise_toggle = ToggleSwitch(config.noise_gate)
        panel.add(_section_row("Noise gate", self._noise_toggle,
                               "Filter ambient noise before voice detection."))

        self._flag_wake = ToggleSwitch(getattr(config, "wake_word_enabled", True))
        self._flag_wake.toggled.connect(self.wake_word_changed.emit)
        panel.add(_section_row("Wake listener", self._flag_wake,
                               "Listen for the wake word in the background."))

        panel.body().addStretch(1)
        return panel

    def _build_behaviour_panel(self) -> PanelCard:
        panel = PanelCard("Behaviour & visuals")

        # Session-mute toggles (mic / TTS)
        self._flag_mic = ToggleSwitch(getattr(config, "mic_muted", False))
        self._flag_mic.toggled.connect(self.mic_muted_changed.emit)
        panel.add(_section_row("Mute mic", self._flag_mic,
                               "Block voice capture session-wide. Hotkey: Ctrl+Shift+M."))

        self._flag_tts = ToggleSwitch(getattr(config, "tts_muted", False))
        self._flag_tts.toggled.connect(self.tts_muted_changed.emit)
        panel.add(_section_row("Mute TTS", self._flag_tts,
                               "Suppress spoken responses. Transcript still updates."))

        self._flag_conf = ToggleSwitch(getattr(config, "auto_confirm", False))
        self._flag_conf.toggled.connect(self.auto_confirm_changed.emit)
        panel.add(_section_row("Auto-confirm", self._flag_conf,
                               "Skip confirmation prompts. Destructive actions run instantly."))

        # Opt-in explicit-content search gate. Applies on save (read per search,
        # no restart). JARVIS never refuses — it just asks first when this is on.
        self._flag_safesearch = ToggleSwitch(getattr(config, "safe_search_confirm", False))
        panel.add(_section_row("Safe search", self._flag_safesearch,
                               "Confirm before an explicit/adult web search. Off by "
                               "default — a speed-bump for shared machines, never a refusal."))

        # Code-execution safety controls (applied on save; read live per command,
        # no restart). code_exec_enabled is the master switch for the whole
        # code_execution intent; autorun lets AI-suggested fixes run without a card.
        self._flag_code_exec = ToggleSwitch(getattr(config, "code_exec_enabled", True))
        panel.add(_section_row(
            "Code execution", self._flag_code_exec,
            "Master switch for running code / shell commands. Off disables the "
            "entire code_execution intent.",
        ))

        self._flag_autorun = ToggleSwitch(getattr(config, "allow_ai_command_autorun", False))
        panel.add(_section_row(
            "Auto-run AI fixes", self._flag_autorun,
            "Caution: lets AI-suggested fixes run WITHOUT a confirmation card. Off "
            "by default — leave off unless you trust every suggested command.",
        ))

        # Default browser engine (voice can still switch at runtime).
        self._browser_engine_combo = QComboBox()
        self._browser_engine_combo.setStyleSheet(_COMBO_SS)
        for display, key in (("Chrome", "chrome"), ("Edge", "edge"),
                             ("Firefox", "firefox"), ("Auto", "auto")):
            self._browser_engine_combo.addItem(display, userData=key)
        _be_idx = next(
            (i for i in range(self._browser_engine_combo.count())
             if self._browser_engine_combo.itemData(i) == getattr(config, "browser_engine", "chrome")), 0
        )
        self._browser_engine_combo.setCurrentIndex(_be_idx)
        panel.add(_section_row(
            "Default browser", self._browser_engine_combo,
            "Which engine JARVIS controls by default. Switchable by voice too.",
        ))

        # Default weather city (used when a query names no location).
        self._weather_city_input = QLineEdit(getattr(config, "weather_default_city", "Monrovia,LR"))
        self._weather_city_input.setStyleSheet(_INPUT_SS)
        self._weather_city_input.setFixedWidth(160)
        panel.add(_section_row(
            "Default weather city", self._weather_city_input,
            "Used when a weather query names no location. Format: City,CC (e.g. Monrovia,LR).",
        ))

        self._flag_dim = ToggleSwitch(getattr(config, "dim_mode", False))
        self._flag_dim.toggled.connect(self.dim_mode_changed.emit)
        panel.add(_section_row("Dim mode", self._flag_dim,
                               "Reduce brightness for low-light use."))

        self._scan_toggle = ToggleSwitch(True)
        self._scan_toggle.toggled.connect(self.scanline_toggled.emit)
        panel.add(_section_row("Scanline FX", self._scan_toggle,
                               "Animated horizontal scanline overlay across the HUD."))

        # ── Theme swatch picker ─────────────────────────────────────────────
        theme_label = QLabel("HUD THEME")
        theme_label.setStyleSheet(
            "QLabel {"
            f"color: {INK};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 10.5px;"
            "letter-spacing: 1.5px;"
            "margin-top: 8px;"
            "}"
        )
        panel.body().addWidget(theme_label)

        swatch_grid = QHBoxLayout()
        swatch_grid.setSpacing(6)
        self._swatches: dict[str, _ThemeSwatch] = {}
        current_theme = getattr(config, "theme", "cyan")
        for key, name, accent, bg in self._THEMES:
            sw = _ThemeSwatch(key, name, accent, bg, active=(key == current_theme))
            sw.clicked.connect(self._on_swatch_clicked)
            self._swatches[key] = sw
            swatch_grid.addWidget(sw, 1)
        panel.body().addLayout(swatch_grid)

        # Hidden field — tracks the selected theme for _apply_cfg to read.
        # _initial_theme is the value at load so _apply_cfg can detect a change
        # and prompt for the restart that actually applies it.
        self._selected_theme = current_theme
        self._initial_theme = current_theme

        theme_helper = QLabel("5 variants. Stark Cyan is default. Applies on restart.")
        theme_helper.setStyleSheet(
            "QLabel {"
            f"color: {INK_FAINT};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 9.5px;"
            "}"
        )
        panel.body().addWidget(theme_helper)

        panel.body().addStretch(1)
        return panel

    # ── Event handlers ───────────────────────────────────────────────────────

    @staticmethod
    def _fmt_settle(v: int) -> str:
        """Compact slider readout: 'Off' at 0, else the millisecond value."""
        return "Off" if v <= 0 else str(v)

    def _on_swatch_clicked(self, key: str) -> None:
        if key == self._selected_theme:
            return
        self._selected_theme = key
        for k, sw in self._swatches.items():
            sw.set_active(k == key)
        self._mark_dirty()

    def _wire_dirty_indicators(self) -> None:
        for sig in (
            self._anthro_key.textChanged,
            self._eleven_key.textChanged,
            self._gemini_key.textChanged,
            self._vapi_key.textChanged,
            self._wake_input.textChanged,
        ):
            sig.connect(lambda _: self._mark_dirty())
        self._voice_combo.currentIndexChanged.connect(lambda _: self._mark_dirty())
        self._model_combo.currentIndexChanged.connect(lambda _: self._mark_dirty())
        self._debug_toggle.toggled.connect(lambda _: self._mark_dirty())
        self._scan_toggle.toggled.connect(lambda _: self._mark_dirty())
        self._mic_slider.valueChanged.connect(lambda _: self._mark_dirty())
        self._tts_slider.valueChanged.connect(lambda _: self._mark_dirty())
        self._settle_slider.valueChanged.connect(lambda _: self._mark_dirty())
        self._noise_toggle.toggled.connect(lambda _: self._mark_dirty())
        self._flag_safesearch.toggled.connect(lambda _: self._mark_dirty())
        self._mic_device_combo.currentIndexChanged.connect(lambda _: self._mark_dirty())
        # Session-flag toggles — persisted on Apply (live signals aside), so they
        # must mark dirty too; these were missed when the wiring was first built.
        self._flag_mic.toggled.connect(lambda _: self._mark_dirty())
        self._flag_tts.toggled.connect(lambda _: self._mark_dirty())
        self._flag_conf.toggled.connect(lambda _: self._mark_dirty())
        self._flag_dim.toggled.connect(lambda _: self._mark_dirty())
        self._flag_wake.toggled.connect(lambda _: self._mark_dirty())
        # Newly-surfaced config controls (§54)
        self._stt_provider_combo.currentIndexChanged.connect(lambda _: self._mark_dirty())
        self._flag_stt_persistent.toggled.connect(lambda _: self._mark_dirty())
        self._flag_code_exec.toggled.connect(lambda _: self._mark_dirty())
        self._flag_autorun.toggled.connect(lambda _: self._mark_dirty())
        self._browser_engine_combo.currentIndexChanged.connect(lambda _: self._mark_dirty())
        self._weather_city_input.textChanged.connect(lambda _: self._mark_dirty())

    def _mark_dirty(self) -> None:
        self._unsaved_lbl.setVisible(True)

    def _mark_clean(self) -> None:
        self._unsaved_lbl.setVisible(False)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _apply_cfg(self) -> None:
        from core.signals import signals
        from core.voice import voice_engine

        config.anthropic_api_key = self._anthro_key.text().strip()
        config.elevenlabs_api_key = self._eleven_key.text().strip()
        if hasattr(config, "gemini_api_key"):
            config.gemini_api_key = self._gemini_key.text().strip()
        config.vapi_api_key      = self._vapi_key.text().strip()
        config.claude_model      = self._model_combo.currentData()
        config.wake_word         = self._wake_input.text().strip() or "jarvis"

        selected_voice = self._voice_combo.currentData() or config.tts_voice
        voice_err = ""
        if selected_voice != config.tts_voice:
            ok, msg, _kind = voice_engine.switch_tts_voice(
                selected_voice,
                validate_provider=True,
                persist=False,
            )
            if not ok:
                voice_err = msg
                selected_voice = config.tts_voice
                voice_idx = next(
                    (i for i in range(self._voice_combo.count())
                     if self._voice_combo.itemData(i) == selected_voice),
                    0,
                )
                self._voice_combo.setCurrentIndex(voice_idx)
        config.tts_voice = selected_voice

        config.theme            = self._selected_theme
        config.debug_mode       = self._debug_toggle.isChecked()
        config.mic_sensitivity  = self._mic_slider.value()
        config.tts_speed        = self._tts_slider.value()
        config.noise_gate       = self._noise_toggle.isChecked()
        config.mic_device       = self._mic_device_combo.currentData()
        config.stt_settle_ms    = self._settle_slider.value()
        config.safe_search_confirm = self._flag_safesearch.isChecked()
        # Session flags snapshot
        config.mic_muted        = self._flag_mic.isChecked()
        config.tts_muted        = self._flag_tts.isChecked()
        config.auto_confirm     = self._flag_conf.isChecked()
        config.dim_mode         = self._flag_dim.isChecked()
        config.wake_word_enabled = self._flag_wake.isChecked()
        # Newly-surfaced config (previously JSON-only)
        config.stt_provider     = self._stt_provider_combo.currentData() or "google"
        config.stt_persistent   = self._flag_stt_persistent.isChecked()
        config.code_exec_enabled = self._flag_code_exec.isChecked()
        config.allow_ai_command_autorun = self._flag_autorun.isChecked()
        config.browser_engine   = self._browser_engine_combo.currentData() or "chrome"
        config.weather_default_city = self._weather_city_input.text().strip() or "Monrovia,LR"

        try:
            config.save()
            self._apply_btn.setText("SAVED ✓" if not voice_err else "SAVED (VOICE UNCHANGED)")
            self._mark_clean()
            self._health.refresh()
            if voice_err:
                signals.error_occurred.emit(voice_err)
            # Theme resolves at startup (ui.theme import), so a change only shows
            # after a restart — tell the user instead of leaving it looking broken.
            if self._selected_theme != self._initial_theme:
                self._initial_theme = self._selected_theme
                try:
                    signals.notice.emit(
                        "Theme saved — restart JARVIS to apply it.", "info")
                except Exception:
                    pass
        except Exception:
            self._apply_btn.setText("SAVE ERROR")

        QTimer.singleShot(2000, lambda: self._apply_btn.setText("APPLY_CFG"))

    # ── External hooks ───────────────────────────────────────────────────────

    def showEvent(self, event) -> None:
        """Re-sync voice combo from live config each time the page is shown."""
        voice_idx = next(
            (i for i in range(self._voice_combo.count())
             if self._voice_combo.itemData(i) == config.tts_voice),
            0,
        )
        self._voice_combo.setCurrentIndex(voice_idx)
        super().showEvent(event)

    def sync_state(
        self,
        mic_muted: bool,
        tts_muted: bool,
        auto_confirm: bool,
        dim_mode: bool = False,
        wake_word: bool = True,
    ) -> None:
        """Reflect external flag values without re-emitting toggle signals."""
        for tog, val in (
            (self._flag_mic,  mic_muted),
            (self._flag_tts,  tts_muted),
            (self._flag_conf, auto_confirm),
            (self._flag_dim,  dim_mode),
            (self._flag_wake, wake_word),
        ):
            tog.blockSignals(True)
            try:
                tog.setChecked(val)
            finally:
                tog.blockSignals(False)

    # ── Paint (dotted backdrop) ──────────────────────────────────────────────

    def _rebuild_bg(self) -> None:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            self._bg_px = None
            return
        px = QPixmap(w, h)
        p = QPainter(px)
        p.fillRect(0, 0, w, h, QColor(BG))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(*ACCENT_RGB, 18))
        for x in range(0, w + 28, 28):
            for y in range(0, h + 28, 28):
                p.drawEllipse(x - 1, y - 1, 2, 2)
        p.end()
        self._bg_px = px
        self._bg_sz = (w, h)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._bg_px = None

    def paintEvent(self, _event) -> None:
        w, h = self.width(), self.height()
        if self._bg_px is None or self._bg_sz != (w, h):
            self._rebuild_bg()
        p = QPainter(self)
        if self._bg_px is not None:
            p.drawPixmap(0, 0, self._bg_px)
