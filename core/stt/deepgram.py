"""Deepgram streaming STT session (websocket, nova-3 by default).

Implements StreamingSttSession over deepgram-sdk's listen.v1 websocket. ALL SDK
specifics are isolated in this file so a version bump can't leak into the rest
of the app, and so a local engine can replace it behind the same interface.

SDK shape (deepgram-sdk 7.x), all verified by introspection:
  client.listen.v1.connect(...) -> contextmanager yielding a V1SocketClient
  conn.send_media(bytes)          push audio
  conn.recv()                     blocking read of one typed event
  conn.send_finalize()            ask for a final result
  conn.send_close_stream()        graceful close
  events: *Results (is_final / speech_final / channel.alternatives[0].transcript)
          *UtteranceEnd (last_word_end)
"""

from __future__ import annotations

import queue
import threading

from core.log import debug as _dbg
from core.stt.base import StreamingSttSession


class DeepgramSttSession(StreamingSttSession):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "nova-3",
        language: str = "en-US",
        endpointing_ms: int = 300,
        utterance_end_ms: int = 1000,
        sample_rate: int = 16000,
        _connect=None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._language = language
        self._endpointing_ms = int(endpointing_ms)
        self._utterance_end_ms = int(utterance_end_ms)
        self._sample_rate = int(sample_rate)
        # Test seam: a zero-arg callable returning a context manager that yields a
        # connection object with send_media/recv/send_finalize/send_close_stream.
        self._connect_override = _connect

        self._cm = None
        self._conn = None
        self._reader: threading.Thread | None = None
        self._writer: threading.Thread | None = None
        self._stop = threading.Event()
        self._finishing = threading.Event()
        # Audio is queued here by feed() (called on the real-time mic thread) and
        # drained by the writer thread, so a slow websocket send NEVER stalls the
        # mic read loop (which would overflow PortAudio's buffer and shred the
        # audio — Deepgram then VADs on the energy but can't transcribe). 256
        # chunks ≈ 16 s of 64 ms frames; drop-oldest if a stall outlasts that.
        self._send_q: "queue.Queue[bytes]" = queue.Queue(maxsize=256)
        self._dropped = 0
        self._on_partial = None
        self._on_final = None
        self._on_utterance_end = None
        self._on_error = None

    # ── StreamingSttSession ───────────────────────────────────────────────────

    def start(self, *, on_partial, on_final, on_utterance_end, on_error) -> None:
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_utterance_end = on_utterance_end
        self._on_error = on_error
        self._stop.clear()
        self._finishing.clear()
        self._cm = self._make_cm()
        self._conn = self._cm.__enter__()
        self._reader = threading.Thread(target=self._read_loop, name="DeepgramRecv", daemon=True)
        self._reader.start()
        self._writer = threading.Thread(target=self._write_loop, name="DeepgramSend", daemon=True)
        self._writer.start()
        _dbg("stt", f"Deepgram session started (model={self._model!r})")

    def feed(self, pcm16: bytes) -> None:
        # Non-blocking by design: just enqueue. The writer thread does the actual
        # websocket send, so the mic thread is never blocked on the network.
        if self._stop.is_set() or self._finishing.is_set():
            return
        try:
            self._send_q.put_nowait(pcm16)
        except queue.Full:
            # Network can't keep up — drop the OLDEST frame to bound latency
            # rather than block the mic thread or grow without limit.
            self._dropped += 1
            try:
                self._send_q.get_nowait()
                self._send_q.put_nowait(pcm16)
            except (queue.Empty, queue.Full):
                pass

    def _write_loop(self) -> None:
        """Drain queued audio to the websocket. Exits when finishing/stopped and
        the queue is empty (so finish() can flush the tail before finalize)."""
        while True:
            try:
                chunk = self._send_q.get(timeout=0.05)
            except queue.Empty:
                if self._finishing.is_set() or self._stop.is_set():
                    return
                continue
            conn = self._conn
            if conn is None or self._stop.is_set():
                return
            try:
                conn.send_media(chunk)
            except Exception as exc:
                self._fail(f"Deepgram send failed: {exc}")
                return

    def finish(self) -> None:
        # Stop accepting new audio, let the writer flush what's already queued,
        # THEN finalize + close so the last words actually reach Deepgram.
        self._finishing.set()
        writer = self._writer
        if writer is not None and writer.is_alive() and writer is not threading.current_thread():
            writer.join(timeout=2.0)
        if self._dropped:
            _dbg("stt", f"Deepgram send queue dropped {self._dropped} frame(s) — network lagged")
        conn = self._conn
        if conn is not None:
            try:
                conn.send_finalize()
                conn.send_close_stream()
            except Exception:
                pass
        self._teardown()

    def close(self) -> None:
        self._teardown()

    # ── Internals ─────────────────────────────────────────────────────────────

    def _make_cm(self):
        if self._connect_override is not None:
            return self._connect_override()
        from deepgram import DeepgramClient  # lazy — keeps SDK off the import path
        client = DeepgramClient(api_key=self._api_key)
        return client.listen.v1.connect(
            model=self._model,
            language=self._language,
            encoding="linear16",
            sample_rate=self._sample_rate,
            channels=1,
            interim_results=True,
            endpointing=self._endpointing_ms,
            utterance_end_ms=self._utterance_end_ms,
            vad_events=True,
            punctuate=True,
            smart_format=True,
        )

    def _read_loop(self) -> None:
        count = 0
        try:
            while not self._stop.is_set():
                event = self._conn.recv()
                if event is None:
                    break
                count += 1
                self._dispatch(event)
        except Exception as exc:
            # A recv() raising after we asked to stop is just the socket closing.
            if not self._stop.is_set():
                self._fail(f"Deepgram stream error: {exc}")
        finally:
            # One concise line per turn: zero events means the connection was
            # alive but the server sent nothing (useful future health signal).
            _dbg("stt", f"Deepgram read loop ended after {count} event(s)")

    def _dispatch(self, event) -> None:
        # Duck-typed so real SDK objects AND test fakes both work. UtteranceEnd
        # also carries `channel`, so check its unique `last_word_end` field FIRST.
        if hasattr(event, "last_word_end"):
            self._safe0(self._on_utterance_end)
            return
        if hasattr(event, "is_final") and hasattr(event, "channel"):
            text = self._extract_text(event)
            if not text:
                return
            if getattr(event, "is_final", False):
                self._safe(self._on_final, text)
            else:
                self._safe(self._on_partial, text)

    @staticmethod
    def _extract_text(event) -> str:
        channel = getattr(event, "channel", None)
        alts = getattr(channel, "alternatives", None) or []
        if not alts:
            return ""
        return (getattr(alts[0], "transcript", "") or "").strip()

    def _teardown(self) -> None:
        self._stop.set()
        cm, self._cm, self._conn = self._cm, None, None
        if cm is not None:
            try:
                cm.__exit__(None, None, None)
            except Exception:
                pass
        for t in (self._writer, self._reader):
            if t is not None and t.is_alive() and t is not threading.current_thread():
                t.join(timeout=1.0)

    def _fail(self, message: str) -> None:
        _dbg("stt", message)
        self._safe(self._on_error, message)

    def _safe(self, cb, arg) -> None:
        if cb is None:
            return
        try:
            cb(arg)
        except Exception as exc:
            _dbg("stt", f"callback error: {exc}")

    def _safe0(self, cb) -> None:
        if cb is None:
            return
        try:
            cb()
        except Exception as exc:
            _dbg("stt", f"callback error: {exc}")
