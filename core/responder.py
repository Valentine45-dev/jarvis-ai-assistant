"""
core/responder.py — Context-aware response assembler for JARVIS.

Replaces the static _SCHEDULED_FOLLOWUP pool in personality.py.

Philosophy:
  - Primary  = Claude's contextual response (already generated, always natural)
  - Follow   = data-rich result line (only where it adds value — step count,
                filename, domain — never a canned "There you go" echo)
  - Suppress = no follow-up when Claude's response alone is complete
  - Error    = params-aware message (names the app, URL, file that failed)
  - Fallback = personality.say() pool as final safety net only
"""
from __future__ import annotations

import re
from typing import Optional


# ── Suppress follow-up: Claude's response is already a complete statement ─────
# "Opening Chrome." needs no echo. "Reminder set for 15 minutes." is done.
_SUPPRESS_FOLLOW: frozenset = frozenset({
    ("open_app",            "*"),
    ("close_app",           "*"),
    ("search_web",          "*"),
    ("type_text",           "*"),
    ("control_mouse",       "*"),
    ("system_control",      "volume_up"),
    ("system_control",      "volume_down"),
    ("system_control",      "volume_mute"),
    ("system_control",      "volume_unmute"),
    ("system_control",      "brightness_up"),
    ("system_control",      "brightness_down"),
    ("system_control",      "lock_screen"),
    ("system_control",      "sleep"),
    ("system_control",      "shutdown"),
    ("system_control",      "restart"),
    ("system_control",      "wifi_toggle"),
    ("system_control",      "bluetooth_toggle"),
    ("browser_automation",  "navigate"),
    ("browser_automation",  "click_element"),
    ("browser_automation",  "close_tab"),
    ("browser_automation",  "new_tab"),
    ("reminder_task",       "set_reminder"),
    ("reminder_task",       "cancel_reminder"),
    ("automation_task",     "create_workflow"),
    ("automation_task",     "rename_workflow"),
    ("automation_task",     "remove_workflow"),
    ("jarvis_meta",         "change_theme"),
    ("jarvis_meta",         "set_wake_word"),
    ("jarvis_meta",         "change_voice"),
})

# ── Output-IS-response: full output goes to TTS — no Claude preamble needed ───
# Listings, OCR text, code output, page content are their own response.
_OUTPUT_IS_RESPONSE: frozenset = frozenset({
    ("browser_automation", "read_page"),
    ("browser_automation", "extract_text"),
    ("read_screen",        "*"),
    ("code_execution",     "*"),
    ("file_operation",     "read_file"),
    ("file_operation",     "list_directory"),
    ("file_operation",     "search_files"),
    ("reminder_task",      "list_reminders"),
    ("automation_task",    "list_workflows"),
    ("jarvis_meta",        "status_report"),
    ("jarvis_meta",        "list_voices"),
})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _in(intent: str, action: str, s: frozenset) -> bool:
    return (intent, action) in s or (intent, "*") in s


def _filename(path: str) -> str:
    """Return just the final filename/folder from a path string."""
    if not path:
        return ""
    if path.startswith("http"):
        return path[:60]
    parts = path.replace("\\", "/").split("/")
    name = next((p for p in reversed(parts) if p), path)
    return name[:80]


def _domain(url: str) -> str:
    """Extract a readable domain name from a URL."""
    if not url:
        return ""
    m = re.match(r"https?://(?:www\.)?([^/?#]+)", url)
    return m.group(1) if m else url[:50]


def _count_ok_steps(output: str) -> int:
    """Count successful steps in workflow output ('Step N: OK — …')."""
    return sum(
        1 for line in (output or "").splitlines()
        if re.match(r"Step\s+\d+:\s+OK", line.strip())
    )


def _first_sentence(text: str, cap: int = 150) -> str:
    """Truncate at first sentence-ending punctuation if text is too long."""
    if not text or len(text) <= cap:
        return text
    m = re.search(r"[.!?]", text[:cap])
    return text[:m.end()].strip() if m else text[:cap].strip()


