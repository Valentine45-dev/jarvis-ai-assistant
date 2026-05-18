"""Shared utilities: result helpers, confirmation system, page cache."""

from __future__ import annotations

import platform
import re
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


def get_pending_confirmation() -> dict | None:
    if _pending_confirmation is None:
        return None
    return {
        "fn": _pending_confirmation.fn,
        "prompt": _pending_confirmation.prompt,
        "confirm_id": _pending_confirmation.confirm_id,
    }


def abandon_pending_confirmation() -> None:
    global _pending_confirmation
    _pending_confirmation = None


def request_confirmation(prompt: str, fn: Any) -> dict:
    global _pending_confirmation
    cid = str(uuid.uuid4())
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
    global _pending_confirmation
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
