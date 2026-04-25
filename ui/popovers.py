"""Anchored popovers for the TopBar trailing icons.

Each popover is a frameless `Qt.Popup` window — clicking outside auto-closes it
(standard menu/dropdown behaviour) so callers don't need to track focus.

Public API:
    QuickSettingsPopover  - settings sliders icon
        signals:
            mic_muted_changed(bool)
            tts_muted_changed(bool)
            auto_confirm_changed(bool)
            open_settings()
        methods:
            show_below(QWidget)         # anchor under a topbar icon button
            sync_state(mic, tts, conf)  # reflect current flag values on open
"""

from __future__ import annotations

from PyQt5.QtCore import QPoint, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ui.theme import CYAN, FM, GREEN, RED, WARNING
from ui.widgets import StatusPip, ToggleSwitch


_POPOVER_WIDTH = 300


def _mono(size: int, bold: bool = False):
    from PyQt5.QtGui import QFont
    f = QFont(FM, size)
    f.setBold(bold)
    return f


class _ToggleRow(QWidget):
    """One row inside a popover: label + optional helper + ToggleSwitch."""

    toggled = pyqtSignal(bool)

    def __init__(
        self,
        label: str,
        helper: str = "",
        checked: bool = False,
        warn: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(10)

        col = QVBoxLayout()
        col.setSpacing(2)

        lbl = QLabel(label)
        lbl.setFont(_mono(10, bold=True))
        lbl.setStyleSheet(
            "color:rgba(195,245,255,0.92);letter-spacing:1px;"
            "background:transparent;border:none;"
        )
        col.addWidget(lbl)

        if helper:
            help_color = WARNING if warn else "rgba(132,147,150,0.55)"
            self._help_lbl = QLabel(helper)
            self._help_lbl.setStyleSheet(
                f"color:{help_color};font-family:'Roboto Mono';"
                "font-size:9px;letter-spacing:0.5px;"
                "background:transparent;border:none;"
            )
            self._help_lbl.setWordWrap(True)
            col.addWidget(self._help_lbl)
        else:
            self._help_lbl = None

        lay.addLayout(col, 1)

        self._toggle = ToggleSwitch(checked)
        self._toggle.toggled.connect(self.toggled.emit)
        lay.addWidget(self._toggle, 0, Qt.AlignVCenter)

    def is_checked(self) -> bool:
        return self._toggle.isChecked()

    def set_checked(self, checked: bool) -> None:
        # setChecked() doesn't re-emit toggled, which is what we want when
        # the popover syncs from external state on open.
        self._toggle.setChecked(checked)


class QuickSettingsPopover(QFrame):
    """Compact dropdown anchored to the TopBar sliders icon."""

    mic_muted_changed    = pyqtSignal(bool)
    tts_muted_changed    = pyqtSignal(bool)
    auto_confirm_changed = pyqtSignal(bool)
    open_settings        = pyqtSignal()

    def __init__(self, parent=None):
        # Qt.Popup gives us click-outside-to-close + correct stacking on top.
        # FramelessWindowHint hides the OS chrome so we paint our own border.
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(_POPOVER_WIDTH)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet("background:transparent;")
        hdr.setFixedHeight(34)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 0, 14, 0)
        title = QLabel("QUICK SETTINGS")
        title.setFont(_mono(10, bold=True))
        title.setStyleSheet(
            f"color:{CYAN};letter-spacing:2px;background:transparent;border:none;"
        )
        hl.addWidget(title)
        hl.addStretch(1)
        outer.addWidget(hdr)
        outer.addWidget(self._sep())

        # Rows
        self._row_mic = _ToggleRow(
            "MUTE MIC",
            "Block voice capture session-wide.",
        )
        self._row_mic.toggled.connect(self.mic_muted_changed.emit)
        outer.addWidget(self._row_mic)

        self._row_tts = _ToggleRow(
            "MUTE TTS",
            "Suppress spoken responses; transcript still updates.",
        )
        self._row_tts.toggled.connect(self.tts_muted_changed.emit)
        outer.addWidget(self._row_tts)

        self._row_conf = _ToggleRow(
            "AUTO-CONFIRM",
            "Skip confirmation prompts. DANGEROUS — destructive actions run instantly.",
            warn=True,
        )
        self._row_conf.toggled.connect(self.auto_confirm_changed.emit)
        outer.addWidget(self._row_conf)

        outer.addWidget(self._sep())

        # Footer link → full settings page
        link = QPushButton("OPEN FULL SETTINGS  →")
        link.setCursor(Qt.PointingHandCursor)
        link.setFlat(True)
        link.setStyleSheet(
            "QPushButton{"
            f"color:{CYAN};font-family:'{FM}';font-size:10px;font-weight:700;"
            "letter-spacing:2px;background:transparent;border:none;"
            "padding:10px 14px;text-align:left;"
            "}"
            "QPushButton:hover{background:rgba(0,229,255,0.10);}"
        )
        link.clicked.connect(self._on_open_settings)
        outer.addWidget(link)

        # Tighten size to content
        self.adjustSize()

    @staticmethod
    def _sep() -> QFrame:
        s = QFrame()
        s.setFrameShape(QFrame.HLine)
        s.setStyleSheet("color:rgba(0,229,255,0.15);background:rgba(0,229,255,0.15);")
        s.setFixedHeight(1)
        return s

    # ── Public API ───────────────────────────────────────────────────────────

    def sync_state(self, mic_muted: bool, tts_muted: bool, auto_confirm: bool) -> None:
        """Reflect external flag values without re-emitting toggle signals."""
        self._row_mic.set_checked(mic_muted)
        self._row_tts.set_checked(tts_muted)
        self._row_conf.set_checked(auto_confirm)

    def show_below(self, anchor: QWidget, x_offset: int = 0, y_gap: int = 6) -> None:
        """Pop up directly under *anchor*, right-aligned to its right edge.

        Right-alignment matches the icon's position in the TopBar (right side)
        and prevents the popover from spilling off the window's right edge.
        """
        if anchor is None:
            self.show()
            return
        global_top_left = anchor.mapToGlobal(QPoint(0, anchor.height() + y_gap))
        # Right-align: shift left by (popover_width - anchor_width)
        x = global_top_left.x() + anchor.width() - self.width() + x_offset
        y = global_top_left.y()
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    # ── Painting ─────────────────────────────────────────────────────────────

    def _on_open_settings(self) -> None:
        self.open_settings.emit()
        self.close()

    def paintEvent(self, _):
        # Hand-painted glass background + cyan hairline border to match the
        # GlassPanel aesthetic used by every other surface in the app.
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        # Body
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(10, 17, 19, 245))
        p.drawRect(rect)
        # Border
        p.setPen(QPen(QColor(0, 229, 255, 110), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(rect)
        # Top accent — slightly brighter line to suggest "anchored to topbar"
        p.setPen(QPen(QColor(0, 229, 255, 180), 1))
        p.drawLine(rect.left(), rect.top(), rect.right(), rect.top())


# ─────────────────────────────────────────────────────────────────────────────
# SystemStatusPopover — broadcast icon
# Honest read-only view of subsystem health. No fake toggles.
# ─────────────────────────────────────────────────────────────────────────────

# Status kind → (StatusPip status, value text color, detail text color)
_KIND_STYLE = {
    "ok":      ("active",  GREEN,                       "rgba(132,147,150,0.55)"),
    "warn":    ("standby", WARNING,                     "rgba(132,147,150,0.55)"),
    "fail":    ("error",   RED,                         "rgba(132,147,150,0.55)"),
    "off":     ("standby", "rgba(132,147,150,0.55)",    "rgba(132,147,150,0.45)"),
    "info":    ("active",  CYAN,                        "rgba(132,147,150,0.55)"),
}


class _StatusRow(QWidget):
    """One subsystem row: pip + label + status value + optional detail."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 6, 14, 6)
        lay.setSpacing(10)

        self._pip = StatusPip("standby")
        self._pip.setFixedSize(8, 8)
        lay.addWidget(self._pip, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(2)

        self._label_lbl = QLabel(label)
        self._label_lbl.setFont(_mono(9, bold=True))
        self._label_lbl.setStyleSheet(
            "color:rgba(195,245,255,0.78);letter-spacing:1px;"
            "background:transparent;border:none;"
        )
        col.addWidget(self._label_lbl)

        self._detail_lbl = QLabel("")
        self._detail_lbl.setStyleSheet(
            "color:rgba(132,147,150,0.55);font-family:'Roboto Mono';"
            "font-size:9px;background:transparent;border:none;"
        )
        self._detail_lbl.setWordWrap(True)
        self._detail_lbl.setVisible(False)
        col.addWidget(self._detail_lbl)

        lay.addLayout(col, 1)

        self._value_lbl = QLabel("—")
        self._value_lbl.setFont(_mono(10, bold=True))
        self._value_lbl.setStyleSheet(
            "color:rgba(132,147,150,0.55);letter-spacing:1px;"
            "background:transparent;border:none;"
        )
        self._value_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self._value_lbl, 0, Qt.AlignVCenter)

    def set_status(self, value: str, kind: str = "ok", detail: str = "") -> None:
        pip_status, value_color, detail_color = _KIND_STYLE.get(
            kind, _KIND_STYLE["off"]
        )
        self._pip.set_status(pip_status)
        self._value_lbl.setText(value)
        self._value_lbl.setStyleSheet(
            f"color:{value_color};font-family:'{FM}';font-size:10px;"
            "font-weight:700;letter-spacing:1px;"
            "background:transparent;border:none;"
        )
        if detail:
            self._detail_lbl.setText(detail)
            self._detail_lbl.setStyleSheet(
                f"color:{detail_color};font-family:'Roboto Mono';"
                "font-size:9px;background:transparent;border:none;"
            )
            self._detail_lbl.setVisible(True)
        else:
            self._detail_lbl.setVisible(False)


class SystemStatusPopover(QFrame):
    """Read-only system status panel — anchored to the broadcast TopBar icon.

    All rows are populated via refresh() which pulls live values from config,
    voice_engine, browser, and the executor's reminder registry. Refreshed on
    every open so values are always current.
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(_POPOVER_WIDTH)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet("background:transparent;")
        hdr.setFixedHeight(34)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 0, 14, 0)
        title = QLabel("SYSTEM STATUS")
        title.setFont(_mono(10, bold=True))
        title.setStyleSheet(
            f"color:{CYAN};letter-spacing:2px;background:transparent;border:none;"
        )
        hl.addWidget(title)
        hl.addStretch(1)
        self._timestamp_lbl = QLabel("")
        self._timestamp_lbl.setStyleSheet(
            "color:rgba(132,147,150,0.45);font-family:'Roboto Mono';"
            "font-size:9px;letter-spacing:1px;background:transparent;border:none;"
        )
        hl.addWidget(self._timestamp_lbl)
        outer.addWidget(hdr)
        outer.addWidget(QuickSettingsPopover._sep())

        # Rows — order chosen to surface the most likely failure points first.
        self._row_claude    = _StatusRow("CLAUDE API")
        self._row_tts       = _StatusRow("TTS · ELEVENLABS")
        self._row_stt       = _StatusRow("STT · GOOGLE")
        self._row_browser   = _StatusRow("BROWSER SESSION")
        self._row_reminders = _StatusRow("ACTIVE REMINDERS")
        self._row_wake      = _StatusRow("WAKE WORD")
        for row in (
            self._row_claude, self._row_tts, self._row_stt,
            self._row_browser, self._row_reminders, self._row_wake,
        ):
            outer.addWidget(row)

        outer.addWidget(QuickSettingsPopover._sep())

        footer = QLabel("Read-only. Edit credentials in the Settings page.")
        footer.setStyleSheet(
            "color:rgba(132,147,150,0.45);font-family:'Roboto Mono';"
            "font-size:9px;background:transparent;border:none;padding:8px 14px;"
        )
        outer.addWidget(footer)

        self.adjustSize()

    # ── Public API ───────────────────────────────────────────────────────────

    def show_below(self, anchor: QWidget, x_offset: int = 0, y_gap: int = 6) -> None:
        # Same anchoring strategy as QuickSettingsPopover — duplicated here
        # rather than inherited so the two popovers stay independent classes.
        if anchor is None:
            self.show()
            return
        global_top_left = anchor.mapToGlobal(QPoint(0, anchor.height() + y_gap))
        x = global_top_left.x() + anchor.width() - self.width() + x_offset
        y = global_top_left.y()
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh(self) -> None:
        """Pull live values from backend modules and update rows.

        Each subsystem check is wrapped so a single failure (e.g. config not
        loaded yet) cannot stop the rest of the popover from rendering.
        """
        from datetime import datetime

        # ── Claude API ───────────────────────────────────────────────────────
        try:
            from config.settings import config
            if config.anthropic_api_key:
                model = getattr(config, "claude_model", "claude")
                self._row_claude.set_status("CONFIGURED", "ok", model)
            else:
                self._row_claude.set_status(
                    "MISSING KEY", "fail",
                    "Set ANTHROPIC_API_KEY in environment.",
                )
        except Exception as exc:
            self._row_claude.set_status("ERROR", "fail", str(exc)[:80])

        # ── ElevenLabs TTS ───────────────────────────────────────────────────
        try:
            from config.settings import config
            from core.voice import voice_engine
            if voice_engine.tts_muted:
                self._row_tts.set_status(
                    "MUTED", "warn", "Toggle in Quick Settings to re-enable.",
                )
            elif config.elevenlabs_api_key:
                self._row_tts.set_status("ACTIVE", "ok")
            else:
                self._row_tts.set_status(
                    "FALLBACK", "warn",
                    "ElevenLabs key missing — using local TTS.",
                )
        except Exception as exc:
            self._row_tts.set_status("ERROR", "fail", str(exc)[:80])

        # ── Google STT ───────────────────────────────────────────────────────
        try:
            from core.voice import voice_engine
            if voice_engine.mic_muted:
                self._row_stt.set_status(
                    "MUTED", "warn", "Toggle in Quick Settings to re-enable.",
                )
            else:
                # speech_recognition is the actual Google STT backend
                try:
                    import speech_recognition  # noqa: F401
                    self._row_stt.set_status("READY", "ok")
                except ImportError:
                    self._row_stt.set_status(
                        "MISSING", "fail",
                        "Install: pip install SpeechRecognition",
                    )
        except Exception as exc:
            self._row_stt.set_status("ERROR", "fail", str(exc)[:80])

        # ── Browser session ──────────────────────────────────────────────────
        try:
            from core.browser import browser
            # is_ready is a @property — never call it.
            if browser.is_ready:
                self._row_browser.set_status("ONLINE", "ok", "Chrome attached.")
            else:
                err = getattr(browser, "_start_err", "") or ""
                if err:
                    self._row_browser.set_status(
                        "FAILED", "fail", err[:80],
                    )
                else:
                    self._row_browser.set_status(
                        "STARTING", "warn", "Launching Chrome…",
                    )
        except Exception as exc:
            self._row_browser.set_status("ERROR", "fail", str(exc)[:80])

        # ── Reminders ────────────────────────────────────────────────────────
        try:
            from core import executor
            count = len(executor._active_reminders)
            if count == 0:
                self._row_reminders.set_status("0 SCHEDULED", "off")
            else:
                self._row_reminders.set_status(f"{count} SCHEDULED", "info")
        except Exception as exc:
            self._row_reminders.set_status("ERROR", "fail", str(exc)[:80])

        # ── Wake word (honest placeholder — backend not implemented yet) ─────
        try:
            from config.settings import config
            self._row_wake.set_status(
                "COMING SOON", "off",
                f"Configured word: \"{config.wake_word}\"",
            )
        except Exception:
            self._row_wake.set_status("COMING SOON", "off")

        self._timestamp_lbl.setText(datetime.now().strftime("AS OF %H:%M:%S"))

    # ── Painting (mirrors QuickSettingsPopover) ──────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(10, 17, 19, 245))
        p.drawRect(rect)
        p.setPen(QPen(QColor(0, 229, 255, 110), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(rect)
        p.setPen(QPen(QColor(0, 229, 255, 180), 1))
        p.drawLine(rect.left(), rect.top(), rect.right(), rect.top())


__all__ = ["QuickSettingsPopover", "SystemStatusPopover"]
