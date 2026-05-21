"""
JARVIS personality layer — maps (intent, action, success/error) → spoken response.
Uses random.choice() across variant pools so JARVIS never sounds like a bot.
"""
from __future__ import annotations
import random

# R2-28: single source for JARVIS voice in auxiliary LLM prompts (shell explain,
# post-execution narration, document framing). Routing JSON still comes from
# CLAUDE.md; this constant is for the smaller side-call system strings only.
JARVIS_PERSONA_PROMPT = (
    "You are JARVIS — a sharp, warm AI assistant running the user's computer. "
    "British-leaning tone: confident and direct, never stiff or butler-formal. "
    "No emojis. No filler ('Certainly', 'Of course', 'I will now'). "
    "Present tense. Be specific — name files, numbers, and errors."
)

JARVIS_SHELL_RESULTS_PROMPT = (
    JARVIS_PERSONA_PROMPT
    + " Summarise shell results in 1-2 sentences. "
    "If success: report what was found or done. "
    "If failure: say why in plain English and suggest the fix. "
    "Never say 'the command'. Just report."
)

JARVIS_POST_EXECUTION_TONE = (
    "British butler tone, present tense. No JSON, no quotes around your reply."
)

# Format keys: {o} = trimmed output, {e} = trimmed error
_P: dict[tuple, dict] = {
    # ── BROWSER AUTOMATION ──────────────────────────────────────────
    ("browser_automation", "navigate"): {
        "ok": [
            "Page is up.",
            "Done — loaded it for you.",
            "There you go — it's open.",
            "Navigated. Take a look.",
        ],
        "err": [
            "Couldn't reach that. {e}",
            "Navigation failed — {e}",
            "That URL didn't load. Check your connection.",
        ],
    },
    ("browser_automation", "fill_form"): {
        "ok": [
            "Typed it in. Take a look.",
            "Done — check the field.",
            "All filled in.",
            "On it — punched that in for you.",
        ],
        "err": [
            "Couldn't find that field. {e}",
            "Field not found — {e}",
            "Nothing matched that input.",
        ],
    },
    ("browser_automation", "click_element"): {
        "ok": [
            "Clicked it.",
            "Done.",
            "Got it — clicked.",
            "Consider it clicked.",
        ],
        "err": [
            "Couldn't find that element. {e}",
            "Click failed — nothing matched. {e}",
            "That element isn't visible.",
        ],
    },
    ("browser_automation", "read_page"): {
        "ok": [
            "{o}",
        ],
        "err": [
            "Nothing readable on that page.",
            "Page read failed — {e}",
            "Couldn't extract anything useful.",
        ],
    },
    ("browser_automation", "extract_text"): {
        "ok": ["{o}"],
        "err": ["Couldn't extract that — {e}"],
    },
    ("browser_automation", "new_tab"): {
        "ok": [
            "Fresh tab open.",
            "New tab ready.",
            "There you go — clean slate.",
        ],
        "err": [
            "Couldn't open a new tab — {e}",
            "Tab open failed. {e}",
        ],
    },
    ("browser_automation", "close_tab"): {
        "ok": [
            "Tab closed.",
            "Done — gone.",
            "Closed it.",
        ],
        "err": [
            "Tab close failed — {e}",
            "Couldn't close that tab.",
        ],
    },
    ("browser_automation", "screenshot"): {
        "ok": [
            "Browser screenshot saved. {o}",
            "Captured it. {o}",
            "Snapped and saved. {o}",
        ],
        "err": [
            "Screenshot failed — {e}",
            "Couldn't capture that. {e}",
        ],
    },

    # ── SYSTEM CONTROL ───────────────────────────────────────────────
    ("system_control", "screenshot"): {
        "ok": [
            "Snapped it. Saved to {o}",
            "Got it — dropped it in {o}",
            "Screenshot's done. Check {o}",
            "Screen captured. You'll find it in {o}",
        ],
        "err": [
            "Screenshot failed — {e}",
            "Couldn't snap that — {e}",
            "Folder not found. {e}",
        ],
    },
    ("system_control", "volume_up"): {
        "ok": [
            "Volume's up. {o}",
            "Louder — sitting at {o} now.",
            "Cranked it up. {o}",
            "Turned it up for you. {o}",
        ],
        "err": ["Volume control failed — {e}"],
    },
    ("system_control", "volume_down"): {
        "ok": [
            "Brought it down. {o}",
            "Quieter now — {o}",
            "Volume's at {o}",
            "Turned it down. {o}",
        ],
        "err": ["Volume control failed — {e}"],
    },
    ("system_control", "volume_mute"): {
        "ok": [
            "Muted.",
            "All quiet now.",
            "Done — silenced.",
            "Muted it for you.",
        ],
        "err": ["Mute failed — {e}"],
    },
    ("system_control", "volume_unmute"): {
        "ok": [
            "Unmuted.",
            "Sound's back.",
            "All good — audio restored.",
        ],
        "err": ["Unmute failed — {e}"],
    },
    ("system_control", "lock_screen"): {
        "ok": [
            "Screen locked.",
            "Locked down.",
            "All secured.",
        ],
        "err": ["Lock failed — {e}"],
    },
    ("system_control", "sleep"): {
        "ok": [
            "Going to sleep. Goodnight.",
            "Putting the system to sleep.",
        ],
        "err": ["Sleep failed — {e}"],
    },
    ("system_control", "shutdown"): {
        "ok": [
            "Shutting down. It's been a pleasure.",
            "Powering off now.",
        ],
        "err": ["Shutdown failed — {e}"],
    },
    ("system_control", "restart"): {
        "ok": [
            "Restarting now. I'll be right back.",
            "Rebooting — give me a moment.",
        ],
        "err": ["Restart failed — {e}"],
    },

    # ── MOUSE CONTROL ────────────────────────────────────────────────
    ("control_mouse", "move_mouse"): {
        "ok": [
            "Mouse moved.",
            "Done — cursor's there.",
            "Moved it.",
        ],
        "err": ["Mouse move failed — {e}"],
    },
    ("control_mouse", "click"): {
        "ok": [
            "Clicked.",
            "Done.",
            "Got it — clicked.",
        ],
        "err": ["Click failed — {e}"],
    },
    ("control_mouse", "right_click"): {
        "ok": [
            "Right-clicked.",
            "Context menu should be up.",
            "Done — right-clicked.",
        ],
        "err": ["Right-click failed — {e}"],
    },
    ("control_mouse", "double_click"): {
        "ok": [
            "Double-clicked.",
            "Done.",
        ],
        "err": ["Double-click failed — {e}"],
    },
    ("control_mouse", "scroll"): {
        "ok": [
            "Scrolled {o}.",
            "Done — scrolled {o}.",
            "Scrolling {o}.",
        ],
        "err": ["Scroll failed — {e}"],
    },
    ("control_mouse", "drag"): {
        "ok": [
            "Dragged it.",
            "Done — moved across.",
        ],
        "err": ["Drag failed — {e}"],
    },
    ("control_mouse", "*"): {
        "ok": ["Done.", "Done."],
        "err": ["Mouse control failed — {e}"],
    },

    # ── KEYBOARD / TYPE ──────────────────────────────────────────────
    ("type_text", "type_text"): {
        "ok": [
            "Typed it in.",
            "Done — check it.",
            "All typed out.",
            "On it — punched that in.",
        ],
        "err": ["Typing failed — {e}"],
    },
    ("type_text", "press_key"): {
        "ok": [
            "Key pressed.",
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
            "It's up.",
            "Pulled it up for you.",
            "There you go — it's open.",
            "Launching now, give it a second.",
        ],
        "err": [
            "Can't find that app. Is it installed?",
            "Application not found — {e}",
            "Nothing matched that name.",
        ],
    },
    ("close_app", "*"): {
        "ok": [
            "Closed it.",
            "All shut down.",
            "Done — terminated.",
        ],
        "err": [
            "Couldn't close that — {e}",
            "Process not found.",
        ],
    },

    # ── WEB SEARCH ──────────────────────────────────────────────────
    ("search_web", "*"): {
        "ok": [
            "Results are up.",
            "Here you go — search is in.",
            "Pulled it up.",
            "Done — take a look.",
        ],
        "err": [
            "Search failed — {e}",
            "Couldn't run that search.",
        ],
    },

    # ── FILE OPERATIONS ──────────────────────────────────────────────
    ("file_operation", "create_file"): {
        "ok": [
            "File's created. {o}",
            "Done — it's in place. {o}",
            "Created it for you. {o}",
        ],
        "err": [
            "Couldn't create that file — {e}",
            "Creation failed. {e}",
        ],
    },
    ("file_operation", "create_directory"): {
        "ok": [
            "Folder is ready. {o}",
            "Directory created. {o}",
            "Done — {o}",
        ],
        "err": [
            "Couldn't create that folder — {e}",
            "That folder failed. {e}",
        ],
    },
    ("file_operation", "read_file"): {
        "ok": [
            "Here's what's in it: {o}",
            "Got it — {o}",
            "Read it. {o}",
        ],
        "err": [
            "Can't read that file — {e}",
            "File not found or unreadable. {e}",
        ],
    },
    ("file_operation", "delete_file"): {
        "ok": [
            "Done — deleted.",
            "Gone.",
            "Removed it.",
        ],
        "err": [
            "Delete failed — {e}",
            "Couldn't remove that. {e}",
        ],
    },
    ("file_operation", "list_directory"): {
        "ok": [
            "Here's what's in there: {o}",
            "Found these: {o}",
            "{o}",
        ],
        "err": [
            "Can't read that directory — {e}",
            "Folder not accessible. {e}",
        ],
    },
    ("file_operation", "search_files"): {
        "ok": [
            "Found it — {o}",
            "Here's what I found: {o}",
            "Located it. {o}",
            "Yes —{o}",
        ],
        "err": [
            "Nothing called that in there. Want me to check elsewhere?",
            "Can't find that file — {e}",
            "No match found.",
        ],
    },
    ("file_operation", "find_in_files"): {
        "ok": [
            "{o}",
            "Grepped — {o}",
            "Here's the hit count, Valentine: {o}",
            "Done scanning. {o}",
        ],
        "err": [
            "Search failed — {e}",
            "Couldn't grep that. {e}",
            "Nothing turned up.",
        ],
    },
    ("file_operation", "move_file"): {
        "ok": [
            "Moved it.",
            "File's in its new spot.",
            "Done — relocated.",
        ],
        "err": ["Move failed — {e}"],
    },
    ("file_operation", "copy_file"): {
        "ok": [
            "Copied.",
            "Done — copy's there.",
        ],
        "err": ["Copy failed — {e}"],
    },
    ("file_operation", "rename_file"): {
        "ok": [
            "Renamed. {o}",
            "Done — {o}",
            "All set. {o}",
        ],
        "err": [
            "Rename failed — {e}",
            "Couldn't rename that. {e}",
        ],
    },
    ("file_operation", "append_file"): {
        "ok": [
            "Added to the file. {o}",
            "Appended. {o}",
            "Done — {o}",
            "Tacked it on, Valentine. {o}",
        ],
        "err": [
            "Couldn't append — {e}",
            "Append failed. {e}",
            "Wouldn't take the new content — {e}",
        ],
    },
    ("file_operation", "file_info"): {
        "ok": [
            "Here's what I found.\n{o}",
            "File details below.\n{o}",
            "Got it:\n{o}",
            "Here's the breakdown, Valentine:\n{o}",
        ],
        "err": [
            "Couldn't inspect that — {e}",
            "No info available. {e}",
        ],
    },
    ("file_operation", "replace_in_file"): {
        "ok": [
            "Done — {o}",
            "Swapped. {o}",
            "Edits saved — {o}",
            "Replaced, Valentine. {o}",
        ],
        "err": [
            "Couldn't replace that — {e}",
            "Replace failed. {e}",
            "Nothing matched — {e}",
        ],
    },
    ("file_operation", "batch_delete"): {
        "ok": [
            "Cleared. {o}",
            "All gone — {o}",
            "Done — {o}",
            "Cleaned up, Valentine. {o}",
        ],
        "err": [
            "Batch delete hit a snag — {e}",
            "Some files wouldn't budge — {e}",
            "Couldn't clear those — {e}",
        ],
    },

    # ── SCREEN READ ──────────────────────────────────────────────────
    ("read_screen", "*"): {
        "ok": [
            "Here's what's on screen: {o}",
            "Scanned it. {o}",
            "Got it — {o}",
        ],
        "err": [
            "Screen read failed — {e}",
            "Couldn't read that. {e}",
        ],
    },

    # ── VISION ANALYSIS ─────────────────────────────────────────────
    # OUTPUT_IS_RESPONSE for these actions: the responder calls say()
    # with the full Claude vision response in `{o}`, so EVERY template
    # below must include `{o}` or the analysis text gets dropped.
    # Preamble is a short lead-in; the bulk is the analysis itself.
    ("vision_analysis", "describe"): {
        "ok": [
            "Here's what I see: {o}",
            "Taking a look — {o}",
            "On screen: {o}",
            "Got it. {o}",
        ],
        "err": [
            "Couldn't analyze that. {e}",
            "Vision check failed. {e}",
            "Didn't get a result. {e}",
        ],
    },
    ("vision_analysis", "read_text"): {
        "ok": [
            "Here's the text: {o}",
            "Reads as: {o}",
            "Text on screen: {o}",
        ],
        "err": [
            "Couldn't analyze that. {e}",
            "Vision check failed. {e}",
            "Didn't get a result. {e}",
        ],
    },
    ("vision_analysis", "find_ui_element"): {
        "ok": [
            "Found it — {o}",
            "Located: {o}",
            "There it is — {o}",
        ],
        "err": [
            "Couldn't analyze that. {e}",
            "Vision check failed. {e}",
            "Didn't get a result. {e}",
        ],
    },
    ("vision_analysis", "answer_question"): {
        # Output IS the answer — no preamble, just speak it.
        "ok": ["{o}"],
        "err": [
            "Couldn't analyze that. {e}",
            "Vision check failed. {e}",
            "Didn't get a result. {e}",
        ],
    },
    ("vision_analysis", "screenshot_and_describe"): {
        "ok": [
            "Screenshot taken — {o}",
            "Here's what's on screen: {o}",
            "Captured. {o}",
        ],
        "err": [
            "Couldn't analyze that. {e}",
            "Vision check failed. {e}",
            "Didn't get a result. {e}",
        ],
    },

    # ── JARVIS META ──────────────────────────────────────────────────
    ("jarvis_meta", "list_voices"): {
        "ok": [
            "Here are the available voices:\n{o}",
            "Here's what I have:\n{o}",
        ],
        "err": ["Couldn't fetch the voice list — {e}"],
    },
    ("jarvis_meta", "change_voice"): {
        "ok": [
            "Done. Switched to {o}.",
            "Voice changed to {o}.",
            "{o} — consider it done.",
        ],
        "err": [
            "Couldn't switch voice — {e}",
            "Voice change failed. {e}",
        ],
    },
    ("jarvis_meta", "tell_time"): {
        "ok": [
            "It's {o}.",
            "The time is {o}.",
            "{o} — right on schedule.",
        ],
        "err": ["Couldn't fetch the time — {e}"],
    },
    ("jarvis_meta", "tell_date"): {
        "ok": [
            "Today is {o}.",
            "{o}.",
            "It's {o}.",
        ],
        "err": ["Date fetch failed — {e}"],
    },
    ("jarvis_meta", "status_report"): {
        "ok": [
            "All systems nominal. {o}",
            "Running clean — {o}",
            "Systems look good. {o}",
            "Here's the report: {o}",
        ],
        "err": ["Status check failed — {e}"],
    },

    # ── REMINDERS ───────────────────────────────────────────────────
    ("reminder_task", "set_reminder"): {
        "ok": [
            "I'll remind you. {o}",
            "Reminder set. {o}",
            "Got it — I'll ping you. {o}",
            "Noted. {o}",
            "On it — {o}",
            "When the time's up, I'll run that for you. {o}",
        ],
        "err": ["Reminder failed — {e}"],
    },
    ("reminder_task", "cancel_reminder"): {
        "ok": [
            "Reminder cancelled.",
            "Done — standing down.",
            "Cancelled it.",
        ],
        "err": ["No reminder found — {e}"],
    },
    ("reminder_task", "list_reminders"): {
        "ok": [
            "Here's what I have: {o}",
            "Active reminders: {o}",
            "{o}",
        ],
        "err": ["Nothing queued up."],
    },

    # ── CODE EXECUTION ───────────────────────────────────────────────
    ("code_execution", "*"): {
        "ok": [
            "Done. Output: {o}",
            "Ran it. Here's the result: {o}",
            "Executed. {o}",
        ],
        "err": [
            "Execution failed — {e}",
            "Script error — {e}",
        ],
    },

    # ── AUTOMATION WORKFLOWS ─────────────────────────────────────────
    ("automation_task", "run_workflow"): {
        "ok": [
            "Workflow complete.",
            "All steps done.",
            "Finished the routine.",
        ],
        "err": [
            "Workflow hit a snag — {e}",
            "Routine failed at — {e}",
        ],
    },
    ("automation_task", "list_workflows"): {
        "ok": [
            "Here's what I have loaded: {o}",
            "Available routines: {o}",
        ],
        "err": ["Can't list workflows — {e}"],
    },
    ("automation_task", "create_workflow"): {
        "ok": [
            "Workflow created. {o}",
            "Done — {o}",
            "Saved it. {o}",
        ],
        "err": ["Workflow creation failed — {e}"],
    },
    ("automation_task", "remove_workflow"): {
        "ok": [
            "Workflow removed.",
            "Done — deleted.",
            "Gone.",
        ],
        "err": ["Remove failed — {e}"],
    },
    ("automation_task", "rename_workflow"): {
        "ok": [
            "Renamed.",
            "Done.",
            "Updated.",
        ],
        "err": ["Rename failed — {e}"],
    },

    # ── CONFIRMATION FLOWS ───────────────────────────────────────────
    ("confirmation", "folder_not_found"): {
        "ask": [
            "Can't find a folder called '{o}'. Want me to create it?",
            "No folder named '{o}' anywhere I can see. Shall I make one?",
            "'{o}' doesn't exist. Create it?",
        ],
    },
    ("confirmation", "create_file"): {
        "ask": [
            "Are you sure you want to create this file in this folder?\n\n{o}",
            "Are you sure you wanna create this file in this folder?\n\n{o}",
            "Shall I create the file at the path below?\n\n{o}",
        ],
    },
    ("confirmation", "confirmed"): {
        "ok": [
            "Done.",
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
            "Just to confirm — you want me to {o}? That can't be undone.",
            "Are you sure about that? {o} is irreversible.",
            "That'll {o} permanently. Confirm?",
        ],
    },
    ("confirmation", "delete_file"): {
        "ask": [
            "Are you sure you want to delete this?\n\n{o}",
            "This cannot be undone:\n\n{o}\n\nShall I proceed?",
            "Confirm permanent deletion:\n\n{o}",
        ],
    },
    ("confirmation", "rename_file"): {
        "ask": [
            "Shall I rename it?\n\n{o}",
            "Confirm the rename below:\n\n{o}",
            "Ready to rename — confirm?\n\n{o}",
        ],
    },
    ("document_creation", "create_docx"): {
        "ok": [
            "Report drafted.",
            "Word doc's ready.",
            "Done — written up, Valentine.",
            "Drafted. {o}",
            "Saved — {o}",
        ],
        "err": [
            "Couldn't draft that. {e}",
            "Document generation failed. {e}",
            "Something went wrong — {e}",
        ],
    },
    ("document_creation", "create_pptx"): {
        "ok": [
            "Slides are ready.",
            "Presentation built.",
            "Deck's done, Valentine.",
        ],
        "err": [
            "Couldn't build the slides. {e}",
            "Presentation failed. {e}",
        ],
    },
    ("document_creation", "create_xlsx"): {
        "ok": [
            "Spreadsheet ready.",
            "Excel file done.",
            "Sheet's ready, Valentine.",
        ],
        "err": [
            "Couldn't build the spreadsheet. {e}",
            "Excel failed. {e}",
        ],
    },
    ("document_creation", "create_pdf"): {
        "ok": [
            "PDF ready.",
            "Document compiled.",
            "Compiled it, Valentine.",
        ],
        "err": [
            "Couldn't generate the PDF. {e}",
            "PDF failed. {e}",
        ],
    },
}

