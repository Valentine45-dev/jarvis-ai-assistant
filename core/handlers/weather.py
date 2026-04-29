"""Handlers: weather intent."""

from __future__ import annotations

from core.handlers.shared import _err, _ok
from core.integrations.weather import (
    WeatherClientError,
    format_current_weather,
    get_current_weather,
)


def _handle_weather(action: str, params: dict) -> dict:
    if action != "get_current_weather":
        return _err(f"Unsupported weather action: {action}")

    location = (
        params.get("location")
        or params.get("city")
        or params.get("place")
        or ""
    )
    try:
        snapshot = get_current_weather(str(location).strip() or None)
    except WeatherClientError as exc:
        return _err(str(exc))
    return _ok(format_current_weather(snapshot))
