"""
Configuration — loads .env, exposes config dataclass.
API keys, model selection, wake word,
debug mode, HUD theme preferences.
"""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

_JSON_PATH = Path(__file__).parent / "jarvis.json"


@dataclass
class AppConfig:
    anthropic_api_key: str = ""
    vapi_api_key: str = ""
    vapi_assistant_id: str = ""
    elevenlabs_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    wake_word: str = "jarvis"
    debug_mode: bool = False
    theme: str = "cyan"
    # Display name for the user — spoken when asked e.g. "what's my name" (see CLAUDE.md + brain context).
    user_name: str = "Valentine"
    tts_provider: str = "elevenlabs"
    tts_voice: str = "male-british"
    tts_speed: int = 100
    mic_sensitivity: int = 70
    noise_gate: bool = True
    mic_device: int = -1      # -1 = system default; ≥0 = sounddevice device index
    # Shared session/UI flags persisted in config and mirrored across surfaces.
    mic_muted: bool = False
    tts_muted: bool = False
    auto_confirm: bool = False
    dim_mode: bool = False

    @classmethod
    def from_env(cls):
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            vapi_api_key=os.getenv("VAPI_API_KEY", ""),
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", ""),
            claude_model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
            wake_word=os.getenv("WAKE_WORD", "jarvis"),
            debug_mode=os.getenv("DEBUG", "false").lower() == "true",
        )

    @classmethod
    def load(cls):
        """Load from JSON if it exists, then overlay env vars.

        API keys live in .env only — they are never written to jarvis.json.
        Overlaying env vars here ensures they are always picked up even after
        a config.save() has created jarvis.json without them.
        """
        if _JSON_PATH.exists():
            try:
                data = json.loads(_JSON_PATH.read_text())
                fields = set(cls.__dataclass_fields__)
                instance = cls(**{k: v for k, v in data.items() if k in fields})
                # Env vars always win — API keys must come from .env, not JSON.
                env = cls.from_env()
                for key in ("anthropic_api_key", "vapi_api_key", "elevenlabs_api_key",
                            "claude_model", "wake_word", "debug_mode"):
                    env_val = getattr(env, key)
                    if env_val:
                        setattr(instance, key, env_val)
                u = os.getenv("USER_NAME", "").strip()
                if u:
                    instance.user_name = u
                return instance
            except Exception:
                pass
        return cls.from_env()

    def save(self):
        """Persist non-sensitive config to JSON. API keys stay in .env only."""
        _SENSITIVE = {"anthropic_api_key", "vapi_api_key", "elevenlabs_api_key"}
        data = {k: v for k, v in asdict(self).items() if k not in _SENSITIVE}
        _JSON_PATH.write_text(json.dumps(data, indent=2))


config = AppConfig.load()
