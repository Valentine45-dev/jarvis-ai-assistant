"""Priority 2 — timezone-aware tell_time (no more code_execution/pytz fallback).

Bug (sweep find): "time in Tokyo?" had no jarvis_meta path (tell_time was local-only),
so the brain fell back to code_execution writing `import pytz` → ModuleNotFoundError →
an offered `pip install pytz` fix whose subprocess hit the 60s stream cap. tell_time now
answers any zone instantly via the stdlib `zoneinfo` (+ the declared `tzdata` dependency
so it works on Windows, which ships no system IANA db).

Design (approved): IANA-first + curated city fallback; an unknown zone returns an HONEST
error (never a silent local-time substitute — that would be a new fake-success).
"""

from __future__ import annotations

import re

from core.handlers.meta import _handle_jarvis_meta

_TIME_RE = re.compile(r"^\d{1,2}:\d{2}\s(?:AM|PM)")


def test_tell_time_local_unchanged():
    res = _handle_jarvis_meta("tell_time", {})
    assert res["success"] is True
    assert _TIME_RE.match(res["output"])
    assert " in " not in res["output"]  # local time carries no location suffix


def test_tell_time_iana_zone():
    res = _handle_jarvis_meta("tell_time", {"location": "Asia/Tokyo"})
    assert res["success"] is True
    assert _TIME_RE.match(res["output"])
    assert res["output"].endswith("in Tokyo")  # IANA prefix + underscores stripped


def test_tell_time_iana_multiword_zone():
    res = _handle_jarvis_meta("tell_time", {"location": "America/New_York"})
    assert res["success"] is True
    assert res["output"].endswith("in New York")


def test_tell_time_bare_city_fallback():
    # brain emitted a plain city name → curated map resolves it
    res = _handle_jarvis_meta("tell_time", {"location": "tokyo"})
    assert res["success"] is True
    assert _TIME_RE.match(res["output"])
    assert "tokyo" in res["output"]


def test_tell_time_unknown_zone_is_honest_error():
    res = _handle_jarvis_meta("tell_time", {"location": "Narnia"})
    assert res["success"] is False
    assert "Narnia" in res["error"]


def test_tell_time_blank_location_falls_back_to_local():
    res = _handle_jarvis_meta("tell_time", {"location": "   "})
    assert res["success"] is True
    assert _TIME_RE.match(res["output"])
    assert " in " not in res["output"]
