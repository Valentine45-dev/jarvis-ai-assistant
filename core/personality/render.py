"""JARVIS response rendering (R2-17d split).

Part of the ``core/personality`` package. The pure functions that turn an
(intent, action, status, output, error) tuple into a humanised, randomised
spoken string, plus the response-assembly helpers. Pulls variant pools from
``core/personality/pools.py``.

The two ``from core.responders.utils import ...`` imports are intentionally
left lazy (inside functions) — ``core.responders.utils`` lazy-imports ``say``
from here, so deferring keeps the mutual dependency cycle-free at import time.
"""
from __future__ import annotations

import random

from core.personality.pools import (
    _DEFAULT,
    _NO_TRIM,
    _P,
    _SCHEDULED_FALLBACK_OK,
    _SCHEDULED_FOLLOWUP,
)


def _brief_scheduled_output(output: str, cap: int = 120) -> str:
    """One short fragment for {o} in scheduled follow-ups — no essay."""
    from core.responders.utils import path_basename
    s = (output or "").strip().replace("\r\n", "\n")
    if not s:
        return ""
    if "\n" in s:
        s = s.split("\n", 1)[0].strip()
    s = s[:cap] + "…" if len(s) > cap else s
    if ("/" in s or "\\" in s) and not s.startswith("http") and cap > 30:
        return path_basename(s, cap=80).strip()
    return s


def ack_scheduled_action(
    intent: str,
    action: str,
    exec_ok: bool,
    output: str = "",
    error: str = "",
) -> str:
    """Spoken + transcript line after an action completes (timer or immediate). Compact."""
    if not exec_ok:
        return say(intent, action, "err", output, error)

    pool = _SCHEDULED_FOLLOWUP.get((intent, action))
    if not pool:
        pool = _SCHEDULED_FOLLOWUP.get((intent, "*"))
    if not pool:
        return random.choice(_SCHEDULED_FALLBACK_OK)

    template = random.choice(pool)
    o = _brief_scheduled_output(output)
    if "{o}" in template:
        if not o:
            plain = [t for t in pool if "{o}" not in t]
            return random.choice(plain) if plain else random.choice(_SCHEDULED_FALLBACK_OK)
        try:
            return template.format(o=o)
        except (KeyError, ValueError):
            return template.replace("{o}", o)
    return template


def _clean_page_for_speech(raw: str, cap: int = 400) -> str:
    """Strip browser metadata headers and URLs; return only readable prose for TTS."""
    import re as _re
    lines = raw.splitlines()
    clean: list[str] = []
    in_content = False
    for line in lines:
        stripped = line.strip()
        # Skip metadata headers produced by browser.read_page()
        if stripped in ("--- Tab ---", "--- Page content ---"):
            in_content = stripped == "--- Page content ---"
            continue
        if stripped.startswith("Document title:") or stripped.startswith("URL:"):
            continue
        # Skip bare URLs
        if _re.match(r"https?://\S+$", stripped):
            continue
        if in_content or not stripped.startswith("---"):
            if stripped:
                clean.append(stripped)
    text = " ".join(clean).strip()
    if not text:
        return raw[:cap]
    return text[:cap] + ("…" if len(text) > cap else "")


def _clean_tabs_for_speech(raw: str) -> str:
    """Turn browser.list_tabs() output into a natural spoken sentence.

    The terminal form is ``N tabs open (* = active):`` + numbered
    ``  i. host — title *`` lines — fine to read but clunky to *hear* (the
    asterisk, the ``(* = active)`` legend, ``(no title)``). This reduces it to
    e.g. "2 tabs open: GitHub, active; and a blank tab." so the TTS says the
    names instead of a generic ack."""
    import re as _re
    lines = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]
    if not lines:
        return "No open tabs."
    head = ""
    items: list[str] = []
    for ln in lines:
        m = _re.match(r"^\d+\.\s*(.+)$", ln)
        if not m:
            hm = _re.match(r"^(\d+)\s+tabs?\s+open", ln, _re.I)
            if hm:
                head = ln.split("(", 1)[0].strip().rstrip(":")
            continue
        body = m.group(1).strip()
        active = body.endswith("*")
        body = body.rstrip("*").strip()
        host, sep, title = body.partition("—")
        host, title = host.strip(), title.strip()
        if title and title.lower() not in ("(no title)", "no title"):
            label = title
        elif "about:blank" in host or host in ("", "?"):
            label = "a blank tab"
        else:
            label = host
        items.append(f"{label}, active" if active else label)
    if not items:
        return "No open tabs."
    head = head or f"{len(items)} tab{'s' if len(items) != 1 else ''} open"
    return f"{head}: " + "; ".join(items) + "."


