"""Screenshot naming is brain-driven and used AS-IS (no timestamp), via ONE
shared sanitizer (core.handlers.paths._slugify_for_filename) used by docs, OS
screenshots, and browser screenshots alike.

- The brain names the file (a filename in save_path, e.g. .../tests/youtube.png)
  → that becomes the filename exactly, so the brain can reference/delete it later.
- When the brain gives only a folder, fall back to the page title (browser) or
  "screen" (OS).
- NO timestamp is appended (a timestamp the brain never sees made later
  reference/delete impossible). Re-using a name overwrites.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from core.browser.tabs import _TabsMixin
from core.handlers.paths import _resolve_screenshot_path, _slugify_for_filename


# ── shared slugify (one helper for docs + screenshots) ──────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("whatsapp_web", "whatsapp_web"),
    ("YouTube home", "YouTube_home"),
    ("a/b\\c..d", "abcd"),                 # path-traversal chars stripped
    ("   ", ""),
])
def test_shared_slugify(raw: str, expected: str) -> None:
    assert _slugify_for_filename(raw) == expected


# ── OS resolver (paths._resolve_screenshot_path) ────────────────────────────

def test_os_brain_filename_used_as_is(tmp_path: Path) -> None:
    out, missing = _resolve_screenshot_path(str(tmp_path / "whatsapp_web.png"))
    assert missing is None
    assert Path(out).name == "whatsapp_web.png"      # exact, no timestamp
    assert Path(out).parent == tmp_path


def test_os_folder_only_uses_screen_fallback(tmp_path: Path) -> None:
    out, _ = _resolve_screenshot_path(str(tmp_path))
    assert Path(out).name == "screen.png"


def test_os_custom_fallback_base(tmp_path: Path) -> None:
    out, _ = _resolve_screenshot_path(str(tmp_path), fallback_base="dashboard")
    assert Path(out).name == "dashboard.png"


# ── browser resolver (tabs._resolve_shot_path) ──────────────────────────────

class _FakeSession(_TabsMixin):
    def __init__(self, title: str = "", url: str = "") -> None:
        self._page = types.SimpleNamespace(title=lambda: title, url=url)


def test_browser_brain_filename_wins(tmp_path: Path) -> None:
    s = _FakeSession(title="YouTube")
    out = s._resolve_shot_path(str(tmp_path / "my_capture.png"))
    assert Path(out).name == "my_capture.png"        # brain's exact name, not the title


def test_browser_folder_falls_back_to_page_title(tmp_path: Path) -> None:
    s = _FakeSession(title="YouTube")
    out = s._resolve_shot_path(str(tmp_path))
    assert Path(out).name == "YouTube.png"
    assert Path(out).parent == tmp_path


def test_browser_falls_back_to_host_without_title(tmp_path: Path) -> None:
    s = _FakeSession(title="", url="https://www.youtube.com/x")
    out = s._resolve_shot_path(str(tmp_path))
    assert Path(out).name == "youtubecom.png"         # dots stripped by sanitizer


def test_browser_falls_back_to_browser_when_nothing(tmp_path: Path) -> None:
    s = _FakeSession(title="", url="")
    out = s._resolve_shot_path(str(tmp_path))
    assert Path(out).name == "browser.png"


def test_browser_element_tag(tmp_path: Path) -> None:
    s = _FakeSession(title="Google")
    out = s._resolve_shot_path(str(tmp_path), tag="element")
    assert Path(out).name == "Google-element.png"


def test_no_timestamp_no_old_clobber_name(tmp_path: Path) -> None:
    s = _FakeSession(title="YouTube")
    name = Path(s._resolve_shot_path(str(tmp_path / "youtube_nba.png"))).name
    assert name == "youtube_nba.png"                  # exactly what the brain said
    assert "jarvis_browser_screenshot" not in name    # old fixed clobber name gone
