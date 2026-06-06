"""The terminal Copy button grabs a whole command block's plain text (prompt +
reply + every output line) so the user can paste it instead of screenshotting.
_block_text is the pure assembler behind that button.
"""

from __future__ import annotations

from ui.components.terminal import _Block, _block_text


def test_block_text_joins_prompt_reply_and_extras() -> None:
    b = _Block(
        kind="command",
        prompt="read my screen",
        response="Reads as:",
        extras=[("line one", "#fff"), ("line two", "#fff"), ("line three", "#fff")],
    )
    assert _block_text(b) == "read my screen\nReads as:\nline one\nline two\nline three"


def test_block_text_skips_empty_prompt_and_reply() -> None:
    b = _Block(kind="command", prompt="", response="", extras=[("only output", "#fff")])
    assert _block_text(b) == "only output"


def test_block_text_prompt_only() -> None:
    b = _Block(kind="command", prompt="git status", response="", extras=[])
    assert _block_text(b) == "git status"


def test_block_text_empty_block() -> None:
    assert _block_text(_Block(kind="command")) == ""
