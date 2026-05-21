"""Response-variety memory.

Persists the spoken response from each routed command so the brain can be
told what it just said and avoid repeating itself — including across
restarts. Solves the cold-start determinism where ``temperature=0.7`` plus
an empty in-process memory makes Claude collapse to its single highest-
likelihood reply (e.g. always the same joke on first launch).

Storage shape: JSONL at ``data/response_history.jsonl`` — one record per
line, ``{"intent", "action", "response", "ts"}``. Append-only with a soft
cap of ~200 entries; we rotate (rewrite, keeping the most recent 200)
when the file grows past 1.5× cap so we're not paying the rewrite cost
every record.

Thread-safe via a module lock: append + size-check + rotate all happen
under the same lock so a concurrent caller never sees a half-truncated
file.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

_HISTORY_PATH = Path(__file__).parent.parent / "data" / "response_history.jsonl"
# Committed bootstrap file with ~6 diverse joke responses. Copied to
# _HISTORY_PATH on first access when the runtime file doesn't exist, so a
# brand-new install still has anti-repetition context on its very first
# request — otherwise temperature alone can let Claude collapse onto its
# single training-modal joke (the dark-mode/bugs one) on cold start.
_SEED_PATH = Path(__file__).parent.parent / "data" / "response_history.seed.jsonl"
_MAX_ENTRIES = 200
_ROTATE_THRESHOLD = int(_MAX_ENTRIES * 1.5)

_lock = threading.Lock()


def _bootstrap_from_seed_if_missing() -> None:
    """Copy the committed seed file to the runtime path on first launch.

    Idempotent: when ``_HISTORY_PATH`` already exists we leave it alone, so
    a user who's been running JARVIS for a while never has their accumulated
    history overwritten. If the seed file is missing (e.g. someone deleted
    it from the repo) we fail silently — the variety system gracefully
    degrades to "no recent block, only the salt" on first call.
    """
    if _HISTORY_PATH.exists():
        return
    if not _SEED_PATH.exists():
        return
    try:
        _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _HISTORY_PATH.write_bytes(_SEED_PATH.read_bytes())
    except OSError:
        pass


def record(intent: str, action: str, response: str) -> None:
    """Append one entry. Silently no-ops when intent or response is empty,
    or when the disk write fails (we'd rather degrade than crash routing)."""
    intent = (intent or "").strip()
    action = (action or "").strip()
    response = (response or "").strip()
    if not intent or not response:
        return

    entry: dict[str, Any] = {
        "intent": intent,
        "action": action,
        "response": response,
        "ts": time.time(),
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"

    with _lock:
        # Lazy bootstrap inside the lock so two concurrent first-callers
        # don't race the seed copy.
        _bootstrap_from_seed_if_missing()
        try:
            _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _HISTORY_PATH.open("a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            return
        # Soft rotate. Reading the whole file just to count is fine at the
        # 200-line scale; if this ever gets hot we can stat + estimate by
        # average line length instead.
        try:
            with _HISTORY_PATH.open("r", encoding="utf-8", errors="replace") as f:
                line_count = sum(1 for _ in f)
            if line_count > _ROTATE_THRESHOLD:
                _rotate_locked()
        except OSError:
            pass


def _rotate_locked() -> None:
    """Caller must hold ``_lock``. Keeps the last ``_MAX_ENTRIES`` lines."""
    try:
        text = _HISTORY_PATH.read_text(encoding="utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        kept = lines[-_MAX_ENTRIES:]
        tmp = _HISTORY_PATH.with_suffix(_HISTORY_PATH.suffix + ".tmp")
        tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        tmp.replace(_HISTORY_PATH)
    except OSError:
        pass


def recent(k: int = 8) -> list[dict[str, Any]]:
    """Return the last ``k`` records (most recent last). Empty list when the
    file is missing, unreadable, or contains no parseable lines."""
    if k <= 0:
        return []
    # Seed first-launch installs so the very first variety block isn't empty.
    # Cheap when _HISTORY_PATH already exists (one exists() syscall).
    if not _HISTORY_PATH.exists():
        with _lock:
            _bootstrap_from_seed_if_missing()
    try:
        with _HISTORY_PATH.open("r", encoding="utf-8", errors="replace") as f:
            tail = list(deque(f, maxlen=k))
    except OSError:
        return []

    out: list[dict[str, Any]] = []
    for raw in tail:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("response"):
            out.append(obj)
    return out


def format_block(k: int = 8, max_response_chars: int = 120) -> str:
    """Compact 'recently said — vary your phrasing' block to append to the
    user message. Empty string when there's no history."""
    items = recent(k)
    if not items:
        return ""
    lines = [
        "Recent spoken lines from prior turns (treat as a STYLE ANCHOR, "
        "not a script — invent fresh wording, never reuse these verbatim):"
    ]
    for it in items:
        intent = it.get("intent", "?")
        action = it.get("action") or ""
        tag = f"{intent}/{action}" if action else intent
        resp = (it.get("response") or "").replace("\n", " ").strip()
        if len(resp) > max_response_chars:
            resp = resp[: max_response_chars - 3] + "..."
        lines.append(f"  - [{tag}] {resp}")
    return "\n".join(lines)
