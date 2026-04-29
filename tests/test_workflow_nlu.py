"""Unit tests for routine/workflow natural-language creation parser."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.workflow_nlu import parse_create_workflow_command


class WorkflowNluTests(unittest.TestCase):
    def test_multiline_routine_creation(self) -> None:
        text = (
            "Hey jarvis, create a night routine which have:\n"
            "open chrome\n"
            "search Sound Sleep Videos on youtube\n"
            "increase volume to max"
        )
        out = parse_create_workflow_command(text)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["intent"], "automation_task")
        self.assertEqual(out["action"], "create_workflow")
        self.assertEqual(out["parameters"]["task_name"], "Night Routine")
        self.assertEqual(len(out["parameters"]["steps"]), 3)

    def test_non_creation_command_returns_none(self) -> None:
        self.assertIsNone(parse_create_workflow_command("run night routine"))

    def test_single_line_with_windows_path_and_after_clause(self) -> None:
        text = (
            "hey jarvis create a morning routine where should take screenshot and store it in "
            "C:\\Users\\Dell Latitude Touch\\Desktop\\jarvis-project\\tests, after you should increase "
            "the brightness to 100% and create a python script of a terminal-based matrix rain effect in "
            "Python — curses, falling green characters, the works."
        )
        out = parse_create_workflow_command(text)
        self.assertIsNotNone(out)
        assert out is not None
        steps = out["parameters"]["steps"]
        self.assertEqual(len(steps), 3)
        self.assertIn("C:\\Users\\Dell Latitude Touch\\Desktop\\jarvis-project\\tests", steps[0])
        self.assertIn("brightness to 100%", steps[1].lower())
        self.assertIn("matrix rain effect", steps[2].lower())


if __name__ == "__main__":
    unittest.main()

