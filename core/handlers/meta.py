"""Handlers: jarvis_meta, unknown."""

from __future__ import annotations

from datetime import datetime

from config.settings import config
from core.handlers.shared import _ok, _err, _tlog, get_page_cache


_VOICE_FIRST_NAMES: dict[str, str] = {
    "male-british":         "George",
    "male-american":        "Adam",
    "female-british":       "Rachel",
    "male-broadcast":       "Daniel",
    "male-resonant":        "Brian",
    "male-smooth":          "Eric",
    "male-gravelly":        "Callum",
    "male-casual":          "Chris",
    "male-australian":      "Charlie",
    "female-professional":  "Sarah",
    "female-british-clear": "Alice",
    "female-british-warm":  "Lily",
    "female-american":      "Matilda",
}

_VOICE_ALIASES: dict[str, str] = {
    "male-british":         "male-british",
    "male-american":        "male-american",
    "female-british":       "female-british",
    "male-broadcast":       "male-broadcast",
    "male-resonant":        "male-resonant",
    "male-smooth":          "male-smooth",
    "male-gravelly":        "male-gravelly",
    "male-casual":          "male-casual",
    "male-australian":      "male-australian",
    "female-professional":  "female-professional",
    "female-british-clear": "female-british-clear",
    "female-british-warm":  "female-british-warm",
    "female-american":      "female-american",
    "george":    "male-british",
    "adam":      "male-american",
    "adams":     "male-american",
    "rachel":    "female-british",
    "daniel":    "male-broadcast",
    "brian":     "male-resonant",
    "eric":      "male-smooth",
    "callum":    "male-gravelly",
    "chris":     "male-casual",
    "charlie":   "male-australian",
    "sarah":     "female-professional",
    "alice":     "female-british-clear",
    "lily":      "female-british-warm",
    "matilda":   "female-american",
    "british":      "male-british",
    "american":     "male-american",
    "female":       "female-british",
    "broadcast":    "male-broadcast",
    "deep":         "male-resonant",
    "smooth":       "male-smooth",
    "gravelly":     "male-gravelly",
    "casual":       "male-casual",
    "australian":   "male-australian",
    "aussie":       "male-australian",
    "professional": "female-professional",
}

_VOICE_LABELS: dict[str, str] = {
    "male-british":         "George (British male)",
    "male-american":        "Adam (American male)",
    "female-british":       "Rachel (British female)",
    "male-broadcast":       "Daniel (broadcast, professional)",
    "male-resonant":        "Brian (resonant, narration)",
    "male-smooth":          "Eric (smooth, conversational)",
    "male-gravelly":        "Callum (gravelly, distinctive)",
    "male-casual":          "Chris (casual, natural American)",
    "male-australian":      "Charlie (Australian, energetic)",
    "female-professional":  "Sarah (professional, warm)",
    "female-british-clear": "Alice (British female, clear)",
    "female-british-warm":  "Lily (British female, warm)",
    "female-american":      "Matilda (American female, professional)",
}


