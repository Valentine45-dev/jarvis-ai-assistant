"""Streaming-STT provider selection.

create_stt_session(config) returns a StreamingSttSession, or None to mean
"no streaming — use the legacy Google batch path". None is returned when the
provider isn't 'deepgram' or the key is missing, so the caller's fallback stays
a trivial `if session is None: <legacy path>`.
"""

from __future__ import annotations

from core.stt.base import StreamingSttSession

# Built-in keyterm vocabulary — brand / proper nouns the general model tends to
# mishear in JARVIS commands (common words like "volume"/"weather" are already
# recognised well and would just dilute the boost, so they're deliberately out).
# The wake word and the user's name are added on top of this at build time.
_KEYTERM_BASE: tuple[str, ...] = (
    "JARVIS", "Chrome", "Edge", "Firefox", "Spotify", "GitHub", "YouTube",
    "Gmail", "VS Code", "Notepad", "Wikipedia", "Reddit", "Deepgram",
)

_KEYTERM_CAP = 50  # keep the list tight — over-stuffing keyterms hurts accuracy


def build_keyterms(config) -> list[str]:
    """Assemble the nova-3 keyterm list: wake word + user name + built-in base +
    the user's `stt_keyterms`. Case-insensitively deduped (first spelling wins),
    blanks dropped, capped so the prompt stays focused."""
    wake = (getattr(config, "wake_word", "") or "").strip()
    user = (getattr(config, "user_name", "") or "").strip()
    extra = getattr(config, "stt_keyterms", None) or []

    ordered: list[str] = [wake, user, *_KEYTERM_BASE, *extra]
    seen: set[str] = set()
    result: list[str] = []
    for term in ordered:
        t = (term or "").strip()
        if not t:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(t)
        if len(result) >= _KEYTERM_CAP:
            break
    return result


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
        keyterms=build_keyterms(config),
    )
