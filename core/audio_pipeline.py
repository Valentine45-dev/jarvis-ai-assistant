"""
JARVIS audio pipeline — internal STT/TTS engines.

Consumed exclusively by core/voice.py (VoiceEngine facade).
Do not import this module from main.py or UI code directly.

Classes
-------
AudioCapture   — sounddevice mic capture with RMS VAD + guaranteed stream cleanup
SttEngine      — Google STT with typed SttError (NO_SPEECH / NETWORK / TIMEOUT / DEVICE)
TtsEngine      — pyttsx3 TTS; ElevenLabs streaming in core/tts_elevenlabs.py (disabled)

Constants
---------
_EL_VOICES        — voice-key → ElevenLabs voice-ID map (re-exported via voice.py)
_DEFAULT_VOICE_ID — fallback when config.tts_voice is unrecognised
SttError          — enum of typed failure modes for the STT path
"""

from __future__ import annotations

import enum
import io
import math
import queue
import struct
import threading
import wave
from typing import Callable

from config.settings import config
from core.log import debug as _dbg


# ── ElevenLabs voice profile map ─────────────────────────────────────────────
# Stable pre-made voice IDs — do not change without verifying on ElevenLabs.

_EL_VOICES: dict[str, str] = {
    "male-british":         "JBFqnCBsd6RMkjVDRZzb",  # George  — deep, warm British
    "male-american":        "pNInz6obpgDQGcFmaJgB",  # Adam    — neutral American
    "female-british":       "21m00Tcm4TlvDq8ikWAM",  # Rachel  — warm, neutral
    "male-broadcast":       "onwK4e9ZLuTAKqWW03F9",  # Daniel  — professional broadcast
    "male-resonant":        "nPczCjzI2devNBz1zQrb",  # Brian   — resonant, narration
    "male-smooth":          "cjVigY5qzO86Huf0OWal",  # Eric    — smooth, conversational
    "male-gravelly":        "N2lVS1w4EtoT3dr4eOWO",  # Callum  — gravelly, distinctive
    "male-casual":          "iP95p4xoKVk53GoZ742B",  # Chris   — natural, down-to-earth
    "male-australian":      "IKne3meq5aSn9XLyUdCD",  # Charlie — energetic Australian
    "female-professional":  "EXAVITQu4vr4xnSDxMaL",  # Sarah   — young professional
    "female-british-clear": "Xb7hH8MSUJpSbSDYk0k2",  # Alice   — British, clear
    "female-british-warm":  "pFZP5JQG7iQjIQuC4Bku",  # Lily    — British, warm
    "female-american":      "XrExE9yKIg1WjnnlVkGX",  # Matilda — professional American
}

_DEFAULT_VOICE_ID = _EL_VOICES["male-british"]


# ── Typed STT errors ──────────────────────────────────────────────────────────

class SttError(enum.Enum):
    NO_SPEECH = "no_speech"   # mic open but nothing above threshold / not understood
    NETWORK   = "network"     # Google STT API unreachable
    TIMEOUT   = "timeout"     # waited full timeout with no speech start
    DEVICE    = "device"      # mic not found or PortAudio error


