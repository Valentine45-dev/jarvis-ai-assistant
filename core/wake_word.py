"""
JARVIS wake-word detector.

Always-on background thread: captures 2.5-second audio windows, transcribes
via Google STT, and fires a callback when the configured wake phrase is heard.

Uses the same sounddevice + SpeechRecognition stack as the main pipeline —
no extra dependencies or API keys needed.

Pause / Resume
--------------
main.py calls pause() whenever the system enters any non-idle state
(listening, thinking, processing, speaking, awaiting_confirmation).
This yields the mic to AudioCapture and prevents false triggers during TTS.
resume() is called when the state returns to idle.

The detector's inner read loop checks _paused on every CHUNK (~64 ms) so it
stops collecting within one chunk of receiving the pause signal.
"""

from __future__ import annotations

import io
import math
import struct
import threading
import time
import wave
from typing import Callable

from config.settings import config
from core.log import debug as _dbg


def _rms(data: bytes) -> float:
    count = len(data) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"{count}h", data)
    return math.sqrt(sum(s * s for s in shorts) / count)


class WakeWordDetector:
    """Always-on wake-word spotter. Non-blocking; runs on a single daemon thread."""

    RATE         = 16_000
    CHANNELS     = 1
    CHUNK        = 1_024

    # ~2.56 s per STT call (40 × 1024 / 16000)
    WINDOW_CHUNKS = 40

    # RMS floor below which we skip STT entirely (dead silence).
    ENERGY_FLOOR  = 280

    def __init__(self) -> None:
        self._callback: Callable[[], None] | None = None
        self._running  = threading.Event()
        self._paused   = threading.Event()
        self._thread:  threading.Thread | None = None

    # ── Public ────────────────────────────────────────────────────────────────

    def start(self, callback: Callable[[], None]) -> None:
        """Start the detector. *callback* fires on the detector thread — route
        to Qt main thread via a pyqtSignal in the caller."""
        if self._running.is_set():
            return
        self._callback = callback
        self._running.set()
        self._paused.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="WakeWordDetector"
        )
        self._thread.start()
        _dbg("wake", "detector started")

    def stop(self) -> None:
        self._running.clear()
        self._paused.clear()
        _dbg("wake", "detector stopped")

    def pause(self) -> None:
        """Yield mic access to the main capture pipeline."""
        self._paused.set()

    def resume(self) -> None:
        """Reclaim mic access after main capture finishes."""
        self._paused.clear()

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    # ── Internal ─────────────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            _dbg("wake", "sounddevice not installed — wake-word disabled")
            return

        try:
            import speech_recognition as sr
        except ImportError:
            _dbg("wake", "SpeechRecognition not installed — wake-word disabled")
            return

        wake_word  = (config.wake_word or "jarvis").lower().strip()
        recognizer = sr.Recognizer()

        while self._running.is_set():
            # Yield while paused (main pipeline owns the mic)
            if self._paused.is_set():
                time.sleep(0.05)
                continue

            device = config.mic_device if config.mic_device >= 0 else None
            frames: list[bytes] = []
            peak_rms = 0.0

            try:
                with sd.RawInputStream(
                    samplerate=self.RATE,
                    channels=self.CHANNELS,
                    dtype="int16",
                    blocksize=self.CHUNK,
                    device=device,
                ) as stream:
                    for _ in range(self.WINDOW_CHUNKS):
                        if not self._running.is_set() or self._paused.is_set():
                            break
                        data, _ = stream.read(self.CHUNK)
                        raw = bytes(data)
                        frames.append(raw)
                        r = _rms(raw)
                        if r > peak_rms:
                            peak_rms = r

            except Exception as exc:
                _dbg("wake", f"stream error: {exc}")
                time.sleep(0.5)
                continue

            # Discard any frames collected before a mid-window pause — the main
            # pipeline (or TTS) owns the mic now; do not run STT on captured speech.
            if self._paused.is_set() or not self._running.is_set():
                continue

            # Skip STT for near-silent windows
            if peak_rms < self.ENERGY_FLOOR or not frames:
                continue

            # Build WAV and transcribe
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(self.CHANNELS)
                wf.setsampwidth(2)
                wf.setframerate(self.RATE)
                wf.writeframes(b"".join(frames))

            try:
                with sr.AudioFile(io.BytesIO(buf.getvalue())) as source:
                    audio = recognizer.record(source)
                # Each ~2.5s window with sound above the floor calls Google STT.
                # Cheap on the free tier; revisit if hitting quota.
                text = recognizer.recognize_google(audio).lower()
                _dbg("wake", f"heard: {text!r}")
                if wake_word in text:
                    _dbg("wake", f"WAKE WORD: {text!r}")
                    # Pause BEFORE callback so the main capture can open the mic
                    self.pause()
                    if self._callback:
                        self._callback()
            except Exception:
                pass


wake_detector = WakeWordDetector()
