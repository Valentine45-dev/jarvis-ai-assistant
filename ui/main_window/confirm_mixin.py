"""Confirmation-flow routing for JarvisWindow (R2-17a split).

Plain mixin — no QObject base, no signals defined here. Methods use only
``self``. Must NOT import ``window`` or ``app`` (no import cycle).

Thread affinity: ``_on_confirmed`` emits ``self._resume_executor_confirm``
(a ``Qt.QueuedConnection`` signal wired in window.py/__init__) rather than
calling ``resolve_confirmation`` inline, so the executor callback — which may
continue a workflow and touch Playwright's thread-affine sync API — always runs
back on the Qt main thread via ``_on_resume_executor_confirm``. This hand-off
is regression-tested by tests/test_workflow_thread_hop.py.
"""

from __future__ import annotations

from datetime import datetime


class _ConfirmMixin:
    """Confirm-card show/hide, confirmation resolution, and the
    ``_resume_executor_confirm`` main-thread hand-off."""

    def _on_confirmation_resolved(self, resolved: dict):
        """Called on the Qt main thread after a pending confirmation is resolved."""
        j_time = datetime.now().strftime("%H:%M")
        self._dashboard.left.typing.hide_typing()

        # A confirmation resolution can itself schedule a follow-up confirmation
        # (workflow continuation with another file-op step). Keep the confirm
        # card loop alive instead of dropping out after the first step.
        if self._confirmation_controller.needs_followup_confirmation(resolved):
            display_resp = self._confirmation_controller.prompt_from_result(resolved)
            self._confirm_mode = "executor"
            if self._history:
                self._history[-1].update({
                    "jarvis": display_resp,
                    "jTime": j_time,
                    "intent": "confirmation",
                    "conf": 1.0,
                    "status": "pending",
                })
            self._show_confirm_card(display_resp)
            self._dashboard.toast.show_toast(display_resp, "warning")
            return

        display_resp = self._confirmation_controller.final_display_response(resolved)

        if self._history:
            self._history[-1].update({
                "jarvis": display_resp, "jTime": j_time,
                "intent": "confirmation", "conf": 1.0,
                "status": self._confirmation_controller.final_history_status(resolved),
            })

        self._set_state("processing")
        self._dashboard.left.status_lbl.setText(display_resp)
        self._dashboard.left.hud_status.set_status(self._confirmation_controller.final_hud_status(resolved))

        self._transcript_update_token += 1
        t = self._transcript_update_token
        payload = (t, display_resp, j_time, "confirmation", 1.0)
        try:
            from core.voice import voice_engine
            voice_engine.say(
                display_resp,
                on_ready=lambda: self._tts_ready.emit(payload),
                on_done=lambda: self._tts_done_signal.emit(t),
            )
        except Exception:
            self._tts_ready.emit(payload)
            self._tts_done_signal.emit(t)

        kind = self._confirmation_controller.final_toast_kind(resolved)
        self._dashboard.toast.show_toast(display_resp, kind)

    def _on_confirmed(self):
        self._hide_confirm_card()
        mode = self._confirm_mode
        self._confirm_mode = None
        if mode == "claude" and self._pending_result:
            r = self._pending_result
            self._pending_result = None
            self._execute_result(
                r,
                r.get("intent", "unknown"),
                float(r.get("confidence", 0.85)),
                r.get("response", ""),
                r.get("hud_status", "STANDBY"),
                confirmed=True,
            )
        elif mode == "executor":
            # Resolve the executor confirmation on the Qt MAIN thread (via signal
            # + QueuedConnection). The callback may continue a workflow whose
            # next steps touch Playwright — sync Playwright is thread-affine and
            # crashes with "Cannot switch to a different thread" if dispatched
            # from a worker. _yield_ui() also calls processEvents() which is
            # main-thread-only.
            self._resume_executor_confirm.emit("yes")

    def _on_resume_executor_confirm(self, answer: str) -> None:
        """Slot for _resume_executor_confirm — runs on Qt main thread.

        Calls resolve_confirmation() here so the callback (which may continue a
        workflow + invoke Playwright/dispatch) executes on the same thread as
        the browser session. Result is forwarded to _on_confirmation_resolved.
        """
        from core.executor import resolve_confirmation
        resolved = resolve_confirmation(answer)
        self._on_confirmation_resolved(resolved)

    def _on_cancelled(self):
        self._hide_confirm_card()
        mode = self._confirm_mode
        self._confirm_mode = None
        self._pending_result = None
        if mode == "executor":
            from core.executor import resolve_confirmation
            resolve_confirmation("no")

        msg = self._confirmation_controller.CANCEL_MESSAGE
        j_time = datetime.now().strftime("%H:%M")

        if self._history:
            self._history[-1].update({
                "jarvis": msg, "jTime": j_time,
                "intent": "confirmation", "conf": 1.0,
                "status": "warning",
            })

        self._set_state("processing")
        self._dashboard.left.hud_status.set_status("CANCELLED")
        self._dashboard.left.status_lbl.setText(msg)
        self._voice_view.clear_pending()

        # Route through _tts_ready so the transcript typewriter fires and
        # state transitions to speaking → idle (mirrors _on_confirmation_resolved)
        self._transcript_update_token += 1
        t = self._transcript_update_token
        payload = (t, msg, j_time, "confirmation", 1.0)
        try:
            from core.voice import voice_engine
            voice_engine.say(
                msg,
                on_ready=lambda: self._tts_ready.emit(payload),
                on_done=lambda: self._tts_done_signal.emit(t),
            )
        except Exception:
            self._tts_ready.emit(payload)
            self._tts_done_signal.emit(t)

    # ── Inline confirm card helpers ───────────────────────────────────────────

    def _show_confirm_card(self, prompt: str) -> None:
        """Show the transcript confirm card and enter awaiting_confirmation state."""
        wait_line = self._dashboard.left.transcript.show_confirm(prompt)
        self._dashboard.left.typing.hide_typing()
        self._set_state("awaiting_confirmation")
        self._dashboard.left.status_lbl.setText(wait_line)

    def _hide_confirm_card(self) -> None:
        self._dashboard.left.transcript.hide_confirm()