class _SttErrorExc(Exception):
    """Internal: typed STT failure raised inside SttEngine, caught in VoiceEngine."""
    def __init__(self, kind: SttError, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class TtsProviderErrorKind(enum.Enum):
    QUOTA = "quota"
    AUTH = "auth"
    NETWORK = "network"
    UNKNOWN = "unknown"


class TtsProviderError(Exception):
    """Typed provider failure for ElevenLabs validation/synthesis."""

    def __init__(
        self,
        kind: TtsProviderErrorKind,
        message: str,
        *,
        raw_error: str = "",
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.raw_error = raw_error


def _is_gemini_quota_error(exc: Exception) -> bool:
    """True when a Gemini SDK exception is the daily-free-tier 429.

    The Gemini SDK currently surfaces these as a `google.genai.errors.ClientError`
    with the literal `RESOURCE_EXHAUSTED` status. We match on the error string
    rather than the class because the SDK doesn't export the error class
    cleanly and the textual signal is stable across SDK minor versions.
    """
    s = str(exc).lower()
    return "resource_exhausted" in s or s.lstrip().startswith("429")


def _classify_elevenlabs_error(exc: Exception) -> TtsProviderError:
    """Normalize ElevenLabs SDK exceptions into typed provider errors."""
    raw = str(exc)
    low = raw.lower()
    if "quota_exceeded" in low or ("credits" in low and "required" in low):
        return TtsProviderError(
            TtsProviderErrorKind.QUOTA,
            "Voice switch failed — ElevenLabs quota exceeded. "
            "Please top up credits or use local fallback voices.",
            raw_error=raw,
        )
    if "status_code: 401" in low or "unauthorized" in low or "invalid_api_key" in low:
        return TtsProviderError(
            TtsProviderErrorKind.AUTH,
            "Voice switch failed — ElevenLabs authentication failed. "
            "Check your API key.",
            raw_error=raw,
        )
    if any(k in low for k in ("timeout", "timed out", "connection", "network", "dns")):
        return TtsProviderError(
            TtsProviderErrorKind.NETWORK,
            "Voice switch failed — ElevenLabs network issue. "
            "Check your connection and try again.",
            raw_error=raw,
        )
    return TtsProviderError(
        TtsProviderErrorKind.UNKNOWN,
        "Voice switch failed — ElevenLabs rejected the request.",
        raw_error=raw,
    )


from core.tts_elevenlabs import (
    say_elevenlabs  as _say_elevenlabs_fn,
    probe_voice     as _probe_el_voice_fn,
)
from core.tts_gemini import (
    say_gemini             as _say_gemini_fn,
    GEMINI_VOICE_BY_PROFILE as _GEMINI_VOICE_BY_PROFILE,
    DEFAULT_VOICE_NAME     as _GEMINI_DEFAULT_VOICE,
)


# ── Lazy module imports ───────────────────────────────────────────────────────

def _sd():
    try:
        import sounddevice as sd
        return sd
    except ImportError:
        return None


def _sr():
    try:
        import speech_recognition as sr
        return sr
    except ImportError:
        return None


# ── RMS helper (audioop removed in Python 3.14) ───────────────────────────────

def _rms(data: bytes) -> float:
    """RMS amplitude of raw 16-bit PCM bytes."""
    count = len(data) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"{count}h", data)
    return math.sqrt(sum(s * s for s in shorts) / count)


# ── AudioCapture ──────────────────────────────────────────────────────────────

class AudioCapture:
    """Mic capture with RMS VAD.

    The sounddevice stream is always closed in a finally block — previous code
    used a context manager that could leave the stream open on exception paths.

    Public API
    ----------
    calibrate_threshold(duration, sensitivity) → float
        Sample ambient noise; return a dynamic silence threshold.
    capture(timeout, phrase_time_limit, threshold) → bytes | None
        Record until silence or timeout. Returns WAV bytes or None (no speech).
        Raises RuntimeError on device errors (→ SttError.DEVICE in SttEngine).
    """

    RATE        = 16_000
    CHANNELS    = 1
    CHUNK       = 1_024
    SILENCE_S   = 2.5     # seconds of silence after speech = end of phrase
    MIN_PHRASE_S = 0.8    # don't end phrase until at least this much speech is captured

    def calibrate_threshold(
        self, duration: float = 0.5, sensitivity: int = 50
    ) -> float:
        """Sample ambient RMS for *duration* seconds; return 2× that floor.

        Falls back to the static sensitivity formula if the device is unavailable.
        Static formula: 200 + (100 - sensitivity) × 38  (range 200–4 000).
        """
        base = 200 + (100 - max(0, min(100, sensitivity))) * 38
        sd = _sd()
        if sd is None:
            return base

        n_frames = max(1, int(self.RATE / self.CHUNK * duration))
        rms_values: list[float] = []
        device = config.mic_device if config.mic_device >= 0 else None
        stream = None
        try:
            stream = sd.RawInputStream(
                samplerate=self.RATE,
                channels=self.CHANNELS,
                dtype="int16",
                blocksize=self.CHUNK,
                device=device,
            )
            stream.start()
            for _ in range(n_frames):
                data, _ = stream.read(self.CHUNK)
                rms_values.append(_rms(bytes(data)))
        except Exception:
            return base
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

        if not rms_values:
            return base
        ambient = sum(rms_values) / len(rms_values)
        # noise_gate ON → 4× ambient (rejects more background noise)
        # noise_gate OFF → 2× ambient (more sensitive)
        multiplier = 4.0 if config.noise_gate else 2.0
        # Floor at 50% of base so breathing / quiet hum never triggers capture.
        return max(base * 0.50, ambient * multiplier)

    def capture(
        self,
        timeout: float = 8.0,
        phrase_time_limit: float = 12.0,
        threshold: float | None = None,
    ) -> bytes | None:
        """Record from the default mic using RMS VAD.

        Parameters
        ----------
        timeout           : seconds to wait for speech to start before giving up
        phrase_time_limit : max recording time after speech has started
        threshold         : RMS silence threshold; uses sensitivity config if None

        Returns WAV bytes, or None when no speech was detected within *timeout*.
        Raises RuntimeError on PortAudio / device errors.
        """
        sd = _sd()
        if sd is None:
            raise RuntimeError(
                "sounddevice not installed — run: uv add sounddevice numpy"
            )

        silence_threshold = (
            threshold
            if threshold is not None
            else 200 + (100 - config.mic_sensitivity) * 38
        )

        frames: list[bytes]  = []
        phrase_started        = False
        silence_frames        = 0
        speech_frames         = 0
        max_silence_frames    = int(self.RATE / self.CHUNK * self.SILENCE_S)
        min_speech_frames     = int(self.RATE / self.CHUNK * self.MIN_PHRASE_S)
        max_frames            = int(self.RATE / self.CHUNK * (timeout + phrase_time_limit))
        timeout_frames        = int(self.RATE / self.CHUNK * timeout)

        device = config.mic_device if config.mic_device >= 0 else None
        try:
            _dbg("capture", f"opening mic stream (threshold={silence_threshold:.0f}, device={device})")
            with sd.RawInputStream(
                samplerate=self.RATE,
                channels=self.CHANNELS,
                dtype="int16",
                blocksize=self.CHUNK,
                device=device,
            ) as stream:
                _dbg("capture", "stream open — listening for speech")
                for frame_idx in range(max_frames):
                    data, _ = stream.read(self.CHUNK)
                    raw = bytes(data)
                    frames.append(raw)
                    rms = _rms(raw)

                    if rms > silence_threshold:
                        phrase_started = True
                        silence_frames = 0
                        speech_frames += 1
                    elif phrase_started:
                        silence_frames += 1
                        if (silence_frames >= max_silence_frames
                                and speech_frames >= min_speech_frames):
                            break
                    elif frame_idx >= timeout_frames:
                        break   # timed out waiting for speech

        except Exception as exc:
            # PaErrorCode -9983 "Stream is stopped" fires when the stream is
            # closed during shutdown or a device change — not a hard failure.
            # Fall through to the phrase_started check so callers get None
            # (no speech) instead of an exception that crashes the voice thread.
            # Any frames already collected in this iteration are intentionally
            # dropped: the stream went away mid-utterance, so the partial audio
            # would be incomplete anyway.
            if "stream is stopped" not in str(exc).lower():
                raise RuntimeError(f"Mic capture failed: {exc}") from exc

        if not phrase_started:
            return None

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.CHANNELS)
            wf.setsampwidth(2)      # int16 = 2 bytes per sample
            wf.setframerate(self.RATE)
            wf.writeframes(b"".join(frames))
        return buf.getvalue()


