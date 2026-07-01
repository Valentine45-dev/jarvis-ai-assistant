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

import logging
import platform
import re
import threading
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
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
# R2-19: single-key dict written from browser handler / read from brain; lock
# keeps concurrent read_page + follow-up routing consistent.
#
# P3 lifecycle: this cache grounds a follow-up ("summarize", "who won") in the
# page/SERP the user just read (the brain injects it as <page_content>). It must
# NOT linger into an unrelated conversation, or it answers new questions with
# stale content. Two invalidations: (1) a NEW search / navigation clears it (a
# topic-change signal — see _do_search_web / browser_handler navigate), and
# (2) a TTL backstop expires it so an unrelated follow-up with no intervening
# navigation can't leak it either. A same-page multi-turn follow-up still works
# (within the TTL).

_PAGE_CACHE: dict[str, object] = {}   # {"text": str, "ts": float(monotonic)}
_PAGE_CACHE_LOCK = threading.Lock()
_PAGE_CACHE_TTL_S = 120.0             # stale content expires after 2 minutes


def get_page_cache() -> str | None:
    with _PAGE_CACHE_LOCK:
        text = _PAGE_CACHE.get("text")
        if not text:
            return None
        ts = float(_PAGE_CACHE.get("ts", 0.0))
        if _PAGE_CACHE_TTL_S and (time.monotonic() - ts) > _PAGE_CACHE_TTL_S:
            _PAGE_CACHE.clear()       # expired — drop it so it can't ground a later turn
            return None
        return text  # type: ignore[return-value]


def _set_page_cache(text: str) -> None:
    with _PAGE_CACHE_LOCK:
        _PAGE_CACHE["text"] = text
        _PAGE_CACHE["ts"] = time.monotonic()


def _clear_page_cache() -> None:
    """Drop any cached page content — called when a new search/navigation starts
    (topic change), so a stale page can't ground an unrelated follow-up."""
    with _PAGE_CACHE_LOCK:
        _PAGE_CACHE.clear()


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
    with _pending_lock:
        # R3-6: never overwrite an outstanding confirmation — that would silently
        # discard the first callback (e.g. a workflow's resume continuation).
        # Refuse instead, matching the _process_cmd "respond to the pending
        # confirmation first" UI guard. The legitimate workflow case (a later
        # step re-registering its own confirmation) is safe: resolve_confirmation
        # clears the slot BEFORE invoking the resume closure, so the slot is empty
        # at re-registration and this guard doesn't fire.
        if _pending_confirmation is not None:
            return _err("Please resolve the current confirmation first.")
        cid = str(uuid.uuid4())
        _pending_confirmation = _PendingConfirmation(cid, fn, prompt)
    # Surface executor-level confirmations in the debug log. The brain's
    # `requires_confirmation` (the [brain] CONFIRM line) is a SEPARATE flag and is
    # often False here — the modal the user sees comes from THIS path, so without
    # this line the log looks like it "got it wrong".
    try:
        from core.log import debug as _dbg
        first_line = next((ln for ln in (prompt or "").splitlines() if ln.strip()), "")
        _dbg("confirm", f"executor confirmation requested → {first_line.strip()}")
    except Exception:
        pass
    return _confirm(prompt)


def replace_confirmation(prompt: str, fn: Any) -> dict:
    """Swap the callback on the CURRENT pending confirmation (keeping its id), or
    register a new one if none exists.

    This is the WRAP path: the workflow runner uses it to replace a leaf step's
    just-registered confirmation with a continuation that runs the leaf callback
    *and then* resumes the remaining steps — the original callback is preserved
    inside `fn`, so nothing is lost. It deliberately overwrites, unlike
    request_confirmation() whose R3-6 guard refuses an overwrite (which protects
    against an UNRELATED second confirmation silently discarding the first).
    """
    global _pending_confirmation
    with _pending_lock:
        cid = _pending_confirmation.confirm_id if _pending_confirmation else str(uuid.uuid4())
        _pending_confirmation = _PendingConfirmation(cid, fn, prompt)
    return _confirm(prompt)


_NEGATION_TOKENS: frozenset[str] = frozenset({
    "no", "don't", "cancel", "stop", "nope", "never", "wait", "abort",
})


