"""Deterministic parser for natural-language 'create routine/workflow' commands."""

from __future__ import annotations

import re
from typing import Any


def _clean_step_line(line: str) -> str:
    s = (line or "").strip()
    s = re.sub(r"^[\-\*\u2022]\s*", "", s)      # bullets
    s = re.sub(r"^\d+[\.\)]\s*", "", s)         # numbered lists
    return s.strip()


def _extract_steps(raw: str, start_at: int) -> list[str]:
    tail = raw[start_at:].strip()
    if not tail:
        return []
    if "\n" in tail:
        return [x for x in (_clean_step_line(line) for line in tail.splitlines()) if x]
    # single-line fallback: split by sequencing markers (not commas)
    # so descriptive clauses like "curses, falling green characters, the works"
    # remain inside one step.
    tail = re.sub(r"^(?:where|that|which)\s+should\s+", "", tail, flags=re.IGNORECASE)
    seq_parts = re.split(
        r"\b(?:after that|afterwards|after you should|after you|then|and then|next|finally)\b[:,]?",
        tail,
        flags=re.IGNORECASE,
    )
    parts: list[str] = []
    for part in seq_parts:
        chunk = part.strip()
        if not chunk:
            continue
        # Split only when conjunction clearly starts a new action command.
        action_chunks = re.split(
            r"\band\s+(?=(?:create|open|search|increase|decrease|run|write|generate|take|set)\b)",
            chunk,
            flags=re.IGNORECASE,
        )
        parts.extend(action_chunks)
    return [x for x in (_clean_step_line(p) for p in parts) if x]


def parse_create_workflow_command(raw_input: str) -> dict[str, Any] | None:
    """Return automation_task/create_workflow dict if text clearly asks for routine creation."""
    text = (raw_input or "").strip()
    if not text:
        return None
    # remove wake-word style prefixes
    stripped = re.sub(r"^\s*(hey|ok|okay)\s+jarvis[\s,\-:]*", "", text, flags=re.IGNORECASE)
    low = stripped.lower()
    if not any(v in low for v in ("create", "make", "build")):
        return None
    if not any(k in low for k in ("routine", "workflow")):
        return None

    name_match = re.search(
        r"(?:create|make|build)\s+(?:a|an|my)?\s*([a-z0-9][a-z0-9 _\-]{0,60}?)\s+(?:routine|workflow)\b",
        low,
    )
    if not name_match:
        return None
    raw_name = name_match.group(1).strip(" -_")
    if not raw_name:
        return None
    display_name = " ".join(w.capitalize() for w in re.split(r"\s+", raw_name) if w)
    if "routine" not in display_name.lower():
        display_name = f"{display_name} Routine"

    marker_match = re.search(
        r"(?:which has|which have|which should|that has|that have|that should|where should|with steps?|have)\s*:?",
        stripped,
        flags=re.IGNORECASE,
    )
    start_at = -1
    if marker_match:
        start_at = marker_match.end()
    else:
        # Colon fallback only when it appears directly after routine/workflow phrase.
        colon_intro = re.search(r"(?:routine|workflow)\s*:\s*", stripped, flags=re.IGNORECASE)
        if colon_intro:
            start_at = colon_intro.end()
    if start_at < 0:
        return None
    steps = _extract_steps(stripped, start_at)
    if not steps:
        return None

    trigger_name = display_name.lower().replace(" routine", "").strip()
    trigger = f"run {trigger_name} routine"

    return {
        "intent": "automation_task",
        "action": "create_workflow",
        "parameters": {
            "task_name": display_name,
            "steps": steps,
            "trigger": trigger,
        },
        "confidence": 0.94,
        "response": f"Building {display_name} now.",
        "hud_status": "AUTOMATION",
        "requires_confirmation": False,
    }


# ── Deterministic file/folder-creation routing guardrail ──────────────────────
# The model is non-deterministic about routing plain "create a folder and a file"
# (no shell named): it sometimes picks run_powershell instead of the cross-platform
# file_operation actions. This fast-path catches the COMMON, unambiguous phrasings
# and returns a file_operation result directly, so the routing is deterministic and
# never reaches raw shell. Anything it can't confidently parse returns None and
# falls through to the model unchanged (zero regression risk).

