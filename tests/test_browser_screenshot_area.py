"""B1: a natural-language `goal` captures just that section of the page (via the
snapshot picker), while a plain screenshot still captures the whole/visible page
and an explicit `selector` captures that element. Tests the handler routing.
"""

from __future__ import annotations

import pytest

import core.browser as cb
from core.handlers.browser_handler import _handle_browser_automation


class _FakeBrowser:
    is_ready = True

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def start(self) -> None:  # pragma: no cover - never hit (is_ready True)
        pass

    def find_and_act(self, goal, action, value="", path=None):
        self.calls.append(("find_and_act", goal, action, path))
        return {"success": True, "output": "ok", "error": ""}

    def screenshot_page(self, path=None, full_page=True):
        self.calls.append(("page", path, full_page))
        return {"success": True, "output": "ok", "error": ""}

    def screenshot_element(self, selector="", path=None):
        self.calls.append(("element", selector, path))
        return {"success": True, "output": "ok", "error": ""}


@pytest.fixture
def fake_browser(monkeypatch: pytest.MonkeyPatch) -> _FakeBrowser:
    fb = _FakeBrowser()
    monkeypatch.setattr(cb, "browser", fb)   # handler does `from core.browser import browser`
    return fb


def test_goal_routes_to_find_and_act_screenshot(fake_browser: _FakeBrowser) -> None:
    _handle_browser_automation("screenshot", {"goal": "comments section",
                                              "save_path": "C:/x/comments.png"})
    assert fake_browser.calls == [("find_and_act", "comments section", "screenshot", "C:/x/comments.png")]


def test_no_goal_routes_to_page_full(fake_browser: _FakeBrowser) -> None:
    _handle_browser_automation("screenshot", {"save_path": "C:/x/p.png"})
    assert fake_browser.calls == [("page", "C:/x/p.png", True)]


def test_viewport_phrasing_routes_to_page_false(fake_browser: _FakeBrowser) -> None:
    _handle_browser_automation("screenshot", {"full_page": False})
    assert fake_browser.calls == [("page", None, False)]


def test_selector_beats_goal(fake_browser: _FakeBrowser) -> None:
    _handle_browser_automation("screenshot", {"selector": "#comments", "goal": "comments"})
    assert fake_browser.calls == [("element", "#comments", None)]
