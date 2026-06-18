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
                data, _ = self._stream.read(self._chunk)
                self._feed(bytes(data))
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

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
