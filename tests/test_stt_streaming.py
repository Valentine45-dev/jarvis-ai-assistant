"""Streaming STT foundation (Phase 1) — factory selection + Deepgram event map.

No network: the Deepgram websocket is replaced by a fake connection that yields
scripted typed-ish events. Asserts interim->on_partial, is_final->on_final,
UtteranceEnd->on_utterance_end, and that finish() flushes + closes the stream.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from core.stt.deepgram import DeepgramSttSession
from core.stt.factory import build_keyterms, create_stt_session


# ── fakes ─────────────────────────────────────────────────────────────────────

def _results(text: str, *, is_final: bool):
    # Results carries channel.alternatives[0].transcript + is_final, no last_word_end.
    alt = SimpleNamespace(transcript=text)
    chan = SimpleNamespace(alternatives=[alt])
    return SimpleNamespace(is_final=is_final, speech_final=is_final, channel=chan)


def _utterance_end():
    # UtteranceEnd is identified by its unique last_word_end field.
    return SimpleNamespace(type="UtteranceEnd", channel=[0], last_word_end=1.23)


class _FakeConn:
    def __init__(self, events):
        self._events = list(events)
        self.sent: list[bytes] = []
        self.finalized = False
        self.closed = False

    def recv(self):
        return self._events.pop(0) if self._events else None  # None ends the loop

    def send_media(self, b: bytes):
        self.sent.append(b)

    def send_finalize(self):
        self.finalized = True

    def send_close_stream(self):
        self.closed = True


class _FakeCM:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *a):
        return False


def _drain(counts_getter, expected, timeout=2.0):
    deadline = time.time() + timeout
    while counts_getter() < expected and time.time() < deadline:
        time.sleep(0.01)


# ── factory ─────────────────────────────────────────────────────────────────

def test_factory_returns_none_for_google():
    cfg = SimpleNamespace(stt_provider="google", deepgram_api_key="k")
    assert create_stt_session(cfg) is None


def test_factory_returns_none_when_key_missing():
    cfg = SimpleNamespace(stt_provider="deepgram", deepgram_api_key="")
    assert create_stt_session(cfg) is None


def test_keyterms_include_wake_word_user_name_and_base():
    cfg = SimpleNamespace(wake_word="Jarvis", user_name="Valentine", stt_keyterms=[])
    terms = build_keyterms(cfg)
    assert terms[0] == "Jarvis" and terms[1] == "Valentine"
    assert "Chrome" in terms and "Firefox" in terms          # built-in base
    assert "volume" not in [t.lower() for t in terms]         # common words excluded


def test_keyterms_append_user_extras_and_dedupe_case_insensitively():
    cfg = SimpleNamespace(
        wake_word="jarvis", user_name="", stt_keyterms=["Kuwait", "chrome", "Mosul"],
    )
    terms = build_keyterms(cfg)
    assert "Kuwait" in terms and "Mosul" in terms             # user extras kept
    # "chrome" dups the base "Chrome" — only one survives (first spelling wins).
    assert sum(1 for t in terms if t.lower() == "chrome") == 1
    assert "Chrome" in terms


def test_keyterms_tolerate_missing_config_fields():
    # The factory may see a bare config; build_keyterms must not raise.
    terms = build_keyterms(SimpleNamespace())
    assert "JARVIS" in terms


def test_connect_params_includes_keyterm_only_for_nova3():
    nova = DeepgramSttSession(api_key="x", model="nova-3", keyterms=["Jarvis", "Mosul"])
    assert nova._connect_params()["keyterm"] == ["Jarvis", "Mosul"]

    other = DeepgramSttSession(api_key="x", model="nova-2", keyterms=["Jarvis"])
    assert "keyterm" not in other._connect_params()           # nova-3 only

    empty = DeepgramSttSession(api_key="x", model="nova-3", keyterms=[])
    assert "keyterm" not in empty._connect_params()           # nothing to send


def test_factory_builds_deepgram_session():
    cfg = SimpleNamespace(
        stt_provider="deepgram", deepgram_api_key="k", deepgram_model="nova-3",
        stt_language="en-US", stt_endpointing_ms=300, stt_utterance_end_ms=1000,
    )
    sess = create_stt_session(cfg)
    assert isinstance(sess, DeepgramSttSession)


# ── Deepgram event mapping ────────────────────────────────────────────────────

def test_dispatch_maps_events_in_order():
    partials, finals, ends, errors = [], [], [], []
    events = [
        _results("what's the", is_final=False),
        _results("what's the weather", is_final=False),
        _results("what's the weather in kuwait", is_final=True),
        _utterance_end(),
    ]
    conn = _FakeConn(events)
    sess = DeepgramSttSession(api_key="x", _connect=lambda: _FakeCM(conn))
    sess.start(
        on_partial=partials.append,
        on_final=finals.append,
        on_utterance_end=lambda: ends.append(True),
        on_error=errors.append,
    )
    _drain(lambda: len(partials) + len(finals) + len(ends), 4)
    sess.finish()

    assert partials == ["what's the", "what's the weather"]
    assert finals == ["what's the weather in kuwait"]
    assert ends == [True]
    assert errors == []
    assert conn.finalized and conn.closed


def test_blank_transcripts_are_dropped():
    partials, finals = [], []
    conn = _FakeConn([_results("   ", is_final=False), _results("", is_final=True)])
    sess = DeepgramSttSession(api_key="x", _connect=lambda: _FakeCM(conn))
    sess.start(on_partial=partials.append, on_final=finals.append,
               on_utterance_end=lambda: None, on_error=lambda m: None)
    time.sleep(0.1)
    sess.finish()
    assert partials == []
    assert finals == []


def test_feed_forwards_audio_then_stops_after_finish():
    conn = _FakeConn([])
    sess = DeepgramSttSession(api_key="x", _connect=lambda: _FakeCM(conn))
    sess.start(on_partial=lambda t: None, on_final=lambda t: None,
               on_utterance_end=lambda: None, on_error=lambda m: None)
    sess.feed(b"\x01\x02")
    sess.feed(b"\x03\x04")
    sess.finish()
    sess.feed(b"\x05\x06")  # after finish → ignored
    assert conn.sent == [b"\x01\x02", b"\x03\x04"]
