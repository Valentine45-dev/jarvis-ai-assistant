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
import threading
from pathlib import Path

from core.log import debug as _dbg

_PERSIST_PATH = Path(__file__).parent.parent / "data" / "memory.jsonl"


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
                        loaded.append({"role": obj["role"], "content": obj["content"]})
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
