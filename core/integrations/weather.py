"""OpenWeather integration helpers."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from config.settings import config


class WeatherClientError(Exception):
    """Raised when the weather provider cannot satisfy a request."""


# OpenWeather returns a 2-letter ISO 3166-1 country code; spoken verbatim it
# reads as letters ("K W"). Map the common ones to full names for TTS; unknown
# codes fall back to the raw code (no regression, just no expansion).
_COUNTRY_NAMES: dict[str, str] = {
    "US": "United States", "GB": "United Kingdom", "UK": "United Kingdom",
    "CA": "Canada", "AU": "Australia", "NZ": "New Zealand", "IE": "Ireland",
    "FR": "France", "DE": "Germany", "ES": "Spain", "PT": "Portugal",
    "IT": "Italy", "NL": "Netherlands", "BE": "Belgium", "CH": "Switzerland",
    "AT": "Austria", "SE": "Sweden", "NO": "Norway", "DK": "Denmark",
    "FI": "Finland", "IS": "Iceland", "PL": "Poland", "CZ": "Czechia",
    "GR": "Greece", "HU": "Hungary", "RO": "Romania", "BG": "Bulgaria",
    "UA": "Ukraine", "RU": "Russia", "TR": "Turkey", "HR": "Croatia",
    "RS": "Serbia", "SK": "Slovakia", "SI": "Slovenia", "LT": "Lithuania",
    "LV": "Latvia", "EE": "Estonia", "LU": "Luxembourg",
    "CN": "China", "JP": "Japan", "KR": "South Korea", "KP": "North Korea",
    "IN": "India", "PK": "Pakistan", "BD": "Bangladesh", "LK": "Sri Lanka",
    "TH": "Thailand", "VN": "Vietnam", "PH": "the Philippines", "ID": "Indonesia",
    "MY": "Malaysia", "SG": "Singapore", "HK": "Hong Kong", "TW": "Taiwan",
    "AE": "the United Arab Emirates", "SA": "Saudi Arabia", "QA": "Qatar",
    "KW": "Kuwait", "BH": "Bahrain", "OM": "Oman", "JO": "Jordan",
    "LB": "Lebanon", "IL": "Israel", "IQ": "Iraq", "IR": "Iran",
    "EG": "Egypt", "MA": "Morocco", "DZ": "Algeria", "TN": "Tunisia",
    "LY": "Libya", "SD": "Sudan", "NG": "Nigeria", "GH": "Ghana",
    "LR": "Liberia", "SL": "Sierra Leone", "CI": "Ivory Coast", "SN": "Senegal",
    "KE": "Kenya", "TZ": "Tanzania", "UG": "Uganda", "ET": "Ethiopia",
    "ZA": "South Africa", "ZW": "Zimbabwe", "ZM": "Zambia", "CM": "Cameroon",
    "BR": "Brazil", "AR": "Argentina", "CL": "Chile", "CO": "Colombia",
    "PE": "Peru", "VE": "Venezuela", "MX": "Mexico", "EC": "Ecuador",
    "UY": "Uruguay", "BO": "Bolivia", "PY": "Paraguay", "CU": "Cuba",
}


def _country_name(code: str) -> str:
    """Full country name for a 2-letter ISO code; the raw code if unmapped."""
    code = (code or "").strip()
    return _COUNTRY_NAMES.get(code.upper(), code)


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
    country = _country_name(str(snapshot.get("country") or "").strip())
    where = f"{place}, {country}" if country else place
    condition = str(snapshot.get("description") or snapshot.get("condition") or "unknown conditions")

    temp = snapshot.get("temp_c")
    feels = snapshot.get("feels_like_c")
    humidity = snapshot.get("humidity")
    wind = snapshot.get("wind_mps")

    # Spell units out — this string is spoken verbatim by TTS (weather is an
    # output-is-response intent). A "°" / "C" / "%" / "m/s" glyph reads wrong or
    # silent across the tiers (ElevenLabs v3 normalization isn't guaranteed, the
    # pyttsx3 SAPI fallback won't voice "°" as "degrees"), so write the words.
    parts = [f"Weather in {where}: {condition}"]
    if temp is not None:
        parts.append(f"{round(float(temp))} degrees Celsius")
    if feels is not None:
        parts.append(f"feels like {round(float(feels))} degrees")
    if humidity is not None:
        parts.append(f"humidity {int(humidity)} percent")
    if wind is not None:
        parts.append(f"wind {float(wind):.1f} meters per second")
    return ", ".join(parts)
