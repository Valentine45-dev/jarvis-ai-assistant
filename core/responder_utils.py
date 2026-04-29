from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

# ── Suppress follow-up: Claude's response is already a complete statement ─────
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


def in_rule_set(intent: str, action: str, s: frozenset) -> bool:
    return (intent, action) in s or (intent, "*") in s


def filename(path: str) -> str:
    if not path:
        return ""
    if path.startswith("http"):
        return path[:60]
    parts = path.replace("\\", "/").split("/")
    name = next((p for p in reversed(parts) if p), path)
    return name[:80]


def domain(url: str) -> str:
    if not url:
        return ""
    m = re.match(r"https?://(?:www\.)?([^/?#]+)", url)
    return m.group(1) if m else url[:50]


def count_ok_steps(output: str) -> int:
    return sum(
        1 for line in (output or "").splitlines()
        if re.match(r"Step\s+\d+:\s+OK", line.strip())
    )


def first_sentence(text: str, cap: int = 150) -> str:
    if not text or len(text) <= cap:
        return text
    m = re.search(r"[.!?]", text[:cap])
    return text[:m.end()].strip() if m else text[:cap].strip()


def compact_path_for_speech(path: str) -> str:
    s = (path or "").strip().strip('"').strip("'")
    if not s:
        return s
    s = s.replace("\\", "/")
    s = re.sub(r"^[A-Za-z]:", "", s)
    parts = [p for p in s.split("/") if p and p not in (".", "..")]
    if not parts:
        return s
    if len(parts) == 1:
        return parts[0]
    return f"{parts[-2]}/{parts[-1]}"


def compact_url_for_speech(url: str) -> str:
    raw = (url or "").strip().strip('"').strip("'")
    if not raw:
        return raw
    p = urlparse(raw)
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return raw
    return host


def speech_compact(text: str) -> str:
    if not text:
        return text
    out = text
    out = re.sub(
        r"https?://[^\s)>\]\"']+",
        lambda m: compact_url_for_speech(m.group(0)),
        out,
    )
    out = re.sub(
        r"[A-Za-z]:\\[^\r\n\"']+",
        lambda m: compact_path_for_speech(m.group(0)),
        out,
    )
    out = re.sub(
        r"/(?:[^/\s]+/)*[^/\s]+",
        lambda m: compact_path_for_speech(m.group(0)),
        out,
    )
    return out


def tts_safe_output(output: str) -> str:
    if not output:
        return "Done."
    kept = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if set(stripped) <= {"=", "-", " "}:
            continue
        shortened = re.sub(
            r"[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*([^\\/:*?\"<>|\r\n]+)",
            lambda m: m.group(1),
            stripped,
        )
        shortened = re.sub(
            r"/(?:[^/\s]+/)+([^/\s]+)",
            lambda m: m.group(1),
            shortened,
        )
        kept.append(shortened)
    text = speech_compact("  ".join(kept).strip())
    return text or "Done."


def traceback_summary(error: str) -> str:
    if not error:
        return ""
    lines = [ln.strip() for ln in error.splitlines() if ln.strip()]
    if not lines:
        return ""
    tail = lines[-1]
    if ":" in tail:
        cls, msg = tail.split(":", 1)
        cls = cls.strip()
        msg = msg.strip()
        if cls.endswith("Error") or cls.endswith("Exception"):
            return f"{cls}: {msg}" if msg else cls
    if tail.endswith("Error") or tail.endswith("Exception"):
        return tail
    return ""


def data_follow(intent: str, action: str, output: str, params: dict) -> Optional[str]:
    output = (output or "").strip()
    params = params or {}

    if intent == "automation_task" and action == "run_workflow":
        n = count_ok_steps(output)
        if n:
            return f"{n} step{'s' if n != 1 else ''} done."
        return "All steps complete."

    if intent == "file_operation":
        if action in ("create_file", "create_directory"):
            path = params.get("path", "") or output
            name = filename(path)
            if action == "create_file":
                return f"Saved at {name}." if name else None
            return f"Folder ready — {name}." if name else None
        if action == "rename_file":
            old = filename(params.get("path", ""))
            new = params.get("new_name", "")
            if old and new:
                return f"{old} → {new}."
        if action in ("move_file", "copy_file"):
            dest = filename(params.get("destination", ""))
            return f"Moved to {dest}." if dest else None
        if action == "delete_file":
            name = filename(params.get("path", ""))
            return f"Deleted — {name}." if name else "Deleted."

    if intent == "browser_automation":
        if action == "fill_form":
            return "Fields confirmed."
        if action == "screenshot":
            name = filename(output or params.get("save_path", ""))
            return f"Saved — {name}." if name else "Captured."

    if intent == "system_control" and action == "screenshot":
        name = filename(output)
        return f"Saved — {name}." if name else None

    return None


def smart_error(intent: str, action: str, error: str, params: dict) -> str:
    params = params or {}
    error = (error or "").strip()
    compact_err = speech_compact(error)
    short_e = (compact_err[:100] + "…" if len(compact_err) > 100 else compact_err)

    if intent == "open_app":
        app = params.get("app_name") or params.get("browser") or params.get("url") or "that application"
        return f"Couldn't open {app}. {short_e}" if short_e else f"Couldn't find {app} — is it installed?"
    if intent == "close_app":
        app = params.get("app_name") or params.get("process_name") or "that application"
        return f"Couldn't close {app}." + (f" {short_e}" if short_e else "")
    if intent == "search_web":
        query = params.get("query", "")
        return f"Search failed for {query!r}." + (f" {short_e}" if short_e else "") if query else f"Search failed. {short_e}"
    if intent == "browser_automation":
        if action == "navigate":
            d = domain(params.get("url", ""))
            base = f"Couldn't load {d}." if d else "Navigation failed."
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
        name = filename(path)
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
            dest = filename(params.get("destination", ""))
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
        tb = speech_compact(traceback_summary(error))
        if tb:
            return f"Execution failed.\n{tb}"
        return "Execution failed." + (f"\n{short_e}" if short_e else "")
    if intent == "automation_task" and action == "run_workflow":
        name = params.get("task_name", "")
        base = f"Workflow {name!r} hit an error." if name else "Workflow failed."
        full_e = compact_err.strip()
        return f"{base}\n{full_e}" if full_e else base
    if intent == "reminder_task":
        if action == "set_reminder":
            msg = params.get("message", "")
            return f"Couldn't set reminder for {msg!r}." if msg else f"Reminder failed. {short_e}"
        if action == "cancel_reminder":
            return f"No matching reminder found." + (f" {short_e}" if short_e else "")

    from core.personality import say as pool_say
    return pool_say(intent, action, "err", "", error)
