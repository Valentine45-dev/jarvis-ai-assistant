"""
JARVIS personality layer — maps (intent, action, success/error) → spoken response.
Uses random.choice() across variant pools so JARVIS never sounds like a bot.
"""
from __future__ import annotations
import random

# Format keys: {o} = trimmed output, {e} = trimmed error
_P: dict[tuple, dict] = {
    ("browser_automation", "navigate"): {
        "ok":  ["Page is up, sir.", "Done — it's loaded.", "There you go."],
        "err": ["Couldn't reach that, sir — {e}", "Navigation failed — {e}"],
    },
    ("browser_automation", "fill_form"): {
        "ok":  ["Done — check the field, sir.", "Typed it in. Take a look.", "All filled in."],
        "err": ["Couldn't find that field, sir — {e}", "No field found matching that — {e}"],
    },
    ("browser_automation", "click_element"): {
        "ok":  ["Done.", "Clicked it.", "Got it, sir."],
        "err": ["Couldn't find that element, sir — {e}", "Click failed — {e}"],
    },
    ("browser_automation", "read_page"): {
        "ok":  ["Scanned it. Here's what I found: {o}", "Done — {o}"],
        "err": ["Nothing readable on that page, sir.", "Page read failed — {e}"],
    },
    ("browser_automation", "extract_text"): {
        "ok":  ["{o}"],
        "err": ["Couldn't extract that, sir — {e}"],
    },
    ("browser_automation", "new_tab"): {
        "ok":  ["New tab open, sir.", "There you go — fresh tab."],
        "err": ["Couldn't open a tab — {e}"],
    },
    ("browser_automation", "close_tab"): {
        "ok":  ["Tab closed, sir.", "Done — gone."],
        "err": ["Tab close failed — {e}"],
    },
    ("browser_automation", "screenshot"): {
        "ok":  ["Captured and saved, sir.", "Browser screenshot saved."],
        "err": ["Browser screenshot failed — {e}"],
    },
    ("system_control", "screenshot"): {
        "ok":  ["Got it — saved to {o}", "Screenshot's done. {o}"],
        "err": ["Screenshot failed, sir — {e}"],
    },
    ("system_control", "volume_up"): {
        "ok":  ["Volume's up, sir. {o}", "Louder — {o}"],
        "err": ["Volume control failed — {e}"],
    },
    ("system_control", "volume_down"): {
        "ok":  ["Volume's down, sir. {o}", "Quieter now. {o}"],
        "err": ["Volume control failed — {e}"],
    },
    ("system_control", "volume_mute"): {
        "ok":  ["Done, sir. {o}", "{o}."],
        "err": ["Mute failed — {e}"],
    },
    ("system_control", "lock_screen"): {
        "ok":  ["Screen locked, sir.", "Locking down."],
        "err": ["Lock failed — {e}"],
    },
    ("open_app", "*"): {
        "ok":  ["It's up, sir.", "There you go.", "Pulled it up."],
        "err": ["Can't find that app, sir — {e}", "Application not found — {e}"],
    },
    ("close_app", "*"): {
        "ok":  ["Done — closed, sir.", "All shut down."],
        "err": ["Couldn't close that — {e}"],
    },
    ("search_web", "*"): {
        "ok":  ["Results are up, sir.", "Here you go.", "Search is in."],
        "err": ["Search failed — {e}"],
    },
    ("file_operation", "create_file"): {
        "ok":  ["Done — file's in place, sir.", "Created it. {o}"],
        "err": ["Couldn't create the file — {e}"],
    },
    ("file_operation", "read_file"): {
        "ok":  ["{o}"],
        "err": ["Can't read that file, sir — {e}"],
    },
    ("file_operation", "delete_file"): {
        "ok":  ["Done — gone, sir.", "Deleted."],
        "err": ["Delete failed — {e}"],
    },
    ("file_operation", "list_directory"): {
        "ok":  ["{o}"],
        "err": ["Can't list that directory — {e}"],
    },
    ("file_operation", "move_file"): {
        "ok":  ["Moved it, sir.", "File's in its new spot."],
        "err": ["Move failed — {e}"],
    },
    ("file_operation", "copy_file"): {
        "ok":  ["Copied, sir.", "Done."],
        "err": ["Copy failed — {e}"],
    },
    ("file_operation", "search_files"): {
        "ok":  ["{o}"],
        "err": ["File search failed — {e}"],
    },
    ("type_text", "*"): {
        "ok":  ["Done.", "Typed it in."],
        "err": ["Typing failed — {e}"],
    },
    ("control_mouse", "*"): {
        "ok":  ["Done.", "Done, sir."],
        "err": ["Mouse control failed — {e}"],
    },
    ("read_screen", "*"): {
        "ok":  ["{o}"],
        "err": ["Screen read failed — {e}"],
    },
    ("reminder_task", "set_reminder"): {
        "ok":  ["I'll remind you, sir. {o}", "Reminder set. {o}"],
        "err": ["Reminder failed — {e}"],
    },
    ("reminder_task", "cancel_reminder"): {
        "ok":  ["Reminder cancelled, sir.", "Done — cancelled."],
        "err": ["No reminder found — {e}"],
    },
    ("reminder_task", "list_reminders"): {
        "ok":  ["{o}"],
        "err": ["Can't list reminders — {e}"],
    },
    ("code_execution", "*"): {
        "ok":  ["{o}"],
        "err": ["Execution failed — {e}"],
    },
    ("automation_task", "run_workflow"): {
        "ok":  ["Workflow complete, sir.", "All done."],
        "err": ["Workflow hit a snag — {e}"],
    },
    ("automation_task", "list_workflows"): {
        "ok":  ["{o}"],
        "err": ["Can't list workflows — {e}"],
    },
    ("automation_task", "create_workflow"): {
        "ok":  ["Workflow created, sir. {o}", "Done — {o}"],
        "err": ["Workflow creation failed — {e}"],
    },
    ("automation_task", "remove_workflow"): {
        "ok":  ["Workflow removed, sir.", "Done — deleted."],
        "err": ["Remove failed — {e}"],
    },
    ("automation_task", "rename_workflow"): {
        "ok":  ["Renamed, sir.", "Done."],
        "err": ["Rename failed — {e}"],
    },
}

_DEFAULT = {
    "ok":  ["Done, sir.", "All set.", "Done."],
    "err": ["That didn't work, sir. {e}", "Something went wrong — {e}"],
}


def say(intent: str, action: str, status: str, output: str = "", error: str = "") -> str:
    """Return a humanized, randomised spoken response.

    status: "ok" | "err"
    """
    pool = _P.get((intent, action)) or _P.get((intent, "*")) or _DEFAULT
    variants = pool.get(status) or _DEFAULT.get(status, ["Done."])

    def _trim(s: str, cap: int = 100) -> str:
        if not s:
            return ""
        if len(s) > cap:
            s = s[:cap] + "…"
        # Show only filename for path-like strings (not URLs)
        if ("\\" in s or ("/" in s and not s.startswith("http"))) and cap > 40:
            parts = s.replace("\\", "/").split("/")
            last = parts[-1] or (parts[-2] if len(parts) > 1 else s)
            return last
        return s

    o = _trim(output)
    e = _trim(error, 80)

    template = random.choice(variants)
    try:
        return template.format(o=o, e=e)
    except (KeyError, IndexError):
        return template