def _is_affirmative_reply(user_response: str) -> bool:
    t = user_response.strip().lower()
    if not t:
        return False
    toks = set(re.findall(r"[a-z0-9']+", t))
    # R3-7: negation guard — a reply containing any negation/abort word is NOT
    # an affirmative even when it also contains "yes"/"sure" ("yes — wait, no",
    # "sure, actually cancel"). Checked before any affirmative match so a hedged
    # or self-correcting reply can't fire a destructive confirmation.
    if toks & _NEGATION_TOKENS:
        return False
    for phrase in (
        "go ahead", "do it", "create it", "sounds good", "that's fine",
        "as planned", "please do", "proceed", "yes please",
    ):
        if phrase in t:
            return True
    # R3-7: bare "please" removed — too weak a signal to execute on its own.
    if t in ("y", "yes", "yeah", "yep", "ok", "okay", "sure", "confirm", "k"):
        return True
    if toks & {"yes", "yeah", "yep", "sure", "confirm", "proceed", "absolutely", "ok"}:
        return True
    return False


def is_decisive_confirmation_reply(text: str) -> bool:
    """True when *text* is a clear yes OR a clear no — i.e. an actual answer to a
    confirmation card. Ambiguous input (a new directive like "open chrome", a
    question, a bare "please") is neither, so the caller should keep the card up
    and re-ask rather than silently standing down (cancelling) on it."""
    if _is_affirmative_reply(text):
        return True
    toks = set(re.findall(r"[a-z0-9']+", (text or "").strip().lower()))
    return bool(toks & _NEGATION_TOKENS)


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


# ── Terminal panel streaming ──────────────────────────────────────────────────
#
# _tlog is the single emit point used by every handler that wants to surface an
# action-summary line to the terminal panel. It also mirrors the same line to
# logs/terminal.log when config.terminal_log_to_file is true.
#
# Format conventions (callers pick the glyph):
#   ❯  action starting
#   ✓  success
#   ✗  failure
#   ⚠  confirmation pending / warning
#   ↳  sub-detail (picker result, path, etc.)
#
# Never raises. Real failures are surfaced to stderr via core.log.error so they
# remain debuggable without crashing the handler that called us.

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
_FILE_LOGGER: logging.Logger | None = None
_FILE_LOGGER_LOCK = threading.Lock()


def _ensure_file_logger() -> logging.Logger | None:
    """Lazy-init a 5MB×3 rotating logger writing to logs/terminal.log."""
    global _FILE_LOGGER
    if _FILE_LOGGER is not None:
        return _FILE_LOGGER
    with _FILE_LOGGER_LOCK:
        if _FILE_LOGGER is not None:
            return _FILE_LOGGER
        try:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                _LOG_DIR / "terminal.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter(
                "[%(asctime)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            logger = logging.getLogger("jarvis.terminal")
            logger.setLevel(logging.INFO)
            logger.propagate = False
            if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
                logger.addHandler(handler)
            _FILE_LOGGER = logger
            return _FILE_LOGGER
        except Exception as exc:
            try:
                from core.log import error
                error("tlog", f"file logger init failed: {exc}")
            except Exception:
                pass
            return None


# UX-2: workflow step context. While automation_handler dispatches a step,
# leaf-handler `_tlog` lines should auto-indent so the workflow output looks
# like:
#
#   ❯ workflow: morning test   ← col 0 (automation header)
#       ❯ open notepad          ← 4sp (leaf handler)
#         ✓ launched            ← 6sp (leaf handler)
#                               ← blank (emitted by automation between steps)
#
# Using a depth counter so nested workflows leave the outer context intact
# when the inner one finishes.
_workflow_ctx = threading.local()


def _enter_workflow_step() -> None:
    """Begin a workflow step — leaf handler _tlog calls will auto-indent."""
    _workflow_ctx.depth = getattr(_workflow_ctx, "depth", 0) + 1


def _leave_workflow_step() -> None:
    """End a workflow step — restore prior indent state."""
    _workflow_ctx.depth = max(0, getattr(_workflow_ctx, "depth", 0) - 1)


def _is_inside_workflow_step() -> bool:
    return getattr(_workflow_ctx, "depth", 0) > 0


def _step_indent_for(stripped: str) -> str:
    """6 spaces for completion / progress markers, 4 spaces otherwise."""
    return "      " if stripped.startswith(("✓", "✗", "↳", "⚠")) else "    "


