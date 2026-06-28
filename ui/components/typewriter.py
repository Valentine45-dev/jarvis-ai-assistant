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
        # Follow-up animations (narration / responder follow) waiting their turn so
        # they type out AFTER the primary, one at a time. Each entry is the same
        # 6-tuple shape as _pending and carries its OWN reserved row id, so starting
        # one just assigns _pending — the typewriter still writes only to that id
        # (Option B invariant). Async appends (reminders/scheduled) do NOT use this;
        # they append instantly via append_jarvis_scheduled(animate=False).
        self._anim_queue: list = []

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

    def append_jarvis_scheduled(self, jarvis, j_time, intent="", conf=None,
                                success=None, animate=False):
        """A JARVIS-only row with no matching YOU line.

        animate=False (default — reminders, scheduled-workflow lines): append
        instantly as a static row. Async notifications must appear immediately and
        must never enter the type-out queue, so they can't collide with a command's
        in-flight animation.

        animate=True (post-execution narration / responder follow): reserve the row
        now (so its position below the command row is fixed), then queue its type-out
        to run AFTER the primary reply finishes animating — one animation at a time.
        The reserved row is empty until it types, which renders as nothing, so there's
        no empty-row flicker."""
        if not animate:
            return self._panel.append_jarvis_scheduled(jarvis, j_time, intent, conf, success)
        rid = self._panel.append_jarvis_scheduled("", j_time, "", None, None)
        self._anim_queue.append((jarvis, j_time, intent, conf, success, rid))
        self._maybe_start_next()
        return rid

    def add_exchange(self, you, time="", jarvis="", j_time="", intent="", conf=None,
                     success=None):
        self._stop_thinking()
        # A new command supersedes any in-flight / queued follow-up animation: snap
        # them to their final text on their OWN rows (don't drop a partial reply, and
        # don't let a prior narration animate after this command's reply).
        self._finalize_all_animations()
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
        Interrupted marker. Also drops any QUEUED follow-up animation so a narration
        can't ghost-type after the user interrupted the turn (its audio is cancelled
        by the interrupt path too)."""
        self._stop_thinking()
        self._timer.stop()
        self._pending = None
        self._anim_queue.clear()
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
            # Primary was instant/empty → it's not animating, so let a queued
            # narration start instead of waiting forever behind it.
            self._maybe_start_next()
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
            # This animation finished → start the next queued follow-up (if any).
            self._maybe_start_next()
        else:
            self._panel.update_jarvis(rid, full_text[: self._pos], j_time, None, None)

    # ── follow-up animation queue (narration / follow type out AFTER the primary) ─

    def _maybe_start_next(self):
        """Start the next queued follow-up animation, but ONLY when the proxy is fully
        idle — the command row has finished its user-text, thinking, and primary-reply
        work. So a narration reserved while the primary is still typing waits its turn;
        exactly one animation runs at a time."""
        if self._pending is not None:
            return
        if self._thinking_timer.isActive() or self._you_timer.isActive():
            return
        if not self._anim_queue:
            return
        entry = self._anim_queue.pop(0)
        _full, j_time, _intent, _conf, _success, rid = entry
        self._pending = entry
        self._pos = 0
        self._panel.update_jarvis(rid, "", j_time, None, None)
        self._timer.start()

    def _finalize_all_animations(self):
        """Snap the in-flight animation AND every queued follow-up to their final text
        on their OWN rows, then clear the queue. Used when a new command supersedes the
        turn: nothing is dropped or left half-typed, and order is preserved (each lands
        on its own reserved row id — the Option B invariant holds)."""
        if self._pending is not None:
            full_text, j_time, intent, conf, success, rid = self._pending
            self._timer.stop()
            self._pending = None
            self._panel.update_jarvis(rid, full_text, j_time, intent, conf, success)
        for full_text, j_time, intent, conf, success, rid in self._anim_queue:
            self._panel.update_jarvis(rid, full_text, j_time, intent, conf, success)
        self._anim_queue.clear()

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
