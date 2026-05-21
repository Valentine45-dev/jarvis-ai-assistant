"""
Configuration — loads .env, exposes config dataclass.
API keys, model selection, wake word,
debug mode, HUD theme preferences.
"""

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

_JSON_PATH = Path(__file__).parent / "jarvis.json"


def _log_settings_error(msg: str) -> None:
    """Route a settings error through core.log when available, else stderr.

    core.log doesn't import config at module-load time, so calling it from
    inside AppConfig.load() is safe (no circular import). The fallback exists
    only because settings can theoretically run before core/ is on sys.path
    (e.g. an external tool importing config.settings standalone)."""
    try:
        from core.log import error as _err
        _err("settings", msg)
    except Exception:
        import sys
        print(f"[settings] {msg}", file=sys.stderr)


@dataclass
class AppConfig:
    anthropic_api_key: str = ""
    vapi_api_key: str = ""
    vapi_assistant_id: str = ""
    elevenlabs_api_key: str = ""
    openweather_api_key: str = ""
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
    wake_word_enabled: bool = True
    weather_default_city: str = "Monrovia,LR"
    # When True, stream Sonnet-generated document scripts to the terminal panel
    # before sandbox execution. Useful during the document_creation rollout;
    # noisy long-term — flip to False once the pipeline is trusted.
    document_show_code: bool = True
    # Universal terminal streaming — emit one-line action summaries from every
    # handler (browser, files, system, etc.). Existing in-flight streamers
    # (code_exec, document_handler, find_in_files) are not gated by this flag.
    terminal_show_actions: bool = True
    # Show the raw Haiku reasoning line behind a browser picker pick. Off by
    # default — only useful when debugging element-selection misses.
    browser_show_picker_reasoning: bool = False
    # Mirror every _tlog line to logs/terminal.log (5MB rotating, 3 backups).
    terminal_log_to_file: bool = False

    @classmethod
    def from_env(cls):
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            vapi_api_key=os.getenv("VAPI_API_KEY", ""),
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", ""),
            openweather_api_key=os.getenv("OPENWEATHER_API_KEY", ""),
            claude_model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
            wake_word=os.getenv("WAKE_WORD", "jarvis"),
            debug_mode=os.getenv("DEBUG", "false").lower() == "true",
            weather_default_city=os.getenv("OPENWEATHER_DEFAULT_CITY", "Monrovia,LR"),
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
                for key in ("anthropic_api_key", "vapi_api_key", "elevenlabs_api_key", "openweather_api_key",
                            "claude_model", "wake_word", "debug_mode"):
                    env_val = getattr(env, key)
                    if env_val:
                        setattr(instance, key, env_val)
                u = os.getenv("USER_NAME", "").strip()
                if u:
                    instance.user_name = u
                return instance
            except Exception as exc:
                # R2-11: never silently swallow a corrupt jarvis.json. Rename
                # the bad file with a timestamp suffix and log the reason so
                # the user knows why their settings reverted to defaults.
                # The corrupt-write scenario (R2-10 atomic save) is what makes
                # this reachable in the first place.
                try:
                    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    bad_path = _JSON_PATH.with_suffix(f".json.bad.{stamp}")
                    os.replace(_JSON_PATH, bad_path)
                    _log_settings_error(
                        f"jarvis.json is corrupt ({exc!r}) — preserved as {bad_path.name}; "
                        "loading defaults this session"
                    )
                except OSError as rename_exc:
                    _log_settings_error(
                        f"jarvis.json is corrupt ({exc!r}) and could not be renamed ({rename_exc!r}); "
                        "loading defaults this session"
                    )
        return cls.from_env()

    def save(self):
        """Persist non-sensitive config to JSON. API keys stay in .env only.

        R2-10: write atomically via tmp + os.replace. A crash mid-write leaves
        the previous version of jarvis.json intact rather than truncated.
        Mirrors the pattern used in core/automation.py for workflows.json.
        """
        _SENSITIVE = {
            "anthropic_api_key", "vapi_api_key", "elevenlabs_api_key", "openweather_api_key",
        }
        data = {k: v for k, v in asdict(self).items() if k not in _SENSITIVE}
        tmp = _JSON_PATH.with_suffix(_JSON_PATH.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, _JSON_PATH)
        except Exception as exc:
            _log_settings_error(f"failed to save {_JSON_PATH.name}: {exc!r}")
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass


config = AppConfig.load()
