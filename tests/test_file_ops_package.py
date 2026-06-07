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
