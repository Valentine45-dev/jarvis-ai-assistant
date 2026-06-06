"""The controlled browser must launch with a PERSISTENT profile + the
anti-automation flag, so Google sees a returning human (fewer reCAPTCHAs) rather
than a fresh anonymous automated context every run.

Fakes Playwright so no real Chrome is launched — asserts how start() calls it.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

import core.browser.session as session


class _FakePage:
    pass


class _FakeContext:
    def __init__(self) -> None:
        self.pages = [_FakePage()]
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self) -> None:
        self.launch_persistent_calls: list[dict] = []
        self.plain_launch_calls = 0

    def launch_persistent_context(self, user_data_dir: str, **kwargs: Any) -> _FakeContext:
        self.launch_persistent_calls.append({"user_data_dir": user_data_dir, **kwargs})
        return _FakeContext()

    def launch(self, **kwargs: Any):  # should NOT be used anymore
        self.plain_launch_calls += 1
        raise AssertionError("plain launch() used instead of launch_persistent_context()")


class _FakePW:
    def __init__(self, chromium: _FakeChromium) -> None:
        self.chromium = chromium

    def stop(self) -> None:
        pass


@pytest.fixture
def fake_playwright(monkeypatch: pytest.MonkeyPatch) -> _FakeChromium:
    chromium = _FakeChromium()

    def _sync_playwright():
        return types.SimpleNamespace(start=lambda: _FakePW(chromium))

    # start() does `from playwright.sync_api import sync_playwright`, so patch the
    # symbol on a stub module installed in sys.modules.
    fake_mod = types.ModuleType("playwright.sync_api")
    fake_mod.sync_playwright = _sync_playwright
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_mod)
    return chromium


def test_start_uses_persistent_context_with_stealth(fake_playwright: _FakeChromium) -> None:
    s = session._SessionBase()
    s.start()

    assert s.is_ready is True
    assert s.start_error == ""
    assert len(fake_playwright.launch_persistent_calls) == 1
    call = fake_playwright.launch_persistent_calls[0]

    # Persistent profile dir under data/browser_profile
    assert "browser_profile" in call["user_data_dir"]
    assert call["channel"] == "chrome"
    assert call["headless"] is False
    # The anti-automation flag is present (hides navigator.webdriver).
    assert "--disable-blink-features=AutomationControlled" in call["args"]
    # And the default --enable-automation switch is dropped (no banner, less
    # fingerprint).
    assert "--enable-automation" in call.get("ignore_default_args", [])


def test_start_reuses_existing_persistent_page(fake_playwright: _FakeChromium) -> None:
    s = session._SessionBase()
    s.start()
    # Persistent context comes with an initial page — use it, don't open a 2nd.
    assert s._page is not None
    assert s._browser is None          # persistent context owns the browser


def test_profile_in_use_gives_friendly_error(monkeypatch: pytest.MonkeyPatch) -> None:
    chromium = _FakeChromium()

    def _boom(*a, **k):
        raise RuntimeError("user data directory is already in use")
    chromium.launch_persistent_context = _boom  # type: ignore[assignment]

    fake_mod = types.ModuleType("playwright.sync_api")
    fake_mod.sync_playwright = lambda: types.SimpleNamespace(start=lambda: _FakePW(chromium))
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_mod)

    s = session._SessionBase()
    s.start()
    assert s.is_ready is False
    assert "profile is in use" in s.start_error.lower()
