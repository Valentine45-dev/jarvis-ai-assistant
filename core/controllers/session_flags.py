"""Shared helpers for quick/full settings synchronization and persistence."""

from __future__ import annotations

from config.settings import config


def sync_session_flag_views(quick_settings, settings_view, *, auto_confirm: bool, dim_mode: bool) -> None:
    from core.voice import voice_engine

    mic_muted = voice_engine.mic_muted
    tts_muted = voice_engine.tts_muted
    quick_settings.sync_state(
        mic_muted=mic_muted,
        tts_muted=tts_muted,
        auto_confirm=auto_confirm,
        dim_mode=dim_mode,
    )
    settings_view.sync_state(
        mic_muted=mic_muted,
        tts_muted=tts_muted,
        auto_confirm=auto_confirm,
        dim_mode=dim_mode,
    )


def persist_session_flags(*, auto_confirm: bool, dim_mode: bool) -> None:
    from core.voice import voice_engine

    config.mic_muted = bool(voice_engine.mic_muted)
    config.tts_muted = bool(voice_engine.tts_muted)
    config.auto_confirm = bool(auto_confirm)
    config.dim_mode = bool(dim_mode)
    try:
        config.save()
    except Exception:
        pass
