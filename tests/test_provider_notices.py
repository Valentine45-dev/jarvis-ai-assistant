"""User-facing fallback notices (TTS tier switch + STT streaming->batch).

Both emit on the central signals hub, deduped once per target/session so a
degraded run doesn't spam toasts. We capture by connecting a plain slot and
emitting synchronously (same thread → direct connection; no QApplication loop
needed).
"""

from __future__ import annotations

import contextlib

from core.signals import signals


@contextlib.contextmanager
def _capture():
    got: list[tuple[str, str]] = []
    slot = lambda m, k: got.append((m, k))  # noqa: E731
    signals.notice.connect(slot)
    try:
        yield got
    finally:
        signals.notice.disconnect(slot)


# ── TTS tier-switch notices ───────────────────────────────────────────────────

def test_tts_switch_announces_once_per_target_with_right_message():
    from core.audio_pipeline import TtsEngine
    eng = TtsEngine()
    with _capture() as got:
        eng._announce_switch("gemini", quota=True)
        eng._announce_switch("gemini", quota=True)   # deduped — same target
        eng._announce_switch("local", quota=False)
        eng._announce_switch("local", quota=True)    # deduped
    assert len(got) == 2
    assert "Google voice" in got[0][0] and got[0][1] == "warning"   # quota → warning
    assert "offline voice" in got[1][0] and got[1][1] == "info"     # transient → info


def test_tts_switch_transient_vs_quota_wording():
    from core.audio_pipeline import TtsEngine
    with _capture() as got:
        TtsEngine()._announce_switch("gemini", quota=False)
    assert "unavailable" in got[0][0].lower()
    assert "credit" not in got[0][0].lower()


# ── STT streaming → batch notice ──────────────────────────────────────────────

def test_stt_fallback_announces_once():
    from core.voice import VoiceEngine
    eng = VoiceEngine()
    with _capture() as got:
        eng._announce_stt_fallback()
        eng._announce_stt_fallback()   # deduped
    assert len(got) == 1
    assert "backup" in got[0][0].lower() and got[0][1] == "warning"
