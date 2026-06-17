"""ElevenLabs eleven_v3 expressiveness upgrade.

Covers the v3 migration in core/tts_elevenlabs:
  - model_id is configurable and forwarded on stream + convert + probe paths
  - voice_settings (stability / similarity_boost / style / use_speaker_boost)
    are built from the passed values and forwarded
  - audio tags ([chuckles] …) are kept on eleven_v3, stripped on tag-blind
    fallback models
  - a model-unavailable error walks the fallback chain (v3 → turbo → flash);
    a quota/auth error fails fast WITHOUT trying other models
  - the first working model is cached for the session

No network, no audio — the SDK client + playback are faked.
"""

from __future__ import annotations

import types as pytypes

import pytest

import core.tts_elevenlabs as e


@pytest.fixture(autouse=True)
def _clear_model_cache():
    """Each test starts with an empty session model cache."""
    e._RESOLVED_MODEL.clear()
    yield
    e._RESOLVED_MODEL.clear()


# ── Fakes ─────────────────────────────────────────────────────────────────────

class _FakeVoiceSettings:
    """Captures the kwargs say_elevenlabs builds VoiceSettings from."""
    def __init__(self, **kw):
        self.kw = kw


def _patch_vs(monkeypatch):
    """Force a known VoiceSettings class regardless of SDK presence."""
    monkeypatch.setattr(e, "_voice_settings_cls", lambda _el: _FakeVoiceSettings)


def _patch_client(monkeypatch, tts):
    """Install a fake ElevenLabs SDK whose .text_to_speech is *tts*."""
    class _FakeClient:
        def __init__(self, **kw):
            self.text_to_speech = tts
    monkeypatch.setattr(e, "_el", lambda: pytypes.SimpleNamespace(ElevenLabs=_FakeClient))


# ── helpers ─────────────────────────────────────────────────────────────────

def test_strip_audio_tags_removes_brackets():
    assert e._strip_audio_tags("Hello [chuckles] there") == "Hello there"
    assert e._strip_audio_tags("[sighs] done") == "done"
    assert e._strip_audio_tags("no tags here") == "no tags here"


def test_v3_stability_levels_documented():
    assert e._V3_STABILITY_LEVELS == (0.0, 0.5, 1.0)


def test_model_candidates_order_and_dedup():
    assert e._model_candidates("eleven_v3") == [
        "eleven_v3", "eleven_turbo_v2_5", "eleven_flash_v2_5",
    ]
    # configured model already in fallbacks → no duplicate
    assert e._model_candidates("eleven_turbo_v2_5") == [
        "eleven_turbo_v2_5", "eleven_flash_v2_5",
    ]


def test_model_unavailable_classifier():
    assert e._is_model_unavailable_error(Exception("status_code: 403 model_access_denied"))
    assert e._is_model_unavailable_error(Exception("model not found"))
    assert not e._is_model_unavailable_error(Exception("quota_exceeded: credits required"))
    assert not e._is_model_unavailable_error(Exception("status_code: 401 unauthorized"))


# ── say: model + voice_settings forwarding (stream path) ─────────────────────

def test_say_forwards_model_and_voice_settings(monkeypatch):
    captured: dict = {}

    class _FakeTTS:
        def stream(self, **kw):
            captured.update(kw)
            return iter([b"\x00\x01"])

    _patch_client(monkeypatch, _FakeTTS())
    _patch_vs(monkeypatch)
    monkeypatch.setattr(e, "play_mp3_stream", lambda *a, **k: None)

    e.say_elevenlabs(
        "hi", None, None, lambda fn: None,
        voice_id="v", api_key="k",
        model="eleven_v3", stability=0.0, similarity_boost=0.75,
        style=0.6, use_speaker_boost=True,
    )

    assert captured["model_id"] == "eleven_v3"
    assert captured["request_options"] == {"max_retries": 0, "timeout_in_seconds": 15}
    vs = captured["voice_settings"]
    assert isinstance(vs, _FakeVoiceSettings)
    assert vs.kw == {
        "stability": 0.0, "similarity_boost": 0.75,
        "style": 0.6, "use_speaker_boost": True,
    }


def test_say_keeps_tags_on_v3(monkeypatch):
    captured: dict = {}

    class _FakeTTS:
        def stream(self, **kw):
            captured.update(kw)
            return iter([b"\x00"])

    _patch_client(monkeypatch, _FakeTTS())
    _patch_vs(monkeypatch)
    monkeypatch.setattr(e, "play_mp3_stream", lambda *a, **k: None)

    e.say_elevenlabs("Hello [chuckles] there", None, None, lambda fn: None,
                     voice_id="v", api_key="k", model="eleven_v3")
    assert captured["text"] == "Hello [chuckles] there"


def test_say_strips_tags_on_non_v3_model(monkeypatch):
    captured: dict = {}

    class _FakeTTS:
        def stream(self, **kw):
            captured.update(kw)
            return iter([b"\x00"])

    _patch_client(monkeypatch, _FakeTTS())
    _patch_vs(monkeypatch)
    monkeypatch.setattr(e, "play_mp3_stream", lambda *a, **k: None)

    e.say_elevenlabs("Hello [chuckles] there", None, None, lambda fn: None,
                     voice_id="v", api_key="k", model="eleven_turbo_v2_5")
    assert captured["text"] == "Hello there"
    assert captured["model_id"] == "eleven_turbo_v2_5"


