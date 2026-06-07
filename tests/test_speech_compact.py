"""speech_compact() must not double-compact a path.

Regression: a Windows path was first reduced to "tests/requirements.txt" by the
drive-letter regex, then the absolute-unix-path regex re-matched the
"/requirements.txt" tail and stripped the slash → "testsrequirements.txt". The
(?<!\\w) lookbehind stops the unix regex from matching a "/tail" glued to a
preceding word, while still compacting genuine absolute unix paths.
"""

from __future__ import annotations

import pytest

from core.responders.utils import speech_compact


def test_windows_path_keeps_separator_after_compaction() -> None:
    s = speech_compact(
        r"Cannot find 'C:\Users\Lenovo\Documents\jarvis-project\tests\requirements.txt' — check the path."
    )
    assert "tests/requirements.txt" in s          # slash preserved
    assert "testsrequirements.txt" not in s        # the bug is gone


@pytest.mark.parametrize("raw,expected_fragment", [
    (r"Saved to C:\Users\Lenovo\Desktop\shot.png", "Desktop/shot.png"),
    (r"C:\a\b\c\d\file.txt", "d/file.txt"),                  # parent/name only
])
def test_windows_path_compacts_to_parent_name(raw: str, expected_fragment: str) -> None:
    out = speech_compact(raw)
    assert expected_fragment in out
    # no glued-together segment (would mean a dropped separator)
    assert "cd/file" not in out and " Desktopshot" not in out


def test_absolute_unix_path_still_compacts() -> None:
    # Preceded by a boundary (space) → still reduced to parent/name.
    out = speech_compact("Read /Users/lenovo/Documents/notes/todo.txt now")
    assert "notes/todo.txt" in out
    assert "/Users/lenovo" not in out               # leading dirs dropped


def test_glued_slash_tail_is_not_compacted() -> None:
    # A "/segment" stuck to a preceding word must be left alone (it's not an
    # absolute path start). This is the exact shape the bug produced.
    assert speech_compact("tests/requirements.txt") == "tests/requirements.txt"


def test_plain_text_untouched() -> None:
    assert speech_compact("no paths here, just words") == "no paths here, just words"


def test_empty_input() -> None:
    assert speech_compact("") == ""
