"""Live ElevenLabs v3 smoke test — REAL API call + audio playback.

Run:  uv run python tests/_live_elevenlabs_v3.py
Uses the real ELEVENLABS_API_KEY from .env. Speaks a short line WITH an audio
tag so we can hear whether v3 performs it. Prints the model that actually served
the request (v3 if the key's tier allows it, else the cached fallback).
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.tts_elevenlabs as e
from config.settings import config
from core.audio_pipeline import _DEFAULT_VOICE_ID, _EL_VOICES, _classify_elevenlabs_error

ready = threading.Event()
done = threading.Event()


def main() -> int:
    if not config.elevenlabs_api_key:
        print("NO KEY — ELEVENLABS_API_KEY missing from .env")
        return 2

    voice_id = _EL_VOICES.get(config.tts_voice, _DEFAULT_VOICE_ID)
    print(f"config model = {config.elevenlabs_model!r}  "
          f"stability={config.elevenlabs_stability} style={config.elevenlabs_style}")
    print(f"voice = {config.tts_voice!r} -> {voice_id}")

    text = "Hello Valentine. [chuckles] The new voice is live."
    try:
        e.say_elevenlabs(
            text,
            on_ready=lambda: ready.set(),
            on_done=lambda: done.set(),
            notify_fn=lambda fn: fn() if fn else None,
            voice_id=voice_id,
            api_key=config.elevenlabs_api_key,
            model=config.elevenlabs_model,
            stability=config.elevenlabs_stability,
            similarity_boost=config.elevenlabs_similarity_boost,
            style=config.elevenlabs_style,
            use_speaker_boost=config.elevenlabs_use_speaker_boost,
        )
    except Exception as exc:
        err = _classify_elevenlabs_error(exc)
        print(f"FAIL [{err.kind.value}] {err}")
        print(f"raw: {exc}")
        return 1

    served = e._RESOLVED_MODEL.get(config.elevenlabs_model, "?")
    print(f"OK — synthesis succeeded. model served = {served!r}  "
          f"ready={ready.is_set()} done={done.is_set()}")
    if served != "eleven_v3":
        print("NOTE: v3 not on this tier — fell back (tags stripped on this model).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
