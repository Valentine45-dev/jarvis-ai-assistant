"""
JARVIS personality layer — maps (intent, action, success/error) → spoken response.
Uses random.choice() across variant pools so JARVIS never sounds like a bot.
"""
from __future__ import annotations
import random

# Format keys: {o} = trimmed output, {e} = trimmed error
_P: dict[tuple, dict] = {
    # ── BROWSER AUTOMATION ──────────────────────────────────────────
    ("browser_automation", "navigate"): {
        "ok": [
            "Page is up, sir.",
            "Done — loaded it for you.",
            "There you go — it's open.",
            "Navigated. Take a look.",
        ],
        "err": [
            "Couldn't reach that, sir. {e}",
            "Navigation failed — {e}",
            "That URL didn't load, sir. Check your connection.",
        ],
    },
    ("browser_automation", "fill_form"): {
        "ok": [
            "Typed it in. Take a look, sir.",
            "Done — check the field.",
            "All filled in, sir.",
            "On it — punched that in for you.",
        ],
        "err": [
            "Couldn't find that field, sir. {e}",
            "Field not found — {e}",
            "Nothing matched that input, sir.",
        ],
    },
    ("browser_automation", "click_element"): {
        "ok": [
            "Clicked it, sir.",
            "Done.",
            "Got it — clicked.",
            "Consider it clicked, sir.",
        ],
        "err": [
            "Couldn't find that element, sir. {e}",
            "Click failed — nothing matched. {e}",
            "That element isn't visible, sir.",
        ],
    },
    ("browser_automation", "read_page"): {
        "ok": [
            "Scanned it. Here's what I see: {o}",
            "Done — {o}",
            "Read it. {o}",
        ],
        "err": [
            "Nothing readable on that page, sir.",
            "Page read failed — {e}",
            "Couldn't extract anything useful, sir.",
        ],
    },
    ("browser_automation", "extract_text"): {
        "ok": ["{o}"],
        "err": ["Couldn't extract that, sir — {e}"],
    },
    ("browser_automation", "new_tab"): {
        "ok": [
            "Fresh tab open, sir.",
            "New tab ready.",
            "There you go — clean slate.",
        ],
        "err": [
            "Couldn't open a new tab — {e}",
            "Tab open failed, sir. {e}",
        ],
    },
    ("browser_automation", "close_tab"): {
        "ok": [
            "Tab closed, sir.",
            "Done — gone.",
            "Closed it.",
        ],
        "err": [
            "Tab close failed — {e}",
            "Couldn't close that tab, sir.",
        ],
    },
    ("browser_automation", "screenshot"): {
        "ok": [
            "Browser screenshot saved, sir. {o}",
            "Captured it. {o}",
            "Snapped and saved. {o}",
        ],
        "err": [
            "Screenshot failed — {e}",
            "Couldn't capture that, sir. {e}",
        ],
    },

    # ── SYSTEM CONTROL ───────────────────────────────────────────────
    ("system_control", "screenshot"): {
        "ok": [
            "Snapped it, sir. Saved to {o}",
            "Got it — dropped it in {o}",
            "Screenshot's done. Check {o}",
            "Screen captured. You'll find it in {o}",
        ],
        "err": [
            "Screenshot failed, sir — {e}",
            "Couldn't snap that — {e}",
            "Folder not found, sir. {e}",
        ],
    },
    ("system_control", "volume_up"): {
        "ok": [
            "Volume's up, sir. {o}",
            "Louder — sitting at {o} now.",
            "Cranked it up. {o}",
            "Turned it up for you. {o}",
        ],
        "err": ["Volume control failed — {e}"],
    },
    ("system_control", "volume_down"): {
        "ok": [
            "Brought it down, sir. {o}",
            "Quieter now — {o}",
            "Volume's at {o}",
            "Turned it down. {o}",
        ],
        "err": ["Volume control failed — {e}"],
    },
    ("system_control", "volume_mute"): {
        "ok": [
            "Muted, sir.",
            "All quiet now.",
            "Done — silenced.",
            "Muted it for you.",
        ],
        "err": ["Mute failed — {e}"],
    },
    ("system_control", "volume_unmute"): {
        "ok": [
            "Unmuted, sir.",
            "Sound's back.",
            "All good — audio restored.",
        ],
        "err": ["Unmute failed — {e}"],
    },
    ("system_control", "lock_screen"): {
        "ok": [
            "Screen locked, sir.",
            "Locked down.",
            "All secured.",
        ],
        "err": ["Lock failed — {e}"],
    },
    ("system_control", "sleep"): {
        "ok": [
            "Going to sleep, sir. Goodnight.",
            "Putting the system to sleep.",
        ],
        "err": ["Sleep failed — {e}"],
    },
    ("system_control", "shutdown"): {
        "ok": [
            "Shutting down, sir. It's been a pleasure.",
            "Powering off now.",
        ],
        "err": ["Shutdown failed — {e}"],
    },
    ("system_control", "restart"): {
        "ok": [
            "Restarting now, sir. I'll be right back.",
            "Rebooting — give me a moment.",
        ],
        "err": ["Restart failed — {e}"],
    },

    # ── MOUSE CONTROL ────────────────────────────────────────────────
    ("control_mouse", "move_mouse"): {
        "ok": [
            "Mouse moved, sir.",
            "Done — cursor's there.",
            "Moved it.",
        ],
        "err": ["Mouse move failed — {e}"],
    },
    ("control_mouse", "click"): {
        "ok": [
            "Clicked, sir.",
            "Done.",
            "Got it — clicked.",
        ],
        "err": ["Click failed — {e}"],
    },
    ("control_mouse", "right_click"): {
        "ok": [
            "Right-clicked, sir.",
            "Context menu should be up.",
            "Done — right-clicked.",
        ],
        "err": ["Right-click failed — {e}"],
    },
    ("control_mouse", "double_click"): {
        "ok": [
            "Double-clicked, sir.",
            "Done.",
        ],
        "err": ["Double-click failed — {e}"],
    },
    ("control_mouse", "scroll"): {
        "ok": [
            "Scrolled {o}, sir.",
            "Done — scrolled {o}.",
            "Scrolling {o}.",
        ],
        "err": ["Scroll failed — {e}"],
    },
    ("control_mouse", "drag"): {
        "ok": [
            "Dragged it, sir.",
            "Done — moved across.",
        ],
        "err": ["Drag failed — {e}"],
    },
    ("control_mouse", "*"): {
        "ok": ["Done, sir.", "Done."],
        "err": ["Mouse control failed — {e}"],
    },

    # ── KEYBOARD / TYPE ──────────────────────────────────────────────
    ("type_text", "type_text"): {
        "ok": [
            "Typed it in, sir.",
            "Done — check it.",
            "All typed out.",
            "On it — punched that in.",
        ],
        "err": ["Typing failed — {e}"],
    },
    ("type_text", "press_key"): {
        "ok": [
            "Key pressed, sir.",
            "Done.",
            "Hit it.",
        ],
        "err": ["Key press failed — {e}"],
    },
    ("type_text", "*"): {
        "ok": ["Done.", "Typed it in."],
        "err": ["Typing failed — {e}"],
    },

    # ── APP CONTROL ──────────────────────────────────────────────────
    ("open_app", "*"): {
        "ok": [
            "It's up, sir.",
            "Pulled it up for you.",
            "There you go — it's open.",
            "Launching now, give it a second.",
        ],
        "err": [
            "Can't find that app, sir. Is it installed?",
            "Application not found — {e}",
            "Nothing matched that name, sir.",
        ],
    },
    ("close_app", "*"): {
        "ok": [
            "Closed it, sir.",
            "All shut down.",
            "Done — terminated.",
        ],
        "err": [
            "Couldn't close that — {e}",
            "Process not found, sir.",
        ],
    },

    # ── WEB SEARCH ──────────────────────────────────────────────────
    ("search_web", "*"): {
        "ok": [
            "Results are up, sir.",
            "Here you go — search is in.",
            "Pulled it up.",
            "Done — take a look.",
        ],
        "err": [
            "Search failed — {e}",
            "Couldn't run that search, sir.",
        ],
    },

    # ── FILE OPERATIONS ──────────────────────────────────────────────
    ("file_operation", "create_file"): {
        "ok": [
            "File's created, sir. {o}",
            "Done — it's in place. {o}",
            "Created it for you. {o}",
        ],
        "err": [
            "Couldn't create that file — {e}",
            "Creation failed, sir. {e}",
        ],
    },
    ("file_operation", "read_file"): {
        "ok": [
            "Here's what's in it, sir: {o}",
            "Got it — {o}",
            "Read it. {o}",
        ],
        "err": [
            "Can't read that file, sir — {e}",
            "File not found or unreadable. {e}",
        ],
    },
    ("file_operation", "delete_file"): {
        "ok": [
            "Done — deleted, sir.",
            "Gone.",
            "Removed it.",
        ],
        "err": [
            "Delete failed — {e}",
            "Couldn't remove that, sir. {e}",
        ],
    },
    ("file_operation", "list_directory"): {
        "ok": [
            "Here's what's in there, sir: {o}",
            "Found these: {o}",
            "{o}",
        ],
        "err": [
            "Can't read that directory — {e}",
            "Folder not accessible, sir. {e}",
        ],
    },
    ("file_operation", "search_files"): {
        "ok": [
            "Found it, sir — {o}",
            "Here's what I found: {o}",
            "Located it. {o}",
            "Yes sir — {o}",
        ],
        "err": [
            "Nothing called that in there, sir. Want me to check elsewhere?",
            "Can't find that file — {e}",
            "No match found, sir.",
        ],
    },
    ("file_operation", "move_file"): {
        "ok": [
            "Moved it, sir.",
            "File's in its new spot.",
            "Done — relocated.",
        ],
        "err": ["Move failed — {e}"],
    },
    ("file_operation", "copy_file"): {
        "ok": [
            "Copied, sir.",
            "Done — copy's there.",
        ],
        "err": ["Copy failed — {e}"],
    },

    # ── SCREEN READ ──────────────────────────────────────────────────
    ("read_screen", "*"): {
        "ok": [
            "Here's what's on screen, sir: {o}",
            "Scanned it. {o}",
            "Got it — {o}",
        ],
        "err": [
            "Screen read failed — {e}",
            "Couldn't read that, sir. {e}",
        ],
    },

    # ── JARVIS META ──────────────────────────────────────────────────
    ("jarvis_meta", "tell_time"): {
        "ok": [
            "It's {o}, sir.",
            "The time is {o}.",
            "{o} — right on schedule, sir.",
        ],
        "err": ["Couldn't fetch the time — {e}"],
    },
    ("jarvis_meta", "tell_date"): {
        "ok": [
            "Today is {o}, sir.",
            "{o}.",
            "It's {o}.",
        ],
        "err": ["Date fetch failed — {e}"],
    },
    ("jarvis_meta", "status_report"): {
        "ok": [
            "All systems nominal, sir. {o}",
            "Running clean — {o}",
            "Systems look good. {o}",
            "Here's the report, sir: {o}",
        ],
        "err": ["Status check failed — {e}"],
    },

    # ── REMINDERS ───────────────────────────────────────────────────
    ("reminder_task", "set_reminder"): {
        "ok": [
            "I'll remind you, sir. {o}",
            "Reminder set. {o}",
            "Got it — I'll ping you. {o}",
            "Noted. {o}",
        ],
        "err": ["Reminder failed — {e}"],
    },
    ("reminder_task", "cancel_reminder"): {
        "ok": [
            "Reminder cancelled, sir.",
            "Done — standing down.",
            "Cancelled it.",
        ],
        "err": ["No reminder found — {e}"],
    },
    ("reminder_task", "list_reminders"): {
        "ok": [
            "Here's what I have, sir: {o}",
            "Active reminders: {o}",
            "{o}",
        ],
        "err": ["Nothing queued up, sir."],
    },

    # ── CODE EXECUTION ───────────────────────────────────────────────
    ("code_execution", "*"): {
        "ok": [
            "Done, sir. Output: {o}",
            "Ran it. Here's the result: {o}",
            "Executed. {o}",
        ],
        "err": [
            "Execution failed, sir — {e}",
            "Script error — {e}",
        ],
    },

    # ── AUTOMATION WORKFLOWS ─────────────────────────────────────────
    ("automation_task", "run_workflow"): {
        "ok": [
            "Workflow complete, sir.",
            "All steps done.",
            "Finished the routine.",
        ],
        "err": [
            "Workflow hit a snag, sir — {e}",
            "Routine failed at — {e}",
        ],
    },
    ("automation_task", "list_workflows"): {
        "ok": [
            "Here's what I have loaded, sir: {o}",
            "Available routines: {o}",
        ],
        "err": ["Can't list workflows — {e}"],
    },
    ("automation_task", "create_workflow"): {
        "ok": [
            "Workflow created, sir. {o}",
            "Done — {o}",
            "Saved it. {o}",
        ],
        "err": ["Workflow creation failed — {e}"],
    },
    ("automation_task", "remove_workflow"): {
        "ok": [
            "Workflow removed, sir.",
            "Done — deleted.",
            "Gone.",
        ],
        "err": ["Remove failed — {e}"],
    },
    ("automation_task", "rename_workflow"): {
        "ok": [
            "Renamed, sir.",
            "Done.",
            "Updated.",
        ],
        "err": ["Rename failed — {e}"],
    },

    # ── CONFIRMATION FLOWS ───────────────────────────────────────────
    ("confirmation", "folder_not_found"): {
        "ask": [
            "Can't find a folder called '{o}', sir. Want me to create it?",
            "No folder named '{o}' anywhere I can see. Shall I make one?",
            "'{o}' doesn't exist, sir. Create it?",
        ],
    },
    ("confirmation", "create_file"): {
        "ask": [
            "Are you sure you want to create this file in this folder, sir?\n\n{o}",
            "Are you sure you wanna create this file in this folder?\n\n{o}",
            "Shall I create the file at the path below, sir?\n\n{o}",
        ],
    },
    ("confirmation", "confirmed"): {
        "ok": [
            "Done, sir.",
            "Understood — on it.",
            "Consider it done.",
        ],
    },
    ("confirmation", "cancelled"): {
        "ok": [
            "Understood, standing down.",
            "No problem — leaving it as is.",
            "Noted. Doing nothing.",
        ],
    },
    ("confirmation", "dangerous_action"): {
        "ask": [
            "Just to confirm, sir — you want me to {o}? That can't be undone.",
            "Are you sure about that, sir? {o} is irreversible.",
            "That'll {o} permanently, sir. Confirm?",
        ],
    },
}

