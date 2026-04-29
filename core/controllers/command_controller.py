"""Command-routing helpers extracted from main window logic."""

from __future__ import annotations


class CommandController:
    _REPEAT_PHRASES: frozenset[str] = frozenset({
        "again", "do it again", "do that again", "repeat that", "repeat it",
        "try again", "run it again", "run that again", "once more", "one more time",
    })

    def __init__(self, run_workflow_prefix: str) -> None:
        self._run_workflow_prefix = run_workflow_prefix

    def parse_command(self, cmd: str) -> tuple[str, str]:
        """Return (direct_workflow_id, display_cmd)."""
        direct_workflow_id = ""
        display_cmd = cmd
        if cmd.startswith(self._run_workflow_prefix):
            direct_workflow_id = cmd[len(self._run_workflow_prefix):].strip()
            display_cmd = f"run {direct_workflow_id.replace('_', ' ')}"
        return direct_workflow_id, display_cmd

    def is_repeat_phrase(self, display_cmd: str) -> bool:
        return display_cmd.strip().lower() in self._REPEAT_PHRASES

    @staticmethod
    def pending_should_yield_to_new_command(cmd: str) -> bool:
        """If True, a full new directive should go to the brain, not resolve_confirmation()."""
        s = (cmd or "").strip()
        if len(s) > 100:
            return True
        low = s.lower()
        if len(s) > 20:
            for needle in (
                "create ", "create a", "write ", "make ", "open ", "read ", "search ",
                "list ", "delete ", "run ", "go to", "remind", "check ", "put ", "save ",
            ):
                if needle in low:
                    return True
        return False
