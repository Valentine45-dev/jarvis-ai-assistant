"""Streaming-STT provider selection.

create_stt_session(config) returns a StreamingSttSession, or None to mean
"no streaming — use the legacy Google batch path". None is returned when the
provider isn't 'deepgram' or the key is missing, so the caller's fallback stays
a trivial `if session is None: <legacy path>`.
"""

from __future__ import annotations

from core.stt.base import StreamingSttSession


def create_stt_session(config) -> StreamingSttSession | None:
    provider = (getattr(config, "stt_provider", "google") or "google").strip().lower()
    if provider != "deepgram":
        return None
    key = (getattr(config, "deepgram_api_key", "") or "").strip()
    if not key:
        return None
    from core.stt.deepgram import DeepgramSttSession
    return DeepgramSttSession(
        api_key=key,
        model=getattr(config, "deepgram_model", "nova-3") or "nova-3",
        language=getattr(config, "stt_language", "en-US") or "en-US",
        endpointing_ms=getattr(config, "stt_endpointing_ms", 300),
        utterance_end_ms=getattr(config, "stt_utterance_end_ms", 1000),
    )
