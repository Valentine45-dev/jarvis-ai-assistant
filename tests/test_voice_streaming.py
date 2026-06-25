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


class _StaleEndSession:
    """Persistent-socket failure mode: a leftover UtteranceEnd from the PRIOR turn
    arrives FIRST (before any speech), then the real utterance lands after a gap
    longer than the capture loop's reaction time."""

    def __init__(self):
        self.fed: list[bytes] = []

    def begin_turn(self, **cbs):
        self.start(**cbs)

    def end_turn(self):
        pass

    def start(self, *, on_partial, on_final, on_utterance_end, on_error):
        def _run():
            time.sleep(0.02)
            on_utterance_end()        # ← stale end from the previous turn (no speech yet)
            time.sleep(0.20)          # gap > loop poll, so an unguarded turn would end here
            on_partial("open")
            on_final("open chrome")
            time.sleep(0.02)
            on_utterance_end()        # ← the real end
        threading.Thread(target=_run, daemon=True).start()

    def feed(self, pcm16: bytes):
        self.fed.append(pcm16)

    def finish(self):
        pass

    def close(self):
        pass


def test_persistent_ignores_stale_utterance_end_before_speech():
    # The stale UtteranceEnd must NOT end the turn (it arrives before any speech);
    # the real utterance is then captured. Without the got_speech guard the stale
    # end would close the mic immediately and `got` would be empty.
    eng = VoiceEngine()
    sess = _StaleEndSession()
    got: list[str] = []
    errs: list[str] = []
    handled = eng._run_streaming_stt(
        sess, got.append, errs.append, 1.0, 2.0,
        persistent=True, mic_streamer=_NoopStreamer(),
    )
    assert handled is True
    assert got == ["open chrome"]   # stale end ignored, real speech captured


# ── re-entry guard ─────────────────────────────────────────────────────────────

def test_second_listen_ignored_while_capture_in_flight():
    """A second listen() while one capture is live must be a no-op — otherwise two
    mic streamers feed the one warm Deepgram socket and audio gets captured twice
    (the 'Alright. Bye.' double-capture). The guard is a dedicated flag, NOT the
    HUD-owned _listening event (which the state machine may clear mid-capture)."""
    eng = VoiceEngine()
    started = threading.Event()
    release = threading.Event()
    spawned = []

    def _fake_thread(callback, on_error, timeout, phrase):
        spawned.append(1)
        started.set()
        release.wait(1.0)            # hold the "capture" open
        with eng._capture_lock:      # mirror the real finally: clear the guard
            eng._capture_active = False

    eng._listen_thread = _fake_thread

    eng.listen(lambda t: None)       # first capture opens
    assert started.wait(1.0)
    eng.listen(lambda t: None)       # second call while first is live → ignored

    # Even if the HUD clears the icon flag mid-capture, re-entry is still blocked.
    eng.clear_listening()
    eng.listen(lambda t: None)

    release.set()
    time.sleep(0.05)
    assert spawned == [1]            # only the first listen() ever spawned a thread


def test_listen_runs_again_after_previous_capture_finishes():
    """Once a capture completes and clears the guard, the next listen() proceeds."""
    eng = VoiceEngine()
    spawned = []

    def _fake_thread(callback, on_error, timeout, phrase):
        spawned.append(1)
        with eng._capture_lock:      # complete immediately, clearing the guard
            eng._capture_active = False

    eng._listen_thread = _fake_thread

    eng.listen(lambda t: None)
    time.sleep(0.02)
    eng.listen(lambda t: None)
    time.sleep(0.02)
    assert spawned == [1, 1]         # both proceeded — guard released between them
