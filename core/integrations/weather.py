"""OpenWeather integration helpers."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from config.settings import config


class WeatherClientError(Exception):
    """Raised when the weather provider cannot satisfy a request."""


def _api_key() -> str:
    key = (config.openweather_api_key or "").strip()
    if not key:
        raise WeatherClientError("OpenWeather API key is missing. Add OPENWEATHER_API_KEY to .env.")
    return key


def _default_city() -> str:
    city = (config.weather_default_city or "").strip()
    return city or "Monrovia,LR"


def get_current_weather(location: str | None = None, *, timeout: int = 8) -> dict:
    city = (location or "").strip() or _default_city()
    params = {
        "q": city,
        "appid": _api_key(),
        "units": "metric",
    }
    url = "https://api.openweathermap.org/data/2.5/weather?" + urlencode(params)

    try:
        with urlopen(url, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        body = (exc.read() or b"").decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("message") or body or str(exc)
        except Exception:
            detail = body or str(exc)
        raise WeatherClientError(f"OpenWeather error: {detail}") from exc
    except URLError as exc:
        raise WeatherClientError(f"Weather request failed: {exc.reason}") from exc
    except Exception as exc:
        raise WeatherClientError(f"Weather request failed: {exc}") from exc

    weather_list = payload.get("weather") or [{}]
    main = payload.get("main") or {}
    wind = payload.get("wind") or {}

    return {
        "location": payload.get("name") or city,
        "country": (payload.get("sys") or {}).get("country", ""),
        "condition": weather_list[0].get("main", "Unknown"),
        "description": weather_list[0].get("description", ""),
        "temp_c": main.get("temp"),
        "feels_like_c": main.get("feels_like"),
        "humidity": main.get("humidity"),
        "wind_mps": wind.get("speed"),
    }


def format_current_weather(snapshot: dict) -> str:
    place = str(snapshot.get("location") or "Unknown location").strip()
    country = str(snapshot.get("country") or "").strip()
    where = f"{place}, {country}" if country else place
    condition = str(snapshot.get("description") or snapshot.get("condition") or "unknown conditions")

    temp = snapshot.get("temp_c")
    feels = snapshot.get("feels_like_c")
    humidity = snapshot.get("humidity")
    wind = snapshot.get("wind_mps")

    parts = [f"Weather in {where}: {condition}"]
    if temp is not None:
        parts.append(f"{round(float(temp))}C")
    if feels is not None:
        parts.append(f"feels like {round(float(feels))}C")
    if humidity is not None:
        parts.append(f"humidity {int(humidity)}%")
    if wind is not None:
        parts.append(f"wind {float(wind):.1f} m/s")
    return ", ".join(parts)
