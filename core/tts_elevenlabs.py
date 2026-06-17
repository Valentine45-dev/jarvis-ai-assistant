"""
ElevenLabs TTS plugin for JARVIS.

All ElevenLabs API code lives here.  To re-enable after disabling:
  uncomment the marked import block in core/audio_pipeline.py.

Public functions (called from TtsEngine when enabled)
------------------------------------------------------
say_elevenlabs(text, on_ready, on_done, notify_fn, *, voice_id, api_key)
play_mp3_stream(chunks, on_ready, on_done, notify_fn)
play_mp3_bytes(mp3_bytes, on_done, notify_fn)
probe_voice(voice_key, *, api_key, el_voices, default_id, text)
"""

from __future__ import annotations

import itertools
import re
import threading
from typing import Callable

from core.log import debug as _dbg


# ── Lazy ElevenLabs SDK import ────────────────────────────────────────────────

def _el():
    try:
        import elevenlabs
        return elevenlabs
    except ImportError:
        return None


# ── MP3 streaming playback via Windows MCI ────────────────────────────────────

def play_mp3_stream(
    chunks,
    on_ready: Callable[[], None] | None,
    on_done:  Callable[[], None] | None,
    notify_fn: Callable[[Callable | None], None],
) -> None:
    """Write MP3 chunks to a temp file and play via Windows MCI as they arrive."""
    import ctypes
    import os as _os
    import tempfile
    import time

    mci = ctypes.windll.winmm.mciSendStringW

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name

    alias   = f"jarvis_tts_{threading.get_ident()}"
    opened  = False
    playing = False

    def _send(cmd: str) -> int:
        return mci(cmd, None, 0, None)

    def _try_start() -> bool:
        nonlocal opened, playing
        if opened:
            return True
        if _send(f'open "{tmp_path}" type mpegvideo alias {alias}') != 0:
            return False
        opened = True
        if _send(f"play {alias}") != 0:
            _send(f"close {alias}")
            opened = False
            return False
        playing = True
        notify_fn(on_ready)
        return True

    def _wait_done() -> None:
        if not opened:
            return
        status = ctypes.create_unicode_buffer(64)
        for _ in range(600):    # 60 s safety cap
            status.value = ""
            if mci(f"status {alias} mode", status, 64, None) != 0:
                break
            if status.value.lower() in {"stopped", "not ready"}:
                break
            time.sleep(0.1)

    try:
        with open(tmp_path, "ab", buffering=0) as audio_file:
            for chunk in chunks:
                if not chunk:
                    continue
                audio_file.write(chunk)
                audio_file.flush()
                if not playing:
                    _try_start()

        if playing:
            _wait_done()
        else:
            notify_fn(on_ready)
            if _send(f'open "{tmp_path}" type mpegvideo alias {alias}') == 0:
                opened = True
                _send(f"play {alias} wait")
    finally:
        if opened:
            _send(f"close {alias}")
        try:
            _os.unlink(tmp_path)
        except OSError:
            pass

    notify_fn(on_done)


def play_mp3_bytes(
    mp3_bytes: bytes,
    on_done: Callable[[], None] | None,
    notify_fn: Callable[[Callable | None], None],
) -> None:
    """Play a complete MP3 buffer synchronously via Windows MCI."""
    import ctypes
    import tempfile
    import os as _os

    mci = ctypes.windll.winmm.mciSendStringW

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(mp3_bytes)
        tmp_path = f.name

    alias = f"jarvis_tts_bytes_{threading.get_ident()}"
    try:
        mci(f'open "{tmp_path}" type mpegvideo alias {alias}', None, 0, None)
        mci(f"play {alias} wait", None, 0, None)
        mci(f"close {alias}", None, 0, None)
    finally:
        try:
            _os.unlink(tmp_path)
        except OSError:
            pass
    notify_fn(on_done)


# ── ElevenLabs TTS synthesis ──────────────────────────────────────────────────

# Fail-fast on quota/429: no SDK retries + a hang-guard timeout, so a quota
# error surfaces immediately and TtsEngine drops to the next tier instead of
# waiting out the SDK's exponential backoff on every first-of-session 429.
_EL_REQUEST_OPTIONS = {"max_retries": 0, "timeout_in_seconds": 15}

_OUTPUT_FORMAT = "mp3_44100_128"

