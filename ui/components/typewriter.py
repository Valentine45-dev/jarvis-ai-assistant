from __future__ import annotations

from PyQt5.QtCore import QObject, QTimer


class _TypewriterProxy(QObject):
    """Wraps TranscriptPanel so JARVIS responses type in character-by-character.

    Delegates every attribute except add_exchange() and update_last_jarvis() to the real panel,
    so main.py and widgets interact with it identically to a bare TranscriptPanel.
    """

    _INTERVAL_MS = 25
    _THINKING_INTERVAL_MS = 500

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self._panel = panel
        self._timer = QTimer(self)
        self._timer.setInterval(self._INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._pending = None  # (full_text, j_time, intent, conf)
        self._pos = 0
        self._thinking_timer = QTimer(self)
        self._thinking_timer.setInterval(self._THINKING_INTERVAL_MS)
        self._thinking_timer.timeout.connect(self._tick_thinking)
        self._thinking_dots = 1

    def __getattr__(self, name):
        if "_panel" not in self.__dict__:
            raise AttributeError(name)
        return getattr(self._panel, name)

    def add_exchange(self, you, time="", jarvis="", j_time="", intent="", conf=None):
        self._stop_thinking()
        self._timer.stop()
        self._pending = None

        # History/mock entries already have a JARVIS response; render them unchanged.
        if jarvis:
            self._panel.add_exchange(you, time, jarvis, j_time, intent, conf)
            return

        self._thinking_dots = 1
        self._panel.add_exchange(you, time, self._thinking_text(), "", None, None)
        self._thinking_timer.start()

    def update_last_jarvis(self, text, j_time="", intent="", conf=None):
        self._stop_thinking()
        self._timer.stop()
        if not text:
            self._panel.update_last_jarvis(text, j_time, intent, conf)
            return
        self._pending = (text, j_time, intent, conf)
        self._pos = 0
        # Seed the row with empty text and no suffix so _render() has a slot to update.
        self._panel.update_last_jarvis("", j_time, None, None)
        self._timer.start()

    def _tick(self):
        if not self._pending:
            self._timer.stop()
            return
        full_text, j_time, intent, conf = self._pending
        self._pos += 1
        if self._pos >= len(full_text):
            self._timer.stop()
            self._pending = None
            # Final call: full text + real intent/conf so the suffix appears.
            self._panel.update_last_jarvis(full_text, j_time, intent, conf)
        else:
            # Partial text, no suffix (None suppresses the " (intent, X%)" line).
            self._panel.update_last_jarvis(full_text[: self._pos], j_time, None, None)

    def _thinking_text(self):
        return f"Thinking{'.' * self._thinking_dots}"

    def _tick_thinking(self):
        self._thinking_dots = 1 if self._thinking_dots >= 3 else self._thinking_dots + 1
        self._panel.update_last_jarvis(self._thinking_text(), "", None, None)

    def _stop_thinking(self):
        if self._thinking_timer.isActive():
            self._thinking_timer.stop()
