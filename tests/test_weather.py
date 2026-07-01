"""Unit tests for weather integration + handler."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core.handlers.weather as weather_handler
from core.handlers.weather import _handle_weather
from core.integrations import weather as weather_mod


class _FakeResp:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_get_current_weather_parses_payload(monkeypatch):
    monkeypatch.setattr(weather_mod.config, "openweather_api_key", "test-key")
    monkeypatch.setattr(weather_mod.config, "weather_default_city", "Monrovia,LR")

    payload = {
        "name": "Monrovia",
        "sys": {"country": "LR"},
        "weather": [{"main": "Clouds", "description": "broken clouds"}],
        "main": {"temp": 27.6, "feels_like": 30.1, "humidity": 84},
        "wind": {"speed": 3.2},
    }
    monkeypatch.setattr(weather_mod, "urlopen", lambda *args, **kwargs: _FakeResp(payload))

    snap = weather_mod.get_current_weather()
    assert snap["location"] == "Monrovia"
    assert snap["country"] == "LR"
    assert snap["description"] == "broken clouds"
    assert snap["humidity"] == 84


def test_geocoding_resolves_country_to_real_city(monkeypatch):
    # 'India' (a country) fuzzy-matches to a random village via the weather q=
    # param; geocoding resolves it to a real city and we query by coords instead.
    monkeypatch.setattr(weather_mod.config, "openweather_api_key", "test-key")
    monkeypatch.setattr(weather_mod.config, "weather_default_city", "Monrovia,LR")
    geo = [{"name": "New Delhi", "lat": 28.61, "lon": 77.21, "country": "IN"}]
    wx = {
        "name": "New Delhi", "sys": {"country": "IN"},
        "weather": [{"main": "Haze", "description": "haze"}],
        "main": {"temp": 40, "feels_like": 42, "humidity": 20}, "wind": {"speed": 2.0},
    }

    def _fake(url, *a, **k):
        return _FakeResp(geo if "geo/1.0" in url else wx)

    monkeypatch.setattr(weather_mod, "urlopen", _fake)
    snap = weather_mod.get_current_weather("India")
    assert snap["location"] == "New Delhi"   # a real city, not a fuzzy q= village
    assert snap["country"] == "IN"
    assert snap["temp_c"] == 40


def test_geocode_miss_falls_back_to_q(monkeypatch):
    # geocoding returns [] (no match) -> the q= city path still works, no crash
    monkeypatch.setattr(weather_mod.config, "openweather_api_key", "test-key")
    monkeypatch.setattr(weather_mod.config, "weather_default_city", "Monrovia,LR")
    wx = {
        "name": "Monrovia", "sys": {"country": "LR"},
        "weather": [{"main": "Rain", "description": "light rain"}],
        "main": {"temp": 25}, "wind": {"speed": 5},
    }

    def _fake(url, *a, **k):
        return _FakeResp([] if "geo/1.0" in url else wx)

    monkeypatch.setattr(weather_mod, "urlopen", _fake)
    snap = weather_mod.get_current_weather("Monrovia")
    assert snap["location"] == "Monrovia"
    assert snap["temp_c"] == 25


def test_handle_weather_success(monkeypatch):
    monkeypatch.setattr(
        weather_handler,
        "get_current_weather",
        lambda location=None, timeout=8: {
            "location": "Accra",
            "country": "GH",
            "description": "clear sky",
            "condition": "Clear",
            "temp_c": 29,
            "feels_like_c": 31,
            "humidity": 73,
            "wind_mps": 2.1,
        },
    )

    out = _handle_weather("get_current_weather", {"location": "Accra"})
    assert out["success"] is True
    # Country code GH is expanded to a spoken-friendly full name.
    assert "Weather in Accra, Ghana" in out["output"]


def test_country_code_expanded_to_full_name():
    # Known code -> full name (so TTS doesn't spell out "K W").
    out = weather_mod.format_current_weather(
        {"location": "Kuwait City", "country": "KW", "description": "clear sky"}
    )
    assert "Weather in Kuwait City, Kuwait" in out
    assert ", KW" not in out


def test_unknown_country_code_falls_back_to_code():
    # Unmapped code is kept as-is (no crash, no regression).
    out = weather_mod.format_current_weather(
        {"location": "Nowhere", "country": "ZZ", "description": "clear sky"}
    )
    assert "Weather in Nowhere, ZZ" in out


def test_format_spells_out_units_for_tts():
    # The weather string is spoken verbatim — units must be words, not glyphs,
    # so TTS doesn't say "41 C" or drop the degree symbol entirely.
    out = weather_mod.format_current_weather({
        "location": "Kuwait City",
        "country": "KW",
        "description": "clear sky",
        "temp_c": 41,
        "feels_like_c": 40,
        "humidity": 19,
        "wind_mps": 9.6,
    })
    assert "41 degrees Celsius" in out
    assert "feels like 40 degrees" in out
    assert "19 percent" in out
    assert "9.6 meters per second" in out
    # No raw glyphs that TTS mangles.
    for glyph in ("°", "41C", "40C", "19%", "m/s"):
        assert glyph not in out


def _forecast_payload(temps, *, desc="light rain", pop=0.6, tz=0, days_ahead=1):
    """Build an OpenWeather /forecast payload whose steps land on the target local
    day (default: tomorrow, UTC)."""
    from datetime import datetime, timedelta, timezone

    target = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).date()
    lst = []
    for i, t in enumerate(temps):
        dt = datetime(target.year, target.month, target.day, 6 + i * 3, tzinfo=timezone.utc)
        lst.append({
            "dt": int(dt.timestamp()),
            "main": {"temp": t},
            "weather": [{"description": desc}],
            "pop": pop,
        })
    return {"city": {"name": "Monrovia", "country": "LR", "timezone": tz}, "list": lst}


def test_get_forecast_aggregates_tomorrow(monkeypatch):
    monkeypatch.setattr(weather_mod.config, "openweather_api_key", "test-key")
    monkeypatch.setattr(weather_mod.config, "weather_default_city", "Monrovia,LR")
    payload = _forecast_payload([24, 28, 22], desc="light rain", pop=0.6)
    monkeypatch.setattr(weather_mod, "urlopen", lambda *a, **k: _FakeResp(payload))

    f = weather_mod.get_forecast(when="tomorrow")
    assert f["when"] == "tomorrow"
    assert f["temp_min_c"] == 22 and f["temp_max_c"] == 28
    assert f["description"] == "light rain"
    assert f["rain_chance"] == 60


def test_format_forecast_spoken_units():
    out = weather_mod.format_forecast({
        "location": "Monrovia", "country": "LR", "when": "tomorrow",
        "description": "light rain", "temp_min_c": 22, "temp_max_c": 28, "rain_chance": 60,
    })
    assert "Forecast for Monrovia, Liberia tomorrow" in out
    assert "between 22 and 28 degrees Celsius" in out
    assert "60 percent chance of rain" in out
    for glyph in ("°", "28C", "%"):
        assert glyph not in out


def test_handle_weather_forecast_success(monkeypatch):
    monkeypatch.setattr(
        weather_handler, "get_forecast",
        lambda location=None, when="tomorrow", timeout=8: {
            "location": "Accra", "country": "GH", "when": "tomorrow",
            "description": "clear sky", "temp_min_c": 25, "temp_max_c": 31, "rain_chance": 10,
        },
    )
    out = _handle_weather("get_forecast", {"location": "Accra", "when": "tomorrow"})
    assert out["success"] is True
    assert "Forecast for Accra, Ghana tomorrow" in out["output"]


def test_handle_weather_unknown_action():
    out = _handle_weather("forecast", {})   # bare 'forecast' is still unsupported
    assert out["success"] is False
    assert "Unsupported weather action" in out["error"]


def test_handle_weather_missing_key(monkeypatch):
    monkeypatch.setattr(weather_mod.config, "openweather_api_key", "")
    out = _handle_weather("get_current_weather", {"location": "Monrovia"})
    assert out["success"] is False
    assert "OPENWEATHER_API_KEY" in out["error"]
