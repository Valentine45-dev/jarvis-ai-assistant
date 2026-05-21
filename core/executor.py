"""
Command router — receives a parsed intent dict from brain.py and
dispatches it to the correct OS handler.

Each handler receives (action: str, params: dict) and returns
{"success": bool, "output": str, "error": str}.

Special keys in return dict:
  "needs_confirmation": True — executor needs user yes/no before proceeding.
  "quit_application":   True — caller should quit the app after TTS.
"""

from __future__ import annotations

from typing import Any

from config.settings import config

# ── Re-export public API (callers import these from core.executor) ─────────────
from core.handlers.shared import (
    _ok,
    _err,
    get_page_cache,
    _set_page_cache,
    get_pending_confirmation,
    abandon_pending_confirmation,
    request_confirmation,
    resolve_confirmation,
)

# ── Re-export private symbols accessed by tests / popovers ────────────────────
from core.handlers.reminders import (
    _active_reminders,
    _validate_reminder_run,
    _reminder_meta,
)
from core.handlers.automation_handler import _CONFIRMATION_REQUIRED_ACTIONS

# ── Handler imports ───────────────────────────────────────────────────────────
from core.handlers.app_launcher import (
    _handle_open_app,
    _handle_close_app,
    _handle_search_web,
)
from core.handlers.input_control import _handle_type_text, _handle_control_mouse
from core.handlers.system import _handle_system_control
from core.handlers.file_ops import _handle_file_operation
from core.handlers.code_exec import _handle_code_execution
from core.handlers.browser_handler import _handle_browser_automation
from core.handlers.screen_handler import _handle_read_screen
from core.handlers.automation_handler import _handle_automation_task
from core.handlers.reminders import _handle_reminder_task
from core.handlers.weather import _handle_weather
from core.handlers.document_handler import _handle_document_creation
from core.handlers.meta import _handle_jarvis_meta, _handle_unknown


# ── Dispatch table ────────────────────────────────────────────────────────────

_HANDLERS = {
    "open_app":           _handle_open_app,
    "close_app":          _handle_close_app,
    "search_web":         _handle_search_web,
    "type_text":          _handle_type_text,
    "control_mouse":      _handle_control_mouse,
    "system_control":     _handle_system_control,
    "file_operation":     _handle_file_operation,
    "code_execution":     _handle_code_execution,
    "browser_automation": _handle_browser_automation,
    "read_screen":        _handle_read_screen,
    "automation_task":    _handle_automation_task,
    "reminder_task":      _handle_reminder_task,
    "weather":            _handle_weather,
    "document_creation":  _handle_document_creation,
    "jarvis_meta":        _handle_jarvis_meta,
    "unknown":            _handle_unknown,
}


def dispatch(result: dict[str, Any], confirmed: bool = False) -> dict[str, Any]:
    """Route a parsed intent dict to its OS handler.

    confirmed=True must be passed for destructive actions.
    Never raises — wraps every handler in try/except.
    """
    intent = result.get("intent", "unknown")
    action = result.get("action", "")
    params = result.get("parameters", {})

    # R2-2: strip any underscore-prefixed keys before the handler sees params.
    # The brain (Claude) could otherwise supply `_danger_confirmed: true` (or
    # any future internal magic key) inside `parameters` and bypass gate
    # checks that read those keys. Underscore-prefixed keys are reserved for
    # handler-internal state passed by trusted callers via separate kwargs,
    # never via the brain-generated params payload.
    if isinstance(params, dict):
        params = {
            k: v for k, v in params.items()
            if not (isinstance(k, str) and k.startswith("_"))
        }

    needs_confirmation = (
        result.get("requires_confirmation")
        or (intent, action) in _CONFIRMATION_REQUIRED_ACTIONS
    )
    if needs_confirmation and not confirmed:
        return _err(f"Action '{action}' requires confirmation before execution.")

    handler = _HANDLERS.get(intent, _handle_unknown)
    try:
        if intent == "file_operation":
            return handler(action, params, confirmed=confirmed)
        return handler(action, params)
    except Exception as exc:
        if config.debug_mode:
            print(f"[executor] Unhandled error in {intent}/{action}: {exc}")
        return _err(str(exc))
