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
    capture_ready()          — mic + STT session are live; safe to speak now
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


# ── Mute state tracking ───────────────────────────────────────────────────────
# Two layers — both designed to never expose comtypes COM proxies to our process
# (since pycaw proxies crash with `ValueError: COM method call without VTable`
# when Python GC reaps them on a thread without a live COM apartment):
#
#   1. App-level flag (_app_audio_muted) — set deterministically when JARVIS
#      itself toggles via the OS hotkey. Zero cost. Always trusted when True.
#   2. Out-of-process pycaw probe — spawns a short-lived `python -c` that
#      queries IAudioEndpointVolume.GetMute() and prints muted/unmuted. The
#      subprocess owns its own COM apartment and dies on exit, taking its
#      proxies with it. Cached for 5 s so back-to-back say() calls don't
#      pay the spawn cost.
#
# The flag is preferred (cheap, instant). The probe is the safety net that
# catches manual Windows-taskbar mute. JARVIS-initiated toggles refresh the
# probe cache directly (no subprocess needed) since we know the new state.

import platform as _platform
import time as _time
import subprocess as _subprocess
import sys as _sys

_OS = _platform.system().lower()  # "windows" | "darwin" | "linux"

_app_audio_muted: bool = False
_PROBE_TTL_S = 5.0
_probe_lock = threading.Lock()
_probe_cache: dict = {"value": None, "checked_at": 0.0, "in_flight": False}  # value: True/False/None

_PROBE_CODE = (
    "from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume;"
    "from ctypes import cast, POINTER;"
    "from comtypes import CLSCTX_ALL;"
    "d = AudioUtilities.GetSpeakers();"
    "raw = getattr(d, '_dev', d);"
    "iface = raw.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None);"
    "vol = cast(iface, POINTER(IAudioEndpointVolume));"
    "print('muted' if vol.GetMute() else 'unmuted')"
)


def _run_mute_probe_subprocess() -> bool | None:
    """Spawn `python -c <probe>` and read its stdout. Returns True/False or None on failure."""
    try:
        creationflags = 0
        if _OS == "windows":
            # CREATE_NO_WINDOW — no flashing console for the brief subprocess.
            creationflags = 0x08000000
        r = _subprocess.run(
            [_sys.executable, "-c", _PROBE_CODE],
            capture_output=True,
            timeout=3.0,
            creationflags=creationflags,
        )
        if r.returncode != 0:
            return None
        out = (r.stdout or b"").decode("utf-8", errors="replace").strip().lower()
        if out == "muted":
            return True
        if out == "unmuted":
            return False
        return None
    except Exception:
        return None


def _refresh_probe_cache() -> None:
    """Run the mute probe and update the cache. Runs on a background daemon so
    the caller (often the Qt main thread via say()) never blocks on the ≤3 s
    subprocess — see R3-5."""
    result = _run_mute_probe_subprocess()
    now = _time.monotonic()
    with _probe_lock:
        # Only cache definitive answers (True/False), not None failures — but
        # always stamp checked_at so a persistently-failing probe is retried at
        # most once per TTL instead of spawning on every say(). Clear in_flight
        # so the next stale read can trigger a fresh refresh.
        if result is not None:
            _probe_cache["value"] = result
        _probe_cache["checked_at"] = now
        _probe_cache["in_flight"] = False


def _probed_system_muted() -> bool:
    """Return True if the OS reports muted, from cache. Never blocks: on a stale
    or missing cache it kicks off a background refresh and returns the last known
    value (default False/unmuted when unknown). An external mute (taskbar/hotkey)
    is therefore noticed one line late rather than freezing the caller — see R3-5.
    App-level mutes go through set_app_audio_muted() and update the cache instantly."""
    if _OS != "windows":
        return False
    now = _time.monotonic()
    with _probe_lock:
        cached_value = _probe_cache["value"]
        cache_fresh  = (now - _probe_cache["checked_at"]) < _PROBE_TTL_S
        # Trigger a background refresh on a stale/missing cache, deduped via
        # in_flight so concurrent say() calls don't spawn a probe storm.
        need_refresh = not cache_fresh and not _probe_cache["in_flight"]
        if need_refresh:
            _probe_cache["in_flight"] = True
    if need_refresh:
        threading.Thread(target=_refresh_probe_cache, daemon=True).start()
    return bool(cached_value) if cached_value is not None else False


def set_app_audio_muted(value: bool) -> None:
    """Mirror state set by the volume_mute/unmute handler.

    Also refreshes the probe cache directly (no subprocess) since JARVIS just
    set the state and knows what it is. Next say() call will hit the cache.
    """
    global _app_audio_muted
    _app_audio_muted = bool(value)
    with _probe_lock:
        _probe_cache["value"] = bool(value)
        _probe_cache["checked_at"] = _time.monotonic()


def get_app_audio_muted() -> bool:
    """Current app-tracked mute state. Used by the system handler to compute
    the post-toggle state."""
    return _app_audio_muted