# ── SttEngine ─────────────────────────────────────────────────────────────────

class SttEngine:
    """Google STT via SpeechRecognition.

    All failure modes surface as _SttErrorExc (caught in VoiceEngine._listen_thread)
    so the UI always gets a typed, human-readable error — not a raw exception string.
    """

    def recognise(self, wav_bytes: bytes) -> str:
        """Transcribe *wav_bytes*. Returns text string (may be empty on very short clips).

        Raises
        ------
        _SttErrorExc(SttError.NO_SPEECH)  — recognised but empty / inaudible
        _SttErrorExc(SttError.TIMEOUT)    — network timeout
        _SttErrorExc(SttError.NETWORK)    — API error
        RuntimeError                       — package not installed
        """
        sr = _sr()
        if sr is None:
            raise RuntimeError(
                "SpeechRecognition not installed — run: uv add SpeechRecognition"
            )

        recognizer = sr.Recognizer()
        with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
            audio = recognizer.record(source)

        try:
            text = recognizer.recognize_google(audio)
            _dbg("stt", f"Heard: {text!r}")
            return text

        except sr.UnknownValueError:
            raise _SttErrorExc(
                SttError.NO_SPEECH,
                "Could not make that out — try speaking a little clearer.",
            )
        except sr.RequestError as exc:
            msg = str(exc).lower()
            if any(k in msg for k in ("timeout", "timed out")):
                raise _SttErrorExc(
                    SttError.TIMEOUT,
                    "Speech recognition timed out — check your connection.",
                )
            raise _SttErrorExc(
                SttError.NETWORK,
                f"Speech service unavailable — {exc}",
            )


