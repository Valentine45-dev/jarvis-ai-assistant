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


def _fetch(endpoint: str, query: dict, timeout: int) -> dict:
    """GET an OpenWeather 2.5 endpoint ('weather' | 'forecast') as JSON.

    `query` is the location selector — {"q": city} or {"lat":…, "lon":…}. Shared
    by current + forecast so the auth/units/error handling lives in one place.
    Raises WeatherClientError with a human message on any failure.
    """
    params = {**query, "appid": _api_key(), "units": "metric"}
    url = f"https://api.openweathermap.org/data/2.5/{endpoint}?" + urlencode(params)
    try:
        with urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
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


def _geocode(name: str, timeout: int) -> dict | None:
    """Resolve a place name to coordinates via OpenWeather direct geocoding.

    Returns {'lat','lon','name','country'} or None (caller falls back to a q=
    city query). Geocoding is far more reliable than the weather `q=` param, which
    fuzzy-matches a bare COUNTRY name to a random village (e.g. 'India' → a hamlet
    in Italy). Any geocoding failure is non-fatal — we degrade to the q= path.
    """
    params = {"q": name, "limit": 1, "appid": _api_key()}
    url = "https://api.openweathermap.org/geo/1.0/direct?" + urlencode(params)
    try:
        with urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None
    if not isinstance(data, list) or not data:
        return None
    top = data[0] or {}
    if top.get("lat") is None or top.get("lon") is None:
        return None
    return {
        "lat": top["lat"], "lon": top["lon"],
        "name": top.get("name") or name, "country": top.get("country", ""),
    }


def _resolve_query(name: str, timeout: int) -> tuple[dict, str | None, str | None]:
    """(query_params, display_name, display_country) for a place name — geocoded
    coords when available, else a q= city query."""
    geo = _geocode(name, timeout)
    if geo:
        return {"lat": geo["lat"], "lon": geo["lon"]}, geo["name"], geo["country"]
    return {"q": name}, None, None


def get_current_weather(location: str | None = None, *, timeout: int = 8) -> dict:
    name = (location or "").strip() or _default_city()
    query, geo_name, geo_country = _resolve_query(name, timeout)
    payload = _fetch("weather", query, timeout)

    weather_list = payload.get("weather") or [{}]
    main = payload.get("main") or {}
    wind = payload.get("wind") or {}

    return {
        "location": geo_name or payload.get("name") or name,
        "country": geo_country or (payload.get("sys") or {}).get("country", ""),
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


def get_forecast(location: str | None = None, when: str = "tomorrow", *, timeout: int = 8) -> dict:
    """Daily forecast summary from OpenWeather's free 5-day/3-hour endpoint.

    Aggregates the 3-hour steps for the target local day (in the CITY's timezone —
    'tomorrow' means tomorrow where the weather is, not where the user is) into
    min/max temp, the dominant condition, and the peak rain probability. `when`
    accepts 'today' or 'tomorrow' (anything else → tomorrow). If the target day
    isn't in the 5-day window, falls back to the soonest available day.
    """
    import time
    from collections import Counter
    from datetime import datetime, timedelta, timezone

    name = (location or "").strip() or _default_city()
    query, geo_name, geo_country = _resolve_query(name, timeout)
    payload = _fetch("forecast", query, timeout)

    city_info = payload.get("city") or {}
    tz_offset = int(city_info.get("timezone", 0) or 0)   # seconds east of UTC
    items = payload.get("list") or []
    if not items:
        raise WeatherClientError("No forecast data was returned.")

    def _local_date(unix_dt: int):
        # shift the UTC instant by the city offset, then read the wall date
        return datetime.fromtimestamp(int(unix_dt) + tz_offset, timezone.utc).date()

    by_date: dict = {}
    for it in items:
        dt = it.get("dt")
        if dt is None:
            continue
        by_date.setdefault(_local_date(dt), []).append(it)

    delta = 0 if "today" in (when or "").lower() else 1
    city_today = datetime.fromtimestamp(time.time() + tz_offset, timezone.utc).date()
    target = city_today + timedelta(days=delta)
    if target not in by_date:
        # target beyond the window (or no steps left today) → soonest future day
        future = sorted(d for d in by_date if d >= city_today)
        target = future[0] if future else sorted(by_date)[0]
    day_items = by_date[target]

    temps = [
        float(it["main"]["temp"]) for it in day_items
        if isinstance(it.get("main"), dict) and it["main"].get("temp") is not None
    ]
    conditions = [
        (it.get("weather") or [{}])[0].get("description", "") for it in day_items
    ]
    pops = [float(it.get("pop") or 0.0) for it in day_items]
    dominant = Counter([c for c in conditions if c]).most_common(1)

    return {
        "location": geo_name or city_info.get("name") or name,
        "country": geo_country or city_info.get("country", ""),
        "when": "today" if target == city_today else ("tomorrow" if target == city_today + timedelta(days=1) else target.isoformat()),
        "date": target.isoformat(),
        "temp_min_c": min(temps) if temps else None,
        "temp_max_c": max(temps) if temps else None,
        "description": dominant[0][0] if dominant else "unknown conditions",
        "rain_chance": round(max(pops) * 100) if pops else None,
    }


def format_forecast(f: dict) -> str:
    """Spoken forecast line — units spelled out (same reasoning as
    format_current_weather: this string is read verbatim by TTS)."""
    place = str(f.get("location") or "Unknown location").strip()
    country = _country_name(str(f.get("country") or "").strip())
    where = f"{place}, {country}" if country else place
    when = str(f.get("when") or "tomorrow")
    cond = str(f.get("description") or "unknown conditions")

    tmin = f.get("temp_min_c")
    tmax = f.get("temp_max_c")
    rain = f.get("rain_chance")

    parts = [f"Forecast for {where} {when}: {cond}"]
    if tmin is not None and tmax is not None:
        parts.append(f"between {round(float(tmin))} and {round(float(tmax))} degrees Celsius")
    elif tmax is not None:
        parts.append(f"around {round(float(tmax))} degrees Celsius")
    if rain is not None:
        parts.append(f"{int(rain)} percent chance of rain")
    return ", ".join(parts)
