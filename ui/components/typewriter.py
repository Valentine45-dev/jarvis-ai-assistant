from __future__ import annotations

import random

from PyQt5.QtCore import QObject, QTimer


# Pool of in-progress verbs the typewriter cycles through while the brain is
# working. One is picked at random per request so the user doesn't watch the
# same "Thinking…" frame on every command. Keep entries short (≤10 chars) so
# the 3-dot animation fits inside the transcript bubble cleanly.
_THINKING_WORDS: tuple[str, ...] = (
    "Thinking",
    "Pondering",
    "Cooking",
    "Baking",
    "Brewing",
    "Crunching",
    "Computing",
    "Processing",
    "Working",
    "Calculating",
    "Considering",
    "Reasoning",
    "Reading",
    "Reflecting",
    "Cogitating",
)


class _TypewriterProxy(QObject):
    """Wraps TranscriptPanel so both user speech and JARVIS responses animate.

    User speech: types in at 20 ms/char (fast, live-captioning feel).
    Thinking dots: animated placeholder while brain is working.
    JARVIS response: types in at 25 ms/char after brain result arrives.

    Row-id anchoring (Option B): each animation captures the stable id of the row
    it is animating (the command row, allocated by panel.add_exchange) and every
    tick targets THAT id via panel.update_you / panel.update_jarvis — never "the
    last row". So a concurrent appender (narration / follow / reminder / scheduled
    row) appending mid-animation can't steal the typewriter's target: the in-flight
    reply keeps writing to its own row, the new row lands as its own row. The id is
    held in the animation state (not re-read from _active_row_id each tick), so even
    a brand-new command starting mid-animation (the "speaking" state isn't guarded)
    can't redirect an in-flight reply onto the new command's row.

    Delegates every attribute except add_exchange()/update_last_jarvis() (and the
    interrupt helpers) to the real panel so callers interact with it identically to
    TranscriptPanel. append_jarvis_scheduled() falls through to the panel unchanged
    — it is an INDEPENDENT row and must not disturb _active_row_id.
    """

    _JARVIS_INTERVAL_MS  = 25
    _YOU_INTERVAL_MS     = 20
    _THINKING_INTERVAL_MS = 500

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self._panel = panel

        # Stable id of the row currently being animated (the command row). Set when
        # add_exchange() creates the row; each animation captures it at start time.
        self._active_row_id = None

        # ── JARVIS typewriter ────────────────────────────────────────────────
        self._timer = QTimer(self)
        self._timer.setInterval(self._JARVIS_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._pending = None   # (full_text, j_time, intent, conf, success, row_id)
        self._pos = 0

        # ── Thinking dots ────────────────────────────────────────────────────
        self._thinking_timer = QTimer(self)
        self._thinking_timer.setInterval(self._THINKING_INTERVAL_MS)
        self._thinking_timer.timeout.connect(self._tick_thinking)
        self._thinking_dots = 1
        self._thinking_row_id = None   # row the dots animate on
        # Chosen at _start_thinking() time — stays stable for the whole
        # request so the dots animate against a single word rather than
        # flicker between variants every 500ms.
        self._thinking_word: str = _THINKING_WORDS[0]

        # ── User speech typewriter ───────────────────────────────────────────
        self._you_timer = QTimer(self)
        self._you_timer.setInterval(self._YOU_INTERVAL_MS)
        self._you_timer.timeout.connect(self._tick_you)
        self._you_pending = None   # (full_you, y_time, row_id)
        self._you_pos = 0

    def __getattr__(self, name):
        if "_panel" not in self.__dict__:
            raise AttributeError(name)
        return getattr(self._panel, name)

    # ── Public API ────────────────────────────────────────────────────────────

    def add_exchange(self, you, time="", jarvis="", j_time="", intent="", conf=None,
                     success=None):
        self._stop_thinking()
        self._timer.stop()
        self._pending = None
        self._flush_you()   # snap any in-progress user text (on its OWN row) to final

        # History / mock entries already have a JARVIS response — render instantly.
        if jarvis:
            self._active_row_id = self._panel.add_exchange(
                you, time, jarvis, j_time, intent, conf, success)
            return

        # New live command: create the row, remember its id, then type into THAT row.
        self._active_row_id = self._panel.add_exchange("", time, "", "", None, None, None)
        if you:
            self._you_pending = (you, time, self._active_row_id)
            self._you_pos = 0
            self._you_timer.start()
        else:
            self._start_thinking()

    def stop_animations(self):
        """Halt every in-progress animation (you / jarvis / thinking dots) so a
        running timer can't keep mutating a row after it's finalized — e.g. on
        Esc-interrupt, where the 'thinking' dots would otherwise clobber the
        Interrupted marker."""
        self._stop_thinking()
        self._timer.stop()
        self._pending = None
        self._flush_you()   # snap in-progress user text to FULL, not truncated

    def mark_interrupted(self, j_time=""):
        """Stop animations and mark the active row's response as 'Interrupted'
        (rendered with the amber marker via the 'interrupted' intent)."""
        self.stop_animations()
        self._panel.update_jarvis(
            self._active_row_id, "Interrupted", j_time, "interrupted", None)

    def update_last_jarvis(self, text, j_time="", intent="", conf=None, success=None):
        self._stop_thinking()
        self._timer.stop()
        # If user text is still animating, snap it to completion first.
        self._flush_you()
        rid = self._active_row_id
        if not text:
            self._panel.update_jarvis(rid, text, j_time, intent, conf, success)
            return
        self._pending = (text, j_time, intent, conf, success, rid)
        self._pos = 0
        # Seed with empty text so _tick() has a row to update.
        self._panel.update_jarvis(rid, "", j_time, None, None)
        self._timer.start()

    # ── JARVIS typewriter ticks ───────────────────────────────────────────────

    def _tick(self):
        if not self._pending:
            self._timer.stop()
            return
        full_text, j_time, intent, conf, success, rid = self._pending
        self._pos += 1
        if self._pos >= len(full_text):
            self._timer.stop()
            self._pending = None
            self._panel.update_jarvis(rid, full_text, j_time, intent, conf, success)
        else:
            self._panel.update_jarvis(rid, full_text[: self._pos], j_time, None, None)

    # ── User speech typewriter ticks ─────────────────────────────────────────

    def _tick_you(self):
        if not self._you_pending:
            self._you_timer.stop()
            return
        full_you, y_time, rid = self._you_pending
        self._you_pos += 1
        if self._you_pos >= len(full_you):
            self._you_timer.stop()
            self._you_pending = None
            self._panel.update_you(rid, full_you, y_time)
            self._start_thinking()
        else:
            self._panel.update_you(rid, full_you[: self._you_pos], y_time)

    # ── Thinking animation ────────────────────────────────────────────────────

    def _thinking_text(self):
        return f"{self._thinking_word}{'.' * self._thinking_dots}"

    def _tick_thinking(self):
        self._thinking_dots = 1 if self._thinking_dots >= 3 else self._thinking_dots + 1
        self._panel.update_jarvis(self._thinking_row_id, self._thinking_text(), "", None, None)

    def _start_thinking(self):
        self._thinking_dots = 1
        # Pick a fresh verb each time the user fires off a new command. A
        # given long-running request shows the same word with animating
        # dots; the NEXT request picks a different word.
        self._thinking_word = random.choice(_THINKING_WORDS)
        self._thinking_row_id = self._active_row_id
        self._panel.update_jarvis(self._thinking_row_id, self._thinking_text(), "", None, None)
        self._thinking_timer.start()

    def _stop_thinking(self):
        if self._thinking_timer.isActive():
            self._thinking_timer.stop()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _flush_you(self):
        """Snap in-progress user text animation to its final state immediately (on
        the row it was animating, by id)."""
        if self._you_pending:
            full_you, y_time, rid = self._you_pending
            self._you_timer.stop()
            self._you_pending = None
            self._panel.update_you(rid, full_you, y_time)
        else:
            self._you_timer.stop()
