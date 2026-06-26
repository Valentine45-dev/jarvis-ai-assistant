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
    install_theme,
    load_jarvis_fonts,
    jarvis_logo_icon,
    tooltip_qss,
)
from config.settings import config
from core.signals import signals
from core.browser import browser
from ui.main_window.window import JarvisWindow


def _install_crash_diagnostics() -> None:
    """Make crashes visible instead of the process vanishing silently.

    Covers all three ways JARVIS can die without a Python traceback:
    native segfault / abort / Qt fatal (faulthandler), an unhandled exception on
    the main thread OR a worker thread (sys/threading excepthook), and Qt's own
    warnings/criticals — including thread-affinity violations like "Cannot create
    children for a parent in a different thread" (qInstallMessageHandler).
    Everything is written to stderr (the terminal) and appended to logs/crash.log.
    """
    import faulthandler
    import threading
    import traceback
    from datetime import datetime
    from pathlib import Path

    try:
        faulthandler.enable()  # native-level dump to stderr on segfault/abort
    except Exception:
        pass

    crash_log = Path(__file__).resolve().parents[2] / "logs" / "crash.log"
    try:
        crash_log.parent.mkdir(exist_ok=True)
    except Exception:
        pass

    def _record(header: str, body: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = f"\n===== {header} @ {stamp} =====\n{body}\n"
        try:
            sys.stderr.write(text)
            sys.stderr.flush()
        except Exception:
            pass
        try:
            with open(crash_log, "a", encoding="utf-8") as fp:
                fp.write(text)
        except Exception:
            pass

    def _excepthook(exc_type, exc, tb):
        _record("UNHANDLED EXCEPTION (main thread)",
                "".join(traceback.format_exception(exc_type, exc, tb)))

    sys.excepthook = _excepthook

    def _thread_excepthook(args):
        name = args.thread.name if args.thread else "?"
        _record(f"UNHANDLED EXCEPTION (thread: {name})",
                "".join(traceback.format_exception(
                    args.exc_type, args.exc_value, args.exc_traceback)))

    try:
        threading.excepthook = _thread_excepthook  # Py3.8+
    except Exception:
        pass

    try:
        from PyQt5.QtCore import QtMsgType, qInstallMessageHandler

        def _qt_handler(mode, _ctx, message):
            msg = message or ""
            if "Could not parse stylesheet" in msg:
                return  # benign Fusion-QSS noise — don't clutter the log
            label = {
                QtMsgType.QtWarningMsg: "Qt WARNING",
                QtMsgType.QtCriticalMsg: "Qt CRITICAL",
                QtMsgType.QtFatalMsg: "Qt FATAL",
            }.get(mode)
            if label is None:
                return  # skip Debug/Info chatter
            _record(label, msg)

        qInstallMessageHandler(_qt_handler)
    except Exception:
        pass


def main():
    _install_crash_diagnostics()
    import signal
    signal.signal(signal.SIGINT,  lambda *_: (browser.stop(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda *_: (browser.stop(), sys.exit(0)))

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # Route every setStyleSheet through the active-theme accent substitution
    # BEFORE any widget is built. No-op for the default cyan theme.
    install_theme()
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
