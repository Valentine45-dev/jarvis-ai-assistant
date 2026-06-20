"""Composite cards + overlay surfaces (R2-17e split).

Part of the ``ui/widgets`` package. Houses the larger composite widgets that
sit on top of the dashboard / voice surfaces: ``GreetingCard`` (session
summary), ``TypingIndicator`` (legacy no-op shim), ``ToastNotification``
(fade-out overlay), ``ConfirmationBar`` (amber confirm/cancel strip).

Cross-file dependency: ``ConfirmationBar`` uses the cached ``_mono`` factory
from ``ui.widgets.primitives``. One-way import; no cycle.
"""

from __future__ import annotations

from PyQt5.QtCore import (
    Qt,
    QPropertyAnimation,
    QTimer,
    pyqtSignal,
)
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from ui.components.panels import GlassPanel
from ui.theme import CYAN, FM, FN, PRIMARY
from ui.widgets.primitives import _mono


class GreetingCard(GlassPanel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._commands = 0
        self._uptime_s = 0
        self.setMinimumHeight(86)

    def set_stats(self, commands, uptime_s):
        self._commands = int(commands)
        self._uptime_s = int(uptime_s)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setPen(QColor(PRIMARY))
        p.setFont(QFont(FM, 9, QFont.Bold))
        p.drawText(10, 18, "SESSION")
        p.setFont(QFont(FN, 10))
        p.drawText(10, 40, f"Commands: {self._commands}")
        p.drawText(10, 58, f"Uptime: {self._uptime_s // 60}m")


class TypingIndicator(QLabel):
    """Legacy 'JARVIS typing...' floating label.

    Kept as a compat shim so the five `main.py` call sites
    (`show_typing()` / `hide_typing()`) don't break. The label itself is
    never made visible — it had no layout placement and was rendering on
    top of the SYS_LOG_BUFFER panel at (0,0) when shown. If you want a
    real typing indicator later, slot a new widget into the dashboard's
    log column with a proper QHBoxLayout slot rather than reviving this.
    """

    def __init__(self, parent=None):
        super().__init__("JARVIS typing...", parent)
        self.setVisible(False)
        self.setStyleSheet(f"QLabel{{color:{PRIMARY};font-family:'{FM}';font-size:10px;}}")

    def show_typing(self):
        # No-op by design — see class docstring.
        return

    def hide_typing(self):
        # No-op; the widget is never shown so there's nothing to hide.
        return


class ToastNotification(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._label = QLabel("", self)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity")
        self._fade.setDuration(350)
        self._label.setStyleSheet(
            f"QLabel{{background:rgba(8,15,17,0.95);border:1px solid {CYAN};"
            f"color:{PRIMARY};font-family:'{FM}';padding:6px 10px;}}"
        )
        self.hide()

    def _reposition(self):
        if not self.parent():
            return
        toast_w = 280
        right_column_w = 260
        margin = 24
        gap = 16
        x = self.parent().width() - margin - right_column_w - gap - toast_w
        self.setGeometry(max(margin, x), 10, toast_w, 36)
        self._label.setGeometry(0, 0, 280, 36)

    def show_toast(self, text, _kind="info", duration_ms=1400):
        """Flash a toast for `duration_ms` before it fades (default 1.4 s).

        Pass a longer duration for messages that precede a delay (e.g. the
        provider-fallback notices) so they stay readable. Floored at 800 ms.
        """
        self._label.setText(str(text))
        self._reposition()
        self.show()
        self._effect.setOpacity(1.0)
        QTimer.singleShot(max(800, int(duration_ms)), self._fade_out)

    def _fade_out(self):
        self._fade.stop()
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.hide)
        self._fade.start()


class ConfirmationBar(QWidget):
    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    _AMBER = "rgba(255,219,60,0.92)"
    _BORDER = "rgba(255,219,60,0.45)"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self.setFixedHeight(46)
        self.setStyleSheet(
            "background:rgba(22,18,8,0.97);"
            "border-top:1px solid rgba(255,219,60,0.30);"
            "border-bottom:1px solid rgba(255,219,60,0.30);"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 10, 0)
        lay.setSpacing(10)

        warn = QLabel("⚠")
        warn.setFixedWidth(18)
        warn.setStyleSheet(
            "color:rgba(255,219,60,0.80);font-size:13px;"
            "background:transparent;border:none;"
        )
        lay.addWidget(warn)

        self._msg = QLabel("Confirm command?")
        self._msg.setFont(_mono(10))
        self._msg.setStyleSheet(
            f"color:{self._AMBER};background:transparent;border:none;"
        )
        lay.addWidget(self._msg, 1)

        self._ok = QPushButton("CONFIRM")
        self._ok.setFixedSize(86, 28)
        self._ok.setCursor(Qt.PointingHandCursor)
        self._ok.setStyleSheet(
            "QPushButton{"
            f"color:{self._AMBER};border:1px solid {self._BORDER};"
            f"font-family:'Roboto Mono';font-size:10px;font-weight:700;"
            "letter-spacing:1px;background:rgba(255,219,60,0.07);"
            "}"
            "QPushButton:hover{background:rgba(255,219,60,0.18);}"
            "QPushButton:pressed{background:rgba(255,219,60,0.30);}"
            "QPushButton:focus{border:1px solid rgba(255,219,60,0.85);}"
        )
        self._ok.clicked.connect(self.confirmed.emit)
        lay.addWidget(self._ok)

        self._no = QPushButton("CANCEL")
        self._no.setFixedSize(72, 28)
        self._no.setCursor(Qt.PointingHandCursor)
        self._no.setStyleSheet(
            "QPushButton{"
            "color:rgba(132,147,150,0.75);border:1px solid rgba(132,147,150,0.25);"
            "font-family:'Roboto Mono';font-size:10px;letter-spacing:1px;"
            "background:transparent;"
            "}"
            "QPushButton:hover{color:rgba(195,245,255,0.90);border-color:rgba(132,147,150,0.50);}"
            "QPushButton:pressed{background:rgba(132,147,150,0.10);}"
        )
        self._no.clicked.connect(self.cancelled.emit)
        lay.addWidget(self._no)

    def show_confirmation(self, message: str = "") -> None:
        """Set message text and make the bar visible."""
        if message:
            self._msg.setText(message)
        self.setVisible(True)
