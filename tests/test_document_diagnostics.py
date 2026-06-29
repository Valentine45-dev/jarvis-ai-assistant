"""Fix A — document generator failure diagnostics.

The generator subprocess used to discard its stdout/stderr (only a 5-line tail
on a non-zero exit; nothing at all on the rc==0 "output file is missing" case),
so every docx failure was a black box. These helpers surface the path the script
actually saved to, the full subprocess output, and machine context (resolved
path, OneDrive redirection, cwd, python).
"""

from __future__ import annotations

import core.handlers.document_handler as dh
from core.handlers.document_handler import _log_run_diagnostics, _script_reported_path


# ── _script_reported_path: parse the script's own "OK: <path>" line ─────────


def test_reports_ok_path():
    out = [
        "│ drafting…",
        r"OK: C:\Users\Lenovo\Documents\jarvis-project\tests\history_of_ai.docx",
    ]
    assert _script_reported_path(out) == (
        r"C:\Users\Lenovo\Documents\jarvis-project\tests\history_of_ai.docx"
    )


def test_reports_none_without_ok_line():
    assert _script_reported_path(["some output", "ERR: boom"]) is None
    assert _script_reported_path([]) is None


def test_reports_last_ok_when_multiple():
    # reversed scan → the most recent save wins
    assert _script_reported_path(["OK: a.docx", "noise", "OK: b.docx"]) == "b.docx"


# ── _log_run_diagnostics: returns the reported path + logs everything ───────


def test_diagnostics_returns_reported_and_logs_full_output(monkeypatch, tmp_path):
    logged: list[tuple[str, str]] = []
    monkeypatch.setattr(dh, "_dbg", lambda tag, msg: logged.append((tag, msg)))

    target = tmp_path / "out.docx"
    output = [
        "Traceback (most recent call last):",
        "PermissionError: [Errno 13] denied",
        "ERR: denied",
        f"OK: {target}",
    ]
    reported = _log_run_diagnostics(target, tmp_path, 0, output, where="missing-file")

    assert reported == str(target)
    blob = "\n".join(m for _, m in logged)
    assert "missing-file" in blob          # the failure site
    assert "OneDrive" in blob              # machine-specific redirect context
    assert "python=" in blob               # which interpreter ran the script
    assert "full generator output" in blob
    # full output, NOT a truncated tail — the traceback line survives
    assert "PermissionError: [Errno 13] denied" in blob


def test_diagnostics_handles_no_output(monkeypatch, tmp_path):
    logged: list[tuple[str, str]] = []
    monkeypatch.setattr(dh, "_dbg", lambda tag, msg: logged.append((tag, msg)))
    reported = _log_run_diagnostics(tmp_path / "x.docx", tmp_path, 1, [], where="nonzero-exit")
    assert reported is None
    blob = "\n".join(m for _, m in logged)
    assert "no subprocess output captured" in blob
