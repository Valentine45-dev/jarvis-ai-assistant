"""R2-17b: file_ops.py (1220-LOC monolith) → core/handlers/file_ops package.

Locks the post-split contract: the single public entry is still importable from
the package root, the dispatch covers every action, the shared _ok/_err singletons
are re-exported, and the per-action _op_* (with their nested _do_* confirm
closures, which moved INTO each _op_* during extraction) still work end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.handlers import file_ops
from core.handlers.file_ops import _DISPATCH, _handle_file_operation, _common
from core.handlers.shared import (
    abandon_pending_confirmation,
    resolve_confirmation,
    _ok as shared_ok,
    _err as shared_err,
)

_ALL_ACTIONS = {
    "create_directory", "create_file", "read_file", "append_file",
    "replace_in_file", "rename_file", "move_file", "copy_file",
    "delete_file", "batch_delete", "list_directory", "search_files",
    "find_in_files", "file_info",
}


class _FakeSignal:
    def emit(self, *a, **k):
        return None


class _FakeSignals:
    terminal_line_ready = _FakeSignal()
    terminal_done = _FakeSignal()


@pytest.fixture(autouse=True)
def _quiet_signals(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # All terminal emission funnels through _common.signals after the split.
    monkeypatch.setattr(_common, "signals", _FakeSignals())
    # Confine Path.home() to tmp so path-resolution fallbacks can't walk the real
    # home dir (the 30s search budget would make these tests crawl).
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "Documents").mkdir(exist_ok=True)
    abandon_pending_confirmation()
    yield
    abandon_pending_confirmation()


# ── structure / contract ─────────────────────────────────────────────────────

def test_public_entry_still_importable() -> None:
    # core.executor imports this exact path — must not break.
    from core.handlers.file_ops import _handle_file_operation as entry
    assert callable(entry)


def test_dispatch_covers_every_action() -> None:
    assert set(_DISPATCH) == _ALL_ACTIONS
    assert all(callable(fn) for fn in _DISPATCH.values())


def test_shared_helpers_reexported_as_singletons() -> None:
    assert file_ops._ok is shared_ok
    assert file_ops._err is shared_err


def test_unknown_action_returns_err() -> None:
    r = _handle_file_operation("frobnicate", {"path": "x"})
    assert r["success"] is False
    assert "Unknown file action" in r["error"]


def test_each_op_lives_in_its_module() -> None:
    from core.handlers.file_ops.create import _op_create_directory, _op_create_file
    from core.handlers.file_ops.read_write import _op_read_file, _op_append_file
    from core.handlers.file_ops.replace import _op_replace_in_file
    from core.handlers.file_ops.move_rename import _op_rename_file, _op_move_file, _op_copy_file
    from core.handlers.file_ops.delete import _op_delete_file
    from core.handlers.file_ops.batch import _op_batch_delete
    from core.handlers.file_ops.search import _op_list_directory, _op_search_files, _op_find_in_files
    from core.handlers.file_ops.info import _op_file_info
    assert _DISPATCH["create_file"] is _op_create_file
    assert _DISPATCH["find_in_files"] is _op_find_in_files


# ── behaviour through the dispatch (closures survived the move) ───────────────

def test_create_file_confirm_closure_writes(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    r = _handle_file_operation("create_file", {"path": str(target), "content": "hello"})
    assert r.get("needs_confirmation"), "create_file should request confirmation"
    out = resolve_confirmation("yes")            # runs the moved _do_create closure
    assert out["success"] is True
    assert target.read_text(encoding="utf-8") == "hello"


def test_read_file_roundtrips(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("line1\nline2\n", encoding="utf-8")
    r = _handle_file_operation("read_file", {"path": str(f)})
    assert r["success"] and "line1" in r["output"] and "line2" in r["output"]


def test_file_info_reads_metadata(tmp_path: Path) -> None:
    f = tmp_path / "script.py"
    f.write_text("x = 1\n", encoding="utf-8")
    r = _handle_file_operation("file_info", {"path": str(f)})
    assert r["success"] and "script.py" in r["output"]


def test_list_directory(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("a", encoding="utf-8")
    (tmp_path / "two.txt").write_text("b", encoding="utf-8")
    r = _handle_file_operation("list_directory", {"path": str(tmp_path)})
    assert r["success"] and "one.txt" in r["output"] and "two.txt" in r["output"]


def test_find_in_files(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text("alpha NEEDLE beta\n", encoding="utf-8")
    (tmp_path / "y.txt").write_text("nothing here\n", encoding="utf-8")
    r = _handle_file_operation("find_in_files", {"path": str(tmp_path), "pattern": "NEEDLE"})
    assert r["success"] and "NEEDLE" in r["output"] or "1 match" in r["output"].lower()


def test_replace_in_file_confirm_closure(tmp_path: Path) -> None:
    f = tmp_path / "edit.txt"
    f.write_text("foo bar foo\n", encoding="utf-8")
    r = _handle_file_operation("replace_in_file", {"path": str(f), "find": "foo", "replace": "baz"})
    assert r.get("needs_confirmation"), "replace_in_file should confirm"
    out = resolve_confirmation("yes")            # runs the moved _do_replace closure
    assert out["success"] is True
    assert "baz" in f.read_text(encoding="utf-8") and "foo" not in f.read_text(encoding="utf-8")


# ── data-loss backstop: never write a redacted `<N chars>` placeholder ────────
# The model can copy a redacted prior turn ("<4921 chars>") into a write op; the
# content-writing ops refuse it (no confirmation, nothing written) so it can't land
# on disk. The root-cause fix is memory.get_prompt_messages(); this is the backstop.

def test_is_redacted_placeholder_helper() -> None:
    assert _common._is_redacted_placeholder("<4921 chars>") is True
    assert _common._is_redacted_placeholder("  <12 chars>  ") is True   # whitespace tolerated
    assert _common._is_redacted_placeholder("<4921 chars> and more") is False  # only EXACT match
    assert _common._is_redacted_placeholder("real file content") is False
    assert _common._is_redacted_placeholder("") is False
    assert _common._is_redacted_placeholder(None) is False


def test_create_file_refuses_redacted_placeholder(tmp_path: Path) -> None:
    target = tmp_path / "file_search_engine.py"
    r = _handle_file_operation("create_file", {"path": str(target), "content": "<4921 chars>"})
    assert r["success"] is False
    assert not r.get("needs_confirmation"), "must refuse outright, not ask to confirm"
    assert "placeholder" in (r.get("error") or "").lower()
    assert not target.exists(), "the placeholder must NOT be written to disk"


def test_create_file_normal_content_still_writes(tmp_path: Path) -> None:
    # The guard is exact-match only — real content that merely mentions chars works.
    target = tmp_path / "ok.txt"
    r = _handle_file_operation("create_file", {"path": str(target), "content": "about 50 chars here"})
    assert r.get("needs_confirmation")
    out = resolve_confirmation("yes")
    assert out["success"] is True
    assert target.read_text(encoding="utf-8") == "about 50 chars here"


# ── Fix B: an empty create_file is NEVER silent (card note + post-write flag) ──
# The model sometimes emits create_file with no `content` for a code-file request
# ("create a python file that prints fizzbuzz"), writing a 0-byte file. Part A
# (CLAUDE.md) tells the model to inline content; Part B is the executor visibility
# net so a miss (or an auto-confirmed/workflow empty create) is always seen.

def test_empty_create_flags_card_and_post_write(tmp_path: Path, monkeypatch) -> None:
    import core.handlers.file_ops.create as create_mod
    logs: list[str] = []
    monkeypatch.setattr(create_mod, "_tlog", lambda msg: logs.append(msg))

    target = tmp_path / "empty.py"          # has an extension → a real file, not a dir
    r = _handle_file_operation("create_file", {"path": str(target), "content": ""})
    assert r.get("needs_confirmation")
    # Layer 1 — the confirmation card flags the emptiness BEFORE the write.
    assert "EMPTY file" in r["output"]

    out = resolve_confirmation("yes")
    assert out["success"] is True
    # Intentional empties are still allowed (we flag, never block).
    assert target.exists() and target.stat().st_size == 0
    # Layer 2 — the post-write path emits a distinct ⚠ EMPTY line (fires even when
    # the card is auto-confirmed), not a plain ✓ that reads as success.
    assert any("created EMPTY" in m for m in logs)
    assert not any(m.startswith("✓ created") for m in logs)


def test_content_create_has_no_empty_flag(tmp_path: Path, monkeypatch) -> None:
    import core.handlers.file_ops.create as create_mod
    logs: list[str] = []
    monkeypatch.setattr(create_mod, "_tlog", lambda msg: logs.append(msg))

    target = tmp_path / "real.py"
    r = _handle_file_operation("create_file", {"path": str(target), "content": "print('hi')\n"})
    assert r.get("needs_confirmation")
    assert "EMPTY file" not in r["output"]          # no false flag on real content

    out = resolve_confirmation("yes")
    assert out["success"] is True
    assert target.read_text(encoding="utf-8") == "print('hi')\n"
    assert not any("created EMPTY" in m for m in logs)
    assert any(m.startswith("✓ created") for m in logs)


def test_append_file_refuses_redacted_placeholder(tmp_path: Path) -> None:
    f = tmp_path / "log.txt"
    f.write_text("existing\n", encoding="utf-8")
    r = _handle_file_operation("append_file", {"path": str(f), "content": "<88 chars>"})
    assert r["success"] is False and "placeholder" in (r.get("error") or "").lower()
    assert f.read_text(encoding="utf-8") == "existing\n", "file must be untouched"


def test_replace_in_file_refuses_redacted_placeholder(tmp_path: Path) -> None:
    f = tmp_path / "edit.txt"
    f.write_text("foo bar\n", encoding="utf-8")
    r = _handle_file_operation("replace_in_file",
                               {"path": str(f), "find": "foo", "replace": "<300 chars>"})
    assert r["success"] is False and "placeholder" in (r.get("error") or "").lower()
    assert f.read_text(encoding="utf-8") == "foo bar\n", "file must be untouched"
