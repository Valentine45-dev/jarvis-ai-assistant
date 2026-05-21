"""Handlers: weather intent."""

from __future__ import annotations

from core.handlers.shared import _err, _ok, _tlog
from core.integrations.weather import (
    WeatherClientError,
    format_current_weather,
    get_current_weather,
)


def _handle_weather(action: str, params: dict) -> dict:
    if action != "get_current_weather":
        _tlog(f"✗ unsupported weather action: {action}")
        return _err(f"Unsupported weather action: {action}")

    location = (
        params.get("location")
        or params.get("city")
        or params.get("place")
        or ""
    )
    loc_str = str(location).strip()
    _tlog(f"❯ weather → {loc_str or 'default location'}")
    try:
        snapshot = get_current_weather(loc_str or None)
    except WeatherClientError as exc:
        _tlog(f"✗ {exc}")
        return _err(str(exc))

    # Pull a short {temp}, {condition} summary for the terminal line without
    # depending on format_current_weather's exact prose output.
    try:
        if isinstance(snapshot, dict):
            temp_c = snapshot.get("temp_c")
            cond = snapshot.get("description") or snapshot.get("condition") or ""
            parts: list[str] = []
            if temp_c is not None:
                parts.append(f"{round(float(temp_c))}C")
            if cond:
                parts.append(str(cond))
            _tlog(f"✓ {', '.join(parts)}" if parts else "✓ done")
        else:
            _tlog("✓ done")
    except Exception:
        _tlog("✓ done")
    return _ok(format_current_weather(snapshot))
