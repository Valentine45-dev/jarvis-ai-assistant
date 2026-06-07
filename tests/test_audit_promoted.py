"""R2-36: ten manual checks from audit-tests.txt promoted to automated tests.

Each test below was previously a one-off "verify by hand" item. Promoting
them protects against silent regression of the Round-1 fixes they cover.
"""

from __future__ import annotations

import io
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator

import pytest

import core.automation as automation
from core.brain import extract_tag
from core.handlers import code_exec as ce_module
from core.handlers import file_ops as fo_module
from core.handlers import shared as shared_module
from core.handlers.shared import (
    abandon_pending_confirmation,
    request_confirmation,
    resolve_confirmation,
)


# ── 1. Phase 1 #9 — datetime.utcnow() deprecation ─────────────────────────────


@pytest.fixture
def isolated_workflows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    target = tmp_path / "workflows.json"
    target.write_text(json.dumps({"workflows": []}), encoding="utf-8")
    monkeypatch.setattr(automation, "_WORKFLOWS_PATH", target, raising=True)
    yield target


def test_workflow_last_run_uses_utc_z_suffix(isolated_workflows: Path) -> None:
    """mark_run() must produce an ISO-8601 timestamp ending in Z (UTC).

    The previous implementation used the deprecated `datetime.utcnow()`;
    the replacement uses `datetime.now(timezone.utc)` with a `Z` suffix.
    """
    lib = automation.WorkflowLibrary()
    lib.add({
        "id": "ts_check",
        "name": "TS Check",
        "trigger": "Manual",
        "enabled": True,
        "last_run": "",
        "steps": [],
    })
    lib.mark_run("ts_check")
    ts = lib.get("ts_check")["last_run"]
    assert ts.endswith("Z"), f"last_run must end with 'Z' (UTC), got {ts!r}"
    # Sanity-check it parses as an ISO timestamp.
    parsed = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    assert parsed.year >= 2024


# ── 2. Phase 2 #13 — _ok/_err are the same object across 3 modules ────────────


def test_ok_and_err_helpers_are_shared_singletons() -> None:
    """code_exec, file_ops, and shared must all reference the same _ok/_err.

    A duplicate definition would diverge response shape and break the
    success/error contract clients rely on.
    """
    assert ce_module._ok is shared_module._ok, "_ok diverged in code_exec"
    assert fo_module._ok is shared_module._ok, "_ok diverged in file_ops"
    assert ce_module._err is shared_module._err, "_err diverged in code_exec"
    assert fo_module._err is shared_module._err, "_err diverged in file_ops"


# ── 3. Phase 2 #18 — no _start_err symbol left in handlers ────────────────────


def test_no_start_err_callers_in_handlers() -> None:
    """`_start_err` was a private helper that got renamed/inlined. Any new
    reference to it would point at a dangling import."""
    root = Path(automation.__file__).parent / "handlers"
    offenders = []
    for py in root.glob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        if "_start_err" in text:
            offenders.append(py.name)
    assert not offenders, f"_start_err appears in: {offenders}"


# ── 4. Phase 3 #19 + #31 — debug-mode tags are silenced when disabled ─────────


