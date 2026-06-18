"""Mic → streaming-STT pump.

Opens a sounddevice RawInputStream and forwards raw 16-bit PCM frames to a
`feed(bytes)` callable (a StreamingSttSession) on a daemon thread. Mirrors the
device / rate / dtype settings AudioCapture uses for the batch path so the
streaming and batch mics behave identically.

Unlike AudioCapture there is NO VAD here — endpointing is the server's job
(Deepgram's `endpointing` / `utterance_end_ms`). This class only moves bytes.

The sounddevice module is resolved lazily (and overridable via `_sd` for tests)
so importing this file never pulls PortAudio into processes that don't record.
"""

from __future__ import annotations

import struct
import threading

from core.log import debug as _dbg


def _default_sd():
    try:
        import sounddevice as sd
        return sd
    except ImportError:
        return None


class MicStreamer:
    """Pump mic frames into a `feed(pcm16_bytes)` callable until stopped.

    start() opens the stream synchronously (so device errors surface to the
    caller) then spawns the read loop. stop() is idempotent and always closes
    the underlying stream.
    """

    RATE     = 16_000
    CHANNELS = 1
    CHUNK    = 1_024

    def __init__(
        self,
        feed,
        *,
        rate: int = RATE,
        channels: int = CHANNELS,
        chunk: int = CHUNK,
        device=None,
        _sd=None,
    ) -> None:
        self._feed     = feed
        self._rate     = int(rate)
        self._channels = int(channels)
        self._chunk    = int(chunk)
        self._device   = device
        self._sd_override = _sd

        self._stream = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # Diagnostics: how much audio we pumped and its peak level. A peak near
        # 0 across a whole turn means the device delivered silence (muted / wrong
        # default device / contended) — the mic is the problem, not the stream.
        self._frames_fed = 0
        self._peak = 0
        self._overflows = 0

    def _sd(self):
        return self._sd_override if self._sd_override is not None else _default_sd()

    def start(self) -> None:
        """Open the mic stream and begin pumping frames. Raises on device error."""
        sd = self._sd()
        if sd is None:
            raise RuntimeError("sounddevice not installed — run: uv add sounddevice numpy")
        self._stop.clear()
        self._stream = sd.RawInputStream(
            samplerate=self._rate,
            channels=self._channels,
            dtype="int16",
            blocksize=self._chunk,
            device=self._device,
        )
        self._stream.start()
        self._thread = threading.Thread(target=self._loop, name="MicStreamer", daemon=True)
        self._thread.start()
        _dbg("stt", f"mic streamer started (device={self._device}, rate={self._rate})")

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                data, overflowed = self._stream.read(self._chunk)
                raw = bytes(data)
                self._frames_fed += 1
                if overflowed:
                    # Input buffer overran — samples were dropped before we read
                    # them. If this is non-zero the audio is gappy and Deepgram
                    # may VAD on it but fail to transcribe. feed() must stay cheap
                    # (it only enqueues now) so this should remain 0.
                    self._overflows += 1
                n = len(raw) // 2
                if n:
                    samples = struct.unpack(f"{n}h", raw)
                    peak = max(max(samples), -min(samples))
                    if peak > self._peak:
                        self._peak = peak
                self._feed(raw)
        except Exception as exc:
            # "stream is stopped" fires when stop() closes the device mid-read —
            # an expected end-of-turn, not a failure worth surfacing.
            if "stream is stopped" not in str(exc).lower() and not self._stop.is_set():
                _dbg("stt", f"mic streamer read error: {exc}")
        finally:
            self._close_stream()

    def stop(self) -> None:
        """Signal the read loop to stop, join it, and close the stream. Idempotent."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._close_stream()
        # int16 full-scale is 32767; a healthy spoken peak is in the thousands.
        # A peak in the low tens across a whole turn == effectively silence.
        pct = round(self._peak / 327.67, 1)  # peak as % of full scale
        _dbg("stt", f"mic streamer stopped: {self._frames_fed} frames fed, "
                    f"peak={self._peak} ({pct}% full-scale), overflows={self._overflows}")

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
