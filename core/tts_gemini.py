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


def _parse_rate_from_mime(mime_type: str | None) -> int:
    """Pull the sample rate out of a Gemini audio mime type.

    Returns ``_PCM_SAMPLE_RATE`` (24000) when the mime type is missing or
    doesn't include a ``rate=`` parameter. Gemini's mime types look like
    ``audio/L16;codec=pcm;rate=24000`` — if Google ever changes the rate
    (16000, 22050, 48000 have all shown up in beta), we follow it.
    """
    if not mime_type:
        return _PCM_SAMPLE_RATE
    for part in str(mime_type).split(";"):
        part = part.strip().lower()
        if part.startswith("rate="):
            try:
                return int(part.split("=", 1)[1])
            except ValueError:
                return _PCM_SAMPLE_RATE
    return _PCM_SAMPLE_RATE


def _extract_pcm(response) -> tuple[bytes, int]:
    """Pull the PCM payload + sample rate out of a generate_content response.

    The SDK delivers audio under candidates[0].content.parts[N], where the
    part with ``inline_data.mime_type`` starting with ``audio/`` carries the
    bytes. We iterate parts defensively rather than assuming index 0
    because the model can return a small leading text part before the audio.
    Returns ``(pcm_bytes, sample_rate_hz)``.
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
                    mime = getattr(inline, "mime_type", None)
                    return data, _parse_rate_from_mime(mime)
    except (AttributeError, TypeError, IndexError):
        pass
    raise RuntimeError("Gemini TTS returned no audio bytes")


def _play_wav_via_mci(
    wav_path: str,
    on_ready: Callable[[], None] | None,
    on_done:  Callable[[], None] | None,
    notify_fn: Callable[[Callable | None], None],
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Play a WAV file via Windows MCI and fire callbacks at start/end.

    Uses the shared interruptible player (core/tts_elevenlabs._mci_play_until_done)
    so an Esc-to-interrupt can cut the clip mid-way: non-blocking ``play`` + a
    poll loop on the SAME worker thread that owns the alias. Runs on TtsEngine's
    single TTS worker thread, one utterance at a time.
    """
    import ctypes
    import os as _os

    from core.tts_elevenlabs import _mci_play_until_done

    mci = ctypes.windll.winmm.mciSendStringW
    alias = f"jarvis_gemini_{threading.get_ident()}"

    try:
        # Quoting the path lets MCI handle spaces in the temp directory.
        rc = mci(f'open "{wav_path}" type waveaudio alias {alias}', None, 0, None)
        if rc != 0:
            raise RuntimeError(f"MCI open failed rc={rc} for {wav_path!r}")
        notify_fn(on_ready)
        _mci_play_until_done(mci, alias, should_stop)
    finally:
        mci(f"close {alias}", None, 0, None)
        try:
            _os.unlink(wav_path)
        except OSError:
            pass
        notify_fn(on_done)


# Prefix prepended to every utterance before the SDK call. Two jobs:
#   1. Tells the Flash TTS model to interpret square-bracket cues
#      (`[chuckles]`, `[sighs]`, `[whispers]`, ...) as audio expressions
#      rather than reading them aloud as words or skipping them.
#   2. Nudges a natural, conversational delivery rather than the slightly
#      slower default cadence (no rate setting in the SDK; this is the
#      only handle we have over pace).
# The instruction itself isn't spoken — Gemini treats it as a directive
# for how to deliver the body that follows.
_STYLE_PREFIX = (
    "Speak the following naturally, at a brisk conversational pace. "
    "Bracketed cues like [chuckles], [sighs], [whispers], [laughs] are "
    "non-verbal audio expressions — render each as the actual sound, "
    "never read the word aloud.\n\n"
)


# Fail-fast on quota/429: build the client with a SINGLE attempt (no retry /
# backoff) plus a hang-guard request timeout. A quota error then surfaces in ~1s
# so TtsEngine can drop to the next tier (pyttsx3) immediately, instead of the
# SDK eating several seconds of exponential backoff on every first-of-session 429.
_GEMINI_TIMEOUT_MS = 15_000


def _fast_http_options(types):
    """HttpOptions tuned to fail fast: one attempt + a request timeout (ms).
    Degrades gracefully if a future SDK drops either field."""
    retry_cls = getattr(types, "HttpRetryOptions", None)
    if retry_cls is not None:
        try:
            return types.HttpOptions(
                timeout=_GEMINI_TIMEOUT_MS,
                retry_options=retry_cls(attempts=1),
            )
        except Exception:
            pass
    try:
        return types.HttpOptions(timeout=_GEMINI_TIMEOUT_MS)
    except Exception:
        return None


def _fast_client(genai, types, api_key: str):
    """genai.Client wired to fail fast; falls back to a plain client if the
    SDK rejects http_options."""
    opts = _fast_http_options(types)
    if opts is not None:
        try:
            return genai.Client(api_key=api_key, http_options=opts)
        except Exception:
            pass
    return genai.Client(api_key=api_key)


def say_gemini(
    text: str,
    on_ready: Callable[[], None] | None,
    on_done:  Callable[[], None] | None,
    notify_fn: Callable[[Callable | None], None],
    *,
    voice_name: str = DEFAULT_VOICE_NAME,
    api_key: str,
    model: str = "gemini-2.5-flash-preview-tts",
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Synthesize *text* with Gemini Flash TTS and play it.

    Blocks the calling thread until playback ends, so callers should
    invoke this from a dedicated TTS worker (TtsEngine's worker loop does).

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

    client = _fast_client(genai, types, api_key)
    response = client.models.generate_content(
        model=model,
        contents=_STYLE_PREFIX + text,
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

    pcm, sample_rate = _extract_pcm(response)
    _dbg("tts", f"Gemini returned {len(pcm)} bytes PCM at {sample_rate} Hz")

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
            wf.setframerate(sample_rate)
            wf.writeframes(pcm)
    except Exception:
        # Best-effort cleanup before re-raising.
        try:
            Path(wav_path).unlink(missing_ok=True)
        except OSError:
            pass
        raise

    _play_wav_via_mci(wav_path, on_ready, on_done, notify_fn, should_stop)


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
    client = _fast_client(genai, types, api_key)
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
    _extract_pcm(response)  # raises (RuntimeError) if no audio in the response
