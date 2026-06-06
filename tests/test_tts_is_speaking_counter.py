"""R3-4: TtsEngine.is_speaking must be a counter, not a binary Event.

Overlapping say() calls serialise on the playback lock, but is_speaking has to
stay True for the WHOLE span — clip one's teardown must not report "not speaking"
while clip two is still playing (that opens the mic mid-speech → feedback loop).

These tests force the tier-3 (local) path by clearing the cloud keys and stub
_say_local with controllable barriers so we can hold each clip open and inspect
is_speaking at the exact overlap window.
"""

from __future__ import annotations

import threading
import time

import pytest

import core.audio_pipeline as ap


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> ap.TtsEngine:
    eng = ap.TtsEngine()
    # No cloud keys → _play falls straight through to _say_local (tier 3).
    monkeypatch.setattr(ap.config, "elevenlabs_api_key", "", raising=False)
    monkeypatch.setattr(ap.config, "gemini_api_key", "", raising=False)
    return eng


def _wait_idle(engine: ap.TtsEngine, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while engine.is_speaking and time.monotonic() < deadline:
        time.sleep(0.01)


def test_is_speaking_false_at_rest(engine: ap.TtsEngine) -> None:
    assert engine.is_speaking is False


def test_overlapping_say_keeps_is_speaking_true(engine: ap.TtsEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    release_one = threading.Event()
    release_two = threading.Event()
    started_one = threading.Event()
    started_two = threading.Event()

    def fake_local(text, on_ready, on_done):
        if text == "one":
            started_one.set()
            if on_ready:
                on_ready()
            release_one.wait(3.0)
        else:
            started_two.set()
            if on_ready:
                on_ready()
            release_two.wait(3.0)
        if on_done:
            on_done()

    monkeypatch.setattr(engine, "_say_local", fake_local)

    engine.say("one")
    engine.say("two")  # queues behind clip one on the playback lock

    assert started_one.wait(3.0)
    assert engine.is_speaking is True

    # Finish clip one; clip two now acquires the lock and starts playing.
    release_one.set()
    assert started_two.wait(3.0)

    # THE BUG-CATCH: clip one is done, clip two is still playing. A binary Event
    # would read False here (clip one cleared it); the counter must read True.
    assert engine.is_speaking is True

    release_two.set()
    _wait_idle(engine)
    assert engine.is_speaking is False


def test_count_returns_to_zero_on_provider_exception(engine: ap.TtsEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    """The finally must decrement even when the tier raises — otherwise a single
    failed clip would wedge is_speaking True forever and the mic never reopens."""
    def boom(text, on_ready, on_done):
        raise RuntimeError("tts blew up")

    monkeypatch.setattr(engine, "_say_local", boom)
    engine.say("kaboom")
    _wait_idle(engine)
    assert engine.is_speaking is False
