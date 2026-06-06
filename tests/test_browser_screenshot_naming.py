"""Browser screenshots get descriptive, timestamped filenames derived from the
page title — so they're meaningful AND never overwrite each other (the old
default was a single fixed name, jarvis_browser_screenshot.png, that clobbered).
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from core.browser.tabs import _TabsMixin, _slugify_title


# ── _slugify_title (pure) ───────────────────────────────────────────────────

@pytest.mark.parametrize("title,expected", [
    ("JARVIS PROJECT - YouTube", "jarvis-project-youtube"),
    ("Google", "google"),
    ("  Spaces   &   Symbols!!! ", "spaces-symbols"),
    ("", ""),
    ("!!!", ""),
])
def test_slugify_title(title: str, expected: str) -> None:
    assert _slugify_title(title) == expected


# ── _resolve_shot_path ──────────────────────────────────────────────────────

class _FakeSession(_TabsMixin):
    def __init__(self, title: str = "", url: str = "") -> None:
        self._page = types.SimpleNamespace(title=lambda: title, url=url)


def test_descriptive_name_from_title(tmp_path: Path) -> None:
    s = _FakeSession(title="JARVIS PROJECT - YouTube")
    out = s._resolve_shot_path(str(tmp_path))
    name = Path(out).name
    assert name.startswith("jarvis-project-youtube_")
    assert name.endswith(".png")
    assert Path(out).parent == tmp_path           # saved in the given folder


def test_not_the_old_fixed_clobber_name(tmp_path: Path) -> None:
    import re
    s = _FakeSession(title="YouTube")
    name = Path(s._resolve_shot_path(str(tmp_path))).name
    # The old fixed name that overwrote every time is gone…
    assert "jarvis_browser_screenshot" not in name
    # …replaced by descriptive slug + a timestamp segment.
    assert re.search(r"^youtube_\d{8}_\d{6}\.png$", name)


def test_explicit_file_path_respected() -> None:
    s = _FakeSession(title="YouTube")
    out = s._resolve_shot_path("C:/tmp/myshot.png")
    assert out == "C:/tmp/myshot.png"             # exact file honored, no rename


def test_element_tag_in_name(tmp_path: Path) -> None:
    s = _FakeSession(title="Google")
    out = s._resolve_shot_path(str(tmp_path), tag="element")
    assert Path(out).name.startswith("google-element_")


def test_falls_back_to_host_when_no_title(tmp_path: Path) -> None:
    s = _FakeSession(title="", url="https://www.youtube.com/results?q=x")
    out = s._resolve_shot_path(str(tmp_path))
    assert Path(out).name.startswith("youtube-com_")


def test_falls_back_to_browser_when_nothing(tmp_path: Path) -> None:
    s = _FakeSession(title="", url="")
    out = s._resolve_shot_path(str(tmp_path))
    assert Path(out).name.startswith("browser_")
