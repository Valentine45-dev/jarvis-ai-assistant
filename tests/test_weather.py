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
    assert "Weather in Accra, GH" in out["output"]


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


def test_handle_weather_unknown_action():
    out = _handle_weather("forecast", {})
    assert out["success"] is False
    assert "Unsupported weather action" in out["error"]


def test_handle_weather_missing_key(monkeypatch):
    monkeypatch.setattr(weather_mod.config, "openweather_api_key", "")
    out = _handle_weather("get_current_weather", {"location": "Monrovia"})
    assert out["success"] is False
    assert "OPENWEATHER_API_KEY" in out["error"]
