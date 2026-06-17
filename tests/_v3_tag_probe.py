"""ElevenLabs v3 audio-tag PROBE — generates labeled .mp3 clips to judge by ear.

Two modes (REAL API calls, costs credits):

  uv run python tests/_v3_tag_probe.py voices
      Same [laughs] line synthesized across several voices. Tells us whether the
      blocker is the VOICE (some laugh, some don't) or our REQUEST (none laugh).

  uv run python tests/_v3_tag_probe.py tags [voice_key]
      One clip per candidate tag, using voice_key (default = config.tts_voice).
      Listen and note which tags actually render. Only the ear-verified ones go
      into CLAUDE.md.

Output: tests/tag_audio/*.mp3  (filenames say exactly what each clip is)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.tts_elevenlabs as e
from config.settings import config
from core.audio_pipeline import _DEFAULT_VOICE_ID, _EL_VOICES

OUT = Path(__file__).resolve().parent / "tag_audio"
OUT.mkdir(exist_ok=True)

# Voices from our profile map most likely to differ on expressiveness.
# George (current) is a deep narration voice — the prime "won't laugh" suspect.
_VOICE_PROBE = ["male-british", "male-gravelly", "male-casual", "male-australian", "male-smooth"]

# Candidate tags we'd actually use in JARVIS, each in a sentence WITH context.
_TAG_CLIPS: list[tuple[str, str]] = [
    ("laughs",        "Well, that worked on the first try. [laughs] Not bad at all."),
    ("laughs_softly", "Oh, you're asking me that again? [laughs softly] Sure, here it is."),
    ("sighs",         "[sighs] Fine, rebooting the whole thing one more time."),
    ("exhales",       "[exhales] Okay. Let's take this from the top."),
    ("whispers",      "Don't tell anyone, but [whispers] this one's my favorite trick."),
    ("sarcastic",     "[sarcastic] Oh, fantastic, another meeting invite. Just what I needed."),
    ("curious",       "[curious] Now that's interesting — I didn't expect that result."),
    ("gasps",         "[gasps] You actually closed every single tab? Bold move."),
    ("clears_throat", "[clears throat] Right then. Here is the status report you asked for."),
    ("excited",       "[excited] The build passed — every test is green!"),
]


def _client():
    el = e._el()
    client = el.ElevenLabs(api_key=config.elevenlabs_api_key)
    vs = e._build_voice_settings(
        e._voice_settings_cls(el),
        config.elevenlabs_stability, config.elevenlabs_similarity_boost,
        config.elevenlabs_style, config.elevenlabs_use_speaker_boost,
    )
    return client, vs


def _synth(client, vs, voice_id: str, text: str) -> bytes:
    return b"".join(client.text_to_speech.convert(
        voice_id=voice_id, text=text, model_id=config.elevenlabs_model,
        output_format=e._OUTPUT_FORMAT, voice_settings=vs,
        request_options=e._EL_REQUEST_OPTIONS,
    ))


def run_voices() -> int:
    client, vs = _client()
    line = "Well, that worked on the first try. [laughs] Not bad at all, Valentine."
    print(f"VOICE PROBE — same [laughs] line, model={config.elevenlabs_model!r}, stability={config.elevenlabs_stability}\n")
    for vk in _VOICE_PROBE:
        vid = _EL_VOICES.get(vk, _DEFAULT_VOICE_ID)
        try:
            data = _synth(client, vs, vid, line)
            path = OUT / f"voice__{vk}.mp3"
            path.write_bytes(data)
            print(f"  {vk:16s} -> {path.name}  ({len(data)} bytes)")
        except Exception as exc:
            print(f"  {vk:16s} -> FAIL {exc}")
    print(f"\nAudition tests/tag_audio/voice__*.mp3 — note which voices actually LAUGH.")
    return 0


def run_tags(voice_key: str) -> int:
    client, vs = _client()
    vid = _EL_VOICES.get(voice_key, _DEFAULT_VOICE_ID)
    print(f"TAG PROBE — voice={voice_key!r} ({vid}), model={config.elevenlabs_model!r}\n")
    for name, text in _TAG_CLIPS:
        try:
            data = _synth(client, vs, vid, text)
            path = OUT / f"tag__{voice_key}__{name}.mp3"
            path.write_bytes(data)
            print(f"  [{name:14s}] -> {path.name}  ({len(data)} bytes)")
        except Exception as exc:
            print(f"  [{name:14s}] -> FAIL {exc}")
    print(f"\nAudition tests/tag_audio/tag__{voice_key}__*.mp3 — note which tags RENDER.")
    return 0


def main(argv: list[str]) -> int:
    if not config.elevenlabs_api_key:
        print("NO KEY — ELEVENLABS_API_KEY missing from .env")
        return 2
    mode = argv[1] if len(argv) > 1 else "voices"
    if mode == "voices":
        return run_voices()
    if mode == "tags":
        return run_tags(argv[2] if len(argv) > 2 else config.tts_voice)
    print(f"unknown mode {mode!r} — use 'voices' or 'tags [voice_key]'")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
