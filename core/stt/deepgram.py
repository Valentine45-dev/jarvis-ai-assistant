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

import logging
import queue
import threading

from core.log import debug as _dbg
from core.stt.base import StreamingSttSession


class _SuppressKeepalivePingFailed(logging.Filter):
    """Drop the websockets library's benign 'keepalive ping failed' ERROR.

    On shutdown we tear down the persistent Deepgram socket; the websockets
    library runs its OWN internal keepalive thread (separate from our
    _keepalive_loop) which, on its next ping after the socket has closed, logs a
    full ConnectionClosedError traceback (websockets/sync/connection.py:791,
    logger.error(..., exc_info=True)). It's a swallowed, post-close race — our
    [stt] layer already reports the connection errors we actually act on — so the
    traceback is pure noise that looks alarming on quit. Suppress only THAT
    record; every other websockets log still passes through.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "keepalive ping failed" not in record.getMessage()


# Install once at import (idempotent — addFilter dedupes by identity isn't
# guaranteed, so guard with a module flag). The connection logs on
# "websockets.client"; cover the parent too for version drift.
_KEEPALIVE_FILTER = _SuppressKeepalivePingFailed()
for _wsname in ("websockets", "websockets.client"):
    _wslog = logging.getLogger(_wsname)
    if not any(isinstance(f, _SuppressKeepalivePingFailed) for f in _wslog.filters):
        _wslog.addFilter(_KEEPALIVE_FILTER)


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _pingless_ws_factory(url, headers):
    """Deepgram SDK transport factory: open the websocket with the library's own
    ping keepalive DISABLED (ping_interval=None) so a slow pong on a laggy network
    can't self-close the socket with a 1011 'keepalive ping timeout' mid-utterance.
    We keep the connection warm with our OWN app-level KeepAlive (send_keep_alive),
    so Deepgram won't idle-close us. Returns the same websockets ClientConnection
    the SDK would otherwise build (it drives .send()/.recv()/iteration on it), so
    the contract is identical apart from the disabled ping. Module-level (stable
    identity) because the SDK's transport install is global + must be idempotent."""
    from websockets.sync.client import connect as _ws_connect
    return _ws_connect(
        url, additional_headers=headers,
        ping_interval=None, open_timeout=8, close_timeout=2,
    )


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
        keyterms: list[str] | None = None,
        _connect=None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._language = language
        # Clamp to sane bounds so a config typo (e.g. 5 or 99999) can't silently
        # wreck capture. endpointing: 10ms-2s; utterance_end: Deepgram requires
        # >=1000ms, cap at 5s. Both are coerced defensively before reaching the API.
        self._endpointing_ms = _clamp(int(endpointing_ms), 10, 2000)
        self._utterance_end_ms = _clamp(int(utterance_end_ms), 1000, 5000)
        self._sample_rate = int(sample_rate)
        self._keyterms = list(keyterms or [])
        # Test seam: a zero-arg callable returning a context manager that yields a
        # connection object with send_media/recv/send_finalize/send_close_stream.
        self._connect_override = _connect

        self._cm = None
        self._conn = None
        self._reader: threading.Thread | None = None
        self._writer: threading.Thread | None = None
        self._keepalive: threading.Thread | None = None
        self._stop = threading.Event()         # permanent teardown (close)
        self._turn_active = threading.Event()  # True while a turn feeds audio
        self._send_lock = threading.Lock()     # serialise all websocket sends
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

    # KeepAlive cadence — Deepgram closes an idle socket after ~10 s (NET-0001),
    # so ping every 5 s between turns to hold a persistent connection open.
    _KEEPALIVE_S = 5.0

    # ── StreamingSttSession (per-turn: socket opens and closes each turn) ──────

    def start(self, *, on_partial, on_final, on_utterance_end, on_error) -> None:
        self.set_callbacks(on_partial=on_partial, on_final=on_final,
                           on_utterance_end=on_utterance_end, on_error=on_error)
        self._stop.clear()
        self._turn_active.set()
        self._open_socket(keepalive=False)
        _dbg("stt", f"Deepgram session started (model={self._model!r})")

    def feed(self, pcm16: bytes) -> None:
        # Non-blocking by design: just enqueue. The writer thread does the actual
        # websocket send, so the mic thread is never blocked on the network.
        # Gated on _turn_active so audio outside a turn (idle, persistent mode)
        # is dropped rather than streamed.
        if self._stop.is_set() or not self._turn_active.is_set():
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

    def finish(self) -> None:
        # Per-turn teardown: stop accepting audio, flush the queue, finalize so
        # the tail is transcribed, then close the socket entirely.
        self._turn_active.clear()
        self._drain()
        self._locked_send(lambda c: c.send_finalize())
        self._locked_send(lambda c: c.send_close_stream())
        self._teardown()

    def close(self) -> None:
        # Best-effort graceful close for a persistent socket (app shutdown).
        self._locked_send(lambda c: c.send_close_stream())
        self._teardown()

    # ── Persistent mode (socket stays open across turns; kept warm by KeepAlive)

    def begin_turn(self, *, on_partial, on_final, on_utterance_end, on_error) -> None:
        """Start a turn on a reused socket — opening it on the first turn (audio
        flows immediately, which is required before KeepAlive can hold it open)."""
        self.set_callbacks(on_partial=on_partial, on_final=on_final,
                           on_utterance_end=on_utterance_end, on_error=on_error)
        if not self.is_alive():
            self._stop.clear()
            self._open_socket(keepalive=True)
            _dbg("stt", f"Deepgram persistent socket open (model={self._model!r})")
        self._turn_active.set()

    def end_turn(self) -> None:
        """End a turn but KEEP the socket open: flush, Finalize (returns the
        final result without closing), then let KeepAlive hold it for next time."""
        self._turn_active.clear()
        self._drain()
        self._locked_send(lambda c: c.send_finalize())

    def is_alive(self) -> bool:
        return (
            self._conn is not None
            and not self._stop.is_set()
            and self._reader is not None
            and self._reader.is_alive()
        )

    def set_callbacks(self, *, on_partial, on_final, on_utterance_end, on_error) -> None:
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_utterance_end = on_utterance_end
        self._on_error = on_error

    # ── Socket / thread plumbing ──────────────────────────────────────────────

    def _open_socket(self, *, keepalive: bool) -> None:
        self._cm = self._make_cm()
        self._conn = self._cm.__enter__()
        self._reader = threading.Thread(target=self._read_loop, name="DeepgramRecv", daemon=True)
        self._reader.start()
        self._writer = threading.Thread(target=self._write_loop, name="DeepgramSend", daemon=True)
        self._writer.start()
        if keepalive:
            self._keepalive = threading.Thread(
                target=self._keepalive_loop, name="DeepgramKeepAlive", daemon=True)
            self._keepalive.start()

    def _locked_send(self, fn) -> bool:
        """Run one websocket send under the send lock so the writer, keepalive,
        and finalize/close threads never interleave frames. Returns True on
        success; surfaces an error and returns False on failure."""
        conn = self._conn
        if conn is None or self._stop.is_set():
            return False
        with self._send_lock:
            try:
                fn(conn)
                return True
            except Exception as exc:
                # The connection is broken (e.g. the network died / the socket was
                # closed by a keepalive timeout). Abandon it: set _stop so the
                # writer/keepalive/reader threads wind down and EVERY subsequent
                # send short-circuits at the guard above — otherwise each queued
                # frame + each keepalive tick logs its own "send failed", flooding
                # the console. is_alive() now returns False, so the next turn
                # reopens a fresh socket. Log only this first failure.
                self._fail(f"Deepgram send failed: {exc}")
                self._stop.set()
                return False

    def _drain(self, timeout: float = 2.0) -> None:
        """Block until the audio queue is flushed (writer caught up) or timeout,
        so Finalize is sent only after the turn's last audio reached the wire."""
        import time
        deadline = time.monotonic() + timeout
        while (not self._send_q.empty() and not self._stop.is_set()
               and time.monotonic() < deadline):
            time.sleep(0.02)
        if self._dropped:
            _dbg("stt", f"Deepgram send queue dropped {self._dropped} frame(s) — network lagged")

    def _write_loop(self) -> None:
        """Drain queued audio to the websocket until the socket is torn down."""
        while not self._stop.is_set():
            try:
                chunk = self._send_q.get(timeout=0.05)
            except queue.Empty:
                continue
            if self._stop.is_set():
                return
            if not self._locked_send(lambda c, b=chunk: c.send_media(b)):
                return

    def _keepalive_loop(self) -> None:
        """Ping every _KEEPALIVE_S while idle (between turns) to hold the socket
        open. Skips pinging while a turn is feeding audio (no need) and exits the
        moment the socket is torn down."""
        while not self._stop.wait(self._KEEPALIVE_S):
            if not self._turn_active.is_set():
                self._locked_send(lambda c: c.send_keep_alive())

    # ── Internals ─────────────────────────────────────────────────────────────

    def _connect_params(self) -> dict:
        """Query params for listen.v1.connect(). Split out (and SDK-free) so the
        keyterm gating is unit-testable without opening a real websocket."""
        params = dict(
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
        # Keyterm prompting is nova-3 only — sending it to another model would be
        # rejected, so gate on the model name. A list serializes to repeated
        # keyterm= query params (Deepgram's expected format).
        if self._keyterms and "nova-3" in (self._model or "").lower():
            params["keyterm"] = list(self._keyterms)
        return params

    def _make_cm(self):
        if self._connect_override is not None:
            return self._connect_override()
        from deepgram import DeepgramClient  # lazy — keeps SDK off the import path
        # Open the socket with the websockets library's OWN ping keepalive DISABLED
        # (transport_factory → ping_interval=None). On a laggy network the library
        # otherwise self-closes the socket with 1011 "keepalive ping timeout"
        # mid-utterance, losing the rest of the speech; we run our own app-level
        # KeepAlive (send_keep_alive) so Deepgram never idle-closes us. Defensive:
        # if this SDK build doesn't accept transport_factory, fall back to defaults
        # (library ping on) — streaming still works, just less resilient to lag.
        try:
            client = DeepgramClient(
                api_key=self._api_key, transport_factory=_pingless_ws_factory)
        except TypeError:
            client = DeepgramClient(api_key=self._api_key)
        return client.listen.v1.connect(**self._connect_params())

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
        for t in (self._writer, self._reader, self._keepalive):
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
