"""Gemini Speech Generation TTS plugin for JARVIS.

Uses Google's gemini-2.5-flash-preview-tts model via the official
``google-genai`` SDK. The Flash TTS model is on the free tier of the
Gemini Developer API as of 2026-05; if rate limits are hit, the caller
falls back to pyttsx3 (handled in audio_pipeline.TtsEngine).

Why this exists: ElevenLabs quota-locks at unpredictable times and
running Nari Dia locally requires a CUDA GPU. Gemini Flash TTS gives
us:
  - the exact ``[chuckles]`` / ``[sighs]`` / ``[whispers]`` inline-tag
    syntax that the CLAUDE.md style guide leans on,
  - 30 voices, 60+ languages,
  - no local GPU,
  - free tier covers normal desktop-assistant usage.

Public surface mirrors ``tts_elevenlabs.say_elevenlabs`` so the
audio-pipeline tier switch is a one-line ``try/except`` per provider.

Output details from the Gemini API:
  - PCM, 24 000 Hz, 16-bit, mono
  - delivered as raw bytes in ``response.candidates[0].content.parts[0].inline_data.data``
  - we wrap in a WAV header and play via the same Windows MCI path that
    the ElevenLabs plugin already uses for MP3
"""

from __future__ import annotations

import threading
import wave
from pathlib import Path
from typing import Callable

from core.log import debug as _dbg


# Default voice when settings doesn't specify one. "Kore" is warm,
# even-paced, and close to the British-male timbre JARVIS uses today.
DEFAULT_VOICE_NAME = "Kore"

# Voice key -> Gemini prebuilt voice name. Keys match the existing
# `tts_voice` profile names in settings so the same Quick Settings
# selector drives both ElevenLabs and Gemini.
GEMINI_VOICE_BY_PROFILE: dict[str, str] = {
    "male-british":   "Kore",       # warm, even
    "male-american":  "Puck",       # upbeat, friendly
    "female-british": "Aoede",      # bright, clear
}

# Sample params returned by the Gemini TTS endpoint. Lock these
# in WAV header — wrong values produce chipmunk / slow-mo audio.
_PCM_CHANNELS    = 1
_PCM_SAMPLE_RATE = 24_000
_PCM_SAMPLE_WIDTH = 2   # bytes per sample = 16-bit


def _genai():
    """Lazy import the google-genai SDK so JARVIS can launch even when
    the dependency isn't installed yet (graceful upstream skip)."""
    try:
        from google import genai
        from google.genai import types
        return genai, types
    except ImportError:
        return None, None


def _extract_pcm(response) -> bytes:
    """Pull the raw PCM payload out of a generate_content response.

    The SDK delivers audio under candidates[0].content.parts[N], where the
    part with inline_data.mime_type=='audio/...' carries the bytes. We
    iterate parts defensively rather than assuming index 0 because the
    model can return a small leading text part before the audio.
    """
    try:
        candidates = getattr(response, "candidates", None) or []
        for cand in candidates:
            content = getattr(cand, "content", None)
            if content is None:
                continue
            parts = getattr(content, "parts", None) or []
            for part in parts:
                inline = getattr(part, "inline_data", None)
                if inline is None:
                    continue
                data = getattr(inline, "data", None)
                if data:
                    return data
    except (AttributeError, TypeError, IndexError):
        pass
    raise RuntimeError("Gemini TTS returned no audio bytes")


def _play_wav_via_mci(
    wav_path: str,
    on_ready: Callable[[], None] | None,
    on_done:  Callable[[], None] | None,
    notify_fn: Callable[[Callable | None], None],
) -> None:
    """Play a WAV file via Windows MCI and fire callbacks at start/end.

    Same pattern as core/tts_elevenlabs.play_mp3_bytes but for WAV. We
    open the file, fire on_ready immediately, ``play wait`` (blocks
    this thread until playback ends), then fire on_done. The thread
    is the worker spawned by TtsEngine._say_thread so blocking here
    is fine — the calling thread is dedicated to a single utterance.
    """
    import ctypes
    import os as _os

    mci = ctypes.windll.winmm.mciSendStringW
    alias = f"jarvis_gemini_{threading.get_ident()}"

    try:
        # Quoting the path lets MCI handle spaces in the temp directory.
        rc = mci(f'open "{wav_path}" type waveaudio alias {alias}', None, 0, None)
        if rc != 0:
            raise RuntimeError(f"MCI open failed rc={rc} for {wav_path!r}")
        notify_fn(on_ready)
        mci(f"play {alias} wait", None, 0, None)
    finally:
        mci(f"close {alias}", None, 0, None)
        try:
            _os.unlink(wav_path)
        except OSError:
            pass
        notify_fn(on_done)


def say_gemini(
    text: str,
    on_ready: Callable[[], None] | None,
    on_done:  Callable[[], None] | None,
    notify_fn: Callable[[Callable | None], None],
    *,
    voice_name: str = DEFAULT_VOICE_NAME,
    api_key: str,
    model: str = "gemini-2.5-flash-preview-tts",
) -> None:
    """Synthesize *text* with Gemini Flash TTS and play it.

    Blocks the calling thread until playback ends, so callers should
    invoke this from a dedicated TTS worker (TtsEngine._say_thread does).

    Raises on SDK errors, transport errors, empty audio, or MCI failure —
    the caller is responsible for falling back to the next TTS tier.
    """
    genai, types = _genai()
    if genai is None:
        raise RuntimeError("google-genai package not installed")
    if not api_key:
        raise RuntimeError("Gemini API key is empty")
    if not (text or "").strip():
        return

    _dbg("tts", f"Gemini voice={voice_name!r} model={model!r}")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name
                    )
                )
            ),
        ),
    )

    pcm = _extract_pcm(response)

    # Write to a uniquely-named temp WAV. We use the same TEMP dir the
    # ElevenLabs plugin uses; MCI cleans up via the close + unlink pair
    # in _play_wav_via_mci.
    import tempfile
    fd_path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    wav_path = fd_path.name
    fd_path.close()

    try:
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(_PCM_CHANNELS)
            wf.setsampwidth(_PCM_SAMPLE_WIDTH)
            wf.setframerate(_PCM_SAMPLE_RATE)
            wf.writeframes(pcm)
    except Exception:
        # Best-effort cleanup before re-raising.
        try:
            Path(wav_path).unlink(missing_ok=True)
        except OSError:
            pass
        raise

    _play_wav_via_mci(wav_path, on_ready, on_done, notify_fn)


def probe_gemini(
    voice_name: str,
    *,
    api_key: str,
    text: str = "Voice check.",
) -> None:
    """Validate Gemini TTS health without driving the UI.

    Mirrors core.tts_elevenlabs.probe_voice — synthesize a short string
    and discard the audio. Raises on auth / network / quota errors so
    the settings UI can surface a clear failure reason.
    """
    genai, types = _genai()
    if genai is None or not api_key:
        return
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name
                    )
                )
            ),
        ),
    )
    _extract_pcm(response)  # raises if no audio in the response
