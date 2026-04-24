"""
Voice I/O — ElevenLabs TTS + Google STT via sounddevice mic capture.

TTS pipeline:  Claude response text
               → ElevenLabs API (humanized voice synthesis)
               → audio stream played through speakers via sounddevice

STT pipeline:  sounddevice mic capture (WAV frames)
               → SpeechRecognition (Google STT free tier)
               → transcribed text → brain.py

ElevenLabs key : ELEVENLABS_API_KEY in .env
Voice selection : controlled by config.tts_voice
                  "male-british"   → George  (EL voice ID)
                  "male-american"  → Adam    (EL voice ID)
                  "female-british" → Rachel  (EL voice ID)

sounddevice + numpy handle raw audio I/O (no C++ build tools required on Windows).
SpeechRecognition handles transcription via Google's free Speech-to-Text API.
"""

from __future__ import annotations

import io
import math
import struct
import threading
import wave
from typing import Callable

from config.settings import config


# ── ElevenLabs voice profile map ────────────────────────────────────────────
# Voice IDs from ElevenLabs' pre-made voice library (stable across accounts).
_EL_VOICES: dict[str, str] = {
    "male-british":   "JBFqnCBsd6RMkjVDRZzb",  # George — deep, British
    "male-american":  "pNInz6obpgDQGcFmaJgB",  # Adam   — neutral American
    "female-british": "21m00Tcm4TlvDq8ikWAM",  # Rachel — warm, neutral
}

_DEFAULT_VOICE_ID = _EL_VOICES["male-british"]

# ── Lazy imports ─────────────────────────────────────────────────────────────

def _el():
    """Return the elevenlabs module, or None if not installed."""
    try:
        import elevenlabs
        return elevenlabs
    except ImportError:
        return None


def _sd():
    """Return sounddevice module, or None if not installed."""
    try:
        import sounddevice as sd
        return sd
    except ImportError:
        return None


def _sr():
    """Return speech_recognition module, or None if not installed."""
    try:
        import speech_recognition as sr
        return sr
    except ImportError:
        return None


def _np():
    try:
        import numpy as np
        return np
    except ImportError:
        return None


# ── RMS helper (audioop removed in Python 3.14) ──────────────────────────────

def _rms(data: bytes) -> float:
    """Compute RMS amplitude of raw 16-bit PCM bytes."""
    count = len(data) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"{count}h", data)
    return math.sqrt(sum(s * s for s in shorts) / count)


# ── VoiceEngine ───────────────────────────────────────────────────────────────

