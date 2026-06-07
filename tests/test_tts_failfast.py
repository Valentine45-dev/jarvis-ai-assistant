"""TTS providers must fail FAST on quota/429 — no SDK retry/backoff.

Both cloud tiers already get session-locked after one quota error (audio_pipeline),
but the *first* hit per provider per session used to eat the SDK's exponential
backoff. These tests assert the wiring that makes that first hit cheap: Gemini
client built with one attempt + a timeout; ElevenLabs calls passed
max_retries=0 + a timeout. No network, no audio.
"""

from __future__ import annotations

import types as pytypes

import core.tts_gemini as g
import core.tts_elevenlabs as e


# ── Gemini: one-attempt + timeout HttpOptions on the client ──────────────────

def test_gemini_fast_http_options_one_attempt_and_timeout() -> None:
    from google.genai import types
    opts = g._fast_http_options(types)
    assert opts.timeout == g._GEMINI_TIMEOUT_MS
    assert opts.retry_options is not None
    assert opts.retry_options.attempts == 1          # 1 attempt == no retries


def test_gemini_fast_client_passes_http_options() -> None:
    from google.genai import types
    captured: dict = {}

    class _FakeGenai:
        @staticmethod
        def Client(**kwargs):
            captured.update(kwargs)
            return object()

    g._fast_client(_FakeGenai, types, "key")
    assert "http_options" in captured
    assert captured["http_options"].retry_options.attempts == 1
    assert captured["http_options"].timeout == g._GEMINI_TIMEOUT_MS


def test_gemini_fast_http_options_degrades_without_retry_cls() -> None:
    # A future SDK lacking HttpRetryOptions must still yield a timeout-only opts.
    class _FakeHttpOptions:
        def __init__(self, **kw):
            self.kw = kw

    fake_types = pytypes.SimpleNamespace(HttpOptions=_FakeHttpOptions)  # no HttpRetryOptions
    opts = g._fast_http_options(fake_types)
    assert opts.kw == {"timeout": g._GEMINI_TIMEOUT_MS}


def test_gemini_fast_client_falls_back_to_plain_on_bad_opts() -> None:
    # If Client rejects http_options, we still get a plain client (never crash).
    calls: list[dict] = []

    class _FakeGenai:
        @staticmethod
        def Client(**kwargs):
            calls.append(kwargs)
            if "http_options" in kwargs:
                raise TypeError("unexpected kwarg http_options")
            return "plain"

    from google.genai import types
    out = g._fast_client(_FakeGenai, types, "key")
    assert out == "plain"
    assert any("http_options" in c for c in calls)     # tried fast first
    assert calls[-1] == {"api_key": "key"}             # then plain fallback


# ── ElevenLabs: no-retry + timeout request_options on every call ─────────────

def test_el_request_options_constant() -> None:
    assert e._EL_REQUEST_OPTIONS == {"max_retries": 0, "timeout_in_seconds": 15}


def test_say_elevenlabs_forwards_no_retry(monkeypatch) -> None:
    captured: dict = {}

    class _FakeTTS:
        def stream(self, **kw):
            captured.update(kw)
            return []

    class _FakeClient:
        def __init__(self, **kw):
            self.text_to_speech = _FakeTTS()

    monkeypatch.setattr(e, "_el", lambda: pytypes.SimpleNamespace(ElevenLabs=_FakeClient))
    monkeypatch.setattr(e, "play_mp3_stream", lambda *a, **k: None)

    e.say_elevenlabs("hi", None, None, lambda fn: None, voice_id="v", api_key="k")
    assert captured["request_options"] == {"max_retries": 0, "timeout_in_seconds": 15}


def test_say_elevenlabs_convert_path_forwards_no_retry(monkeypatch) -> None:
    captured: dict = {}

    class _FakeTTS:
        # no `stream` attr → say_elevenlabs uses the convert() path
        def convert(self, **kw):
            captured.update(kw)
            return [b""]

    class _FakeClient:
        def __init__(self, **kw):
            self.text_to_speech = _FakeTTS()

    monkeypatch.setattr(e, "_el", lambda: pytypes.SimpleNamespace(ElevenLabs=_FakeClient))
    monkeypatch.setattr(e, "play_mp3_bytes", lambda *a, **k: None)

    e.say_elevenlabs("hi", None, None, lambda fn: None, voice_id="v", api_key="k")
    assert captured["request_options"]["max_retries"] == 0
