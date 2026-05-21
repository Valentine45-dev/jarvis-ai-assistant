"""Unit tests for scheduled reminder action validation (no timers)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# _validate_reminder_run is re-exported from core.executor; _format_run_summary
# is not — both originally lived under executor but were moved into the
# reminders handler. Import each from its current canonical home so this test
# doesn't break the next time someone tidies the executor's re-export list.
from core import executor as ex
from core.handlers.reminders import _format_run_summary


def test_validate_reminder_run_none():
    d, err = ex._validate_reminder_run(None)
    assert d is None and err is None


def test_validate_reminder_run_safe_open():
    d, err = ex._validate_reminder_run(
        {"intent": "open_app", "action": "open_browser", "parameters": {"browser": "chrome"}}
    )
    assert err is None and d is not None
    assert d["intent"] == "open_app"


def test_validate_reminder_run_blocks_file_op():
    d, err = ex._validate_reminder_run(
        {"intent": "file_operation", "action": "delete_file", "parameters": {"path": "x"}}
    )
    assert d is None and err and "not allowed" in err.lower()


def test_format_run_summary():
    s = _format_run_summary(
        {"intent": "search_web", "action": "google_search", "parameters": {"query": "jarvis"}}
    )
    assert "search" in s.lower() or "jarvis" in s.lower()
