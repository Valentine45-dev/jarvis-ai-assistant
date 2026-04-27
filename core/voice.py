"""
Voice I/O facade — delegates all audio work to core/audio_pipeline.py.

Public API (unchanged — main.py and executor.py import from here):
    voice_engine.say(text, on_ready, on_done)
    voice_engine.listen(callback, on_error, timeout, phrase_time_limit)
    voice_engine.is_listening  → bool
    voice_engine.mic_muted     → bool
    voice_engine.tts_muted     → bool
    voice_engine.set_mic_muted(bool)
    voice_engine.set_tts_muted(bool)
    _EL_VOICES                 → dict[str, str]  (re-exported for executor.py)
"""

from __future__ import annotations

import threading
from typing import Callable

from config.settings import config
from core.audio_pipeline import (
    _EL_VOICES,
    _SttErrorExc,
    AudioCapture,
    SttEngine,
    TtsEngine,
)

__all__ = ["_EL_VOICES", "VoiceEngine", "voice_engine"]


class VoiceEngine:
    """Thin facade over AudioCapture / SttEngine / TtsEngine.

    Both say() and listen() return immediately; all audio work runs on daemon
    threads so the Qt main thread is never blocked.

    Overlap guard: listen() refuses to open the mic while is_speaking is True,
    preventing mic-pickup of JARVIS's own TTS output.
    """

    def __init__(self) -> None:
        self._capture   = AudioCapture()
        self._stt       = SttEngine()
        self._tts       = TtsEngine()
        self._listening = threading.Event()
        self._mic_muted = False
        self._tts_muted = False

    # ── Mute controls ────────────────────────────────────────────────────────

    def set_mic_muted(self, muted: bool) -> None:
        self._mic_muted = bool(muted)

    def set_tts_muted(self, muted: bool) -> None:
        self._tts_muted = bool(muted)

    @property
    def mic_muted(self) -> bool:
        return self._mic_muted

    @property
    def tts_muted(self) -> bool:
        return self._tts_muted

    # ── Status ───────────────────────────────────────────────────────────────

    @property
    def is_listening(self) -> bool:
        return self._listening.is_set()

    @property
    def is_speaking(self) -> bool:
        return self._tts.is_speaking

    # ── TTS ──────────────────────────────────────────────────────────────────

    def say(
        self,
        text: str,
        on_ready: Callable[[], None] | None = None,
        on_done:  Callable[[], None] | None = None,
    ) -> None:
        """Speak *text* via ElevenLabs (pyttsx3 fallback). Non-blocking."""
        if not text.strip():
            return
        if self._tts_muted:
            # Fire callbacks so dependent UI animations don't stall.
            self._fire(on_ready)
            self._fire(on_done)
            return
        self._tts.say(text, on_ready=on_ready, on_done=on_done)

    # ── STT ──────────────────────────────────────────────────────────────────

    def listen(
        self,
        callback:         Callable[[str], None],
        on_error:         Callable[[str], None] | None = None,
        timeout:          float = 8.0,
        phrase_time_limit: float = 12.0,
    ) -> None:
        """Capture mic → transcribe → call *callback(text)*. Non-blocking."""
        print("[voice] listen() called")
        if self._mic_muted:
            print("[voice] mic is muted — aborting")
            if on_error is not None:
                on_error("Microphone muted.")
            return
        print("[voice] starting _listen_thread")
        threading.Thread(
            target=self._listen_thread,
            args=(callback, on_error, timeout, phrase_time_limit),
            daemon=True,
        ).start()

    def _listen_thread(
        self,
        callback:          Callable[[str], None],
        on_error:          Callable[[str], None] | None,
        timeout:           float,
        phrase_time_limit: float,
    ) -> None:
        import time as _time
        print("[voice] _listen_thread running")
        self._listening.set()
        # Brief yield so the wake detector (if mid-window) can finish its chunk
        # loop and close its RawInputStream before we open ours.
        _time.sleep(0.2)
        try:
            threshold = self._capture.calibrate_threshold(
                duration=0.3,
                sensitivity=config.mic_sensitivity,
            )
            print(f"[voice] calibrated threshold: {threshold:.0f}")
            wav_bytes = self._capture.capture(
                timeout=timeout,
                phrase_time_limit=phrase_time_limit,
                threshold=threshold,
            )
            print(f"[voice] capture() returned: {'WAV bytes' if wav_bytes else 'None (no speech)'}")
            if wav_bytes is None:
                if on_error:
                    on_error("No speech detected — try speaking louder.")
                return
            print("[voice] calling STT recognise()...")
            text = self._stt.recognise(wav_bytes)
            print(f"[voice] recognise() returned: {text!r}")
            if text:
                callback(text)
            else:
                if on_error:
                    on_error("Could not understand audio.")
        except _SttErrorExc as exc:
            print(f"[voice] SttError: {exc}")
            if on_error:
                on_error(str(exc))
        except Exception as exc:
            print(f"[voice] Exception in _listen_thread: {type(exc).__name__}: {exc}")
            if on_error:
                on_error(f"Voice error: {exc}")
        finally:
            self._listening.clear()
            print("[voice] _listen_thread done")

    # ── Internal ─────────────────────────────────────────────────────────────

    def _fire(self, cb: Callable[[], None] | None) -> None:
        if cb is None:
            return
        try:
            cb()
        except Exception:
            pass


voice_engine = VoiceEngine()
