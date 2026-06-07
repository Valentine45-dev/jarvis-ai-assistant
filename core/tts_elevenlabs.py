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


def say_elevenlabs(
    text: str,
    on_ready: Callable[[], None] | None,
    on_done:  Callable[[], None] | None,
    notify_fn: Callable[[Callable | None], None],
    *,
    voice_id: str,
    api_key: str,
) -> None:
    el = _el()
    if el is None:
        raise RuntimeError("elevenlabs package not installed")

    _dbg("tts", f"ElevenLabs voice_id={voice_id!r}")
    client = el.ElevenLabs(api_key=api_key)

    stream_fn = getattr(client.text_to_speech, "stream", None)
    if stream_fn is not None:
        chunks = stream_fn(
            voice_id=voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
            request_options=_EL_REQUEST_OPTIONS,
        )
        play_mp3_stream(chunks, on_ready, on_done, notify_fn)
        return

    mp3_bytes = b"".join(
        client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
            request_options=_EL_REQUEST_OPTIONS,
        )
    )
    notify_fn(on_ready)
    play_mp3_bytes(mp3_bytes, on_done, notify_fn)


def probe_voice(
    voice_key: str,
    *,
    api_key: str,
    el_voices: dict,
    default_id: str,
    text: str = "Voice check.",
) -> None:
    """Validate voice/provider health without committing playback in UI flow.

    Raises TtsProviderError (from audio_pipeline) on auth/quota/network failure.
    Lazy import breaks the circular dependency — both modules are fully loaded
    before this function is ever called.
    """
    from core.audio_pipeline import TtsProviderError, _classify_elevenlabs_error  # noqa: PLC0415

    el = _el()
    if el is None:
        return
    voice_id = el_voices.get(voice_key, default_id)
    client = el.ElevenLabs(api_key=api_key)
    try:
        for chunk in client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
            request_options=_EL_REQUEST_OPTIONS,
        ):
            if chunk:
                break
    except Exception as exc:
        err = _classify_elevenlabs_error(exc)
        raise err from exc