class VoiceEngine:
    """Thread-safe voice engine.

    Both say() and listen() return immediately; all audio work runs on daemon
    threads so the Qt main thread is never blocked.
    """

    def __init__(self):
        self._tts_lock = threading.Lock()
        self._listening = threading.Event()

    # ── TTS ──────────────────────────────────────────────────────────────────

    def say(self, text: str, on_ready: Callable[[], None] | None = None) -> None:
        """Speak *text* using ElevenLabs TTS. Non-blocking."""
        if not text.strip():
            return
        threading.Thread(target=self._say_thread, args=(text, on_ready), daemon=True).start()

    def _say_thread(self, text: str, on_ready: Callable[[], None] | None = None) -> None:
        ready_called = threading.Event()

        def _on_ready_once() -> None:
            if ready_called.is_set():
                return
            ready_called.set()
            self._notify_ready(on_ready)

        with self._tts_lock:
            if config.elevenlabs_api_key:
                try:
                    self._say_elevenlabs(text, _on_ready_once)
                    return
                except Exception as exc:
                    if config.debug_mode:
                        print(f"[voice/tts] ElevenLabs error, falling back: {exc}")
                    if ready_called.is_set():
                        return
            self._say_local(text, _on_ready_once)

    def _notify_ready(self, on_ready: Callable[[], None] | None) -> None:
        """Notify UI code that audio is ready without letting UI errors break TTS."""
        if on_ready is None:
            return
        try:
            on_ready()
        except Exception as exc:
            if config.debug_mode:
                print(f"[voice/tts] on_ready callback failed: {exc}")

    def _say_elevenlabs(
        self,
        text: str,
        on_ready: Callable[[], None] | None = None,
    ) -> None:
        """Stream ElevenLabs MP3 chunks and start playback as soon as MCI can open them."""
        el = _el()
        if el is None:
            raise RuntimeError("elevenlabs package not installed")

        voice_id = _EL_VOICES.get(config.tts_voice, _DEFAULT_VOICE_ID)
        client = el.ElevenLabs(api_key=config.elevenlabs_api_key)

        stream = getattr(client.text_to_speech, "stream", None)
        if stream is not None:
            chunks = stream(
                voice_id=voice_id,
                text=text,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128",
            )
            self._play_mp3_stream(chunks, on_ready)
            return

        mp3_bytes = b"".join(
            client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128",
            )
        )
        self._notify_ready(on_ready)
        self._play_mp3_bytes(mp3_bytes)

    def _play_mp3_stream(
        self,
        chunks,
        on_ready: Callable[[], None] | None = None,
    ) -> None:
        """Write MP3 chunks to disk and ask MCI to begin playback once readable."""
        import ctypes
        import os as _os
        import tempfile
        import time

        mci = ctypes.windll.winmm.mciSendStringW

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name

        alias = f"jarvis_tts_{threading.get_ident()}"
        opened = False
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
            self._notify_ready(on_ready)
            return True

        def _wait_until_stopped() -> None:
            if not opened:
                return
            status = ctypes.create_unicode_buffer(64)
            for _ in range(600):  # 60s safety cap
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
                _wait_until_stopped()
            else:
                self._notify_ready(on_ready)
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

    def _play_mp3_bytes(self, mp3_bytes: bytes) -> None:
        """Play MP3 bytes synchronously via Windows MCI (no extra deps required)."""
        import ctypes
        import tempfile
        import os as _os

        mci = ctypes.windll.winmm.mciSendStringW

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(mp3_bytes)
            tmp_path = f.name

        alias = "jarvis_tts"
        try:
            mci(f'open "{tmp_path}" type mpegvideo alias {alias}', None, 0, None)
            mci(f"play {alias} wait", None, 0, None)
            mci(f"close {alias}", None, 0, None)
        finally:
            try:
                _os.unlink(tmp_path)
            except OSError:
                pass

    def _say_local(
        self,
        text: str,
        on_ready: Callable[[], None] | None = None,
    ) -> None:
        """Fallback TTS via pyttsx3 (Windows SAPI)."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            base_rate = engine.getProperty("rate") or 200
            engine.setProperty("rate", int(base_rate * config.tts_speed / 100))
            for v in engine.getProperty("voices") or []:
                combined = (v.name + v.id).lower()
                if "british" in config.tts_voice and any(
                    k in combined for k in ("british", "en_gb", "en-gb")
                ):
                    engine.setProperty("voice", v.id)
                    break
            self._notify_ready(on_ready)
            engine.say(text)
            engine.runAndWait()
        except Exception as exc:
            if config.debug_mode:
                print(f"[voice/tts] pyttsx3 fallback failed: {exc}")
            # Ultimate fallback: print to console (no audio)
            self._notify_ready(on_ready)
            print(f"[JARVIS] {text}")

    # ── STT ──────────────────────────────────────────────────────────────────

    def listen(
        self,
        callback: Callable[[str], None],
        on_error: Callable[[str], None] | None = None,
        timeout: float = 8.0,
        phrase_time_limit: float = 12.0,
    ) -> None:
        """Capture mic → transcribe → call *callback(text)*. Non-blocking."""
        threading.Thread(
            target=self._listen_thread,
            args=(callback, on_error, timeout, phrase_time_limit),
            daemon=True,
        ).start()

    def _listen_thread(
        self,
        callback: Callable[[str], None],
        on_error: Callable[[str], None] | None,
        timeout: float,
        phrase_time_limit: float,
    ) -> None:
        self._listening.set()
        try:
            wav_bytes = self._record_wav(timeout, phrase_time_limit)
            if wav_bytes is None:
                if on_error:
                    on_error("No speech detected — try speaking louder.")
                return
            text = self._transcribe(wav_bytes)
            if text:
                callback(text)
            else:
                if on_error:
                    on_error("Could not understand audio.")
        except Exception as exc:
            if on_error:
                on_error(f"Voice error: {exc}")
        finally:
            self._listening.clear()

    def _record_wav(self, timeout: float, phrase_time_limit: float) -> bytes | None:
        """Record from the default mic using sounddevice. Returns WAV bytes or None."""
        sd = _sd()
        np = _np()
        if sd is None or np is None:
            raise RuntimeError(
                "sounddevice / numpy not installed — run: uv add sounddevice numpy"
            )

        RATE = 16_000
        CHANNELS = 1
        CHUNK = 1024
        # Map mic_sensitivity (0–100) → RMS silence threshold (200–4000)
        silence_threshold = 200 + (100 - config.mic_sensitivity) * 38

        if config.debug_mode:
            print("[voice/stt] Listening…")

        frames: list[bytes] = []
        phrase_started = False
        silence_frames = 0
        # 1.5 s of silence after speech ends = stop recording
        max_silence_frames = int(RATE / CHUNK * 1.5)
        max_frames = int(RATE / CHUNK * (timeout + phrase_time_limit))
        timeout_frames = int(RATE / CHUNK * timeout)

        with sd.RawInputStream(
            samplerate=RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK,
        ) as stream:
            for frame_idx in range(max_frames):
                data, _ = stream.read(CHUNK)
                raw = bytes(data)
                frames.append(raw)
                rms = _rms(raw)

                if rms > silence_threshold:
                    phrase_started = True
                    silence_frames = 0
                elif phrase_started:
                    silence_frames += 1
                    if silence_frames >= max_silence_frames:
                        break
                elif frame_idx >= timeout_frames:
                    break  # timed out waiting for speech to start

        if not phrase_started:
            return None

        # Pack frames into a WAV buffer
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)   # int16 = 2 bytes
            wf.setframerate(RATE)
            wf.writeframes(b"".join(frames))
        return buf.getvalue()

    def _transcribe(self, wav_bytes: bytes) -> str:
        """Send WAV bytes to Google STT via SpeechRecognition."""
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
                print(f"[voice/stt] Heard: {text!r}")
            return text
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as exc:
            raise RuntimeError(f"Google STT error: {exc}") from exc

    @property
    def is_listening(self) -> bool:
        return self._listening.is_set()


voice_engine = VoiceEngine()