def _handle_jarvis_meta(action: str, params: dict) -> dict:
    if action == "tell_time":
        return _ok(datetime.now().strftime("%I:%M %p").lstrip("0"))

    if action == "tell_date":
        return _ok(datetime.now().strftime("%A, %d %B %Y"))

    if action == "status_report":
        _tlog("❯ status")
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.3)
            mem = psutil.virtual_memory()
            parts = [
                f"CPU {cpu:.0f}%",
                f"memory {mem.percent:.0f}% ({mem.used/1e9:.1f}/{mem.total/1e9:.1f} GB)",
            ]
            try:
                bat = psutil.sensors_battery()
            except (AttributeError, NotImplementedError):
                bat = None
            if bat is not None and bat.percent is not None:
                plug = "plugged in" if bat.power_plugged else "on battery"
                parts.append(f"battery {bat.percent:.0f}% ({plug})")
            # Compact terminal summary uses · separator and rounds battery integer.
            term_parts = [f"CPU {cpu:.0f}%", f"RAM {mem.percent:.0f}%"]
            if bat is not None and bat.percent is not None:
                term_parts.append(f"Battery {bat.percent:.0f}%")
            _tlog("✓ " + " · ".join(term_parts))
            return _ok(", ".join(parts))
        except Exception as exc:
            _tlog(f"✗ {exc}")
            return _err(str(exc))

    if action == "conversational":
        cached = get_page_cache()
        if cached:
            return _ok(cached[:800])
        return _ok("")

    if action == "wipe_memory":
        # Privacy escape hatch — clears in-process conversation history AND
        # the persisted data/memory.jsonl. Response_memory (the spoken-line
        # variety log) is separate and intentionally NOT touched here.
        _tlog("❯ wipe conversation memory")
        try:
            from core.memory import memory as _conv_memory
            count = _conv_memory.exchange_count
            _conv_memory.clear()
            _tlog(f"✓ cleared {count} exchange{'s' if count != 1 else ''}")
            return _ok(
                f"Memory wiped — cleared {count} exchange{'s' if count != 1 else ''}."
            )
        except Exception as exc:
            _tlog(f"✗ {exc}")
            return _err(f"Couldn't clear memory: {exc}")

    if action == "list_voices":
        from core.voice import _EL_VOICES
        _LABELS = {
            "male-british":         "George  — deep, warm British",
            "male-american":        "Adam    — neutral American",
            "female-british":       "Rachel  — warm British female",
            "male-broadcast":       "Daniel  — strong broadcast voice",
            "male-resonant":        "Brian   — resonant, narration",
            "male-smooth":          "Eric    — smooth, conversational",
            "male-gravelly":        "Callum  — gravelly, distinctive",
            "male-casual":          "Chris   — natural, down-to-earth",
            "male-australian":      "Charlie — energetic Australian",
            "female-professional":  "Sarah   — professional, warm",
            "female-british-clear": "Alice   — British female, clear",
            "female-british-warm":  "Lily    — British female, warm",
            "female-american":      "Matilda — professional American female",
        }
        current = config.tts_voice
        lines = ["Available voices (* = current):"]
        for key in _EL_VOICES:
            label = _LABELS.get(key, key)
            marker = " *" if key == current else ""
            lines.append(f"  • {label}{marker}")
        return _ok("\n".join(lines))

    if action == "change_voice":
        raw = (params.get("voice") or "").strip().lower()
        _tlog(f"❯ voice → {raw or '(no voice)'}")
        key = _VOICE_ALIASES.get(raw)
        if not key:
            available = ", ".join(_VOICE_LABELS.values())
            _tlog(f"✗ unknown voice {raw!r}")
            return _err(f"Unknown voice {raw!r}. Available: {available}")
        from core.voice import voice_engine
        ok, msg, _kind = voice_engine.switch_tts_voice(
            key,
            validate_provider=True,
            persist=True,
        )
        if not ok:
            _tlog(f"✗ {msg}")
            return _err(msg)
        name = _VOICE_FIRST_NAMES.get(key, key)
        _tlog("✓ switched")
        # Spoken in the NEW voice — the caller must read output (not Claude's
        # pre-execution response) so the user hears audible proof of the switch.
        return _ok(f"Now {name}'s speaking.")

    if action == "change_theme":
        theme_name = (params.get("theme") or "").strip()
        _tlog(f"❯ theme → {theme_name or '(no theme)'}")
        # The actual theme switch is wired upstream via a signal — this handler
        # just acknowledges so the response pipeline can fire its confirmation TTS.
        _tlog("✓ applied")
        return _ok(action)

    if action in ("quit_application", "close_jarvis"):
        _tlog("❯ shutting down JARVIS")
        _tlog("✓ goodbye")
        return {"success": True, "output": "", "error": "", "quit_application": True}

    return _ok(action)


def _handle_unknown(action: str, params: dict) -> dict:
    return _err("Intent not recognised")
