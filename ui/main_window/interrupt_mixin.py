"""Esc-to-interrupt for JarvisWindow.

Plain mixin — no QObject base, no signals defined here. Methods use only
``self``. Must NOT import ``window`` or ``app`` (no import cycle).

One key (Esc) aborts whatever's in flight: it invalidates a pending brain reply
via the existing ``_transcript_update_token`` staleness mechanism, silences the
voice mid-clip, cancels a live mic capture, stands down a pending confirmation,
logs an "Interrupted" row in the sys-log, and restores the prompt to the command
bar so it can be edited/resent.

Known limit: ``dispatch()`` runs synchronously on the Qt main thread, so an
action already executing (e.g. a browser step) blocks the event loop and Esc
can't fire until it returns. Interrupt covers the threaded stages
(thinking / speaking / listening) and confirmation.
"""

from __future__ import annotations

from datetime import datetime


class _InterruptMixin:
    """``_on_interrupt_requested`` — wired to a global Esc QShortcut in window.py."""

    def _on_interrupt_requested(self):
        # Let an open command palette handle its own Esc (close itself).
        palette = getattr(self, "_palette", None)
        if palette is not None and palette.isVisible():
            return

        from core.voice import voice_engine
        try:
            speaking = voice_engine.is_speaking
        except Exception:
            speaking = False

        # Nothing in flight → Esc stays harmless when idle.
        if self._state == "idle" and not speaking:
            return

        was_confirm = self._state == "awaiting_confirmation"
        # A command is genuinely in flight (a transcript row exists for it) only
        # in these states. "listening"/"connecting" cancelled a capture before
        # anything was submitted — nothing to log or restore.
        in_command = self._state in ("thinking", "processing", "speaking",
                                     "awaiting_confirmation")

        # 1. Invalidate any in-flight brain reply / follow-up narration / stale
        #    TTS callbacks (the token checks across the pipeline drop them).
        self._transcript_update_token += 1

        # 2. Silence the voice immediately (cuts the current clip mid-play).
        try:
            voice_engine.stop_speaking()
        except Exception:
            pass

        # 3. Abort a live mic capture.
        if self._state in ("listening", "connecting"):
            try:
                voice_engine.cancel_listening()
            except Exception:
                pass

        # 4. Stand down a pending confirmation (mirror the Cancel-button path).
        if was_confirm:
            try:
                self._hide_confirm_card()
            except Exception:
                pass
            self._confirm_mode = None
            self._pending_result = None
            try:
                from core.executor import resolve_confirmation
                resolve_confirmation("no")
            except Exception:
                pass
            try:
                self._voice_view.clear_pending()
            except Exception:
                pass

        now = datetime.now().strftime("%H:%M")
        prompt = (getattr(self, "_last_cmd_text", "") or "").strip()

        if in_command:
            # 5. Mark the existing command row as Interrupted (UPDATE, not
            #    append) so the running typewriter can't clobber it, then mark
            #    history.
            try:
                self._dashboard.left.transcript.mark_interrupted(now)
            except Exception:
                pass
            if self._history and self._history[-1].get("status") == "pending":
                self._history[-1].update({
                    "jarvis": "Interrupted", "jTime": now,
                    "intent": "interrupted", "status": "interrupted",
                })
            # 6. Restore the prompt — but don't clobber text already typed.
            try:
                field = self._dashboard.left.cmd_bar._input  # noqa: SLF001
                if prompt and not field.text().strip():
                    field.setText(prompt)
                    field.setFocus()
            except Exception:
                pass
        else:
            # Cancelled a live capture — no command was submitted. Just stop any
            # animation and clear the half-typed dictation for a clean idle.
            try:
                self._dashboard.left.transcript.stop_animations()
            except Exception:
                pass
            try:
                self._clear_voice_dictation()
            except Exception:
                pass

        # 7. Reset: hide the typing indicator, drop to idle, flash the HUD.
        try:
            self._dashboard.left.typing.hide_typing()
        except Exception:
            pass
        self._set_state("idle")
        try:
            self._dashboard.left.hud_status.set_status("INTERRUPTED")
        except Exception:
            pass
        try:
            self._dashboard.toast.show_toast("Interrupted.", "warning")
        except Exception:
            pass
