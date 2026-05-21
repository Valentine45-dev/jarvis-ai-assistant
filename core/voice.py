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
    voice_engine.bridge        → VoiceBridge (lazy; access only from main thread)
    _EL_VOICES                 → dict[str, str]  (re-exported for executor.py)

Signals (on voice_engine.bridge — connect from main thread):
    transcript_partial(str)  — interim word-by-word transcript
    transcript_final(str)    — confirmed full utterance
    speaking_started()       — TTS audio has begun
    speaking_finished()      — TTS audio is done
"""

from __future__ import annotations

import threading
from typing import Callable

from PyQt5.QtCore import QObject, pyqtSignal

from config.settings import config
from core.log import debug as _dbg
from core.audio_pipeline import (
    _EL_VOICES,
    _SttErrorExc,
    AudioCapture,
    SttEngine,
    TtsProviderError,
    TtsProviderErrorKind,
    TtsEngine,
)

__all__ = [
    "_EL_VOICES",
    "TtsProviderError",
    "TtsProviderErrorKind",
    "VoiceBridge",
    "VoiceEngine",
    "voice_engine",
]


# ── System mute probe ─────────────────────────────────────────────────────────
# Query Windows' default audio endpoint mute state via pycaw. Cached for a brief
# window so back-to-back TTS calls don't pay the COM cost. Returns False (i.e.
# "don't skip TTS") on any failure — never raises.

import time as _time
_MUTE_CACHE_TTL_S = 0.25
_mute_cache_lock = threading.Lock()
_mute_cache: dict = {"value": False, "checked_at": 0.0}


def _system_audio_muted() -> bool:
    """Return True if the OS default playback endpoint is currently muted."""
    try:
        now = _time.monotonic()
        with _mute_cache_lock:
            if now - _mute_cache["checked_at"] < _MUTE_CACHE_TTL_S:
                return bool(_mute_cache["value"])
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            device = AudioUtilities.GetSpeakers()
            raw = getattr(device, "_dev", device)
            iface = raw.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol = cast(iface, POINTER(IAudioEndpointVolume))
            muted = bool(vol.GetMute())
        except Exception:
            muted = False
        with _mute_cache_lock:
            _mute_cache["value"] = muted
            _mute_cache["checked_at"] = now
        return muted
    except Exception:
        return False


# ── Signal carrier ────────────────────────────────────────────────────────────

class VoiceBridge(QObject):
    """Qt signal carrier for VoiceEngine.

    Kept separate from VoiceEngine so that VoiceEngine can be instantiated at
    module load time (before QApplication exists).  VoiceBridge is created
    lazily via voice_engine.bridge on the first access from the main thread.
    """
    transcript_partial = pyqtSignal(str)   # interim word-by-word transcript
    transcript_final   = pyqtSignal(str)   # confirmed full utterance
    speaking_started   = pyqtSignal()      # TTS audio has begun playing
    speaking_finished  = pyqtSignal()      # TTS audio finished


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
        self._bridge: VoiceBridge | None = None  # lazy — created on main thread

    # ── Signal bridge ─────────────────────────────────────────────────────────

    @property
    def bridge(self) -> VoiceBridge:
        """Return the Qt signal carrier, creating it on first access.

        MUST be first accessed from the Qt main thread (QApplication must exist).
        Subsequent emit() calls from worker threads are safe — Qt queues them.
        """
        if self._bridge is None:
            self._bridge = VoiceBridge()
        return self._bridge

    def _emit(self, signal_name: str, *args) -> None:
        """Thread-safe helper: emit a bridge signal only if bridge is initialised."""
        if self._bridge is None:
            return
        getattr(self._bridge, signal_name).emit(*args)

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

    def clear_listening(self) -> None:
        """Public reset of the listening flag.

        Used by the HUD's state machine when leaving the "listening" state.
        Avoids reaching into _listening directly from main.py.
        """
        self._listening.clear()

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
        """Speak *text* (pyttsx3; ElevenLabs via tts_elevenlabs.py when re-enabled). Non-blocking."""
        if not text.strip():
            return
        if self._tts_muted or _system_audio_muted():
            # Skip when the app-level TTS mute is on OR when the Windows audio
            # endpoint is currently muted. Playing to a muted endpoint after a
            # pycaw SetMute toggle has been observed to hard-crash the audio
            # backend (process dies during ElevenLabs/pyaudio stream playback).
            # Fire callbacks so dependent UI animations don't stall.
            self._fire(on_ready)
            self._fire(on_done)
            return

        def _ready_wrapper():
            self._emit("speaking_started")
            self._fire(on_ready)

        def _done_wrapper():
            self._emit("speaking_finished")
            self._fire(on_done)

        self._tts.say(text, on_ready=_ready_wrapper, on_done=_done_wrapper)

    def switch_tts_voice(
        self,
        voice_key: str,
        *,
        validate_provider: bool = True,
        persist: bool = True,
    ) -> tuple[bool, str, str]:
        """Switch TTS voice with rollback-safe provider validation.

        Returns: (ok, message, error_kind)
        - ok=True  -> message is empty, error_kind='ok'
        - ok=False -> message is user-readable failure detail
        """
        key = (voice_key or "").strip().lower()
        if key not in _EL_VOICES:
            return (False, f"Unknown voice '{voice_key}'.", "unknown_voice")

        prev = config.tts_voice
        config.tts_voice = key
        try:
            if validate_provider:
                self._tts.probe_elevenlabs_voice(key)
        except TtsProviderError as exc:
            config.tts_voice = prev
            return (False, str(exc), exc.kind.value)
        except Exception as exc:
            config.tts_voice = prev
            return (False, f"Voice switch failed — {exc}", "unknown")

        if persist:
            try:
                config.save()
            except Exception as exc:
                # Roll back if persistence fails so runtime + disk stay consistent.
                config.tts_voice = prev
                return (False, f"Voice switch failed — couldn't save config ({exc}).", "save")
        return (True, "", "ok")

    # ── STT ──────────────────────────────────────────────────────────────────

    def listen(
        self,
        callback:         Callable[[str], None],
        on_error:         Callable[[str], None] | None = None,
        timeout:          float = 8.0,
        phrase_time_limit: float = 12.0,
    ) -> None:
        """Capture mic → transcribe → call *callback(text)*. Non-blocking."""
        _dbg("voice", "listen() called")
        if self._mic_muted:
            _dbg("voice", "mic is muted — aborting")
            if on_error is not None:
                on_error("Microphone muted.")
            return

        _dbg("voice", "starting _listen_thread (Google STT)")
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
        _dbg("voice", "_listen_thread running")
        self._listening.set()
        # Brief yield so the wake detector (if mid-window) can finish its chunk
        # loop and close its RawInputStream before we open ours.
        _time.sleep(0.2)
        try:
            threshold = self._capture.calibrate_threshold(
                duration=0.3,
                sensitivity=config.mic_sensitivity,
            )
            _dbg("voice", f"calibrated threshold: {threshold:.0f}")
            wav_bytes = self._capture.capture(
                timeout=timeout,
                phrase_time_limit=phrase_time_limit,
                threshold=threshold,
            )
            _dbg("voice", f"capture() returned: {'WAV bytes' if wav_bytes else 'None (no speech)'}")
            if wav_bytes is None:
                if on_error:
                    try:
                        on_error("No speech detected — try speaking louder.")
                    except RuntimeError:
                        pass
                return
            _dbg("voice", "calling STT recognise()...")
            text = self._stt.recognise(wav_bytes)
            _dbg("voice", f"recognise() returned: {text!r}")
            if text:
                callback(text)
            else:
                if on_error:
                    try:
                        on_error("Could not understand audio.")
                    except RuntimeError:
                        pass
        except _SttErrorExc as exc:
            _dbg("voice", f"SttError: {exc}")
            if on_error:
                try:
                    on_error(str(exc))
                except RuntimeError:
                    pass
        except Exception as exc:
            _dbg("voice", f"Exception in _listen_thread: {type(exc).__name__}: {exc}")
            if on_error:
                try:
                    on_error(f"Voice error: {exc}")
                except RuntimeError:
                    pass
        finally:
            self._listening.clear()
            _dbg("voice", "_listen_thread done")

    # ── Internal ─────────────────────────────────────────────────────────────

    def _fire(self, cb: Callable[[], None] | None) -> None:
        if cb is None:
            return
        try:
            cb()
        except Exception:
            pass


voice_engine = VoiceEngine()