# ── say: model fallback chain ────────────────────────────────────────────────

def test_say_falls_back_when_v3_unavailable(monkeypatch):
    attempts: list[str] = []

    class _FakeTTS:
        def stream(self, **kw):
            attempts.append(kw["model_id"])
            def gen():
                if kw["model_id"] == "eleven_v3":
                    raise RuntimeError("status_code: 403 model_access_denied")
                yield b"\x00"
            return gen()

    _patch_client(monkeypatch, _FakeTTS())
    _patch_vs(monkeypatch)
    monkeypatch.setattr(e, "play_mp3_stream", lambda *a, **k: None)

    e.say_elevenlabs("hello [sighs]", None, None, lambda fn: None,
                     voice_id="v", api_key="k", model="eleven_v3")

    # v3 tried first (failed), then turbo succeeded
    assert attempts == ["eleven_v3", "eleven_turbo_v2_5"]
    # session cache now points at the working model
    assert e._RESOLVED_MODEL["eleven_v3"] == "eleven_turbo_v2_5"


def test_quota_error_fails_fast_no_fallback(monkeypatch):
    attempts: list[str] = []

    class _FakeTTS:
        def stream(self, **kw):
            attempts.append(kw["model_id"])
            def gen():
                raise RuntimeError("quota_exceeded: credits required")
                yield  # pragma: no cover
            return gen()

    _patch_client(monkeypatch, _FakeTTS())
    _patch_vs(monkeypatch)
    monkeypatch.setattr(e, "play_mp3_stream", lambda *a, **k: None)

    with pytest.raises(RuntimeError, match="quota_exceeded"):
        e.say_elevenlabs("hi", None, None, lambda fn: None,
                         voice_id="v", api_key="k", model="eleven_v3")
    # only the configured model attempted — no wasteful fallback walk on quota
    assert attempts == ["eleven_v3"]


def test_session_cache_skips_dead_model_on_next_call(monkeypatch):
    attempts: list[str] = []

    class _FakeTTS:
        def stream(self, **kw):
            attempts.append(kw["model_id"])
            def gen():
                if kw["model_id"] == "eleven_v3":
                    raise RuntimeError("model not available on this tier")
                yield b"\x00"
            return gen()

    _patch_client(monkeypatch, _FakeTTS())
    _patch_vs(monkeypatch)
    monkeypatch.setattr(e, "play_mp3_stream", lambda *a, **k: None)

    for _ in range(2):
        e.say_elevenlabs("hi", None, None, lambda fn: None,
                         voice_id="v", api_key="k", model="eleven_v3")

    # 1st call: v3 (fail) + turbo (ok). 2nd call: cached turbo only — v3 not re-probed.
    assert attempts == ["eleven_v3", "eleven_turbo_v2_5", "eleven_turbo_v2_5"]


# ── convert path (no .stream attr) ───────────────────────────────────────────

def test_say_convert_path_forwards_model_and_settings(monkeypatch):
    captured: dict = {}

    class _FakeTTS:
        # no `stream` → convert path
        def convert(self, **kw):
            captured.update(kw)
            return [b"\x00"]

    _patch_client(monkeypatch, _FakeTTS())
    _patch_vs(monkeypatch)
    monkeypatch.setattr(e, "play_mp3_bytes", lambda *a, **k: None)

    e.say_elevenlabs("hi", None, None, lambda fn: None,
                     voice_id="v", api_key="k", model="eleven_v3", style=0.6)
    assert captured["model_id"] == "eleven_v3"
    assert captured["request_options"]["max_retries"] == 0
    assert isinstance(captured["voice_settings"], _FakeVoiceSettings)


# ── voice_settings builder degrades gracefully ───────────────────────────────

def test_build_voice_settings_falls_back_to_core_kwargs():
    class _OnlyCore:
        def __init__(self, **kw):
            if set(kw) - {"stability", "similarity_boost"}:
                raise TypeError("unexpected kwarg")
            self.kw = kw

    vs = e._build_voice_settings(_OnlyCore, 0.0, 0.75, 0.6, True)
    assert vs.kw == {"stability": 0.0, "similarity_boost": 0.75}


def test_build_voice_settings_none_when_no_cls():
    assert e._build_voice_settings(None, 0.0, 0.75, 0.6, True) is None


# ── probe walks fallback + forwards model ────────────────────────────────────

def test_probe_forwards_model_and_falls_back(monkeypatch):
    attempts: list[str] = []

    class _FakeTTS:
        def convert(self, **kw):
            attempts.append(kw["model_id"])
            if kw["model_id"] == "eleven_v3":
                raise RuntimeError("status_code: 403 model_access_denied")
            return [b"\x00"]

    _patch_client(monkeypatch, _FakeTTS())
    _patch_vs(monkeypatch)

    e.probe_voice("male-british", api_key="k",
                  el_voices={"male-british": "vid"}, default_id="d",
                  model="eleven_v3")
    assert attempts == ["eleven_v3", "eleven_turbo_v2_5"]
