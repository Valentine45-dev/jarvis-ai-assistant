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
        "response": f"Building {display_name} now, sir.",
        "hud_status": "AUTOMATION",
        "requires_confirmation": False,
    }

