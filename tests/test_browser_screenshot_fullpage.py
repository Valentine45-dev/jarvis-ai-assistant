"""Browser screenshot full_page toggle: default = whole scrollable page;
full_page=False = visible viewport only. Plus the handler's bool coercion.
"""

from __future__ import annotations

import threading
import types
from pathlib import Path

import pytest

from core.browser.tabs import _TabsMixin
from core.handlers.browser_handler import _as_bool


class _FakeShotSession(_TabsMixin):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.calls: list[dict] = []
        self._page = types.SimpleNamespace(
            title=lambda: "YouTube",
            url="https://www.youtube.com",
            screenshot=lambda **kw: self.calls.append(kw),
        )

    def _not_ready(self):
        return None


def test_screenshot_page_defaults_to_full_page(tmp_path: Path) -> None:
    s = _FakeShotSession()
    s.screenshot_page(str(tmp_path))
    assert s.calls[0]["full_page"] is True


def test_screenshot_page_viewport_when_false(tmp_path: Path) -> None:
    s = _FakeShotSession()
    s.screenshot_page(str(tmp_path), full_page=False)
    assert s.calls[0]["full_page"] is False


@pytest.mark.parametrize("raw,expected", [
    (True, True), (False, False),
    ("true", True), ("false", False),
    ("no", False), ("0", False), ("off", False), ("", False),
    ("yes", True), ("1", True), (1, True), (0, False),
])
def test_as_bool(raw, expected: bool) -> None:
    assert _as_bool(raw) is expected
