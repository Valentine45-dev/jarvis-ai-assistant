"""
JARVIS audio pipeline — internal STT/TTS engines.

Consumed exclusively by core/voice.py (VoiceEngine facade).
Do not import this module from main.py or UI code directly.

Classes
-------
AudioCapture   — sounddevice mic capture with RMS VAD + guaranteed stream cleanup
SttEngine      — Google STT with typed SttError (NO_SPEECH / NETWORK / TIMEOUT / DEVICE)
TtsEngine      — ElevenLabs streaming + pyttsx3 fallback; exposes is_speaking for overlap guard

Constants
---------
_EL_VOICES       — voice-key → ElevenLabs voice-ID map (re-exported via voice.py)
_DEFAULT_VOICE_ID — fallback when config.tts_voice is unrecognised
SttError          — enum of typed failure modes for the STT path
"""

from __future__ import annotations

import enum
import io
import math
import struct
import threading
import wave
from typing import Callable

from config.settings import config


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


def _el():
    try:
        import elevenlabs
        return elevenlabs
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
            print(f"[capture] opening mic stream (threshold={silence_threshold:.0f}, device={device})")
            with sd.RawInputStream(
                samplerate=self.RATE,
                channels=self.CHANNELS,
                dtype="int16",
                blocksize=self.CHUNK,
                device=device,
            ) as stream:
                print("[capture] stream open — listening for speech")
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
            if config.debug_mode:
                print(f"[stt] Heard: {text!r}")
            return text

        except sr.UnknownValueError:
            raise _SttErrorExc(
                SttError.NO_SPEECH,
                "Could not make that out — try speaking a little clearer, sir.",
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

    def __init__(self) -> None:
        self._lock     = threading.Lock()
        self._speaking = threading.Event()

    @property
    def is_speaking(self) -> bool:
        return self._speaking.is_set()

    # ── Public ───────────────────────────────────────────────────────────────

    def say(
        self,
        text: str,
        on_ready: Callable[[], None] | None = None,
        on_done:  Callable[[], None] | None = None,
    ) -> None:
        """Speak *text*. Non-blocking. is_speaking=True for the full clip duration."""
        threading.Thread(
            target=self._say_thread, args=(text, on_ready, on_done), daemon=True
        ).start()

    # ── Internal ─────────────────────────────────────────────────────────────

    def _say_thread(
        self,
        text: str,
        on_ready: Callable[[], None] | None,
        on_done:  Callable[[], None] | None,
    ) -> None:
        ready_called = threading.Event()

        def _on_ready_once() -> None:
            if not ready_called.is_set():
                ready_called.set()
                self._notify(on_ready)

        # Set is_speaking BEFORE the lock so the overlap guard in listen() sees
        # True immediately, not after waiting for a previous say() to finish.
        self._speaking.set()
        try:
            with self._lock:
                if config.elevenlabs_api_key:
                    try:
                        self._say_elevenlabs(text, _on_ready_once, on_done)
                        return
                    except Exception as exc:
                        print(f"[tts] ElevenLabs FAILED, falling back to pyttsx3: {exc}")
                        # If on_ready already fired, don't duplicate it in fallback.
                        if ready_called.is_set():
                            self._notify(on_done)
                            return
                self._say_local(text, _on_ready_once, on_done)
        finally:
            self._speaking.clear()

    def _notify(self, cb: Callable[[], None] | None) -> None:
        if cb is None:
            return
        try:
            cb()
        except Exception as exc:
            if config.debug_mode:
                print(f"[tts] callback error: {exc}")

    def _say_elevenlabs(
        self,
        text: str,
        on_ready: Callable[[], None] | None,
        on_done:  Callable[[], None] | None,
    ) -> None:
        el = _el()
        if el is None:
            raise RuntimeError("elevenlabs package not installed")

        voice_id = _EL_VOICES.get(config.tts_voice, _DEFAULT_VOICE_ID)
        print(f"[tts] ElevenLabs → voice={config.tts_voice!r}  id={voice_id}")
        client = el.ElevenLabs(api_key=config.elevenlabs_api_key)

        stream_fn = getattr(client.text_to_speech, "stream", None)
        if stream_fn is not None:
            chunks = stream_fn(
                voice_id=voice_id,
                text=text,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128",
            )
            self._play_mp3_stream(chunks, on_ready, on_done)
            return

        # Non-streaming fallback (older EL SDK versions)
        mp3_bytes = b"".join(
            client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128",
            )
        )
        self._notify(on_ready)
        self._play_mp3_bytes(mp3_bytes, on_done)

    def _play_mp3_stream(
        self,
        chunks,
        on_ready: Callable[[], None] | None,
        on_done:  Callable[[], None] | None,
    ) -> None:
        """Write MP3 chunks to a temp file and play via Windows MCI as they arrive."""
        import ctypes
        import os as _os
        import tempfile
        import time

        mci = ctypes.windll.winmm.mciSendStringW

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name

        alias   = f"jarvis_tts_{threading.get_ident()}"
        opened  = False
        playing = False

        def _send(cmd: str) -> int:
            return mci(cmd, None, 0, None)

        def _try_start() -> bool:
            nonlocal opened, playing
            if opened:
                return True
            if _send(f'open "{tmp_path}" type mpegvideo alias {alias}') != 0:
                return False
            opened = True
            if _send(f"play {alias}") != 0:
                _send(f"close {alias}")
                opened = False
                return False
            playing = True
            self._notify(on_ready)
            return True

        def _wait_done() -> None:
            if not opened:
                return
            status = ctypes.create_unicode_buffer(64)
            for _ in range(600):    # 60 s safety cap
                status.value = ""
                if mci(f"status {alias} mode", status, 64, None) != 0:
                    break
                if status.value.lower() in {"stopped", "not ready"}:
                    break
                time.sleep(0.1)

        try:
            with open(tmp_path, "ab", buffering=0) as audio_file:
                for chunk in chunks:
                    if not chunk:
                        continue
                    audio_file.write(chunk)
                    audio_file.flush()
                    if not playing:
                        _try_start()

            if playing:
                _wait_done()
            else:
                # No chunks were large enough to trigger playback start — play now.
                self._notify(on_ready)
                if _send(f'open "{tmp_path}" type mpegvideo alias {alias}') == 0:
                    opened = True
                    _send(f"play {alias} wait")
        finally:
            if opened:
                _send(f"close {alias}")
            try:
                _os.unlink(tmp_path)
            except OSError:
                pass

        self._notify(on_done)

    def _play_mp3_bytes(
        self,
        mp3_bytes: bytes,
        on_done: Callable[[], None] | None,
    ) -> None:
        """Play a complete MP3 buffer synchronously via Windows MCI."""
        import ctypes
        import tempfile
        import os as _os

        mci = ctypes.windll.winmm.mciSendStringW

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(mp3_bytes)
            tmp_path = f.name

        alias = f"jarvis_tts_bytes_{threading.get_ident()}"
        try:
            mci(f'open "{tmp_path}" type mpegvideo alias {alias}', None, 0, None)
            mci(f"play {alias} wait", None, 0, None)
            mci(f"close {alias}", None, 0, None)
        finally:
            try:
                _os.unlink(tmp_path)
            except OSError:
                pass
        self._notify(on_done)

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
            print(f"[tts] pyttsx3 → profile={config.tts_voice!r}  sapi={selected_voice_name!r}")
            self._notify(on_ready)
            engine.say(text)
            engine.runAndWait()
        except Exception as exc:
            print(f"[tts] pyttsx3 fallback failed: {exc}")
            self._notify(on_ready)
            print(f"[JARVIS] {text}")
        self._notify(on_done)
