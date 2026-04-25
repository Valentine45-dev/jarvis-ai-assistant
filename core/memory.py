"""
Conversation context manager.
Maintains a rolling message history for multi-turn Claude conversations.
Token budget enforced via character-based estimation (len(text) // 4 ≈ tokens).
Thread-safe for concurrent use alongside ask_claude_async().
"""

from __future__ import annotations

import threading


class ConversationMemory:
    """Rolling conversation history for the Claude API messages[] parameter.

    Stores alternating user/assistant pairs. Trims oldest complete pairs
    when the estimated token budget is exceeded — never splits a pair.
    """

    def __init__(self, max_tokens: int = 8_000):
        self._messages: list[dict[str, str]] = []
        self._lock = threading.Lock()
        self._max_tokens = max_tokens

    # ── Public API ─────────────────────────────────────────────────────────────

    def add_exchange(self, user_text: str, assistant_json: str) -> None:
        """Append a user+assistant pair then trim to stay within budget."""
        with self._lock:
            self._messages.append({"role": "user",      "content": user_text})
            self._messages.append({"role": "assistant", "content": assistant_json})
            self._trim()

    def get_messages(self) -> list[dict[str, str]]:
        """Return a thread-safe snapshot of the current history."""
        with self._lock:
            return list(self._messages)

    def clear(self) -> None:
        """Wipe all conversation history."""
        with self._lock:
            self._messages.clear()

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


memory = ConversationMemory()
