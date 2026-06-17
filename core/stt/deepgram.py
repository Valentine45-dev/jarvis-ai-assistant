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
        self._stop = threading.Event()
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
        self._cm = self._make_cm()
        self._conn = self._cm.__enter__()
        self._reader = threading.Thread(target=self._read_loop, name="DeepgramRecv", daemon=True)
        self._reader.start()
        _dbg("stt", f"Deepgram session started (model={self._model!r})")

    def feed(self, pcm16: bytes) -> None:
        conn = self._conn
        if conn is None or self._stop.is_set():
            return
        try:
            conn.send_media(pcm16)
        except Exception as exc:
            self._fail(f"Deepgram send failed: {exc}")

    def finish(self) -> None:
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
        try:
            while not self._stop.is_set():
                event = self._conn.recv()
                if event is None:
                    break
                self._dispatch(event)
        except Exception as exc:
            # A recv() raising after we asked to stop is just the socket closing.
            if not self._stop.is_set():
                self._fail(f"Deepgram stream error: {exc}")

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
        reader = self._reader
        if reader is not None and reader.is_alive() and reader is not threading.current_thread():
            reader.join(timeout=1.0)

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