# ── TtsEngine ─────────────────────────────────────────────────────────────────

class TtsEngine:
    """ElevenLabs TTS (streaming MP3 via Windows MCI) with pyttsx3 fallback.

    is_speaking is True from the moment audio starts until playback ends,
    including any fallback path. VoiceEngine uses this to block mic capture
    while JARVIS is talking (overlap / feedback guard).

    The _lock serialises concurrent say() calls; is_speaking is set *before*
    acquiring the lock so callers see True immediately, not after queuing.
    """

    # R3-21: max queued (not-yet-playing) utterances before we drop the stalest.
    _QUEUE_MAX = 8

    def __init__(self) -> None:
        self._lock     = threading.Lock()
        # R3-4: is_speaking is a COUNTER, not a binary Event. Overlapping say()
        # calls serialise on _lock, but each clip must keep is_speaking True for
        # its whole duration — a bool/Event lets clip A's clear() fire while
        # clip B is still playing, opening the mic mid-speech (feedback loop).
        # The counter is guarded by its own tiny lock, NOT _lock (which is held
        # for an entire clip — is_speaking would block on it).
        self._speaking_lock  = threading.Lock()
        self._speaking_count = 0
        self._last_provider_error: TtsProviderError | None = None
        # Session-scoped lock: once ElevenLabs returns quota_exceeded once, we
        # stop hammering it on every subsequent line. Cleared on restart (so
        # a top-up takes effect on the next launch) or whenever the user
        # changes the ElevenLabs API key in Settings (see clear_quota_lock).
        self._elevenlabs_quota_locked = False
        # Same pattern for Gemini Flash TTS — when the free-tier daily limit
        # (10 calls/day on gemini-2.5-flash-tts as of 2026-05) hits, every
        # subsequent line wastes ~3-5s on a 429 retry before falling to
        # pyttsx3. One quota failure flips this flag for the rest of the
        # session and we go straight to pyttsx3 on every line until restart.
        self._gemini_quota_locked = False
        # R3-21: a single TTS worker drains a bounded queue, instead of spawning
        # an unbounded daemon thread per say(). A burst of utterances (a chatty
        # workflow narrating each step) can't pile up N threads all blocked on
        # _lock; the queue caps the backlog and drops the stalest line. Worker
        # starts lazily on first say() (no import-time thread).
        self._queue: "queue.Queue" = queue.Queue(maxsize=self._QUEUE_MAX)
        self._worker_lock    = threading.Lock()
        self._worker_started = False

    @property
    def is_speaking(self) -> bool:
        with self._speaking_lock:
            return self._speaking_count > 0

    # ── Public ───────────────────────────────────────────────────────────────

    def say(
        self,
        text: str,
        on_ready: Callable[[], None] | None = None,
        on_done:  Callable[[], None] | None = None,
    ) -> None:
        """Speak *text*. Non-blocking — enqueues to the single TTS worker.

        is_speaking goes True at enqueue (R3-4 counter) so the mic-overlap guard
        sees it immediately, and stays True until the clip finishes playing.
        """
        # Count at enqueue so a queued-but-not-yet-playing line still blocks the
        # mic; the worker (or a drop) decrements it.
        with self._speaking_lock:
            self._speaking_count += 1
        self._ensure_worker()
        item = (text, on_ready, on_done)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            # R3-21: bounded backlog — drop the OLDEST queued (not-yet-playing)
            # line rather than grow unboundedly, then queue this newest one.
            self._drop_oldest()
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                with self._speaking_lock:
                    self._speaking_count -= 1
                self._notify(on_done)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _drop_oldest(self) -> None:
        """Discard the oldest queued utterance (still accounting for is_speaking
        and firing its on_done so a dependent UI animation doesn't stall)."""
        try:
            old = self._queue.get_nowait()
        except queue.Empty:
            return
        self._queue.task_done()
        with self._speaking_lock:
            self._speaking_count -= 1
        self._notify(old[2])

    def _ensure_worker(self) -> None:
        """Start the single TTS worker once, on first say() (no import-time thread)."""
        with self._worker_lock:
            if self._worker_started:
                return
            self._worker_started = True
        threading.Thread(target=self._worker_loop, daemon=True, name="TtsWorker").start()

    def _worker_loop(self) -> None:
        while True:
            text, on_ready, on_done = self._queue.get()
            try:
                self._play(text, on_ready, on_done)
            except Exception as exc:
                _dbg("tts", f"tts worker error: {exc}")
            finally:
                with self._speaking_lock:
                    self._speaking_count -= 1
                self._queue.task_done()

    def _play(
        self,
        text: str,
        on_ready: Callable[[], None] | None,
        on_done:  Callable[[], None] | None,
    ) -> None:
        """Play one utterance through the provider tiers. Runs on the single TTS
        worker thread; is_speaking accounting is handled by say()/_worker_loop."""
        ready_called = threading.Event()

        def _on_ready_once() -> None:
            if not ready_called.is_set():
                ready_called.set()
                self._notify(on_ready)

        try:
            with self._lock:
                # ── Tier 1: ElevenLabs ──────────────────────────────────────
                # Skipped once a quota_exceeded has been seen this session —
                # otherwise we'd burn through ElevenLabs latency on every line
                # only to fall back to Gemini anyway.
                if config.elevenlabs_api_key and not self._elevenlabs_quota_locked:
                    try:
                        _say_elevenlabs_fn(
                            text, _on_ready_once, on_done, self._notify,
                            voice_id=_EL_VOICES.get(config.tts_voice, _DEFAULT_VOICE_ID),
                            api_key=config.elevenlabs_api_key,
                        )
                        return
                    except Exception as exc:
                        provider_err = _classify_elevenlabs_error(exc)
                        self._last_provider_error = provider_err
                        if provider_err.kind == TtsProviderErrorKind.QUOTA:
                            self._elevenlabs_quota_locked = True
                            _dbg("tts", "ElevenLabs quota exceeded — disabling for this session, switching to Gemini")
                        else:
                            _dbg("tts", f"ElevenLabs failed ({provider_err.kind.value}), trying Gemini: {exc}")
                        if ready_called.is_set():
                            # We already signalled on_ready (some bytes
                            # streamed) — don't replay the line on the next
                            # tier or the user hears half of it twice.
                            self._notify(on_done)
                            return

                # ── Tier 2: Gemini Flash TTS ────────────────────────────────
                # Free tier as of 2026-05; speaks inline [chuckles] / [sighs]
                # tags directly. Skipped if no key is configured OR the
                # session-level quota lock fired earlier this run.
                if config.gemini_api_key and not self._gemini_quota_locked:
                    voice_name = (
                        (config.gemini_voice or "").strip()
                        or _GEMINI_VOICE_BY_PROFILE.get(config.tts_voice, _GEMINI_DEFAULT_VOICE)
                    )
                    try:
                        _say_gemini_fn(
                            text, _on_ready_once, on_done, self._notify,
                            voice_name=voice_name,
                            api_key=config.gemini_api_key,
                        )
                        return
                    except Exception as exc:
                        if _is_gemini_quota_error(exc):
                            self._gemini_quota_locked = True
                            _dbg("tts", "Gemini daily quota exceeded — disabling for this session, switching to pyttsx3")
                        else:
                            _dbg("tts", f"Gemini failed, falling back to pyttsx3: {exc}")
                        if ready_called.is_set():
                            self._notify(on_done)
                            return

                # ── Tier 3: pyttsx3 local fallback ──────────────────────────
                self._say_local(text, _on_ready_once, on_done)
        except Exception as exc:
            # A tier raised after the earlier ones were exhausted (typically the
            # pyttsx3 fallback). Log and fire on_done so the speaking_finished
            # signal still lands (UI animations don't stall). is_speaking is
            # released by the worker loop's finally regardless.
            _dbg("tts", f"say failed on all tiers: {exc}")
            self._notify(on_done)

    def clear_elevenlabs_quota_lock(self) -> None:
        """Re-enable ElevenLabs after the user tops up credits or changes
        the API key. Called by the Settings UI when the key is edited."""
        self._elevenlabs_quota_locked = False

    def clear_gemini_quota_lock(self) -> None:
        """Re-enable Gemini after the daily reset or a key change. Useful
        from the Settings UI when the user edits gemini_api_key, and from
        any future timer that wants to retry past the daily reset boundary
        without forcing a full app restart."""
        self._gemini_quota_locked = False

    def probe_elevenlabs_voice(self, voice_key: str, text: str = "Voice check.") -> None:
        if config.elevenlabs_api_key:
            _probe_el_voice_fn(
                voice_key,
                api_key=config.elevenlabs_api_key,
                el_voices=_EL_VOICES,
                default_id=_DEFAULT_VOICE_ID,
                text=text,
            )

    def _notify(self, cb: Callable[[], None] | None) -> None:
        if cb is None:
            return
        try:
            cb()
        except Exception as exc:
            _dbg("tts", f"callback error: {exc}")

    def _say_local(
        self,
        text: str,
        on_ready: Callable[[], None] | None,
        on_done:  Callable[[], None] | None,
    ) -> None:
        """pyttsx3 (Windows SAPI) fallback TTS.

        Picks a system voice matching the profile and adjusts rate so voices
        within the same gender sound noticeably different.
        """
        # First keyword that matches a SAPI voice name/id wins.
        # Male profiles → David/Mark; female profiles → Zira/Hazel.
        _VOICE_HINTS: dict[str, tuple[str, ...]] = {
            "male-british":         ("george", "james", "british", "en_gb", "en-gb", "david", "mark"),
            "male-american":        ("david", "mark", "en_us", "en-us"),
            "female-british":       ("hazel", "british", "en_gb", "en-gb", "zira"),
            "male-broadcast":       ("mark", "david", "en_us"),
            "male-resonant":        ("david", "mark", "en_us"),
            "male-smooth":          ("david", "en_us"),
            "male-gravelly":        ("mark", "david"),
            "male-casual":          ("david", "mark", "en_us"),
            "male-australian":      ("english_australia", "en_au", "en-au", "australian", "david"),
            "female-professional":  ("zira", "en_us"),
            "female-british-clear": ("hazel", "british", "en_gb", "zira"),
            "female-british-warm":  ("hazel", "british", "en_gb", "zira"),
            "female-american":      ("zira", "en_us"),
        }
        # Rate multiplier per profile — differentiates voices that share the same SAPI engine.
        _RATE_MULT: dict[str, float] = {
            "male-british":         1.00,
            "male-american":        1.05,
            "female-british":       0.95,
            "male-broadcast":       0.90,
            "male-resonant":        0.88,
            "male-smooth":          1.08,
            "male-gravelly":        0.85,
            "male-casual":          1.10,
            "male-australian":      1.05,
            "female-professional":  1.00,
            "female-british-clear": 0.97,
            "female-british-warm":  0.93,
            "female-american":      1.03,
        }
        try:
            import pyttsx3
            engine = pyttsx3.init()
            base_rate = engine.getProperty("rate") or 200
            rate_mult = _RATE_MULT.get(config.tts_voice, 1.0)
            engine.setProperty("rate", int(base_rate * config.tts_speed / 100 * rate_mult))
            hints = _VOICE_HINTS.get(config.tts_voice, ())
            selected_voice_name = None
            if hints:
                for v in engine.getProperty("voices") or []:
                    combined = (v.name + v.id).lower()
                    if any(k in combined for k in hints):
                        engine.setProperty("voice", v.id)
                        selected_voice_name = v.name
                        break
            _dbg("tts", f"pyttsx3 → profile={config.tts_voice!r}  sapi={selected_voice_name!r}")
            self._notify(on_ready)
            engine.say(text)
            engine.runAndWait()
        except Exception as exc:
            _dbg("tts", f"pyttsx3 fallback failed: {exc}")
            self._notify(on_ready)
            _dbg("JARVIS", text)
        self._notify(on_done)