def say(intent: str, action: str, status: str, output: str = "", error: str = "") -> str:
    """Return a humanized, randomised spoken response.

    status: "ok" | "err"
    output: executor output string
    error:  executor error string
    """
    pool     = _P.get((intent, action)) or _P.get((intent, "*")) or _DEFAULT
    variants = pool.get(status) or _DEFAULT.get(status, ["Done."])

    def _trim(s: str, cap: int = 100) -> str:
        from core.responders.utils import path_basename
        if not s:
            return ""
        if len(s) > cap:
            s = s[:cap] + "…"
        # Show only filename/folder name for path-like strings (not URLs)
        if ("\\" in s or ("/" in s and not s.startswith("http"))) and cap > 40:
            return path_basename(s, cap=cap)
        return s

    def _trim_error(s: str, cap: int = 500) -> str:
        """Errors are explanations, not path listings — no basename shortcut."""
        if not s:
            return ""
        return s[:cap] + "…" if len(s) > cap else s

    if intent == "browser_automation" and action == "read_page":
        o = _clean_page_for_speech(output)
    elif intent == "browser_automation" and action == "list_tabs":
        o = _clean_tabs_for_speech(output)
    elif (intent, action) in _NO_TRIM or (intent, "*") in _NO_TRIM:
        o = output      # full output — never trim listings, OCR, code results
    else:
        o = _trim(output)
    e = _trim_error(error)

    template = random.choice(variants)
    try:
        return template.format(o=o, e=e)
    except (KeyError, IndexError):
        return template


def ask(confirmation_type: str, subject: str = "") -> str:
    """Return a confirmation question string for executor-level prompts."""
    pool     = _P.get(("confirmation", confirmation_type), {})
    variants = pool.get("ask", [f"Confirm: {subject}?"])
    template = random.choice(variants)
    try:
        return template.format(o=subject)
    except (KeyError, IndexError):
        return template


# ── Response assembler (Phase 1/2) ───────────────────────────────────────────

def _is_no_trim_action(intent: str, action: str) -> bool:
    return (intent, action) in _NO_TRIM or (intent, "*") in _NO_TRIM


def action_speech_pair(
    intent: str,
    action: str,
    exec_ok: bool,
    claude_response: str,
    output: str = "",
    error: str = "",
    *,
    last_step: tuple[str, str] | None = None,
) -> tuple[str, str | None]:
    """Primary line (usually Claude's preamble) plus optional compact done line.

    The follow-up uses the same pools as :func:`ack_scheduled_action` so normal
    commands get the same "There you go" cadence as timer-fired steps. Full
    listings/OCR/code are left as a single TTS (no chaser) via ``_NO_TRIM``.
    """
    if not exec_ok:
        return (say(intent, action, "err", output, error), None)

    if (
        intent == "automation_task"
        and action == "run_workflow"
    ):
        cr = (claude_response or "").strip()
        primary = cr or "All steps complete."
        out = (output or "").strip()
        if not out:
            follow = ack_scheduled_action(intent, action, True, output, error)
        else:
            li, la = (last_step[0], last_step[1]) if (
                last_step and last_step[0] and last_step[1]
            ) else (intent, action)
            follow = ack_scheduled_action(li, la, True, output, error)
        return (primary, follow)

    if _is_no_trim_action(intent, action):
        return (say(intent, action, "ok", output, error), None)

    cr = (claude_response or "").strip()
    if not cr:
        return (say(intent, action, "ok", output, error), None)

    follow = ack_scheduled_action(intent, action, True, output, error)
    return (cr, follow)


def build_response(
    intent: str,
    action: str,
    exec_ok: bool,
    claude_response: str,
    output: str = "",
    error: str = "",
    last_step: tuple[str, str] | None = None,
) -> str:
    """Assemble the final **display** string for an action (primary + follow-up lines).

    For UI/TTS, prefer :func:`action_speech_pair` in ``main`` so the two lines can
    be spoken sequentially.
    """
    primary, follow = action_speech_pair(
        intent, action, exec_ok, claude_response, output, error, last_step=last_step
    )
    if follow:
        return f"{primary}\n{follow}"
    return primary