def _system_audio_muted() -> bool:
    """True when TTS should be skipped. App flag wins fast; OS probe catches
    manual taskbar/hotkey mute the app doesn't know about."""
    if _app_audio_muted:
        return True
    return _probed_system_muted()


# ── Signal carrier ────────────────────────────────────────────────────────────

class VoiceBridge(QObject):
    """Qt signal carrier for VoiceEngine.

    Kept separate from VoiceEngine so that VoiceEngine can be instantiated at
    module load time (before QApplication exists).  VoiceBridge is created
    lazily via voice_engine.bridge on the first access from the main thread.
    """
    capture_ready      = pyqtSignal()      # mic + STT session live; ok to speak
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
        self._stt_fallback_announced = False     # one-shot streaming→batch toast
        self._persistent_session = None          # reused warm Deepgram socket

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
            # endpoint is currently muted (user muted via taskbar/voice/hotkey).
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

        _dbg("voice", "starting _listen_thread")
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
        _dbg("voice", "_listen_thread running")
        self._listening.set()
        try:
            self._wake_handshake()
            # Streaming path (Deepgram) when configured; otherwise None → batch.
            # If streaming starts but fails before producing any text, it returns
            # False and we fall through to the Google batch path for this turn.
            session, persistent = self._acquire_stt_session()
            if session is not None:
                _dbg("voice", f"using streaming STT (persistent={persistent})")
                if self._run_streaming_stt(
                    session, callback, on_error, timeout, phrase_time_limit,
                    persistent=persistent,
                ):
                    return
                _dbg("voice", "streaming STT failed to produce a result — falling back to Google batch")
                self._announce_stt_fallback()
            self._run_batch_stt(callback, on_error, timeout, phrase_time_limit)
        finally:
            self._listening.clear()
            _dbg("voice", "_listen_thread done")

    def _wake_handshake(self) -> None:
        """R3-15: wait for the wake detector to confirm its mic stream is closed
        before we open ours — two RawInputStreams on one device cause
        PortAudio/WASAPI device-busy errors. Falls back to a short sleep if the
        detector isn't running or the wait times out."""
        import time as _time
        try:
            from core.wake_word import wake_detector
            if wake_detector.is_running:
                if not wake_detector.wait_closed(1.0):
                    _dbg("voice", "wake stream-closed wait timed out; proceeding")
            else:
                _time.sleep(0.05)
        except Exception:
            _time.sleep(0.2)

    def _announce_stt_fallback(self) -> None:
        """One-time toast when streaming recognition drops to the Google batch
        path mid-session, so the user knows why latency/behaviour changed."""
        if self._stt_fallback_announced:
            return
        self._stt_fallback_announced = True
        try:
            from core.signals import signals
            signals.notice.emit(
                "Live transcription dropped — using backup recognition.", "warning"
            )
        except Exception as exc:
            _dbg("voice", f"notice emit failed: {exc}")

    def _acquire_stt_session(self):
        """Return (session, persistent) for this turn, or (None, False) for batch.

        Persistent mode (config.stt_persistent) reuses one warm socket across
        turns; we hand back the live one when it's healthy, else build a fresh
        session (its socket opens on the first begin_turn). Never raises — any
        failure degrades to the Google batch path."""
        persistent = bool(getattr(config, "stt_persistent", False))
        if persistent and self._persistent_session is not None:
            try:
                if self._persistent_session.is_alive():
                    return self._persistent_session, True
            except Exception:
                pass
            self._discard_persistent()
        try:
            from core.stt import create_stt_session
            session = create_stt_session(config)
        except Exception as exc:
            _dbg("voice", f"create_stt_session failed ({exc}) — using batch")
            return None, False
        if session is None:
            return None, False
        if persistent:
            self._persistent_session = session
        return session, persistent

    def _discard_persistent(self) -> None:
        """Drop the warm session (e.g. after a stream error) so the next turn
        opens a fresh socket."""
        session, self._persistent_session = self._persistent_session, None
        if session is not None:
            try:
                session.close()
            except Exception:
                pass

    def close_persistent(self) -> None:
        """Public: gracefully close the warm socket on app shutdown."""
        self._discard_persistent()

    def _run_streaming_stt(
        self,
        session,
        callback:          Callable[[str], None],
        on_error:          Callable[[str], None] | None,
        timeout:           float,
        phrase_time_limit: float,
        *,
        persistent: bool = False,
        mic_streamer=None,
    ) -> bool:
        """Drive a StreamingSttSession to one utterance.

        Returns True when the turn was handled (text delivered via callback, or a
        clean no-speech reported via on_error). Returns False when streaming
        couldn't start or errored before any text — the caller then falls back to
        the Google batch path.

        `persistent` reuses one warm socket across turns: begin_turn/end_turn
        (Finalize, keep open) instead of start/finish (open/close). A broken warm
        socket is discarded so the next turn reopens fresh.

        `mic_streamer` is injectable for tests; in production a real MicStreamer
        is built from config.mic_device.
        """
        import time as _time

        finals: list[str] = []
        finals_lock = threading.Lock()
        last_partial = {"text": ""}
        done = threading.Event()
        got_speech = threading.Event()
        err = {"msg": None}

        def _interim() -> str:
            with finals_lock:
                joined = " ".join(p for p in finals if p).strip()
            return joined

        def _on_partial(text: str) -> None:
            got_speech.set()
            last_partial["text"] = text
            tail = (_interim() + " " + text).strip()
            self._emit("transcript_partial", tail)

        def _on_final(text: str) -> None:
            got_speech.set()
            with finals_lock:
                finals.append(text)
            self._emit("transcript_partial", _interim())

        def _on_utt_end() -> None:
            done.set()

        def _on_sess_error(msg: str) -> None:
            err["msg"] = msg
            done.set()

        cbs = dict(on_partial=_on_partial, on_final=_on_final,
                   on_utterance_end=_on_utt_end, on_error=_on_sess_error)
        try:
            if persistent:
                session.begin_turn(**cbs)
            else:
                session.start(**cbs)
        except Exception as exc:
            _dbg("voice", f"streaming session start failed: {exc}")
            self._fail_session(session, persistent)
            return False

        streamer = mic_streamer
        if streamer is None:
            try:
                from core.stt import MicStreamer
                device = config.mic_device if config.mic_device >= 0 else None
                streamer = MicStreamer(feed=session.feed, device=device)
            except Exception as exc:
                _dbg("voice", f"mic streamer init failed: {exc}")
                self._end_turn_or_close(session, persistent)
                return False
        try:
            streamer.start()
        except Exception as exc:
            _dbg("voice", f"mic streamer start failed: {exc}")
            self._end_turn_or_close(session, persistent)
            return False

        # Mic stream + Deepgram session are both live now — tell the UI it's
        # genuinely safe to speak (closes the "spoke too early" gap).
        self._emit("capture_ready")

        start_t = _time.monotonic()
        try:
            while not done.is_set():
                now = _time.monotonic()
                if not got_speech.is_set():
                    if now - start_t >= timeout:
                        _dbg("voice", "streaming: no speech within timeout")
                        break
                elif now - start_t >= timeout + phrase_time_limit:
                    _dbg("voice", "streaming: phrase time limit reached")
                    break
                _time.sleep(0.05)
        finally:
            try:
                streamer.stop()
            except Exception:
                pass
            try:
                # Persistent: Finalize but keep the socket warm for next turn.
                # Per-turn: Finalize + close.
                session.end_turn() if persistent else session.finish()
            except Exception:
                pass

        text = _interim() or (last_partial["text"] or "").strip()
        if not text and err["msg"]:
            _dbg("voice", f"streaming errored before any text ({err['msg']}) — falling back")
            # A warm socket that errored is suspect — drop it so the next turn
            # reopens a fresh one rather than reusing a broken connection.
            if persistent:
                self._discard_persistent()
            return False
        if text:
            _dbg("voice", f"streaming final: {text!r}")
            self._emit("transcript_final", text)
            try:
                callback(text)
            except Exception as exc:
                _dbg("voice", f"callback error: {exc}")
            return True
        # Connected fine but the user genuinely didn't speak.
        if on_error:
            try:
                on_error("No speech detected — try speaking louder.")
            except RuntimeError:
                pass
        return True

    @staticmethod
    def _safe_close(session) -> None:
        try:
            session.close()
        except Exception:
            pass

    def _fail_session(self, session, persistent: bool) -> None:
        """A turn couldn't start. Persistent: drop the warm socket so the next
        turn reopens fresh. Per-turn: just close this session."""
        if persistent:
            self._discard_persistent()
        else:
            self._safe_close(session)

    def _end_turn_or_close(self, session, persistent: bool) -> None:
        """Mic failed after the socket was up. Persistent: end the (empty) turn
        but keep the socket warm. Per-turn: close it."""
        if persistent:
            try:
                session.end_turn()
            except Exception:
                pass
        else:
            self._safe_close(session)

    def _run_batch_stt(
        self,
        callback:          Callable[[str], None],
        on_error:          Callable[[str], None] | None,
        timeout:           float,
        phrase_time_limit: float,
    ) -> None:
        """Legacy capture → Google batch STT path (unchanged behaviour)."""
        try:
            threshold = self._capture.calibrate_threshold(
                duration=0.3,
                sensitivity=config.mic_sensitivity,
            )
            _dbg("voice", f"calibrated threshold: {threshold:.0f}")
            # Calibration proved the device works and capture() is about to open
            # the mic — signal the UI it's safe to speak (parity with streaming).
            self._emit("capture_ready")
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
            elif on_error:
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
            _dbg("voice", f"Exception in _run_batch_stt: {type(exc).__name__}: {exc}")
            if on_error:
                try:
                    on_error(f"Voice error: {exc}")
                except RuntimeError:
                    pass

    # ── Internal ─────────────────────────────────────────────────────────────

    def _fire(self, cb: Callable[[], None] | None) -> None:
        if cb is None:
            return
        try:
            cb()
        except Exception:
            pass


voice_engine = VoiceEngine()