_DEFAULT = {
    "ok":  ["Done, sir.", "All set.", "Done."],
    "err": ["That didn't work, sir. {e}", "Something went wrong — {e}"],
}

# Intents/actions whose output must never be trimmed (listings, OCR, code output).
# Use ("intent", "*") to match any action under that intent.
_NO_TRIM: set[tuple[str, str]] = {
    ("file_operation",   "list_directory"),
    ("file_operation",   "search_files"),
    ("file_operation",   "read_file"),
    ("reminder_task",    "list_reminders"),
    ("automation_task",  "list_workflows"),
    ("read_screen",      "*"),
    ("browser_automation", "read_page"),
    ("code_execution",   "*"),
    ("jarvis_meta",      "status_report"),
}


def say(intent: str, action: str, status: str, output: str = "", error: str = "") -> str:
    """Return a humanized, randomised spoken response.

    status: "ok" | "err"
    output: executor output string
    error:  executor error string
    """
    pool     = _P.get((intent, action)) or _P.get((intent, "*")) or _DEFAULT
    variants = pool.get(status) or _DEFAULT.get(status, ["Done."])

    def _trim(s: str, cap: int = 100) -> str:
        if not s:
            return ""
        if len(s) > cap:
            s = s[:cap] + "…"
        # Show only filename/folder name for path-like strings (not URLs)
        if ("\\" in s or ("/" in s and not s.startswith("http"))) and cap > 40:
            parts = s.replace("\\", "/").split("/")
            last  = next((p for p in reversed(parts) if p), s)
            return last
        return s

    if (intent, action) in _NO_TRIM or (intent, "*") in _NO_TRIM:
        o = output      # full output — never trim listings, OCR, code results
    else:
        o = _trim(output)
    e = _trim(error, 80)

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
