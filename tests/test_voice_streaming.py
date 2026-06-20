"""Phase 2 — VoiceEngine streaming branch (turn assembly + batch fallback).

No mic, no network: a fake StreamingSttSession emits scripted events from a
background thread, and a no-op MicStreamer stands in for the real device. We
assert that VoiceEngine._run_streaming_stt assembles finals into one utterance,
falls back (returns False) when streaming can't start or errors before any text,
and reports a clean no-speech when the session connects but nothing is said.
"""

from __future__ import annotations

import threading
import time

from core.voice import VoiceEngine


# ── fakes ─────────────────────────────────────────────────────────────────────

class _FakeSession:
    """Emits a scripted event sequence on start(), one item at a time."""

    def __init__(self, events, *, raise_on_start=False):
        self._events = list(events)
        self._raise_on_start = raise_on_start
        self.finished = False
        self.closed = False
        self.fed: list[bytes] = []

    def begin_turn(self, **cbs):
        self.began = getattr(self, "began", 0) + 1
        self.start(**cbs)

    def end_turn(self):
        self.ended = getattr(self, "ended", 0) + 1

    def start(self, *, on_partial, on_final, on_utterance_end, on_error):
        self.started = getattr(self, "started", 0) + 1
        if self._raise_on_start:
            raise RuntimeError("connect refused")

        def _run():
            time.sleep(0.02)
            for kind, val in self._events:
                if kind == "partial":
                    on_partial(val)
                elif kind == "final":
                    on_final(val)
                elif kind == "err":
                    on_error(val)
                elif kind == "utt":
                    on_utterance_end()
                time.sleep(0.01)

        threading.Thread(target=_run, daemon=True).start()

    def feed(self, pcm16: bytes):
        self.fed.append(pcm16)

    def finish(self):
        self.finished = True

    def close(self):
        self.closed = True


class _NoopStreamer:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def _run(engine, session, *, timeout=1.0, phrase=2.0, streamer=None):
    got = []
    errs = []
    streamer = streamer or _NoopStreamer()
    handled = engine._run_streaming_stt(
        session, got.append, errs.append, timeout, phrase, mic_streamer=streamer,
    )
    return handled, got, errs, streamer


# ── tests ─────────────────────────────────────────────────────────────────────

def test_assembles_finals_and_calls_callback():
    eng = VoiceEngine()
    sess = _FakeSession([
        ("partial", "what's the"),
        ("final", "what's the weather"),
        ("final", "in kuwait"),
        ("utt", None),
    ])
    handled, got, errs, streamer = _run(eng, sess)
    assert handled is True
    assert got == ["what's the weather in kuwait"]
    assert errs == []
    assert sess.finished and streamer.started and streamer.stopped


def test_uses_last_partial_when_no_final_arrives():
    eng = VoiceEngine()
    sess = _FakeSession([("partial", "hello there"), ("utt", None)])
    handled, got, errs, _ = _run(eng, sess)
    assert handled is True
    assert got == ["hello there"]


def test_start_failure_falls_back_to_batch():
    eng = VoiceEngine()
    sess = _FakeSession([], raise_on_start=True)
    handled, got, errs, _ = _run(eng, sess)
    assert handled is False          # caller will run the Google batch path
    assert got == [] and errs == []
    assert sess.closed


def test_session_error_before_text_falls_back():
    eng = VoiceEngine()
    sess = _FakeSession([("err", "stream dropped"), ("utt", None)])
    handled, got, errs, _ = _run(eng, sess)
    assert handled is False          # fall back to batch for this turn
    assert got == []


def test_no_speech_reports_clean_error_not_fallback():
    eng = VoiceEngine()
    sess = _FakeSession([])          # connects, says nothing
    handled, got, errs, streamer = _run(eng, sess, timeout=0.2, phrase=0.2)
    assert handled is True           # handled — no batch retry on genuine silence
    assert got == []
    assert errs and "No speech" in errs[0]
    assert sess.finished and streamer.stopped


def test_error_after_text_still_delivers_text():
    eng = VoiceEngine()
    sess = _FakeSession([("final", "turn on the lights"), ("err", "late drop"), ("utt", None)])
    handled, got, errs, _ = _run(eng, sess)
    assert handled is True
    assert got == ["turn on the lights"]


# ── persistent mode ───────────────────────────────────────────────────────────

def test_persistent_uses_begin_end_turn_and_keeps_socket_warm():
    eng = VoiceEngine()
    sess = _FakeSession([("final", "open chrome"), ("utt", None)])
    got = []
    handled = eng._run_streaming_stt(
        sess, got.append, lambda m: None, 1.0, 2.0,
        persistent=True, mic_streamer=_NoopStreamer(),
    )
    assert handled is True and got == ["open chrome"]
    assert getattr(sess, "began", 0) == 1 and getattr(sess, "ended", 0) == 1
    assert getattr(sess, "finished", False) is False   # finish() not used in persistent
    assert sess.closed is False                        # socket stays warm