def _tts_safe_output(output: str) -> str:
    """Sanitize raw code/script stdout for spoken delivery.

    Removes decorative separator lines, shortens absolute file paths to just
    the filename, and caps at 180 chars so TTS stays concise.
    """
    if not output:
        return "Done."
    kept = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Drop pure decorator lines (only =, -, or space characters)
        if set(stripped) <= {"=", "-", " "}:
            continue
        # Shorten Windows absolute paths — keep only the final filename/folder
        shortened = re.sub(
            r"[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*([^\\/:*?\"<>|\r\n]+)",
            lambda m: m.group(1),
            stripped,
        )
        # Also shorten Unix-style absolute paths
        shortened = re.sub(
            r"/(?:[^/\s]+/)+([^/\s]+)",
            lambda m: m.group(1),
            shortened,
        )
        kept.append(shortened)

    text = "  ".join(kept).strip()
    if not text:
        return "Done."
    if len(text) > 180:
        text = text[:180].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return text


# ── Data-rich follow-up builders ──────────────────────────────────────────────

def _data_follow(
    intent: str,
    action: str,
    output: str,
    params: dict,
) -> Optional[str]:
    """Return a result-aware follow-up string, or None if nothing useful to add."""
    output = (output or "").strip()
    params = params or {}

    # Workflow completion — report step count
    if intent == "automation_task" and action == "run_workflow":
        n = _count_ok_steps(output)
        if n:
            return f"{n} step{'s' if n != 1 else ''} done."
        return "All steps complete."

    if intent == "file_operation":
        if action in ("create_file", "create_directory"):
            path = params.get("path", "") or output
            name = _filename(path)
            if action == "create_file":
                return f"Saved at {name}." if name else None
            return f"Folder ready — {name}." if name else None
        if action == "rename_file":
            old = _filename(params.get("path", ""))
            new = params.get("new_name", "")
            if old and new:
                return f"{old} → {new}."
        if action in ("move_file", "copy_file"):
            dest = _filename(params.get("destination", ""))
            return f"Moved to {dest}." if dest else None
        if action == "delete_file":
            name = _filename(params.get("path", ""))
            return f"Deleted — {name}." if name else "Deleted."

    if intent == "browser_automation":
        if action == "fill_form":
            return "Fields confirmed."
        if action == "screenshot":
            name = _filename(output or params.get("save_path", ""))
            return f"Saved — {name}." if name else "Captured."

    if intent == "system_control" and action == "screenshot":
        name = _filename(output)
        return f"Saved — {name}." if name else None

    return None


# ── Params-aware error messages ───────────────────────────────────────────────

