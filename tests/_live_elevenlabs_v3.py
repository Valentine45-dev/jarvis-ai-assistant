"""Live ElevenLabs v3 smoke test — REAL API call + audio playback.

Run:  uv run python tests/_live_elevenlabs_v3.py
Uses the real ELEVENLABS_API_KEY from .env. Speaks a short line containing a
SUPPORTED v3 audio tag ([laughs]) embedded in a real sentence so the model has
context to perform it. Saves the audio to tests/_v3_tag_check.mp3 so you can
replay it, prints the model that actually served the request, and plays it.
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

_OUT = Path(__file__).resolve().parent / "_v3_tag_check.mp3"

# A SUPPORTED tag ([laughs]) with surrounding words so v3 has context to act on.
TEXT = "Well, that actually worked on the first try. [laughs] Not bad at all, Valentine."


def main() -> int:
    if not config.elevenlabs_api_key:
        print("NO KEY — ELEVENLABS_API_KEY missing from .env")
        return 2

    voice_id = _EL_VOICES.get(config.tts_voice, _DEFAULT_VOICE_ID)
    print(f"config model = {config.elevenlabs_model!r}  "
          f"stability={config.elevenlabs_stability} style={config.elevenlabs_style}")
    print(f"voice = {config.tts_voice!r} -> {voice_id}")
    print(f"text  = {TEXT!r}")

    # Tee the streamed chunks to a file so the clip is replayable, then hand the
    # same bytes to the real MCI playback.
    real_stream = e.play_mp3_stream

    def _tee(chunks, on_ready, on_done, notify_fn):
        buf = bytearray()

        def _gen():
            for c in chunks:
                if c:
                    buf.extend(c)
                yield c
        try:
            real_stream(_gen(), on_ready, on_done, notify_fn)
        finally:
            _OUT.write_bytes(bytes(buf))

    e.play_mp3_stream = _tee  # type: ignore[assignment]
    try:
        e.say_elevenlabs(
            TEXT,
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
    finally:
        e.play_mp3_stream = real_stream  # type: ignore[assignment]

    served = e._RESOLVED_MODEL.get(config.elevenlabs_model, "?")
    size = _OUT.stat().st_size if _OUT.exists() else 0
    print(f"OK — synthesis succeeded. model served = {served!r}  "
          f"ready={ready.is_set()} done={done.is_set()}  bytes={size}")
    print(f"saved clip -> {_OUT}  (replay it and listen for an actual laugh)")
    if served != "eleven_v3":
        print("NOTE: v3 not on this tier — fell back; tags are stripped on this model.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
