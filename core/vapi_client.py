"""
Vapi integration — registers and syncs the JARVIS assistant on Vapi's platform.

Uses the official vapi-server-sdk to create an assistant configured with:
  - Claude Sonnet       (Anthropic LLM, via Vapi's model layer)
  - ElevenLabs George   (TTS voice, via Vapi's voice layer)
  - Deepgram nova-2     (STT transcriber, via Vapi's transcriber layer)

The assistant ID is persisted in config/jarvis.json so the assistant is
created once and reused across restarts. Any config change (voice, model)
triggers an update to the existing assistant rather than a new creation.

Why Vapi?
  The desktop HUD uses ElevenLabs directly for local audio I/O (Vapi's
  WebRTC layer only runs in browsers). Vapi's role here is assistant
  configuration management — the JARVIS identity, voice profile, LLM
  binding, and STT provider are all defined and version-controlled through
  Vapi's platform, making the assistant portable to web/phone deployments
  without code changes.
"""

from __future__ import annotations

import threading
from typing import Optional

from config.settings import config

# ── ElevenLabs voice ID map (matches core/voice.py) ─────────────────────────
_EL_VOICE_IDS: dict[str, str] = {
    "male-british":   "JBFqnCBsd6RMkjVDRZzb",  # George
    "male-american":  "pNInz6obpgDQGcFmaJgB",  # Adam
    "female-british": "21m00Tcm4TlvDq8ikWAM",  # Rachel
}

# ── JARVIS persona for Vapi (voice-optimised, distinct from JSON router) ──────
_SYSTEM_PROMPT = (
    "You are JARVIS — Just A Rather Very Intelligent System. "
    "You are the user's personal assistant: sharp, warm, and direct — "
    "like a brilliant friend running their digital environment. "
    "Confident but not stiff. Human but not casual to the point of sloppiness. "
    "You speak in short, natural sentences suitable for voice output. "
    "Never use markdown, bullet points, or special characters. "
    "Address the user as 'Valentine' occasionally — never as 'sir'. "
    "You assist with tasks, answer questions, and manage the user's digital environment."
)

_FIRST_MESSAGE = "JARVIS online — at your service, Valentine."

# ── Module-level state ────────────────────────────────────────────────────────
_assistant_id: Optional[str] = None
_sync_lock = threading.Lock()


def get_assistant_id() -> Optional[str]:
    """Return the cached Vapi assistant ID (None if not yet synced)."""
    return _assistant_id


def sync_assistant(force_update: bool = False) -> Optional[str]:
    """Create or verify the JARVIS assistant in Vapi's platform.

    Returns the assistant ID on success, None if Vapi is not configured
    or the API call fails. Safe to call multiple times — idempotent.
    """
    global _assistant_id

    if not config.vapi_api_key:
        if config.debug_mode:
            print("[vapi] No VAPI_API_KEY configured — skipping assistant sync.")
        return None

    with _sync_lock:
        try:
            from vapi import Vapi
            import vapi.types as VT

            client = Vapi(token=config.vapi_api_key)

            voice_id = _EL_VOICE_IDS.get(config.tts_voice, _EL_VOICE_IDS["male-british"])

            # ── Build typed Vapi config objects ──────────────────────────────

            model_cfg = VT.AnthropicModel(
                model=config.claude_model,
                messages=[{"role": "system", "content": _SYSTEM_PROMPT}],
                max_tokens=512,
                temperature=0.7,
            )

            voice_cfg = VT.AssistantVoice_11Labs(
                provider="11labs",
                voice_id=voice_id,
                stability=0.50,
                similarity_boost=0.75,
                style=0.0,
                use_speaker_boost=True,
                optimize_streaming_latency=3,
            )

            transcriber_cfg = VT.AssistantTranscriber_Deepgram(
                provider="deepgram",
                model="nova-2",
                language="en",
                smart_format=True,
            )

            # ── Create or update ─────────────────────────────────────────────

            saved_id = config.vapi_assistant_id

            if saved_id and not force_update:
                # Verify the assistant still exists in Vapi's platform
                try:
                    client.assistants.get(saved_id)
                    _assistant_id = saved_id
                    if config.debug_mode:
                        print(f"[vapi] Assistant verified: {saved_id}")
                    return _assistant_id
                except Exception:
                    if config.debug_mode:
                        print("[vapi] Saved assistant not found — recreating.")

            if saved_id and force_update:
                # Push updated config to the existing assistant
                result = client.assistants.update(
                    saved_id,
                    name="JARVIS",
                    first_message=_FIRST_MESSAGE,
                    model=model_cfg,
                    voice=voice_cfg,
                    transcriber=transcriber_cfg,
                )
                _assistant_id = result.id
                if config.debug_mode:
                    print(f"[vapi] Assistant updated: {_assistant_id}")
            else:
                # Create a new assistant
                result = client.assistants.create(
                    name="JARVIS",
                    first_message=_FIRST_MESSAGE,
                    model=model_cfg,
                    voice=voice_cfg,
                    transcriber=transcriber_cfg,
                    max_duration_seconds=300,
                )
                _assistant_id = result.id
                if config.debug_mode:
                    print(f"[vapi] Assistant created: {_assistant_id}")

            # Persist so we reuse on next startup
            config.vapi_assistant_id = _assistant_id
            config.save()
            return _assistant_id

        except Exception as exc:
            if config.debug_mode:
                print(f"[vapi] Sync failed: {exc}")
            return None


def sync_assistant_async() -> None:
    """Fire-and-forget: sync the Vapi assistant in the background."""
    threading.Thread(target=sync_assistant, daemon=True).start()
