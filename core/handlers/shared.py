"""Shared utilities: result helpers, confirmation system, page cache.

Confirmation matrix — who shows the confirm card for what:

  | Intent / Action                                  | Where confirm fires       |
  |--------------------------------------------------|---------------------------|
  | system_control: shutdown / restart / sleep       | executor (_CONFIRMATION_  |
  | close_app: force_quit                            |  REQUIRED_ACTIONS gate)   |
  | code_execution: kill_process                     | executor                  |
  | automation_task: remove_workflow                 | executor                  |
  | file_operation: delete_file                      | brain sets requires_      |
  |                                                  |  confirmation=true        |
  | file_operation: create_file / create_directory / | handler calls             |
  |  rename_file / move_file / replace_in_file /     |  request_confirmation()   |
  |  batch_delete                                    |  (brain leaves rc=false)  |
  | code_execution: any with _danger_check hit       | handler (in-flight prompt)|

  Verify each path under: (a) direct command, (b) auto-confirm ON,
  (c) inside a workflow step.
"""

from __future__ import annotations

import platform
import re
import threading
import uuid
from typing import Any

_OS = platform.system().lower()  # "windows" | "darwin" | "linux"


# ── Result helpers ────────────────────────────────────────────────────────────

def _ok(output: str = "") -> dict:
    return {"success": True, "output": output, "error": ""}


def _err(msg: str) -> dict:
    return {"success": False, "output": "", "error": msg}


def _coerce_volume_level(params: dict) -> int | None:
    """Parse `parameters.level` for absolute 0–100%. Returns None to mean 'step'."""
    raw = params.get("level")
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return max(0, min(100, int(raw)))
    s = str(raw).strip().lower()
    if s in ("max", "full", "maximum", "100%", "all", "highest"):
        return 100
    if s.endswith("%"):
        try:
            return max(0, min(100, int(s[:-1].strip())))
        except ValueError:
            return None
    try:
        return max(0, min(100, int(float(s))))
    except ValueError:
        return None


def _confirm(prompt: str) -> dict:
    return {"success": False, "output": prompt, "error": "", "needs_confirmation": True}


# ── Page cache ────────────────────────────────────────────────────────────────

_PAGE_CACHE: dict[str, str] = {}


def get_page_cache() -> str | None:
    return _PAGE_CACHE.get("last_read")


def _set_page_cache(text: str) -> None:
    _PAGE_CACHE["last_read"] = text


# ── Confirmation system ───────────────────────────────────────────────────────

class _PendingConfirmation:
    __slots__ = ("confirm_id", "fn", "prompt")

    def __init__(self, confirm_id: str, fn: Any, prompt: str) -> None:
        self.confirm_id = confirm_id
        self.fn         = fn
        self.prompt     = prompt


_pending_confirmation: _PendingConfirmation | None = None
# All access to _pending_confirmation goes through this lock so the brain
# thread, voice thread, and Qt main thread can't race when a new command
# arrives while a confirmation is in flight.
_pending_lock = threading.Lock()


def get_pending_confirmation() -> dict | None:
    with _pending_lock:
        if _pending_confirmation is None:
            return None
        return {
            "fn": _pending_confirmation.fn,
            "prompt": _pending_confirmation.prompt,
            "confirm_id": _pending_confirmation.confirm_id,
        }


def abandon_pending_confirmation() -> None:
    global _pending_confirmation
    with _pending_lock:
        _pending_confirmation = None


def request_confirmation(prompt: str, fn: Any) -> dict:
    global _pending_confirmation
    cid = str(uuid.uuid4())
    with _pending_lock:
        _pending_confirmation = _PendingConfirmation(cid, fn, prompt)
    return _confirm(prompt)


def _is_affirmative_reply(user_response: str) -> bool:
    t = user_response.strip().lower()
    if not t:
        return False
    for phrase in (
        "go ahead", "do it", "create it", "sounds good", "that's fine",
        "as planned", "please do", "proceed", "yes please",
    ):
        if phrase in t:
            return True
    if t in ("y", "yes", "yeah", "yep", "ok", "okay", "sure", "confirm", "please", "k"):
        return True
    toks = set(re.findall(r"[a-z0-9']+", t))
    if toks & {"yes", "yeah", "yep", "sure", "confirm", "proceed", "absolutely", "ok"}:
        return True
    return False


def resolve_confirmation(user_response: str) -> dict:
    """Pop the pending confirmation and either invoke it or stand down.

    The pending slot is cleared BEFORE pc.fn() runs so the callback can register
    a fresh confirmation (e.g. a workflow continuation that itself prompts).
    The lock is released before pc.fn() so the callback can call other
    confirmation APIs without deadlocking.
    """
    global _pending_confirmation
    with _pending_lock:
        if _pending_confirmation is None:
            return _err("No pending action to confirm.")
        pc = _pending_confirmation
        _pending_confirmation = None
    if _is_affirmative_reply(user_response):
        if pc.fn:
            try:
                return pc.fn()
            except Exception as exc:
                return _err(str(exc))
        return _err("Action missing.")
    return {"success": False, "output": "Understood — standing down.", "error": ""}
