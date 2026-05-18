"""Regression tests for review fixes in code_exec and file_ops."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.handlers import code_exec, file_ops
from core.handlers.shared import abandon_pending_confirmation, get_pending_confirmation, resolve_confirmation


class _FakeSignal:
    def emit(self, *args, **kwargs):
        return None


class _FakeSignals:
    terminal_line_ready = _FakeSignal()
    terminal_done = _FakeSignal()


def _use_tmp_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.append(patch.object(Path, "home", classmethod(lambda cls: tmp_path)))
    monkeypatch[-1].start()
    (tmp_path / "Documents").mkdir(exist_ok=True)
    monkeypatch.append(patch.object(file_ops, "signals", _FakeSignals()))
    monkeypatch[-1].start()


class ReviewFixTests(unittest.TestCase):
    def setUp(self) -> None:
        abandon_pending_confirmation()
        self._patches = []

    def tearDown(self) -> None:
        abandon_pending_confirmation()
        for item in reversed(self._patches):
            item.stop()

    def test_dangerous_shell_command_confirmation_executes_callback(self):
        executed: list[list[str]] = []

        def fake_stream_execute(args, cwd, timeout=30):
            executed.append(args)
            return "confirmed execution", 0, 1

        self._patches.append(patch.object(code_exec, "_stream_execute", fake_stream_execute))
        self._patches[-1].start()

        result = code_exec._handle_code_execution("run_shell", {"code": "rm -rf temp"})

        self.assertFalse(result["success"])
        self.assertTrue(result.get("needs_confirmation"))
        self.assertIsNotNone(get_pending_confirmation())

        confirmed = resolve_confirmation("yes")

        self.assertTrue(confirmed["success"])
        self.assertEqual(confirmed["output"], "confirmed execution")
        self.assertEqual(executed, [["rm", "-rf", "temp"]])

    def test_batch_delete_confirmation_shows_all_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            _use_tmp_home(self._patches, tmp_path)
            target_dir = tmp_path / "batch"
            target_dir.mkdir()
            for idx in range(25):
                (target_dir / f"delete_{idx:02d}.tmp").write_text("x", encoding="utf-8")

            result = file_ops._handle_file_operation(
                "batch_delete",
                {"path": str(target_dir), "pattern": "*.tmp", "recursive": False},
            )

        self.assertTrue(result.get("needs_confirmation"))
        self.assertIn("delete_24.tmp", result["output"])
        self.assertNotIn("+ 5 more", result["output"])

    def test_search_files_bad_supplied_path_does_not_fall_back_to_home(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            _use_tmp_home(self._patches, tmp_path)
            (tmp_path / "unrelated.txt").write_text("do not find me", encoding="utf-8")

            result = file_ops._handle_file_operation(
                "search_files",
                {"path": str(tmp_path / "missing"), "pattern": "unrelated.txt"},
            )

        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"].lower())

    def test_search_files_without_path_uses_home(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            _use_tmp_home(self._patches, tmp_path)
            (tmp_path / "target.txt").write_text("find me", encoding="utf-8")

            result = file_ops._handle_file_operation("search_files", {"pattern": "target.txt"})

        self.assertTrue(result["success"])
        self.assertIn("target.txt", result["output"])

    def test_qualified_missing_read_path_does_not_fall_back_to_same_basename(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            _use_tmp_home(self._patches, tmp_path)
            (tmp_path / "Desktop").mkdir()
            (tmp_path / "Desktop" / "target.txt").write_text("wrong file", encoding="utf-8")
            requested = "missing_dir/target.txt"
            resolved = tmp_path / "Documents" / "missing_dir" / "target.txt"

            result = file_ops._handle_file_operation("read_file", {"path": requested})

        self.assertFalse(result["success"])
        self.assertIn(str(resolved), result["error"])


if __name__ == "__main__":
    unittest.main()
