"""Handlers: weather intent."""

from __future__ import annotations

from core import log as _log
from core.handlers.shared import _err, _ok, _tlog
from core.integrations.weather import (
    WeatherClientError,
    format_current_weather,
    format_forecast,
    get_current_weather,
    get_forecast,
)


def _handle_weather(action: str, params: dict) -> dict:
    if action not in ("get_current_weather", "get_forecast"):
        _tlog(f"✗ unsupported weather action: {action}")
        return _err(f"Unsupported weather action: {action}")

    location = (
        params.get("location")
        or params.get("city")
        or params.get("place")
        or ""
    )
    loc_str = str(location).strip()

    # Forecast (tomorrow / today / "will it rain") — native path so a forecast
    # query never falls back to code_execution (writing pytz/urllib by hand).
    if action == "get_forecast":
        when = str(params.get("when") or params.get("day") or "tomorrow").strip() or "tomorrow"
        _tlog(f"❯ forecast → {loc_str or 'default location'} ({when})")
        try:
            forecast = get_forecast(loc_str or None, when)
        except WeatherClientError as exc:
            _tlog(f"✗ {exc}")
            return _err(str(exc))
        try:
            tmax = forecast.get("temp_max_c")
            cond = forecast.get("description") or ""
            bits = [str(forecast.get("when") or "")]
            if tmax is not None:
                bits.append(f"{round(float(tmax))}C")
            if cond:
                bits.append(str(cond))
            _tlog("✓ " + ", ".join(b for b in bits if b))
        except (TypeError, ValueError, AttributeError):
            _tlog("✓ done")
        return _ok(format_forecast(forecast))

    _tlog(f"❯ weather → {loc_str or 'default location'}")
    try:
        snapshot = get_current_weather(loc_str or None)
    except WeatherClientError as exc:
        _tlog(f"✗ {exc}")
        return _err(str(exc))

    # Pull a short {temp}, {condition} summary for the terminal line without
    # depending on format_current_weather's exact prose output.
    # R2-22: narrowed from bare `Exception` to the three exceptions actually
    # raised here (snapshot.get returning a non-numeric, round/float on garbage,
    # missing attribute on a non-dict snapshot). Anything else propagates and
    # surfaces in the executor's R2-12 traceback log.
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
    except (TypeError, ValueError, AttributeError) as exc:
        _log.debug("weather", f"summary line skipped: {exc!r}")
        _tlog("✓ done")
    return _ok(format_current_weather(snapshot))
