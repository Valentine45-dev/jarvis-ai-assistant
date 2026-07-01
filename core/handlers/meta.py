"""Handlers: jarvis_meta, unknown."""

from __future__ import annotations

import random
from datetime import datetime

from config.settings import config
from core.handlers.shared import _ok, _err, _tlog, request_confirmation


# Pool of programmer / dry-wit one-liners for jarvis_meta.tell_joke.
# Per CLAUDE.md: pick fresh each time; do NOT default to the dark-mode joke.
_JARVIS_JOKES: tuple[str, ...] = (
    "I would tell you a UDP joke, but you might not get it.",
    "There are 10 kinds of people in this world — those who understand binary and those who don't.",
    "I told my computer I needed a break. It froze on me.",
    "Why did the developer go broke? Used up all his cache.",
    "Knock knock. … … … Race condition.",
    "Two bytes meet. One says, 'You look ill.' The other replies, 'I have a parity error.'",
    "A SQL query walks into a bar, walks up to two tables and asks, 'May I join you?'",
    "I named my home Wi-Fi 'The Promised LAN'.",
    "Floating point joke: it's only ever approximately funny.",
    "Why did the function break up with the variable? It wasn't in scope.",
    "Old programmers never die — they just decompile.",
    "If you put a million monkeys at a million keyboards, you'd get Stack Overflow.",
)


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


# Curated common-city → IANA fallback for tell_time when the brain emits a bare
# city name instead of an IANA zone. The brain is instructed (Claude.md §12) to
# prefer the IANA zone directly, so this is only a safety net — it does NOT need
# to be exhaustive. Unknown → honest error (never a silent local-time substitute).
_CITY_TZ: dict[str, str] = {
    "tokyo": "Asia/Tokyo", "japan": "Asia/Tokyo",
    "london": "Europe/London", "uk": "Europe/London",
    "paris": "Europe/Paris", "berlin": "Europe/Berlin", "madrid": "Europe/Madrid",
    "rome": "Europe/Rome", "moscow": "Europe/Moscow",
    "dubai": "Asia/Dubai",
    "delhi": "Asia/Kolkata", "new delhi": "Asia/Kolkata", "mumbai": "Asia/Kolkata",
    "india": "Asia/Kolkata",
    "beijing": "Asia/Shanghai", "shanghai": "Asia/Shanghai", "china": "Asia/Shanghai",
    "hong kong": "Asia/Hong_Kong", "singapore": "Asia/Singapore", "seoul": "Asia/Seoul",
    "sydney": "Australia/Sydney", "melbourne": "Australia/Melbourne",
    "new york": "America/New_York", "nyc": "America/New_York",
    "washington": "America/New_York",
    "chicago": "America/Chicago", "houston": "America/Chicago",
    "denver": "America/Denver",
    "los angeles": "America/Los_Angeles", "la": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles", "seattle": "America/Los_Angeles",
    "toronto": "America/Toronto", "sao paulo": "America/Sao_Paulo",
    "mexico city": "America/Mexico_City",
    "monrovia": "Africa/Monrovia", "lagos": "Africa/Lagos", "accra": "Africa/Accra",
    "cairo": "Africa/Cairo", "nairobi": "Africa/Nairobi",
    "johannesburg": "Africa/Johannesburg",
    "utc": "UTC", "gmt": "Etc/GMT",
}


