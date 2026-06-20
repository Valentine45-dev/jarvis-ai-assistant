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

def _mci_play_until_done(mci, alias: str, should_stop: Callable[[], bool] | None) -> None:
    """Play an opened MCI alias WITHOUT blocking on `wait`, polling its status so
    a stop signal can cut the clip mid-way (the Esc-to-interrupt feature).

    Runs on the worker thread that owns `alias`, so the `stop` is issued on the
    same thread that opened it — no MCI thread-affinity risk. Polls `status mode`
    every ~40ms: stops on `should_stop()`, returns when playback finishes, and
    bails if the clip never reaches `playing` within ~0.5s (already done)."""
    import ctypes
    import time as _time

    mci(f"play {alias}", None, 0, None)          # async start (no `wait`)
    buf = ctypes.create_unicode_buffer(64)
    started = False
    misses = 0
    while True:
        if should_stop is not None and should_stop():
            mci(f"stop {alias}", None, 0, None)
            return
        mci(f"status {alias} mode", buf, 64, None)
        mode = (buf.value or "").strip().lower()
        if mode == "playing":
            started, misses = True, 0
        elif started:
            return                                # finished naturally
        else:
            misses += 1
            if misses > 12:                       # ~0.5s, never started → done
                return
        _time.sleep(0.04)


def play_mp3_stream(
    chunks,
    on_ready: Callable[[], None] | None,
    on_done:  Callable[[], None] | None,
    notify_fn: Callable[[Callable | None], None],
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Buffer the MP3 stream to a temp file, then play the COMPLETE file via MCI.

    Why not play incrementally as chunks arrive: Windows MCI fixes the media
    length at `open`, so playback kicked off on the first (tiny) chunk only
    played that sliver and stopped — which silently dropped the rest of the
    FIRST clip of a session (cold network dribbles the chunks in slowly),
    including any audio tag past the opening words. Warm requests happened to
    arrive nearly complete by the time play started, so they sounded fine, which
    is exactly why only the first line of a session lost its tag. Writing the
    whole stream out first, then opening + playing, makes MCI see the full
    duration every time. For short assistant lines the extra wait is negligible.
    """
    import ctypes
    import os as _os
    import tempfile

    mci = ctypes.windll.winmm.mciSendStringW

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name

    alias   = f"jarvis_tts_{threading.get_ident()}"
    opened  = False
    aborted = False
    try:
        with open(tmp_path, "ab", buffering=0) as audio_file:
            for chunk in chunks:
                if should_stop is not None and should_stop():
                    aborted = True       # interrupted while still buffering
                    break
                if chunk:
                    audio_file.write(chunk)

        # on_ready right before playback so the UI "speaking" cue lines up with
        # audio start (not with first-byte-received).
        if not aborted:
            notify_fn(on_ready)
            if mci(f'open "{tmp_path}" type mpegvideo alias {alias}', None, 0, None) == 0:
                opened = True
                _mci_play_until_done(mci, alias, should_stop)
    finally:
        if opened:
            mci(f"close {alias}", None, 0, None)
        try:
            _os.unlink(tmp_path)
        except OSError:
            pass

    notify_fn(on_done)


def play_mp3_bytes(
    mp3_bytes: bytes,
    on_done: Callable[[], None] | None,
    notify_fn: Callable[[Callable | None], None],
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Play a complete MP3 buffer via Windows MCI (interruptible)."""
    import ctypes
    import tempfile
    import os as _os

    mci = ctypes.windll.winmm.mciSendStringW

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(mp3_bytes)
        tmp_path = f.name

    alias  = f"jarvis_tts_bytes_{threading.get_ident()}"
    opened = False
    try:
        if mci(f'open "{tmp_path}" type mpegvideo alias {alias}', None, 0, None) == 0:
            opened = True
            _mci_play_until_done(mci, alias, should_stop)
    finally:
        if opened:
            mci(f"close {alias}", None, 0, None)
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
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """One synthesis attempt for a single model. Errors propagate to the caller
    BEFORE any playback/on_ready fires (the stream path is primed first), so a
    model-unavailable error can be retried on the next model without the user
    ever hearing a half-spoken line."""
    # Ground-truth trace: the EXACT string handed to the ElevenLabs API, so any
    # upstream tag-stripping/truncation (e.g. first_sentence) is visible in the
    # debug terminal / logs/terminal.log. Compare against what the probe sends.
    _dbg("tts", f"ElevenLabs -> API model={model!r} text={text!r}")
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
        play_mp3_stream(itertools.chain([first], iterator), on_ready, on_done,
                        notify_fn, should_stop)
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
    play_mp3_bytes(mp3_bytes, on_done, notify_fn, should_stop)


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
    should_stop: Callable[[], bool] | None = None,
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
                should_stop=should_stop,
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
