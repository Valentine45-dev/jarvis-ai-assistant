"""Voice / mic / wake-word glue for JarvisWindow (R2-17a split).

Plain mixin — no QObject base, no signals defined here. Methods use only
``self`` (the composed JarvisWindow instance owns all state and signals).
This module must NOT import ``window`` or ``app`` (no import cycle).

Signals like ``self._voice_text_ready`` / ``self._voice_error_ready`` are
emitted from here; that is safe because ``self`` is the JarvisWindow QObject
that owns them — only the signal *definitions* and ``connect()`` calls must
stay on JarvisWindow (they do, in window.py / __init__).
"""

from __future__ import annotations

from config.settings import config


class _VoiceMixin:
    """Mic capture, STT result handling, wake-word, and TTS-done auto-resume."""

    def _toggle_mic(self):
        if self._state == "listening":
            self._set_state("idle")
        else:
            self._set_state("listening")
            self._voice_capture()

    def _voice_capture(self, auto_resume: bool = False):
        """Open the mic for one capture cycle.

        auto_resume=True: 15-second timeout, silent on timeout (no toast).
        auto_resume=False: 8-second timeout, toast on any error.
        """
        if self._state != "listening":
            return
        from core.voice import voice_engine
        timeout = 15.0 if auto_resume else 8.0

        def _on_err(err: str):
            # Suppress the toast when auto-resume simply timed out with no speech.
            # Guard emit against the window being deleted during shutdown.
            try:
                if auto_resume and "no speech" in err.lower():
                    self._voice_error_ready.emit("")
                else:
                    self._voice_error_ready.emit(err)
            except RuntimeError:
                pass

        voice_engine.listen(
            callback=lambda text: self._voice_text_ready.emit(text),
            on_error=_on_err,
            timeout=timeout,
        )

    def _on_voice_heard(self, text: str):
        """Qt main thread — STT captured speech successfully."""
        if self._state == "listening" and text.strip():
            self._process_cmd(text)
        else:
            self._set_state("idle")

    def _on_voice_error_ui(self, msg: str):
        """Qt main thread — STT timed out or failed."""
        self._set_state("idle")
        if msg:  # empty = silent auto-resume timeout, no toast needed
            self._dashboard.toast.show_toast(msg, "warning")

    def _on_wake_word(self):
        """Qt main thread — wake word detected. Start listening if idle."""
        from core.voice import voice_engine
        # Hard guard: never let wake events re-open the mic during active TTS.
        if voice_engine.is_speaking:
            if config.debug_mode:
                print("[wake] ignored: detector fired while TTS speaking")
            return
        if self._state != "idle":
            return
        if voice_engine.mic_muted:
            return
        self._set_state("listening")
        self._voice_capture()

    def _on_tts_done(self, token: int):
        """Qt main thread — TTS audio has fully finished playing.

        Auto-resumes the mic for follow-up input unless:
        - the token is stale (a newer command replaced this one)
        - we are waiting for a confirmation card response
        - the mic is muted
        - wake word is disabled (user is in explicit interaction mode —
          they'll click the mic or type when they want to talk)

        Auto-resume also opens a sounddevice INPUT stream that conflicts with
        a subsequent TTS OUTPUT stream on some Windows audio configs, hanging
        or crashing the audio backend; gating it on wake_word_enabled avoids
        that path entirely for users in text-input mode.
        """
        if token != self._transcript_update_token:
            return
        if getattr(self, "_confirm_mode", None) in ("claude", "executor"):
            return
        from core.voice import voice_engine
        if voice_engine.mic_muted:
            self._set_state("idle")
            return
        if not getattr(self, "_wake_word_enabled", True):
            self._set_state("idle")
            return
        # Auto-resume: listen for follow-up with a longer timeout.
        # If the user stays silent for 15 s, _on_voice_error_ui("") fires → idle.
        self._set_state("listening")
        self._voice_capture(auto_resume=True)

    def _on_wake_word_toggle(self, enabled: bool):
        from core.wake_word import wake_detector
        self._wake_word_enabled = bool(enabled)
        self._sync_session_flag_views()
        self._persist_session_flags()
        if enabled:
            wake_detector.resume()
            self._dashboard.toast.show_toast("Wake word active — say 'Jarvis' to start.", "info")
        else:
            wake_detector.pause()
            self._dashboard.toast.show_toast("Wake word disabled — use mic button to speak.", "warning")
