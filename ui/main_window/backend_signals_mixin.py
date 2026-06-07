"""Backend-signal slots for JarvisWindow (R2-17a split).

Plain mixin — no QObject base, no signals defined here. Methods use only
``self``. Must NOT import ``window`` or ``app`` (no import cycle).

Every method here runs on the Qt main thread (the signals that drive them use
``Qt.QueuedConnection`` where they originate off-thread). ``_on_reminder_action``
and ``_on_scheduled_workflow_fire`` reach ``dispatch()`` — which must stay on the
main thread for Playwright thread-affinity — and they do, because these slots
are invoked on the main thread.
"""

from __future__ import annotations

import time
from datetime import datetime

from core.history_store import history_store


class _BackendSignalsMixin:
    """Slots wired to ``core.signals`` (status, reminders, errors), the F-4
    hotkey dispatcher, and the F-3 scheduled-workflow fire handler.

    ``self._INTENT_HUD`` resolves through the MRO to the constant defined on
    JarvisWindow.
    """

    def _on_status_signal(self, msg: str):
        """Qt main thread — backend status update (e.g., a reminder fires)."""
        self._dashboard.toast.show_toast(msg, "info")
        self._dashboard.left.status_lbl.setText(msg)

    def _on_reminder_fired(self, payload: dict):
        """Qt main thread — a plain (message-only) reminder elapsed.

        Speaks it, shows a toast, and logs it to the transcript + history so a
        fired reminder is impossible to miss (previously it only flashed the
        HUD status line for a moment).
        """
        msg = str((payload or {}).get("message", "Reminder")).strip() or "Reminder"
        spoken = f"Reminder — {msg}."

        self._dashboard.toast.show_toast(f"⏰ Reminder — {msg}", "info")
        self._dashboard.left.status_lbl.setText(f"REMINDER: {msg}")
        self._dashboard.left.hud_status.set_status("REMINDER")

        j_time = datetime.now().strftime("%H:%M")
        entry = {
            "time": j_time, "you": "⏱ reminder", "jarvis": spoken,
            "jTime": j_time, "intent": "reminder_task", "conf": 1.0,
            "status": "success",
        }
        self._history.append(entry)
        history_store.save_entry(entry)
        try:
            self._dashboard.left.transcript.append_jarvis_scheduled(
                spoken, j_time, "reminder_task", 1.0)
        except Exception:
            pass
        try:
            from core.voice import voice_engine
            voice_engine.say(spoken)
        except Exception:
            pass

    def _on_error_signal(self, msg: str) -> None:
        """Qt main thread — throttled error toasts for noisy provider failures."""
        text = (msg or "").strip()
        if not text:
            return
        now = time.monotonic()
        # [ELEVENLABS-DISABLED] is_voice_provider_error = (
        # [ELEVENLABS-DISABLED]     "voice switch failed" in text.lower()
        # [ELEVENLABS-DISABLED]     and "elevenlabs" in text.lower()
        # [ELEVENLABS-DISABLED] )
        is_voice_provider_error = False  # [ELEVENLABS-DISABLED] always False until re-enabled
        if (
            is_voice_provider_error
            and text == self._last_error_toast_msg
            and (now - self._last_error_toast_ts) < 4.0
        ):
            return
        self._last_error_toast_msg = text
        self._last_error_toast_ts = now
        self._dashboard.toast.show_toast(text, "error")

    def _on_reminder_action(self, payload: dict):
        """Qt main thread — delayed reminder with an executable JARVIS step."""
        from core.executor import dispatch
        from core.responders.assembler import responder
        from core.voice import voice_engine

        run = payload.get("run") or {}
        msg = str(payload.get("message", "Scheduled task"))
        sc = float(payload.get("schedule_confidence", 0.92))
        sc = max(0.0, min(1.0, sc))

        intent = str(run.get("intent", "unknown"))
        act = str(run.get("action", "none"))
        parameters = run.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {}

        result_dict = {
            "intent": intent,
            "action": act,
            "parameters": parameters,
            "requires_confirmation": False,
        }
        exec_out = dispatch(result_dict, confirmed=True)
        exec_ok = bool(exec_out.get("success"))

        display_resp = responder.build_scheduled(
            intent,
            act,
            exec_ok,
            exec_out.get("output", ""),
            exec_out.get("error", ""),
            params=parameters,
        )
        hud_conf = sc if exec_ok else 0.0
        j_time = datetime.now().strftime("%H:%M")

        entry = {
            "time": j_time,
            "you": "⏱ scheduled",
            "jarvis": display_resp,
            "jTime": j_time,
            "intent": intent,
            "conf": hud_conf,
            "status": "success" if exec_ok else "error",
        }
        self._history.append(entry)
        history_store.save_entry(entry)
        self._dashboard.left.transcript.append_jarvis_scheduled(
            display_resp, j_time, intent, hud_conf
        )

        secs = int((datetime.now() - self._session_start).total_seconds())
        h, m = divmod(secs // 60, 60)
        self._history_view.refresh_history(self._history, uptime_str=f"{h}h {m:02d}m")

        self._dashboard.left.hud_status.set_status(
            self._INTENT_HUD.get(intent, "STANDBY"))
        self._dashboard.left.last_action.set_action(intent, hud_conf)
        self._voice_view.set_execution(
            intent, act, hud_conf, exec_ok, exec_out.get("error"))

        self._dashboard.left.status_lbl.setText(display_resp[:120])
        toast_msg = (
            exec_out.get("error", "Scheduled action failed")
            if not exec_ok
            else f"Scheduled: {msg[:40]}"
        )
        self._dashboard.toast.show_toast(toast_msg, "error" if not exec_ok else "info")

        self._set_state("speaking")
        try:
            voice_engine.say(
                display_resp,
                on_ready=lambda: self._set_state("idle"),
            )
        except Exception:
            self._set_state("idle")

    def _on_hotkey(self, action: str) -> None:
        """Slot for `signals.hotkey_triggered` (F-4 global hotkeys).

        Each branch maps one ``core.hotkeys.KNOWN_ACTIONS`` value to a real
        side effect. Unknown actions are dropped silently — the registry
        already validates against KNOWN_ACTIONS at bind time, but a config
        edit between binding and firing could land an unknown name here.
        """
        if not action:
            return
        action = action.strip()
        try:
            if action == "focus_command_bar":
                # Bring the window forward and focus the input field so the
                # user can start typing immediately.
                self.raise_()
                self.activateWindow()
                try:
                    self._dashboard.left.cmd_bar.setFocus()
                except Exception:
                    pass
                return

            if action == "toggle_mic_mute":
                from core.voice import voice_engine
                new_state = not voice_engine.mic_muted
                self._on_mic_mute_toggled(new_state)
                return

            if action == "toggle_tts_mute":
                from core.voice import voice_engine
                new_state = not voice_engine.tts_muted
                self._on_tts_mute_toggled(new_state)
                return

            if action == "take_screenshot":
                # Drive through the standard brain-result path so the
                # screenshot ends up where any other take-screenshot
                # command would (Desktop, default save path, etc.).
                self._on_brain_result({
                    "intent": "system_control",
                    "action": "screenshot",
                    "parameters": {},
                    "confidence": 0.99,
                    "response": "Hotkey screenshot.",
                    "hud_status": "SYS CONTROL",
                    "requires_confirmation": False,
                })
                return

            if action == "read_screen":
                # Vision describe of the current screen, same path as the
                # voice/text command "what's on my screen".
                self._on_brain_result({
                    "intent": "vision_analysis",
                    "action": "describe",
                    "parameters": {"source": "screenshot"},
                    "confidence": 0.99,
                    "response": "Hotkey vision read.",
                    "hud_status": "VISION",
                    "requires_confirmation": False,
                })
                return
        except Exception as exc:
            print(f"[hotkeys] action {action!r} raised: {exc!r}")

    def _on_scheduled_workflow_fire(self, workflow_id: str) -> None:
        """Slot for `signals.scheduled_workflow_fire` (F-3 cron scheduler).

        Builds a synthetic brain result equivalent to the user typing
        ``run <workflow_id>`` and routes it through the standard
        execution path. The ``_scheduled`` flag flips the auto-confirm
        bypass — even when the user has auto_confirm ON, scheduled fires
        always present confirmation cards so a long-running cron can't
        silently kick off a destructive workflow step.
        """
        if not workflow_id:
            return
        # R3-1: never re-enter dispatch from a cron tick. If JARVIS isn't idle
        # (a command/confirmation/workflow is active) or a workflow/doc is in
        # flight, DROP this fire — do not queue it. The next scheduled slot fires
        # normally; a missed fire is safer than overlapping a paused workflow or
        # replacing a confirmation card out from under the user.
        from core.handlers.automation_handler import is_workflow_in_flight
        from core.handlers.document_handler import is_document_generation_in_flight
        if (self._state != "idle"
                or is_workflow_in_flight()
                or is_document_generation_in_flight()):
            from core.log import debug as _dbg
            _dbg("scheduler",
                 f"scheduled workflow {workflow_id!r} skipped — JARVIS busy "
                 f"(state={self._state})")
            # Surface the skip to the user (toast), not just the console — they
            # shouldn't have to watch the log to know a scheduled fire was dropped.
            # Defensive: a toast failure must never break the drop path.
            try:
                self._dashboard.toast.show_toast(
                    f"Scheduled '{workflow_id}' skipped — JARVIS busy.", "warning")
            except Exception:
                pass
            return
        from core.automation import workflow_library
        wf = workflow_library.get(workflow_id)
        if wf is None or not wf.get("enabled", True):
            return
        result = {
            "intent": "automation_task",
            "action": "run_workflow",
            "parameters": {"task_name": workflow_id},
            "confidence": 0.99,
            "response": f"Scheduled workflow firing — {wf.get('name', workflow_id)}.",
            "hud_status": "AUTOMATION",
            "requires_confirmation": False,
            # Sentinel that the auto-confirm guard checks below.
            "_scheduled": True,
        }
        # Synthesize a transcript entry so the user sees what fired.
        from datetime import datetime as _dt
        j_time = _dt.now().strftime("%H:%M")
        if hasattr(self, "_history") and isinstance(self._history, list):
            self._history.append({
                "you": f"[scheduled] {wf.get('name', workflow_id)}",
                "jarvis": result["response"],
                "jTime": j_time,
                "intent": "automation_task",
                "conf": 0.99,
                "status": "pending",
            })
        self._on_brain_result(result)