# Only eleven_v3 performs inline audio tags. If the key's tier can't reach v3
# we walk these (both stream-capable + low-latency, but tag-blind — so tags are
# stripped before synthesis on them). Tried left-to-right after the configured
# model. The first working model is cached per session (see _RESOLVED_MODEL).
_MODEL_FALLBACKS: tuple[str, ...] = ("eleven_turbo_v2_5", "eleven_flash_v2_5")

# eleven_v3 quantises stability to exactly these modes; any other value is
# rounded to the nearest by the API (0.0 Creative / 0.5 Natural / 1.0 Robust).
# We pass the configured value through untouched — this only documents the rule.
_V3_STABILITY_LEVELS: tuple[float, ...] = (0.0, 0.5, 1.0)

# Session cache: configured-model -> first model that actually synthesised.
# Avoids re-probing an unavailable v3 (and eating its error) on every line.
# Cleared on restart, mirroring the session quota-locks in audio_pipeline.
_RESOLVED_MODEL: dict[str, str] = {}

_TAG_RE = re.compile(r"\[[^\]]*\]")


def _strip_audio_tags(text: str) -> str:
    """Drop [chuckles]/[sighs]/… bracket cues for models that can't perform
    them (anything but eleven_v3) so they aren't read aloud literally."""
    return re.sub(r"\s{2,}", " ", _TAG_RE.sub("", text)).strip()


def _model_candidates(configured: str) -> list[str]:
    """Configured model first, then the tag-blind fallbacks (deduped). A
    session-cached working model is hoisted to the front to skip dead probes."""
    out = [configured]
    for m in _MODEL_FALLBACKS:
        if m not in out:
            out.append(m)
    cached = _RESOLVED_MODEL.get(configured)
    if cached and cached in out:
        out.remove(cached)
        out.insert(0, cached)
    return out


def _is_model_unavailable_error(exc: Exception) -> bool:
    """True when the SDK error is the key's tier lacking access to the model
    (so we should try the next model) — NOT a quota/auth/network failure, which
    must fail fast and let TtsEngine drop to the next provider tier."""
    s = str(exc).lower()
    if "model" in s and any(
        k in s for k in (
            "access", "not found", "not available", "unavailable",
            "invalid", "not have", "denied",
        )
    ):
        return True
    # ElevenLabs returns 403 specifically for model-tier gating.
    return "status_code: 403" in s


def _voice_settings_cls(el):
    """Resolve the VoiceSettings type across SDK layouts (None if unavailable)."""
    try:
        from elevenlabs.types import VoiceSettings  # noqa: PLC0415
        return VoiceSettings
    except Exception:
        return getattr(el, "VoiceSettings", None)


def _build_voice_settings(vs_cls, stability, similarity_boost, style, use_speaker_boost):
    """Build a VoiceSettings object, degrading gracefully on older SDKs that
    don't accept the full kwarg set (None means 'send no voice_settings')."""
    if vs_cls is None:
        return None
    try:
        return vs_cls(
            stability=stability,
            similarity_boost=similarity_boost,
            style=style,
            use_speaker_boost=use_speaker_boost,
        )
    except Exception:
        try:
            return vs_cls(stability=stability, similarity_boost=similarity_boost)
        except Exception:
            return None


def _synth_once(
    client,
    text: str,
    on_ready: Callable[[], None] | None,
    on_done:  Callable[[], None] | None,
    notify_fn: Callable[[Callable | None], None],
    *,
    voice_id: str,
    model: str,
    voice_settings,
) -> None:
    """One synthesis attempt for a single model. Errors propagate to the caller
    BEFORE any playback/on_ready fires (the stream path is primed first), so a
    model-unavailable error can be retried on the next model without the user
    ever hearing a half-spoken line."""
    stream_fn = getattr(client.text_to_speech, "stream", None)
    if stream_fn is not None:
        chunks = stream_fn(
            voice_id=voice_id,
            text=text,
            model_id=model,
            output_format=_OUTPUT_FORMAT,
            voice_settings=voice_settings,
            request_options=_EL_REQUEST_OPTIONS,
        )
        # Prime the generator: the HTTP request (and any model/quota error)
        # fires on first iteration — pull one chunk here so failures raise
        # before playback. The chunk is chained back so none is lost.
        iterator = iter(chunks)
        first = next(iterator, None)
        if first is None:
            notify_fn(on_ready)
            notify_fn(on_done)
            return
        play_mp3_stream(itertools.chain([first], iterator), on_ready, on_done, notify_fn)
        return

    mp3_bytes = b"".join(
        client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id=model,
            output_format=_OUTPUT_FORMAT,
            voice_settings=voice_settings,
            request_options=_EL_REQUEST_OPTIONS,
        )
    )
    notify_fn(on_ready)
    play_mp3_bytes(mp3_bytes, on_done, notify_fn)


