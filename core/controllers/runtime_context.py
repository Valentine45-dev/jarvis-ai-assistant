"""Runtime command-context tracker for JarvisWindow."""

from __future__ import annotations

from pathlib import Path


class RuntimeCommandContext:
    def __init__(self) -> None:
        self.last_python_file: str = ""
        self.last_directory: str = ""
        self.previous_user_command: str = ""

    def get_previous_command(self, history: list[dict]) -> str:
        if history:
            return str(history[-1].get("you") or "")
        return self.previous_user_command

    def note_user_command(self, cmd: str) -> None:
        self.previous_user_command = cmd

    def build_brain_context(self, previous_command: str) -> dict:
        return {
            "previous_command": previous_command or "",
            "last_python_file": self.last_python_file,
            "last_directory": self.last_directory,
        }

    def absorb_execution(self, intent: str, result: dict, exec_out: dict) -> None:
        if not exec_out.get("success"):
            return

        last_py = str(exec_out.get("last_python_file") or "").strip()
        last_dir = str(exec_out.get("last_directory") or "").strip()
        if last_py:
            self.last_python_file = last_py
        if last_dir:
            self.last_directory = last_dir

        if intent == "file_operation" and result.get("action") == "create_file":
            p = str((result.get("parameters") or {}).get("path") or "").strip()
            if p.lower().endswith(".py"):
                self.last_python_file = p
                try:
                    self.last_directory = str(Path(p).parent)
                except Exception:
                    pass