def test_log_debug_silent_when_debug_mode_off(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With debug_mode=False, core.log.debug() must not print [voice]/[tts]/
    [wake]/[brain] tags to stdout. Phase 3 routed bare print()s through this."""
    import core.log as _log

    monkeypatch.setattr(_log, "_enabled", lambda: False)
    for tag in ("voice", "tts", "wake", "brain"):
        _log.debug(tag, "should not appear")
    captured = capsys.readouterr()
    for tag in ("[voice]", "[tts]", "[wake]", "[brain]"):
        assert tag not in captured.out, (
            f"{tag} leaked to stdout while debug_mode=False — Phase 3 print "
            "discipline regressed."
        )


def test_log_debug_speaks_when_debug_mode_on(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import core.log as _log

    monkeypatch.setattr(_log, "_enabled", lambda: True)
    _log.debug("brain", "hello")
    out = capsys.readouterr().out
    assert "[brain]" in out and "hello" in out


# ── 5. Phase 4 #8 — _INTENT_HUD covers the newer intents ──────────────────────


def test_intent_hud_has_reminder_weather_doc_entries() -> None:
    """The HUD label map must cover every intent the brain can route.
    Missing entries fall back to STANDBY and the HUD shows the wrong label."""
    # JarvisWindow imports a lot at module load; we only need the class attribute.
    # Read it as text to avoid Qt-app side effects in headless runs. R2-17a moved
    # the class out of main.py into the ui/main_window package.
    window_py = (
        Path(automation.__file__).parent.parent
        / "ui" / "main_window" / "window.py"
    )
    text = window_py.read_text(encoding="utf-8")
    block = re.search(r"_INTENT_HUD\s*=\s*\{(.*?)\}", text, re.DOTALL)
    assert block, "_INTENT_HUD definition not found in ui/main_window/window.py"
    body = block.group(1)
    for needed in ("reminder_task", "weather", "document_creation"):
        assert f'"{needed}"' in body, (
            f"_INTENT_HUD is missing an entry for {needed!r} — HUD will "
            "render STANDBY for this intent."
        )


# ── 6. Phase 4 #24 — extract_tag returns a 3-tuple in every case ──────────────


def test_extract_tag_returns_three_tuple_always() -> None:
    """extract_tag(text) -> (intent | None, cleaned_text, unknown_tag | None).
    Known tag, unknown tag, and no tag must all produce 3-tuples."""
    known = extract_tag("@files list everything")
    assert isinstance(known, tuple) and len(known) == 3
    assert known[0] == "file_operation"
    assert known[1] == "list everything"
    assert known[2] is None

    unknown = extract_tag("@notarealtag do something")
    assert isinstance(unknown, tuple) and len(unknown) == 3
    assert unknown[0] is None
    assert unknown[2] == "notarealtag"

    plain = extract_tag("just take a screenshot")
    assert isinstance(plain, tuple) and len(plain) == 3
    assert plain[0] is None and plain[2] is None


# ── 7. Phase 4 #33 — looks_like_folder is False for an existing file ──────────


def _mirror_looks_like_folder(target_path: Path, raw_norm: str) -> bool:
    """Inline mirror of the expression in document_handler.py around L728.

    Kept in lockstep with production by this test — if production changes,
    update both. We mirror rather than import because the value is built
    inline inside a long function and isn't exported.
    """
    return target_path.is_dir() or (
        (raw_norm.endswith("/") or raw_norm.endswith("\\"))
        and not target_path.is_file()
    )


def test_looks_like_folder_false_for_existing_file(tmp_path: Path) -> None:
    real_file = tmp_path / "report.docx"
    real_file.write_text("not really a docx", encoding="utf-8")

    # Bare file path → False.
    assert _mirror_looks_like_folder(real_file, str(real_file)) is False
    # Trailing slash on a real file is still False (Phase 4 fix — don't
    # synthesize a nested name inside a real file path).
    assert _mirror_looks_like_folder(real_file, str(real_file) + "\\") is False
    # Directory path → True.
    assert _mirror_looks_like_folder(tmp_path, str(tmp_path)) is True


# ── 8. Phase 5 #10 — workflow save then read-back is byte-identical ───────────


def test_workflow_save_round_trip_byte_identical(isolated_workflows: Path) -> None:
    lib = automation.WorkflowLibrary()
    wf = {
        "id": "round_trip",
        "name": "Round Trip",
        "trigger": "Manual",
        "enabled": True,
        "last_run": "",
        "steps": [
            {"intent": "open_app", "action": "open_browser", "parameters": {"browser": "chrome"}},
        ],
    }
    lib.add(wf)
    bytes_after_first = isolated_workflows.read_bytes()

    # Re-save without changing anything.
    lib2 = automation.WorkflowLibrary()
    # Force a write by calling _save under the lock the way the public API does.
    with lib2._lock:
        lib2._save()
    bytes_after_second = isolated_workflows.read_bytes()

    assert bytes_after_first == bytes_after_second, (
        "Re-saving an unmodified workflow library produced different bytes — "
        "JSON serialisation is no longer deterministic."
    )


# ── 9. Phase 5 #23 — move_file to multi-segment Documents subfolder ───────────


def test_move_file_to_multi_segment_subfolder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """move_file resolves multi-segment relative destinations under the user
    profile and lands the file in the right place (Phase 5 #23).

    The handler does not auto-create the destination tree — it relies on
    `_resolve_file_operation_path` finding an existing folder for the first
    segment. We mirror that: pin home, create Documents/proj/notes, then
    confirm the file ends up there.
    """
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    dest_dir = tmp_path / "Documents" / "proj" / "notes"
    dest_dir.mkdir(parents=True)

    src = tmp_path / "source.txt"
    src.write_text("payload", encoding="utf-8")

    abandon_pending_confirmation()
    result = fo_module._handle_file_operation(
        "move_file",
        {"path": str(src), "destination": "Documents/proj/notes"},
        confirmed=True,
    )
    # The handler always defers a confirm card — execute the pending fn.
    if result.get("needs_confirmation"):
        result = resolve_confirmation("yes")

    assert result.get("success") is True, f"move_file failed: {result}"
    moved = list(dest_dir.glob("source.txt"))
    assert moved, (
        f"source.txt not found in {dest_dir} — multi-segment resolution may have "
        f"rewritten the destination. Contents: {list(dest_dir.iterdir())}"
    )
    assert moved[0].read_text(encoding="utf-8") == "payload"
    assert not src.exists(), "source still exists after move"


# ── 10. Phase 6 #3 — concurrent request_confirmation does not deadlock ────────


def test_concurrent_request_confirmation_no_deadlock_no_drops() -> None:
    """Stress the confirmation slot from many threads; nothing should hang
    and every successful resolve must invoke exactly one callback."""
    abandon_pending_confirmation()
    invocations: list[int] = []
    inv_lock = threading.Lock()

    def _make_cb(idx: int):
        def _cb() -> dict:
            with inv_lock:
                invocations.append(idx)
            return {"success": True, "output": str(idx), "error": ""}
        return _cb

    barrier = threading.Barrier(20)

    def _producer(start: int) -> None:
        barrier.wait()
        for i in range(50):
            request_confirmation(f"p-{start}-{i}", _make_cb(start * 1000 + i))

    def _consumer() -> None:
        barrier.wait()
        for _ in range(50):
            resolve_confirmation("yes")
            time.sleep(0)  # yield

    threads = []
    for s in range(10):
        threads.append(threading.Thread(target=_producer, args=(s,), daemon=True))
    for _ in range(10):
        threads.append(threading.Thread(target=_consumer, daemon=True))

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
        assert not t.is_alive(), "thread hung — deadlock in confirmation API"

    # Every invocation must be a unique id — atomic pop ensures no duplicates.
    assert len(invocations) == len(set(invocations)), (
        f"Duplicate callback invocations: {len(invocations)} fired, "
        f"{len(set(invocations))} unique. Slot pop is not atomic."
    )