def _resolve_timezone(location: str):
    """Resolve a location string to a ZoneInfo, or None if unknown.

    IANA-first (the brain emits e.g. "Asia/Tokyo" for any city it knows), then the
    curated common-city map for a bare city name, then None — the caller reports an
    honest 'unknown zone' rather than silently substituting local time (which would
    be a new fake-success). Needs the `tzdata` package on Windows (zoneinfo has no
    system IANA db there); it is a declared dependency.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    raw = (location or "").strip()
    if not raw:
        return None
    try:
        return ZoneInfo(raw)  # "Asia/Tokyo", "America/New_York", "UTC"
    except (ZoneInfoNotFoundError, ValueError):
        pass
    iana = _CITY_TZ.get(raw.lower().replace("_", " "))
    if not iana:
        return None
    try:
        return ZoneInfo(iana)
    except (ZoneInfoNotFoundError, ValueError):
        return None


# HUD accent themes. The real palette keys live in ui/theme.py `_THEME_PALETTES`
# (kept in sync here so the handler layer needs no Qt import). Aliases map common
# spoken colour names onto a real palette; anything else is an honest "unknown
# theme" (never a silent fallback that fakes success). Theme changes follow the
# wake-word convention: persisted to jarvis.json + applied on restart (live
# in-session re-theming is a separate parked refactor).
_VALID_THEMES: frozenset[str] = frozenset({"cyan", "teal", "amber", "indigo", "matrix"})
_THEME_ALIASES: dict[str, str] = {
    "gold": "amber", "yellow": "amber", "orange": "amber",
    "green": "matrix", "emerald": "matrix",
    "blue": "indigo", "purple": "indigo", "violet": "indigo",
    "turquoise": "teal", "aqua": "cyan", "default": "cyan",
}
_THEME_OPTIONS = "cyan, teal, amber, indigo, matrix"


def _handle_jarvis_meta(action: str, params: dict) -> dict:
    if action == "tell_time":
        location = (params.get("location") or "").strip()
        if not location:
            return _ok(datetime.now().strftime("%I:%M %p").lstrip("0"))
        tz = _resolve_timezone(location)
        if tz is None:
            return _err(f"I don't recognize the timezone for {location!r}.")
        # Friendly display name: strip the IANA area prefix and underscores
        # ("Asia/Tokyo" → "Tokyo", "America/New_York" → "New York").
        display = location.split("/")[-1].replace("_", " ") if "/" in location else location
        now = datetime.now(tz).strftime("%I:%M %p").lstrip("0")
        return _ok(f"{now} in {display}")

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
        # P3 BUG A: do NOT dump the raw page cache here. Returning the scrape
        # verbatim overrode the brain's own synthesized answer (see the
        # conversational branch in response_composer) — so a "summarize the
        # search" turn read the literal "--- Page content ---" dump aloud, and a
        # stale cache leaked into unrelated questions. Return empty so the
        # composer falls through to the brain's `resp`, which the brain writes
        # FROM the injected <page_content> (Claude.md §3 grounding rule):
        # synthesis, not a raw dump.
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

    if action == "forget_memory":
        # Selective wipe — delete only the exchanges about a specific topic,
        # keeping the rest of the conversation. Previews the matches and confirms
        # before deleting (the handler owns the confirm card, like file-ops).
        query = (params.get("query") or "").strip()
        if not query:
            return _err(
                "What should I forget? Name the topic — e.g. "
                "'forget what my brother said about X'."
            )
        _tlog(f"❯ forget memory about {query!r}")
        try:
            from core.memory import memory as _conv_memory
            matches = _conv_memory.find_exchanges(query)
            if not matches:
                _tlog("✓ nothing matched")
                return _ok(f"No memory about '{query}' found — nothing to forget.")

            def _forget_now() -> dict:
                removed = _conv_memory.forget_exchanges(matches)
                _tlog(f"✓ forgot {removed} exchange{'s' if removed != 1 else ''}")
                return _ok(
                    f"Forgotten — removed {removed} "
                    f"exchange{'s' if removed != 1 else ''} about '{query}'."
                )

            n = len(matches)
            preview = "\n".join(f"  • {m['preview']}" for m in matches[:5])
            more = f"\n  …and {n - 5} more" if n > 5 else ""
            prompt = (
                f"Forget {n} exchange{'s' if n != 1 else ''} about '{query}'? "
                f"The rest of our conversation stays.\n\n{preview}{more}"
            )
            result = request_confirmation(prompt, _forget_now)
            result.update({"confirm_type": "forget_memory", "subject": query})
            return result
        except Exception as exc:
            _tlog(f"✗ {exc}")
            return _err(f"Couldn't forget that memory: {exc}")

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
        raw = (params.get("theme") or "").strip().lower()
        _tlog(f"❯ theme → {raw or '(no theme)'}")
        # P7 (fake-success #3): this used to return _ok without persisting or
        # applying ANYTHING — the theme never changed. Now it validates against
        # the real palettes, persists config.theme, and reports honestly that a
        # restart applies it (the documented wake-word convention). An unknown
        # theme is an honest error, not a silent fallback dressed as success.
        if not raw:
            _tlog("✗ no theme provided")
            return _err(f"Which theme? Options: {_THEME_OPTIONS}.")
        theme_key = raw if raw in _VALID_THEMES else _THEME_ALIASES.get(raw)
        if not theme_key:
            _tlog(f"✗ unknown theme {raw!r}")
            return _err(f"'{raw}' isn't a theme I have. Options: {_THEME_OPTIONS}.")
        old = getattr(config, "theme", "cyan")
        config.theme = theme_key
        try:
            config.save()
        except Exception as exc:
            config.theme = old
            _tlog(f"✗ persist failed: {exc}")
            return _err(f"Couldn't save the theme: {exc}")
        _tlog(f"✓ theme → {theme_key} (restart required)")
        return _ok(f"Theme set to {theme_key}. Restart JARVIS to see it applied.")

    if action in ("quit_application", "close_jarvis"):
        _tlog("❯ shutting down JARVIS")
        _tlog("✓ goodbye")
        return {"success": True, "output": "", "error": "", "quit_application": True}

    if action == "who_are_you":
        _tlog("❯ identity")
        user_name = (getattr(config, "user_name", None) or "Valentine").strip() or "Valentine"
        _tlog("✓ replied")
        return _ok(
            f"I am JARVIS — Just A Rather Very Intelligent System. "
            f"At your service, {user_name}."
        )

    if action == "tell_joke":
        _tlog("❯ tell joke")
        joke = random.choice(_JARVIS_JOKES)
        _tlog("✓ told")
        return _ok(joke)

    if action == "help":
        _tlog("❯ help")
        lines = (
            "I'm JARVIS — here's what I can do:",
            "  • Apps & web: open / close / search (Google, YouTube, GitHub, Wikipedia).",
            "  • Browser: navigate, click, fill forms, scroll, screenshot, tab management.",
            "  • Files: create / read / edit / move / rename / delete / search / grep.",
            "  • System: volume, brightness, screenshot, lock, sleep / restart / shutdown.",
            "  • Vision: describe screen, read text, find UI elements.",
            "  • Reminders, weather, automation workflows.",
            "  • Documents: Word, Excel, PowerPoint, PDF.",
            "  • Code: run Python / shell / PowerShell / CMD; install packages.",
            "  • Voice: switch voices, change theme, set wake word.",
            "Use @tags to force an intent — e.g. @browser, @files, @system, @code.",
            "Say 'help with X' for more on a specific area.",
        )
        _tlog("✓ shown")
        return _ok("\n".join(lines))

    if action == "set_wake_word":
        new_word = (params.get("wake_word") or params.get("word") or "").strip()
        _tlog(f"❯ set wake word → {new_word!r}")
        if not new_word:
            _tlog("✗ no wake word provided")
            return _err("No wake word provided.")
        # Sanity-check: short, single token, alphanumeric-ish.
        if len(new_word.split()) > 1:
            _tlog("✗ multi-word wake word rejected")
            return _err("Wake word must be a single word.")
        if not new_word.replace("-", "").replace("_", "").isalnum():
            _tlog("✗ invalid characters")
            return _err("Wake word must be alphanumeric (hyphens / underscores allowed).")
        old = config.wake_word
        config.wake_word = new_word.lower()
        try:
            config.save()
        except Exception as exc:
            config.wake_word = old
            _tlog(f"✗ persist failed: {exc}")
            return _err(f"Couldn't persist wake word: {exc}")
        _tlog(f"✓ wake word → {new_word!r} (restart required)")
        return _ok(
            f"Wake word changed to '{new_word.lower()}'. "
            f"Restart JARVIS for the listener to pick it up."
        )

    return _err(f"Unknown jarvis_meta action: {action!r}")


def _handle_unknown(action: str, params: dict) -> dict:
    return _err("Intent not recognised")
