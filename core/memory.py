"""
Conversation context manager.
Maintains a rolling message history for multi-turn Claude conversations.
Token budget enforced via character-based estimation (len(text) // 4 ≈ tokens).
Thread-safe for concurrent use alongside ask_claude_async().

Persistence (F-1):
    Each completed user+assistant pair is flushed to data/memory.jsonl
    atomically (tmp + os.replace), and reloaded at module import so
    context survives JARVIS restarts. The file is gitignored — it
    contains conversation history that may include personal content.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

from core.log import debug as _dbg

_PERSIST_PATH = Path(__file__).parent.parent / "data" / "memory.jsonl"


# inject_outcome appends "\n[Result: intent/action → detail]" lines to an assistant
# message. forget_exchanges compares content by identity, so it strips these (which
# may be added between capture and delete) to stay robust.
_RESULT_MARKER_RE = re.compile(r"\n\[Result:[^\n]*\]")


def _strip_result_markers(text: str) -> str:
    return _RESULT_MARKER_RE.sub("", text or "")


def _match_window(text: str, q: str, width: int = 60) -> str:
    """A short snippet of *text* around the first case-insensitive hit of *q*,
    with ellipses when truncated — so a forget preview can show WHY a match hit."""
    flat = " ".join((text or "").split())
    idx = flat.lower().find(q.lower())
    if idx < 0:
        return flat[:width] + ("…" if len(flat) > width else "")
    start = max(0, idx - width // 3)
    end = min(len(flat), idx + len(q) + width)
    return ("…" if start > 0 else "") + flat[start:end] + ("…" if end < len(flat) else "")


def _assistant_match_snippet(assistant: str, q: str) -> str:
    """Show the matched text from an assistant message in a human-readable way:
    prefer the model's spoken `response` field over the raw JSON when the hit is
    there; otherwise window the raw content."""
    try:
        obj = json.loads(_strip_result_markers(assistant))
        resp = obj.get("response", "") if isinstance(obj, dict) else ""
        if resp and q.lower() in resp.lower():
            return _match_window(resp, q)
    except Exception:
        pass
    return _match_window(assistant, q)


def _redact_assistant_json(assistant_json: str) -> str:
    """R3-13: redact long sensitive parameter values from the model's JSON before
    it enters conversation memory, so dictated secrets (file bodies, passwords,
    API keys, code) don't land in data/memory.jsonl in plaintext — nor get
    reloaded into the prompt every session. Reuses brain._redact_params (the same
    helper R2-13 uses for logs) so the redaction set never drifts. Fail-soft:
    returns the input unchanged if it isn't the expected JSON shape (e.g. an
    assistant line already carrying an inject_outcome '[Result: …]' suffix)."""
    try:
        from core.brain import _redact_params
        obj = json.loads(assistant_json)
        if isinstance(obj, dict) and "parameters" in obj:
            obj["parameters"] = _redact_params(obj.get("parameters"))
            return json.dumps(obj)
    except Exception:
        pass
    return assistant_json


class ConversationMemory:
    """Rolling conversation history for the Claude API messages[] parameter.

    Stores alternating user/assistant pairs. Trims oldest complete pairs
    when the estimated token budget is exceeded — never splits a pair.
    """

    def __init__(self, max_tokens: int = 8_000):
        self._messages: list[dict[str, str]] = []
        self._lock = threading.Lock()
        self._max_tokens = max_tokens
        self._load()

    # ── Public API ─────────────────────────────────────────────────────────────

    def add_exchange(self, user_text: str, assistant_json: str) -> None:
        """Append a user+assistant pair then trim to stay within budget."""
        # R3-13: scrub dictated secrets from the assistant JSON before it's stored
        # or persisted (and thus before it re-enters any future prompt).
        assistant_json = _redact_assistant_json(assistant_json)
        with self._lock:
            self._messages.append({"role": "user",      "content": user_text})
            self._messages.append({"role": "assistant", "content": assistant_json})
            self._trim()
            self._save_locked()

    def get_messages(self) -> list[dict[str, str]]:
        """Return a thread-safe snapshot of the current history."""
        with self._lock:
            return list(self._messages)

    def inject_outcome(
        self,
        intent: str,
        action: str,
        success: bool,
        output: str = "",
        error: str = "",
    ) -> None:
        """Amend the last assistant message with the actual execution result.

        Called after dispatch() returns so memory reflects what really happened,
        not the pre-execution guess in Claude's `response` field.
        Skipped for pure success actions with no output — nothing useful to add.
        """
        output = (output or "").strip()
        error  = (error or "").strip()

        if success and not output and not error:
            return

        if success:
            detail = output[:80] if output else "ok"
            suffix = f"\n[Result: {intent}/{action} → {detail}]"
        else:
            detail = error[:80] if error else "failed"
            suffix = f"\n[Result: {intent}/{action} → FAILED: {detail}]"

        with self._lock:
            for i in range(len(self._messages) - 1, -1, -1):
                if self._messages[i]["role"] == "assistant":
                    self._messages[i] = {
                        "role": "assistant",
                        "content": self._messages[i]["content"] + suffix,
                    }
                    self._save_locked()
                    break

    def clear(self) -> None:
        """Wipe all conversation history (in memory AND on disk)."""
        with self._lock:
            self._messages.clear()
            self._save_locked()

    def find_exchanges(self, query: str) -> list[dict[str, str]]:
        """Return conversation exchanges (user+assistant pairs) whose user OR
        assistant content contains *query* (case-insensitive substring).

        Each match is ``{"user", "assistant", "matched_in", "preview"}``. "preview"
        is human-readable and shows WHY the exchange matched: the user line, plus —
        when the hit was only in JARVIS's reply — the matched reply snippet (so a
        greeting that matched via its response isn't a mystery in the confirm card).
        Used by jarvis_meta/forget_memory for selective (not all-or-nothing) wipes.
        """
        q = (query or "").strip().lower()
        if not q:
            return []
        matches: list[dict[str, str]] = []
        with self._lock:
            msgs = self._messages
            for i in range(0, len(msgs) - 1, 2):
                if msgs[i].get("role") != "user" or msgs[i + 1].get("role") != "assistant":
                    continue
                u = msgs[i].get("content", "")
                a = msgs[i + 1].get("content", "")
                in_user = q in u.lower()
                in_asst = q in a.lower()
                if not (in_user or in_asst):
                    continue
                user_line = " ".join(u.split())
                if len(user_line) > 80:
                    user_line = user_line[:80] + "…"
                if in_user:
                    preview = user_line
                    matched_in = "user"
                else:
                    preview = f'{user_line}  ← matched in reply: "{_assistant_match_snippet(a, q)}"'
                    matched_in = "assistant"
                matches.append(
                    {"user": u, "assistant": a, "matched_in": matched_in, "preview": preview}
                )
        return matches

    def forget_exchanges(self, matches: list[dict[str, str]]) -> int:
        """Remove the given exchanges from memory AND disk; return the count
        removed. Matched by exact user+assistant content (identity, not re-query)
        so it's robust to new exchanges added since find_exchanges() ran — and the
        'forget X' command itself (recorded after this turn) is never caught."""
        if not matches:
            return 0
        # Compare with [Result: …] markers stripped: inject_outcome can append one
        # to a matched assistant message between find_exchanges (capture) and here
        # (delete), which would otherwise break the exact-content identity match.
        targets = {
            (m.get("user", ""), _strip_result_markers(m.get("assistant", "")))
            for m in matches
        }
        removed = 0
        with self._lock:
            msgs = self._messages
            kept: list[dict[str, str]] = []
            i, n = 0, len(msgs)
            while i < n:
                if (
                    i + 1 < n
                    and msgs[i].get("role") == "user"
                    and msgs[i + 1].get("role") == "assistant"
                    and (
                        msgs[i].get("content", ""),
                        _strip_result_markers(msgs[i + 1].get("content", "")),
                    ) in targets
                ):
                    removed += 1
                    i += 2  # drop this pair
                    continue
                kept.append(msgs[i])
                i += 1
            if removed:
                self._messages = kept
                self._save_locked()
        return removed

    @property
    def exchange_count(self) -> int:
        with self._lock:
            return len(self._messages) // 2

    @property
    def estimated_tokens(self) -> int:
        with self._lock:
            return self._estimate_tokens()

    # ── Internal ───────────────────────────────────────────────────────────────

    def _estimate_tokens(self) -> int:
        # Called only while _lock is already held.
        return sum(len(m["content"]) for m in self._messages) // 4

    def _trim(self) -> None:
        # Called only while _lock is already held.
        # Drop oldest (user, assistant) pairs together until under budget.
        while self._estimate_tokens() > self._max_tokens and len(self._messages) >= 2:
            self._messages.pop(0)  # user
            self._messages.pop(0)  # assistant

    # ── Persistence (F-1) ─────────────────────────────────────────────────────

    def _load(self) -> None:
        """Read persisted history from disk on construction.

        Per-line JSON objects with the same shape as in-memory entries:
        ``{"role": "user"|"assistant", "content": "..."}``. Silently skips
        malformed lines so a partially-corrupt file doesn't block startup.
        Applies the same trim invariant in case the disk file was written
        with a larger budget than the current process uses.
        """
        if not _PERSIST_PATH.exists():
            return
        loaded: list[dict[str, str]] = []
        try:
            with _PERSIST_PATH.open("r", encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if (isinstance(obj, dict)
                            and obj.get("role") in ("user", "assistant")
                            and isinstance(obj.get("content"), str)):
                        content = obj["content"]
                        # R3-13: scrub any legacy plaintext secrets so they don't
                        # re-enter the prompt; the next _save_locked migrates the
                        # file to the redacted form.
                        if obj["role"] == "assistant":
                            content = _redact_assistant_json(content)
                        loaded.append({"role": obj["role"], "content": content})
        except OSError as exc:
            _dbg("memory", f"failed to load {_PERSIST_PATH}: {exc}")
            return

        # Drop a trailing unpaired user message so the list always starts/ends
        # on the same alternation invariant the in-process code assumes.
        if loaded and len(loaded) % 2 != 0:
            loaded.pop()

        with self._lock:
            self._messages = loaded
            self._trim()

    def _save_locked(self) -> None:
        """Persist current messages to disk atomically. Caller must hold ``_lock``.

        Writes the full list to a sibling ``.tmp`` then ``os.replace``s it
        over the canonical path — mirrors core/automation.py's atomic
        workflows.json write (R2-10 pattern). A crash mid-write leaves the
        previous version intact rather than truncated.
        """
        try:
            _PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _PERSIST_PATH.with_suffix(_PERSIST_PATH.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                for msg in self._messages:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            os.replace(tmp, _PERSIST_PATH)
        except OSError as exc:
            _dbg("memory", f"failed to save {_PERSIST_PATH}: {exc}")
            try:
                if tmp.exists():
                    tmp.unlink()
            except (OSError, UnboundLocalError):
                pass


memory = ConversationMemory()
