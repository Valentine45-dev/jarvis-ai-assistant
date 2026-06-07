"""QApplication bootstrap for JARVIS (R2-17a split).

Houses ``main()`` — the process entry point. ``main.py`` at the repo root
re-exports this so ``uv run python main.py`` keeps working unchanged.
"""

from __future__ import annotations

import sys

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QPalette, QColor

from ui.theme import (
    PRIMARY,
    BG,
    _c,
    _primary,
    load_jarvis_fonts,
    jarvis_logo_icon,
    tooltip_qss,
)
from config.settings import config
from core.signals import signals
from core.browser import browser
from ui.main_window.window import JarvisWindow


def main():
    import signal
    signal.signal(signal.SIGINT,  lambda *_: (browser.stop(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda *_: (browser.stop(), sys.exit(0)))

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setWindowIcon(jarvis_logo_icon())

    # Register bundled .ttf files (Roboto Mono, etc.) into Qt's font database
    # so QSS `font-family:'Roboto Mono'` declarations actually resolve
    # instead of silently falling back to a default monospace.
    load_jarvis_fonts()

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(PRIMARY))
    pal.setColor(QPalette.Base, _c(9, 9, 11))
    pal.setColor(QPalette.Text, QColor(PRIMARY))
    pal.setColor(QPalette.Button, _c(39, 39, 42))
    pal.setColor(QPalette.ButtonText, QColor(PRIMARY))
    pal.setColor(QPalette.Highlight, QColor(PRIMARY))
    pal.setColor(QPalette.HighlightedText, QColor(BG))
    pal.setColor(QPalette.PlaceholderText, _primary(46))
    # Fusion defaults can make QToolTip text nearly invisible; QSS + palette for ToolTip roles
    pal.setColor(QPalette.ToolTipBase, _c(25, 33, 34))
    pal.setColor(QPalette.ToolTipText, _c(220, 232, 235))
    app.setPalette(pal)
    app.setStyleSheet(tooltip_qss())

    w = JarvisWindow()
    w.setMinimumSize(1280, 800)
    w.showMaximized()

    # R2-31: surface a missing ANTHROPIC_API_KEY before the user types or
    # speaks. Without this, the first command silently 401s and the user
    # gets a vague "I'm unable to process that" with no clue why. Deferred
    # by 800ms so the window has rendered and the toast actually animates
    # in (zero-delay queues the toast before the panel exists).
    if not (config.anthropic_api_key or "").strip():
        QTimer.singleShot(
            800,
            lambda: signals.status_changed.emit(
                "Set ANTHROPIC_API_KEY in .env — JARVIS can't route commands without it"
            ),
        )

    sys.exit(app.exec_())
