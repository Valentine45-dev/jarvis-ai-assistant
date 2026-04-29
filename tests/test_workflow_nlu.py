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


if __name__ == "__main__":
    unittest.main()