def say_elevenlabs(
    text: str,
    on_ready: Callable[[], None] | None,
    on_done:  Callable[[], None] | None,
    notify_fn: Callable[[Callable | None], None],
    *,
    voice_id: str,
    api_key: str,
    model: str = "eleven_v3",
    stability: float = 0.0,
    similarity_boost: float = 0.75,
    style: float = 0.6,
    use_speaker_boost: bool = True,
) -> None:
    el = _el()
    if el is None:
        raise RuntimeError("elevenlabs package not installed")

    _dbg("tts", f"ElevenLabs voice_id={voice_id!r} model={model!r}")
    client = el.ElevenLabs(api_key=api_key)
    voice_settings = _build_voice_settings(
        _voice_settings_cls(el), stability, similarity_boost, style, use_speaker_boost
    )

    last_model_exc: Exception | None = None
    for candidate in _model_candidates(model):
        # Tags only perform on v3; strip them on the tag-blind fallbacks so the
        # user never hears "open bracket chuckles".
        synth_text = text if candidate == "eleven_v3" else _strip_audio_tags(text)
        try:
            _synth_once(
                client, synth_text, on_ready, on_done, notify_fn,
                voice_id=voice_id, model=candidate, voice_settings=voice_settings,
            )
            _RESOLVED_MODEL[model] = candidate
            if candidate != model:
                _dbg("tts", f"ElevenLabs model {model!r} unavailable — used {candidate!r}")
            return
        except Exception as exc:
            if _is_model_unavailable_error(exc):
                last_model_exc = exc
                _dbg("tts", f"ElevenLabs model {candidate!r} not available, trying next")
                continue
            raise  # quota/auth/network → fail fast, let TtsEngine drop a tier
    if last_model_exc is not None:
        raise last_model_exc


def probe_voice(
    voice_key: str,
    *,
    api_key: str,
    el_voices: dict,
    default_id: str,
    text: str = "Voice check.",
    model: str = "eleven_v3",
    stability: float = 0.0,
    similarity_boost: float = 0.75,
    style: float = 0.6,
    use_speaker_boost: bool = True,
) -> None:
    """Validate voice/provider health without committing playback in UI flow.

    Raises TtsProviderError (from audio_pipeline) on auth/quota/network failure.
    Walks the same model-fallback chain as say_elevenlabs so a v3-less tier still
    validates the voice (on a tag-blind model). Lazy import breaks the circular
    dependency — both modules are fully loaded before this function is called.
    """
    from core.audio_pipeline import TtsProviderError, _classify_elevenlabs_error  # noqa: PLC0415

    el = _el()
    if el is None:
        return
    voice_id = el_voices.get(voice_key, default_id)
    client = el.ElevenLabs(api_key=api_key)
    voice_settings = _build_voice_settings(
        _voice_settings_cls(el), stability, similarity_boost, style, use_speaker_boost
    )

    last_model_exc: Exception | None = None
    for candidate in _model_candidates(model):
        synth_text = text if candidate == "eleven_v3" else _strip_audio_tags(text)
        try:
            for chunk in client.text_to_speech.convert(
                voice_id=voice_id,
                text=synth_text,
                model_id=candidate,
                output_format=_OUTPUT_FORMAT,
                voice_settings=voice_settings,
                request_options=_EL_REQUEST_OPTIONS,
            ):
                if chunk:
                    break
            _RESOLVED_MODEL[model] = candidate
            return
        except Exception as exc:
            if _is_model_unavailable_error(exc):
                last_model_exc = exc
                continue
            err = _classify_elevenlabs_error(exc)
            raise err from exc
    if last_model_exc is not None:
        err = _classify_elevenlabs_error(last_model_exc)
        raise err from last_model_exc
