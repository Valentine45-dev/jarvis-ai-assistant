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
    tts_provider: str = "elevenlabs"
    tts_voice: str = "male-british"
    tts_speed: int = 100
    mic_sensitivity: int = 70
    noise_gate: bool = True

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
        """Load from JSON if it exists, otherwise fall back to env vars."""
        if _JSON_PATH.exists():
            try:
                data = json.loads(_JSON_PATH.read_text())
                fields = {f for f in cls.__dataclass_fields__}
                return cls(**{k: v for k, v in data.items() if k in fields})
            except Exception:
                pass
        return cls.from_env()

    def save(self):
        """Persist non-sensitive config to JSON. API keys stay in .env only."""
        _SENSITIVE = {"anthropic_api_key", "vapi_api_key", "elevenlabs_api_key"}
        data = {k: v for k, v in asdict(self).items() if k not in _SENSITIVE}
        _JSON_PATH.write_text(json.dumps(data, indent=2))


config = AppConfig.load()
