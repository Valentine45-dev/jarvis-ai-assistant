"""Phase 2 — Edge live + switching (no confirm).

`ensure_engine()` makes an engine the active controlled browser: launch if cold,
flip the pointer if already alive (instant, closes nothing), no-op if already
active, clean error if not installed. The open_browser handler maps a spoken
browser name → engine and drives ensure_engine, with an uncontrolled-launch
fallback only when the controlled launch fails but the app exists.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

import core.browser as cb
import core.browser.session as session
from core.handlers.app_launcher import _BROWSER_NAME_TO_ENGINE, _handle_open_app


# ── ensure_engine (faked Playwright driver) ──────────────────────────────────

class _FakeContext:
    def __init__(self) -> None:
        self.pages = [object()]
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeType:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def launch_persistent_context(self, user_data_dir: str, **kwargs: Any) -> _FakeContext:
        self.calls.append({"user_data_dir": user_data_dir, **kwargs})
        return _FakeContext()


class _FakePW:
    def __init__(self) -> None:
        self.chromium = _FakeType()
        self.firefox = _FakeType()

    def stop(self) -> None:
        pass


@pytest.fixture
def fake_pw(monkeypatch: pytest.MonkeyPatch) -> _FakePW:
    pw = _FakePW()
    fake_mod = types.ModuleType("playwright.sync_api")
    fake_mod.sync_playwright = lambda: types.SimpleNamespace(start=lambda: pw)
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_mod)
    # Treat all engines as installed unless a test overrides it.
    monkeypatch.setattr(session, "_find_chromium_channel", lambda e: r"C:\fake.exe")
    monkeypatch.setattr(session, "_playwright_firefox_present", lambda pw: True)
    return pw


def test_ensure_engine_cold_launch(fake_pw: _FakePW) -> None:
    s = session._SessionBase()
    r = s.ensure_engine("edge")
    assert r["success"] is True
    assert s.active_engine == "edge" and s.is_ready is True
    assert fake_pw.chromium.calls[0]["channel"] == "msedge"


def test_ensure_engine_switch_is_pointer_flip(fake_pw: _FakePW) -> None:
    s = session._SessionBase()
    s.ensure_engine("chrome")
    s.ensure_engine("edge")
    chrome_ctx = s._sessions["chrome"].context
    r = s.ensure_engine("chrome")            # switch back
    assert r["success"] is True and "Switched" in r["output"]
    assert s.active_engine == "chrome"
    assert len(fake_pw.chromium.calls) == 2  # no relaunch on switch
    assert chrome_ctx.closed is False        # nothing closed


def test_ensure_engine_already_active_noop(fake_pw: _FakePW) -> None:
    s = session._SessionBase()
    s.ensure_engine("chrome")
    r = s.ensure_engine("chrome")
    assert r["success"] is True and "Already" in r["output"]
    assert len(fake_pw.chromium.calls) == 1


def test_ensure_engine_not_installed_clean_error(fake_pw: _FakePW,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session, "_find_chromium_channel",
                        lambda e: None if e == "edge" else r"C:\fake.exe")
    s = session._SessionBase()
    r = s.ensure_engine("edge")
    assert r["success"] is False
    assert "Edge isn't installed" in r["error"]
    assert "edge" not in s._sessions          # nothing launched


# ── open_browser handler routing ─────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("chrome", "chrome"),
    ("google chrome", "chrome"),
    ("edge", "edge"),
    ("microsoft edge", "edge"),
    ("firefox", "firefox"),
    ("mozilla firefox", "firefox"),
    ("auto", "auto"),
    ("something-weird", "chrome"),   # fallback
])
def test_browser_name_to_engine(name: str, expected: str) -> None:
    assert _BROWSER_NAME_TO_ENGINE.get(name, "chrome") == expected


class _FakeBrowser:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.result = {"success": True, "output": "edge ready", "error": ""}

    def ensure_engine(self, engine: str) -> dict:
        self.calls.append(engine)
        return self.result


def test_open_browser_routes_to_ensure_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    fb = _FakeBrowser()
    monkeypatch.setattr(cb, "browser", fb)   # handler does `from core.browser import browser`
    r = _handle_open_app("open_browser", {"browser": "edge"})
    assert r["success"] is True
    assert fb.calls == ["edge"]


def test_open_browser_defaults_to_chrome(monkeypatch: pytest.MonkeyPatch) -> None:
    fb = _FakeBrowser()
    monkeypatch.setattr(cb, "browser", fb)
    _handle_open_app("open_browser", {})
    assert fb.calls == ["chrome"]
