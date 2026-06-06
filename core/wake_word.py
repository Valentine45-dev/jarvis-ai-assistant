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

Capture / recognition split (R3-17)
-----------------------------------
Capture and recognition run on SEPARATE threads. The capture loop fills a
window and hands the frames to a 1-slot mailbox, then immediately captures the
next window; a recognizer worker drains the mailbox and calls Google STT. This
keeps the mic capturing during the (blocking, ~0.5-2 s) network call, so a wake
word spoken during recognition is no longer dropped.

Stream-closed handshake (R3-15)
-------------------------------
The capture loop owns the single RawInputStream and sets `_stream_closed` once
that stream is actually closed. listen() (core/voice.py) waits on it before
opening its own stream, instead of guessing with a fixed sleep — preventing two
input streams on one mic device.

STT failure surfacing (R3-16)
-----------------------------
Recognition errors are classified: `UnknownValueError` (service reachable, no
speech) is benign; network/quota/`RequestError` are counted, and after a run of
consecutive failures a one-time warning toast is raised so a silently-dead wake
word becomes visible.
"""

from __future__ import annotations

import io
import math
import struct
import threading
import time
import wave
from typing import Callable, Optional

from config.settings import config
from core.log import debug as _dbg


def _rms(data: bytes) -> float:
    count = len(data) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"{count}h", data)
    return math.sqrt(sum(s * s for s in shorts) / count)


class WakeWordDetector:
    """Always-on wake-word spotter. Capture + recognition on two daemon threads."""

    RATE         = 16_000
    CHANNELS     = 1
    CHUNK        = 1_024

    # ~2.56 s per STT call (40 × 1024 / 16000)
    WINDOW_CHUNKS = 40

    # RMS floor below which we skip STT entirely (dead silence).
    ENERGY_FLOOR  = 280

    # Consecutive non-benign STT failures before we warn the user once.
    OFFLINE_THRESHOLD = 5

    def __init__(self) -> None:
        self._callback: Callable[[], None] | None = None
        self._running  = threading.Event()
        self._paused   = threading.Event()
        self._thread:  threading.Thread | None = None
        self._worker:  threading.Thread | None = None

        # R3-15: set whenever the capture stream is confirmed closed (or no
        # stream is open). listen() waits on this before opening its own stream.
        self._stream_closed = threading.Event()
        self._stream_closed.set()

        # R3-17: 1-slot mailbox handing the latest captured window to the worker.
        # Overwrite-if-busy (drop the stale window) so recognition can never
        # build a backlog behind a slow network call.
        self._mailbox_cv     = threading.Condition()
        self._pending_frames: Optional[bytes] = None

        # R3-16: consecutive-failure tracking for the warn-once.
        self._fail_count     = 0
        self._warned_offline = False

    # ── Public ────────────────────────────────────────────────────────────────

    def start(self, callback: Callable[[], None]) -> None:
        """Start the detector. *callback* fires on the worker thread — route
        to Qt main thread via a pyqtSignal in the caller."""
        if self._running.is_set():
            return
        self._callback = callback
        self._running.set()
        self._paused.clear()
        self._stream_closed.set()
        self._pending_frames = None
        self._fail_count = 0
        self._warned_offline = False
        self._worker = threading.Thread(
            target=self._recognizer_loop, daemon=True, name="WakeWordRecognizer"
        )
        self._worker.start()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="WakeWordDetector"
        )
        self._thread.start()
        _dbg("wake", "detector started")

    def stop(self) -> None:
        self._running.clear()
        self._paused.clear()
        with self._mailbox_cv:
            self._mailbox_cv.notify_all()   # wake the worker so it can exit
        _dbg("wake", "detector stopped")

    def pause(self) -> None:
        """Yield mic access to the main capture pipeline."""
        self._paused.set()
        # Drop any window queued before the pause so it isn't recognised (and
        # can't fire a wake) while the main pipeline owns the mic.
        with self._mailbox_cv:
            self._pending_frames = None

    def resume(self) -> None:
        """Reclaim mic access after main capture finishes."""
        self._paused.clear()

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    def wait_closed(self, timeout: float = 1.0) -> bool:
        """R3-15: block until the capture stream is confirmed closed (True) or
        the timeout elapses (False). Used by listen() for the mic handoff."""
        return self._stream_closed.wait(timeout)

    # ── Capture thread ─────────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            _dbg("wake", "sounddevice not installed — wake-word disabled")
            return

        while self._running.is_set():
            # Yield while paused (main pipeline owns the mic). No stream open,
            # so the handoff event stays set.
            if self._paused.is_set():
                self._stream_closed.set()
                time.sleep(0.05)
                continue

            device = config.mic_device if config.mic_device >= 0 else None
            frames: list[bytes] = []
            peak_rms = 0.0

            # Re-check right before opening to shrink the open-vs-pause race; the
            # handshake's timeout covers any residual sliver.
            if self._paused.is_set():
                self._stream_closed.set()
                continue
            self._stream_closed.clear()

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
                self._stream_closed.set()
                time.sleep(0.5)
                continue
            finally:
                # The `with` has exited here → the stream is closed.
                self._stream_closed.set()

            # Discard frames if a pause landed mid-window — main owns the mic now.
            if self._paused.is_set() or not self._running.is_set():
                continue
            # Skip near-silent windows entirely (no STT call).
            if peak_rms < self.ENERGY_FLOOR or not frames:
                continue

            # Hand the window to the recognizer worker (overwrite stale).
            joined = b"".join(frames)
            with self._mailbox_cv:
                self._pending_frames = joined
                self._mailbox_cv.notify()

    # ── Recognition worker ─────────────────────────────────────────────────────

    def _recognizer_loop(self) -> None:
        try:
            import speech_recognition as sr
        except ImportError:
            _dbg("wake", "SpeechRecognition not installed — wake-word disabled")
            return

        self._recognizer = sr.Recognizer()
        wake_word = (config.wake_word or "jarvis").lower().strip()

        while self._running.is_set():
            with self._mailbox_cv:
                while self._running.is_set() and self._pending_frames is None:
                    self._mailbox_cv.wait(timeout=0.5)
                if not self._running.is_set():
                    break
                frames = self._pending_frames
                self._pending_frames = None
            if frames:
                self._handle_window(frames, transcribe=self._transcribe, wake_word=wake_word)

    def _transcribe(self, frames: bytes) -> str:
        """Build a WAV from raw frames and return the lower-cased Google STT
        transcript. Raises on any STT/network error (handled by _handle_window)."""
        import speech_recognition as sr
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(self.RATE)
            wf.writeframes(frames)
        with sr.AudioFile(io.BytesIO(buf.getvalue())) as source:
            audio = self._recognizer.record(source)
        return self._recognizer.recognize_google(audio).lower()

    def _handle_window(
        self,
        frames: bytes,
        *,
        transcribe: Callable[[bytes], str],
        wake_word: str,
    ) -> None:
        """Recognise one window and fire the wake callback on a match. Classifies
        and surfaces STT failures (R3-16). Pure orchestration — `transcribe` is
        injected so this is unit-testable without audio/network."""
        try:
            text = transcribe(frames)
        except Exception as exc:
            benign = self._stt_error_benign(exc)
            if not benign:
                _dbg("wake", f"STT error: {exc!r}")
            self._note_stt_failure(benign)
            return

        self._note_stt_success()
        _dbg("wake", f"heard: {text!r}")
        if wake_word in text and not self._paused.is_set():
            _dbg("wake", f"WAKE WORD: {text!r}")
            self.pause()                       # close mic before main opens it
            if self._callback:
                self._callback()

    # ── STT failure classification / surfacing (R3-16) ──────────────────────────

    @staticmethod
    def _stt_error_benign(exc: BaseException) -> bool:
        """True for 'service reachable, no speech recognised' — not a failure.
        Matched by name so we don't need to import speech_recognition here."""
        return type(exc).__name__ == "UnknownValueError"

    def _note_stt_success(self) -> None:
        self._fail_count = 0
        self._warned_offline = False

    def _note_stt_failure(self, benign: bool) -> None:
        if benign:
            # Service answered, just no words — reset the streak.
            self._fail_count = 0
            return
        self._fail_count += 1
        if self._fail_count >= self.OFFLINE_THRESHOLD and not self._warned_offline:
            self._warned_offline = True
            self._emit_offline_warning()

    def _emit_offline_warning(self) -> None:
        """One-time, best-effort: tell the user the wake word went offline."""
        _dbg("wake", "wake word offline — speech service unavailable (warning emitted)")
        try:
            from core.signals import signals
            signals.error_occurred.emit("Wake word offline — speech service unavailable.")
        except Exception:
            pass


wake_detector = WakeWordDetector()
