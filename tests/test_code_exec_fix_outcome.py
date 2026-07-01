"""D2 — a suggested fix that runs after the user's command FAILED must never turn
the SYS_LOG row green.

Bug (fake-success #1): "run python that divides 1 by 0" → print(1/0) errored, the
post-execute layer offered a Sonnet "fix", the user confirmed it, the fix exited 0,
and its `_ok` overwrote the failed command's outcome → the row showed green/success
for a command that actually failed.

Fix (D2, "the user's command owns the row"): when a fix runs after a failure —
either the auto path in `_attempt_fix` (autorun ON) or the confirmed path in
`_ai_command_confirmation` (confirm_type="fix") — the result is reported on the
FAIL rail (success=False) even when the fix exits 0, with the fix success as a
secondary note. NL-translation / plan confirmations ARE the user's intended
command, so their success stays a genuine `_ok` (regression guard below).

Physical gate: re-run "divide 1 by 0" in the app and confirm the row goes RED/FAIL,
not green — a green pytest run alone does not close this.
"""

from __future__ import annotations

import types

import core.handlers.code_exec as ce
from core.handlers import shared


# ── confirmed-fix path (the one reproducer A hit) ───────────────────────────

def _confirm_and_resolve(command, confirm_type, exit_code, monkeypatch):
    """Drive _ai_command_confirmation → resolve_confirmation('yes'), with
    _stream_execute stubbed to return (output, exit_code, duration)."""
    shared.abandon_pending_confirmation()  # no leftover from a prior test
    monkeypatch.setattr(
        ce, "_stream_execute",
        lambda args, cwd=None, timeout=60: ("simulated output", exit_code, 12),
    )
    monkeypatch.setattr(ce, "_store_block", lambda block: None)
    pending = ce._ai_command_confirmation(
        "prompt text", command, None, confirm_type=confirm_type,
    )
    assert pending.get("needs_confirmation") is True
    return shared.resolve_confirmation("yes")


def test_confirmed_fix_success_reports_fail_rail(monkeypatch):
    # user's command failed → a confirmed fix that exits 0 must NOT go green
    res = _confirm_and_resolve('python -c "print(1)"', "fix", 0, monkeypatch)
    assert res["success"] is False
    assert "original command did not run" in res["error"]


def test_confirmed_fix_failure_reports_fail_rail(monkeypatch):
    res = _confirm_and_resolve('python -c "print(1)"', "fix", 1, monkeypatch)
    assert res["success"] is False


def test_confirmed_ai_command_success_stays_ok(monkeypatch):
    # regression guard: an NL-translation confirmation IS the user's intended
    # command, so a clean exit is a genuine success (rail stays green).
    res = _confirm_and_resolve("git status", "ai_command", 0, monkeypatch)
    assert res["success"] is True


# ── auto-fix path (_attempt_fix, autorun ON) ────────────────────────────────

class _FakeMessages:
    def __init__(self, text):
        self._text = text

    def create(self, **_k):
        return types.SimpleNamespace(content=[types.SimpleNamespace(text=self._text)])


class _FakeClient:
    def __init__(self, text):
        self.messages = _FakeMessages(text)


def test_auto_applied_fix_success_reports_fail_rail(monkeypatch):
    from config.settings import config

    monkeypatch.setattr(config, "anthropic_api_key", "test-key", raising=False)
    # Sonnet proposes an auto_safe fix; autorun is ON so it runs without a card.
    fix_json = '{"fix_command":"python -c \\"print(1)\\"","explanation":"ran a fix","auto_safe":true}'
    monkeypatch.setattr(ce, "_get_client", lambda: _FakeClient(fix_json))
    monkeypatch.setattr(ce, "_autorun_allowed", lambda: True)
    monkeypatch.setattr(ce, "_danger_check", lambda cmd: None)
    monkeypatch.setattr(ce, "_store_block", lambda block: None)
    monkeypatch.setattr(
        ce, "_stream_execute",
        lambda args, cwd=None, timeout=60: ("fix output", 0, 9),  # fix succeeds
    )

    block = ce.CommandBlock(
        command="print(1 / 0)", output="Traceback ... ZeroDivisionError", exit_code=1,
        duration_ms=5, cwd=".",
    )
    res = ce._attempt_fix(block, None)
    assert res is not None
    assert res["success"] is False  # user's command failed → row stays red
    assert "original command did not run" in res["error"]