def _smart_error(
    intent: str,
    action: str,
    error: str,
    params: dict,
) -> str:
    """Build an informative error message that names the specific thing that failed."""
    params   = params or {}
    error    = (error or "").strip()
    short_e  = (error[:100] + "…" if len(error) > 100 else error)

    if intent == "open_app":
        app = (
            params.get("app_name")
            or params.get("browser")
            or params.get("url")
            or "that application"
        )
        return f"Couldn't open {app}. {short_e}" if short_e else f"Couldn't find {app} — is it installed?"

    if intent == "close_app":
        app = params.get("app_name") or params.get("process_name") or "that application"
        return f"Couldn't close {app}." + (f" {short_e}" if short_e else "")

    if intent == "search_web":
        query = params.get("query", "")
        return f"Search failed for {query!r}." + (f" {short_e}" if short_e else "") if query else f"Search failed. {short_e}"

    if intent == "browser_automation":
        if action == "navigate":
            domain = _domain(params.get("url", ""))
            base   = f"Couldn't load {domain}." if domain else "Navigation failed."
            return f"{base} {short_e}" if short_e else base
        if action == "click_element":
            target = params.get("text") or params.get("selector") or "that element"
            return f"Couldn't click {target!r}." + (f" {short_e}" if short_e else "")
        if action == "fill_form":
            return "Couldn't fill the form." + (f" {short_e}" if short_e else "")
        if action in ("new_tab", "close_tab"):
            return f"Tab action failed." + (f" {short_e}" if short_e else "")

    if intent == "file_operation":
        path = params.get("path", "")
        name = _filename(path)
        label = f"{name!r}" if name else "that file"
        if action in ("create_file", "create_directory"):
            return f"Couldn't create {label}." + (f" {short_e}" if short_e else "")
        if action == "delete_file":
            return f"Couldn't delete {label}." + (f" {short_e}" if short_e else "")
        if action == "read_file":
            return f"Couldn't read {label}." + (f" {short_e}" if short_e else "")
        if action == "rename_file":
            new = params.get("new_name", "")
            return f"Couldn't rename {label} to {new!r}." if new else f"Rename failed. {short_e}"
        if action == "move_file":
            dest = _filename(params.get("destination", ""))
            return f"Couldn't move {label} to {dest!r}." if dest else f"Move failed. {short_e}"
        if action == "search_files":
            return f"Nothing found." + (f" {short_e}" if short_e else "")

    if intent == "system_control":
        if action == "screenshot":
            return "Screenshot failed." + (f" {short_e}" if short_e else "")
        if action in ("volume_up", "volume_down", "volume_mute", "volume_unmute"):
            return "Volume control failed." + (f" {short_e}" if short_e else "")
        if action in ("brightness_up", "brightness_down"):
            return "Brightness adjustment failed." + (f" {short_e}" if short_e else "")

    if intent == "code_execution":
        return "Execution failed." + (f"\n{short_e}" if short_e else "")

    if intent == "automation_task":
        if action == "run_workflow":
            name = params.get("task_name", "")
            base = f"Workflow {name!r} hit an error." if name else "Workflow failed."
            return f"{base}\n{short_e}" if short_e else base

    if intent == "reminder_task":
        if action == "set_reminder":
            msg = params.get("message", "")
            return f"Couldn't set reminder for {msg!r}." if msg else f"Reminder failed. {short_e}"
        if action == "cancel_reminder":
            return f"No matching reminder found." + (f" {short_e}" if short_e else "")

    # Final fallback — personality pool knows all intent/action pairs
    from core.personality import say as _pool_say
    return _pool_say(intent, action, "err", "", error)


# ── Main assembler ────────────────────────────────────────────────────────────

class ResponseAssembler:
    """Assembles (primary, follow) spoken response for any JARVIS command."""

    def build(
        self,
        intent: str,
        action: str,
        exec_ok: bool,
        claude_response: str,
        output: str = "",
        error: str = "",
        params: Optional[dict] = None,
        last_step: Optional[tuple] = None,
    ) -> tuple[str, Optional[str]]:
        """
        Returns (primary_tts, follow_tts | None).

        primary is guaranteed non-empty.
        follow is None unless it adds actionable result data.
        """
        params = params or {}

        # ── Error path ────────────────────────────────────────────────────────
        if not exec_ok:
            return (_smart_error(intent, action, error, params), None)

        # ── Output-IS-response (listings, OCR, code, read_page) ──────────────
        if _in(intent, action, _OUTPUT_IS_RESPONSE):
            from core.personality import say as _pool_say
            # Code output can contain separator bars, long paths, and hundreds
            # of lines — sanitize to a spoken-length summary before TTS.
            tts_out = _tts_safe_output(output) if intent == "code_execution" else output
            return (_pool_say(intent, action, "ok", tts_out, error), None)

        # ── Standard path: Claude primary + optional data-rich follow ─────────
        primary = _first_sentence((claude_response or "").strip())
        if not primary:
            from core.personality import say as _pool_say
            primary = _pool_say(intent, action, "ok", output, error)

        # Suppress follow-up for self-contained responses
        if _in(intent, action, _SUPPRESS_FOLLOW):
            return (primary, None)

        # Build data-rich follow-up
        follow = _data_follow(intent, action, output, params)
        return (primary, follow)

    def build_scheduled(
        self,
        intent: str,
        action: str,
        exec_ok: bool,
        output: str = "",
        error: str = "",
        params: Optional[dict] = None,
    ) -> str:
        """
        Single spoken line for reminder-fired (scheduled) actions.
        Always returns a non-empty string.
        """
        params = params or {}

        if not exec_ok:
            return _smart_error(intent, action, error, params)

        follow = _data_follow(intent, action, output, params)
        if follow:
            return follow

        # Fallback: personality pool for scheduled actions
        from core.personality import ack_scheduled_action
        return ack_scheduled_action(intent, action, True, output, error)


responder = ResponseAssembler()