_DEFAULT = {
    "ok":  ["Done.", "All set.", "Done."],
    "err": ["That didn't work. {e}", "Something went wrong — {e}"],
}

# When a *scheduled* reminder fires and runs an action, the transcript second line
# should always sound like a crisp follow-up (same cadence as "There you go — it's open"),
# not a wall of raw executor output. Keys match reminder allowlist in executor.py.
_SCHEDULED_FOLLOWUP: dict[tuple, list[str]] = {
    ("open_app", "*"): [
        "There you go — it's open.",
        "Launched — all yours.",
        "Up now — you should see it.",
        "Pulled it up. There you are.",
    ],
    ("search_web", "*"): [
        "There you go — results are up.",
        "Search is live — have a look.",
        "On screen — as requested.",
    ],
    ("system_control", "screenshot"): [
        "There you go — screen captured.",
        "Snapped and saved.",
        "Capture's on disk.",
    ],
    ("system_control", "volume_up"): [
        "There you go — volume up.",
        "Dialed it louder.",
    ],
    ("system_control", "volume_down"): [
        "There you go — volume down.",
        "Brought it down a notch.",
    ],
    ("system_control", "volume_mute"): [
        "There you go — audio muted.",
        "Muted.",
    ],
    ("system_control", "lock_screen"): [
        "There you go — workstation locked.",
        "Locked.",
    ],
    ("system_control", "brightness_up"): [
        "Brightness nudged up.",
        "A touch brighter.",
    ],
    ("system_control", "brightness_down"): [
        "Brightness nudged down.",
        "A touch dimmer.",
    ],
    ("browser_automation", "navigate"): [
        "There you go — page is up.",
        "Loaded — it's open.",
    ],
    ("browser_automation", "new_tab"): [
        "There you go — new tab.",
        "Fresh tab ready.",
    ],
    ("browser_automation", "read_page"): [
        "There you are — I read the page.",
        "Pulled the visible text for you.",
    ],
    ("browser_automation", "fill_form"): [
        "There you go — form filled.",
        "Fields are in.",
    ],
    ("browser_automation", "click_element"): [
        "There you go — clicked.",
        "That click's in.",
    ],
    ("browser_automation", "screenshot"): [
        "There you go — browser capture done.",
        "Page snap saved.",
    ],
    ("browser_automation", "extract_text"): [
        "There you are — text pulled.",
        "Extracted. {o}",
    ],
    ("read_screen", "*"): [
        "There you go — text from the screen.",
        "OCR's done.",
    ],
    ("jarvis_meta", "tell_time"): [
        "There you are — {o}.",
    ],
    ("jarvis_meta", "tell_date"): [
        "There you are — {o}.",
    ],
    ("jarvis_meta", "status_report"): [
        "Here's the readout — {o}.",
        "Status in — {o}",
    ],
    ("jarvis_meta", "list_voices"): [
        "Voices on file. {o}",
    ],
    # Whole workflow done — used only if last-step ack cannot be chosen
    ("automation_task", "run_workflow"): [
        "There you go — all steps are done.",
        "That's the full run.",
        "All requested steps are through.",
    ],
    ("file_operation", "*"): [
        "There you go — file op complete.",
        "All set on disk.",
    ],
    ("type_text", "*"): [
        "There you go — input's in.",
        "Sent to the field.",
    ],
    ("code_execution", "git_command"): [
        "There you go — git's done.",
        "Command's through.",
    ],
    ("code_execution", "run_shell"): [
        "There you go — shell command finished.",
        "That's the terminal output.",
    ],
}

_SCHEDULED_FALLBACK_OK = [
    "There you go — all set.",
    "There you go — done.",
    "That's taken care of.",
    "Consider it done.",
    "All finished on schedule.",
]


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


# Intents/actions whose output must never be trimmed (listings, OCR, code output).
# Use ("intent", "*") to match any action under that intent.
_NO_TRIM: set[tuple[str, str]] = {
    ("file_operation",   "list_directory"),
    ("file_operation",   "search_files"),
    ("file_operation",   "read_file"),
    ("reminder_task",    "list_reminders"),
    ("automation_task",  "list_workflows"),
    ("read_screen",      "*"),
    # read_page intentionally excluded — output is cleaned before speaking
    ("code_execution",   "*"),
    ("jarvis_meta",      "status_report"),
    ("jarvis_meta",      "list_voices"),
    # vision_analysis: keep the full Claude vision response intact for TTS.
    # Trimming would chop the description mid-sentence; the user explicitly
    # asked for a vision read, they get the whole thing.
    ("vision_analysis",  "*"),
}


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
