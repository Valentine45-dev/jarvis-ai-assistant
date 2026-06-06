"""R3-21: TtsEngine uses ONE worker draining a bounded queue, not a daemon
thread per say(). A burst of utterances caps the backlog (dropping the stalest)
instead of piling up unbounded threads.
"""

from __future__ import annotations

import threading
import time

import pytest

import core.audio_pipeline as ap


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> ap.TtsEngine:
    eng = ap.TtsEngine()
    monkeypatch.setattr(ap.config, "elevenlabs_api_key", "", raising=False)
    monkeypatch.setattr(ap.config, "gemini_api_key", "", raising=False)
    return eng


def test_worker_not_started_until_first_say(engine: ap.TtsEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    assert engine._worker_started is False
    monkeypatch.setattr(engine, "_play", lambda *a: None)
    engine.say("hi")
    assert engine._worker_started is True


def test_single_worker_processes_serially(engine: ap.TtsEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    seen_threads: list[str] = []
    processed: list[str] = []

    def fake_play(text, on_ready, on_done):
        seen_threads.append(threading.current_thread().name)
        processed.append(text)
        if on_done:
            on_done()

    monkeypatch.setattr(engine, "_play", fake_play)
    for i in range(5):
        engine.say(f"line{i}")

    deadline = time.monotonic() + 3.0
    while len(processed) < 5 and time.monotonic() < deadline:
        time.sleep(0.01)

    assert processed == [f"line{i}" for i in range(5)]   # FIFO order
    assert set(seen_threads) == {"TtsWorker"}            # exactly one worker thread
    # is_speaking returns to False once the queue drains.
    deadline = time.monotonic() + 2.0
    while engine.is_speaking and time.monotonic() < deadline:
        time.sleep(0.01)
    assert engine.is_speaking is False


def test_bounded_queue_drops_oldest(engine: ap.TtsEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    gate = threading.Event()

    def fake_play(text, on_ready, on_done):
        gate.wait(5.0)            # hold the worker so the queue fills behind it
        if on_done:
            on_done()

    monkeypatch.setattr(engine, "_play", fake_play)

    engine.say("playing")         # worker dequeues this and blocks on the gate
    time.sleep(0.1)

    n = engine._QUEUE_MAX + 5
    fired: list[int] = []
    for i in range(n):
        engine.say(f"q{i}", on_done=lambda i=i: fired.append(i))

    # The queue is capped; the earliest-queued lines were dropped (on_done fired).
    assert engine._queue.qsize() <= engine._QUEUE_MAX
    assert len(fired) >= n - engine._QUEUE_MAX
    assert fired == list(range(len(fired)))   # the OLDEST were the ones dropped

    gate.set()                    # let everything drain
    deadline = time.monotonic() + 3.0
    while not engine._queue.empty() and time.monotonic() < deadline:
        time.sleep(0.01)


def test_count_returns_to_zero_after_drops(engine: ap.TtsEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    gate = threading.Event()
    monkeypatch.setattr(engine, "_play", lambda *a: gate.wait(5.0))
    engine.say("playing")
    time.sleep(0.1)
    for i in range(engine._QUEUE_MAX + 5):
        engine.say(f"q{i}")
    gate.set()
    deadline = time.monotonic() + 3.0
    while engine.is_speaking and time.monotonic() < deadline:
        time.sleep(0.01)
    assert engine.is_speaking is False     # drops + plays all balanced the counter