# Bail signals — let the model handle these richer cases.
_FC_SHELL_NAMED = re.compile(
    r"\b(?:powershell|pwsh|cmd|command prompt|command-line|bash|shell|terminal)\b",
    re.IGNORECASE,
)
_FC_HAS_CONTENT = re.compile(
    r"\b(?:with (?:the )?(?:content|text)|containing|that says|that reads|write\b)",
    re.IGNORECASE,
)
# A single path token: word chars, dot, hyphen — no spaces (spaced names are
# ambiguous, so we bail to the model). Optional surrounding quotes.
_FC_NAME = r"['\"]?([\w.\-]+)['\"]?"
_FC_LOC = r"(?:\s+(?:in|inside|under|within|into)\s+(?:the\s+)?['\"]?([\w./\\\-]+?)['\"]?(?:\s+(?:folder|directory))?)?"
_FC_CREATE = r"(?:create|make|add|new)\s+(?:a\s+|an\s+)?(?:new\s+)?"

_FC_FOLDER_AND_FILE = re.compile(
    _FC_CREATE + r"folder\s+(?:called\s+|named\s+)?" + _FC_NAME + _FC_LOC +
    # second clause: verb optional ("...and a file"), article optional ("...and file")
    r"\s+and\s+(?:then\s+)?(?:also\s+)?(?:(?:create|make|add|new)\s+)?"
    r"(?:a\s+|an\s+)?(?:new\s+)?(?:empty\s+)?file\s+(?:called\s+|named\s+)?" + _FC_NAME,
    re.IGNORECASE,
)
_FC_FOLDER_ONLY = re.compile(
    _FC_CREATE + r"folder\s+(?:called\s+|named\s+)?" + _FC_NAME + _FC_LOC + r"\s*$",
    re.IGNORECASE,
)
_FC_FILE_ONLY = re.compile(
    _FC_CREATE + r"(?:empty\s+)?file\s+(?:called\s+|named\s+)?" + _FC_NAME + _FC_LOC + r"\s*$",
    re.IGNORECASE,
)


def _fc_join(loc: str | None, name: str) -> str:
    """Join an optional location with a name using forward slashes (the executor
    resolves relative paths). Normalises any backslashes in the location."""
    name = (name or "").strip().strip("'\"")
    if not loc:
        return name
    loc = loc.strip().strip("'\"").replace("\\", "/").rstrip("/")
    return f"{loc}/{name}" if loc else name


def parse_file_creation_command(raw_input: str) -> dict[str, Any] | None:
    """Return a file_operation / automation_task dict for a clearly-phrased file or
    folder creation request with NO shell named; else None (model handles it).

    Deterministic guardrail against the brain occasionally routing plain file work
    to run_powershell. Conservative on purpose — single-token names only, no
    dictated content, no shell keyword.
    """
    text = (raw_input or "").strip()
    if not text:
        return None
    stripped = re.sub(r"^\s*(hey|ok|okay)\s+jarvis[\s,\-:]*", "", text, flags=re.IGNORECASE)
    low = stripped.lower()

    # Gate: must be a creation of a folder/file, with no shell named and no content.
    if not any(v in low for v in ("create", "make", "add", "new ")):
        return None
    if "folder" not in low and "file" not in low and "directory" not in low:
        return None
    if _FC_SHELL_NAMED.search(stripped) or _FC_HAS_CONTENT.search(stripped):
        return None

    # 1. Folder + file (file nested inside the new folder) → 2-step workflow.
    m = _FC_FOLDER_AND_FILE.search(stripped)
    if m:
        folder = _fc_join(m.group(2), m.group(1))     # loc/folder
        file_path = f"{folder}/{(m.group(3) or '').strip().strip(chr(39) + chr(34))}"
        if folder and m.group(3):
            return {
                "intent": "automation_task",
                "action": "run_workflow",
                "parameters": {
                    "steps": [
                        {"intent": "file_operation", "action": "create_directory",
                         "parameters": {"path": folder}},
                        {"intent": "file_operation", "action": "create_file",
                         "parameters": {"path": file_path, "content": ""}},
                    ],
                },
                "confidence": 0.95,
                "response": f"Creating {folder}, then {m.group(3)} inside it.",
                "hud_status": "AUTOMATION",
                "requires_confirmation": False,
            }

    # 2. Folder only.
    m = _FC_FOLDER_ONLY.search(stripped)
    if m:
        folder = _fc_join(m.group(2), m.group(1))
        if folder:
            return {
                "intent": "file_operation",
                "action": "create_directory",
                "parameters": {"path": folder},
                "confidence": 0.95,
                "response": f"Creating the {m.group(1)} folder.",
                "hud_status": "FILE OPS",
                "requires_confirmation": False,
            }

    # 3. File only (empty).
    m = _FC_FILE_ONLY.search(stripped)
    if m:
        file_path = _fc_join(m.group(2), m.group(1))
        if file_path:
            return {
                "intent": "file_operation",
                "action": "create_file",
                "parameters": {"path": file_path, "content": ""},
                "confidence": 0.95,
                "response": f"Creating {m.group(1)}.",
                "hud_status": "FILE OPS",
                "requires_confirmation": False,
            }

    return None

