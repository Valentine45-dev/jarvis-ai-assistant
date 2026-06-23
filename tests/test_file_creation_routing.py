"""Deterministic file/folder-creation routing guardrail.

The brain occasionally routes plain "create a folder and a file" (no shell named)
to run_powershell instead of the cross-platform file_operation actions.
parse_file_creation_command (core/workflow_nlu.py) is a deterministic fast-path
that catches the common phrasings and returns a file_operation result, wired into
ask_claude BEFORE the model call so routing can't drift to raw shell.
"""

from __future__ import annotations

from core.workflow_nlu import parse_file_creation_command

# ── folder + file (the case the user kept hitting) ──────────────────────────


def test_folder_and_file_nested_workflow():
    r = parse_file_creation_command(
        "create a folder called temp inside the tests folder and then create a file readme.txt inside it"
    )
    assert r is not None
    assert r["intent"] == "automation_task"
    assert r["action"] == "run_workflow"
    steps = r["parameters"]["steps"]
    assert [s["action"] for s in steps] == ["create_directory", "create_file"]
    assert steps[0]["parameters"]["path"] == "tests/temp"
    assert steps[1]["parameters"]["path"] == "tests/temp/readme.txt"
    assert steps[1]["parameters"]["content"] == ""


def test_folder_and_file_no_location():
    r = parse_file_creation_command("create a folder build and a file notes.txt inside it")
    assert r is not None and r["intent"] == "automation_task"
    steps = r["parameters"]["steps"]
    assert steps[0]["parameters"]["path"] == "build"
    assert steps[1]["parameters"]["path"] == "build/notes.txt"


# ── folder only / file only ─────────────────────────────────────────────────


def test_folder_only():
    r = parse_file_creation_command("create a folder called reports in Documents")
    assert r is not None
    assert r["intent"] == "file_operation" and r["action"] == "create_directory"
    assert r["parameters"]["path"] == "Documents/reports"


def test_file_only_empty():
    r = parse_file_creation_command("create a file called log.txt in tests")
    assert r is not None
    assert r["intent"] == "file_operation" and r["action"] == "create_file"
    assert r["parameters"]["path"] == "tests/log.txt"
    assert r["parameters"]["content"] == ""


# ── bail cases → None (model handles them) ──────────────────────────────────


def test_shell_named_bails():
    assert parse_file_creation_command(
        "use PowerShell to create a folder build and a file inside it"
    ) is None
    assert parse_file_creation_command("in cmd create a folder temp") is None


def test_dictated_content_bails():
    assert parse_file_creation_command(
        "create a file notes.txt with content hello world"
    ) is None
    assert parse_file_creation_command(
        "create a file todo.txt that says buy milk"
    ) is None


def test_spaced_name_bails():
    # Ambiguous multi-word name → let the model handle it.
    assert parse_file_creation_command("create a folder called my big reports") is None


def test_non_creation_bails():
    assert parse_file_creation_command("what's in the tests folder") is None
    assert parse_file_creation_command("delete the temp folder") is None
    assert parse_file_creation_command("") is None


# ── brain integration: fast-path returns before any model/network call ───────


def test_brain_uses_guardrail_without_model_call():
    from core.brain import ask_claude

    r = ask_claude(
        "create a folder called temp inside the tests folder and then create a file readme.txt inside it"
    )
    # Deterministic file_operation routing — never code_execution/run_powershell.
    assert r["intent"] == "automation_task"
    assert r["action"] == "run_workflow"
    assert all(s["intent"] == "file_operation" for s in r["parameters"]["steps"])


def test_brain_respects_explicit_shell_request():
    # Naming the shell must NOT be hijacked by the guardrail — it bails to None so
    # ask_claude falls through to the model (which routes to run_powershell).
    r = parse_file_creation_command("use PowerShell to make a folder build and a file inside it")
    assert r is None