def _tlog(line: str) -> None:
    """Emit one action-summary line to the terminal panel.

    Gated by `config.terminal_show_actions`. When `config.terminal_log_to_file`
    is also true, mirrors the line to logs/terminal.log via a rotating handler.

    UX-1: completion lines (✓ / ✗) get a trailing blank line so back-to-back
    actions in the terminal panel stay visually separated. Header / progress
    lines (❯, ↳, ⚠) are not separated since they belong with the action
    that follows them.

    UX-2: when called from inside a workflow step (the dispatch from
    automation_handler._run_from), auto-indent the line so leaf handlers'
    output sits below the workflow header. Also suppress the auto-blank —
    automation_handler emits one blank between steps deliberately so
    nested completions don't double-space.
    """
    try:
        from config.settings import config
        if not config.terminal_show_actions:
            return
        from core.signals import signals

        inside_workflow = _is_inside_workflow_step()
        emit_line = line
        if inside_workflow and not (line.startswith(" ") or line.startswith("\t")):
            stripped = line.lstrip()
            emit_line = _step_indent_for(stripped) + line

        signals.terminal_line_ready.emit(emit_line)

        if not inside_workflow:
            # UX-1: blank line after action completion (only outside workflows;
            # automation_handler emits its own between-step blank otherwise).
            stripped = line.lstrip()
            if stripped.startswith(("✓", "✗")):
                signals.terminal_line_ready.emit("")
        if getattr(config, "terminal_log_to_file", False):
            logger = _ensure_file_logger()
            if logger is not None:
                try:
                    logger.info(emit_line)
                except Exception as exc:
                    try:
                        from core.log import error
                        error("tlog", f"file write failed: {exc}")
                    except Exception:
                        pass
    except Exception as exc:
        try:
            from core.log import error
            error("tlog", f"emit failed: {exc}")
        except Exception:
            pass


def _tlog_step(line: str) -> None:
    """Emit one indented workflow step line. Skips _tlog's auto-blank-line
    so automation_handler controls its own between-step spacing.

    Used by automation_handler itself when it wants to emit a step-level
    line (rather than a leaf handler doing so). Leaf-handler _tlog calls
    inside a workflow already auto-indent via the workflow context, so
    they don't need to switch to _tlog_step.
    """
    try:
        from config.settings import config
        if not config.terminal_show_actions:
            return
        from core.signals import signals
        stripped = line.lstrip()
        emit_line = _step_indent_for(stripped) + line.lstrip()
        signals.terminal_line_ready.emit(emit_line)
        if getattr(config, "terminal_log_to_file", False):
            logger = _ensure_file_logger()
            if logger is not None:
                try:
                    logger.info(emit_line)
                except Exception as exc:
                    try:
                        from core.log import error
                        error("tlog_step", f"file write failed: {exc}")
                    except Exception:
                        pass
    except Exception as exc:
        try:
            from core.log import error
            error("tlog_step", f"emit failed: {exc}")
        except Exception:
            pass


# ── Redaction for fill/type values ────────────────────────────────────────────
#
# _redact_value masks sensitive values before they reach the terminal panel.
# Applied in order:
#   1. Field goal/selector mentions a sensitive keyword → "••••"
#   2. Email-shaped value → "v•••@domain.com"
#   3. Single token >24 chars (no whitespace) → "<redacted N chars>"
#   4. Otherwise → truncate at 60 chars with ellipsis
#
# "key" and "token" alone are too ambiguous (cf. "key takeaway",
# "token of appreciation") so they only mask when paired with an auth-context
# modifier (api key, access token, ssh key, etc.).

_REDACT_GOAL_RE = re.compile(
    r"""
    \b(?:
        password | passwd | pwd | pin | ssn | cvv | secret | otp |
        api[\s_-]?key | api[\s_-]?token |
        access[\s_-]?token | auth[\s_-]?token | refresh[\s_-]?token |
        bearer[\s_-]?token | session[\s_-]?token | csrf[\s_-]?token |
        private[\s_-]?key | public[\s_-]?key | ssh[\s_-]?key |
        encryption[\s_-]?key | security[\s_-]?key | license[\s_-]?key
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_EMAIL_RE = re.compile(r"^([^\s@]+)@([^\s@]+\.[^\s@]+)$")


def _redact_value(goal: str, value: str) -> str:
    """Mask sensitive values for terminal display. Never raises."""
    try:
        if value is None:
            return ""
        s = str(value)
        g = str(goal or "")
        if _REDACT_GOAL_RE.search(g):
            return "••••"
        m = _EMAIL_RE.match(s.strip())
        if m:
            local, domain = m.group(1), m.group(2)
            head = local[:1] if local else ""
            return f"{head}•••@{domain}"
        if len(s) > 24 and " " not in s and "\t" not in s:
            return f"<redacted {len(s)} chars>"
        if len(s) > 60:
            return s[:60] + "…"
        return s
    except Exception:
        return "<redact-failed>"
