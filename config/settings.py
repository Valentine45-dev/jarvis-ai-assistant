"""
Configuration — loads .env, exposes config dataclass.
API keys, model selection, wake word,
debug mode, HUD theme preferences.

R2-30: `config` at module bottom is a shared mutable singleton loaded once
at import. Treat it as read-only outside the Settings UI / explicit save()
calls — handlers should not assign new attributes on the fly.
"""

import json
import os
from dataclasses import asdict, dataclass, field
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
    # Gemini Speech Generation key (free tier on Flash TTS as of 2026-05).
    # Gemini sits between ElevenLabs and pyttsx3 in TtsEngine — used when
    # ElevenLabs is unset or quota-locked; pyttsx3 stays as the last resort.
    gemini_api_key: str = ""
    # Prebuilt voice name passed to gemini-2.5-flash-preview-tts. See
    # core/tts_gemini.GEMINI_VOICE_BY_PROFILE for the profile→voice mapping;
    # this field lets a power user override that mapping with a raw voice
    # name (Kore, Puck, Charon, Zephyr, Aoede, ...).
    gemini_voice: str = ""
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
    browser_show_picker_reasoning: bool = True
    # Default controlled-browser engine: "chrome" | "edge" | "firefox" | "auto".
    # "auto" picks the first installed of chrome → edge → firefox. Anything that
    # auto-opens the browser (workflows, search, navigate) uses this engine; the
    # user can switch at runtime with "open edge" / "open firefox". Engines run
    # concurrently — switching just re-points the active engine, closing nothing.
    browser_engine: str = "chrome"
    # Mirror every _tlog line to logs/terminal.log (5MB rotating, 3 backups).
    terminal_log_to_file: bool = True
    # Stream the raw Claude vision response to the terminal panel line by
    # line BEFORE it's spoken. Useful while rolling out vision_analysis;
    # noisy long-term — flip to False once the pipeline is trusted.
    vision_show_analysis: bool = True
    # F-4: global OS hotkey bindings. Keys are hotkey-strings parsed by the
    # `keyboard` package; values are action names from
    # core/hotkeys.KNOWN_ACTIONS. Editing this dict at runtime requires
    # calling core.hotkeys.register_bindings(...) again to take effect.
    # field(default_factory=...) gives each AppConfig instance its own
    # dict rather than aliasing one mutable default across instances.
    hotkeys: dict = field(default_factory=lambda: {
        "ctrl+shift+j": "focus_command_bar",
        "ctrl+shift+m": "toggle_mic_mute",
        "ctrl+shift+s": "take_screenshot",
        "ctrl+shift+r": "read_screen",
    })
    # R2-5: master kill switch for core/handlers/code_exec.py. When False, every
    # action under intent `code_execution` short-circuits with an explicit
    # "disabled" reply. Use this to run JARVIS on a shared machine without
    # exposing the RCE endpoint.
    code_exec_enabled: bool = True
    # R2-1 / R2-7: when False (default), every AI-generated shell command from
    # _nl_to_command, _attempt_fix, and _run_plan shows a confirmation card
    # before subprocess launch. Flip to True only on a trusted single-user
    # machine — the danger regex inside code_exec is intentionally narrow and
    # cannot be relied on alone to gate Sonnet output.
    allow_ai_command_autorun: bool = False

    @classmethod
    def from_env(cls):
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            vapi_api_key=os.getenv("VAPI_API_KEY", ""),
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_voice=os.getenv("GEMINI_VOICE", ""),
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
                for key in ("anthropic_api_key", "vapi_api_key", "elevenlabs_api_key", "gemini_api_key",
                            "openweather_api_key", "claude_model", "wake_word", "debug_mode"):
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
            "anthropic_api_key", "vapi_api_key", "elevenlabs_api_key", "gemini_api_key",
            "openweather_api_key",
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
