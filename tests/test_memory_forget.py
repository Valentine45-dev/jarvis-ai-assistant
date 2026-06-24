"""Selective conversation-memory deletion (jarvis_meta/forget_memory).

ConversationMemory.find_exchanges / forget_exchanges let JARVIS delete the
exchanges about ONE topic (e.g. an embarrassing search) while keeping the rest of
the history, instead of the all-or-nothing wipe_memory.
"""

from __future__ import annotations

import pytest

import core.memory as mem_mod
from core.memory import ConversationMemory


@pytest.fixture
def mem(tmp_path, monkeypatch):
    # Isolate persistence so tests never touch the real data/memory.jsonl.
    monkeypatch.setattr(mem_mod, "_PERSIST_PATH", tmp_path / "memory.jsonl")
    m = ConversationMemory()
    m.add_exchange("lock my pc", '{"intent": "system_control", "action": "lock_screen"}')
    m.add_exchange("search for porn movies", '{"intent": "search_web", "action": "google_search"}')
    m.add_exchange("what time is it", '{"intent": "jarvis_meta", "action": "tell_time"}')
    return m


# ── find_exchanges ──────────────────────────────────────────────────────────


def test_find_matches_only_the_relevant_pair(mem):
    matches = mem.find_exchanges("porn")
    assert len(matches) == 1
    assert matches[0]["user"] == "search for porn movies"
    assert "search_web" in matches[0]["assistant"]
    assert matches[0]["preview"]  # non-empty snippet for the confirm card


def test_find_is_case_insensitive_and_matches_assistant_content(mem):
    assert len(mem.find_exchanges("PORN")) == 1
    # query present in the assistant JSON, not the user text
    assert len(mem.find_exchanges("lock_screen")) == 1


def test_find_no_match_returns_empty(mem):
    assert mem.find_exchanges("bitcoin") == []
    assert mem.find_exchanges("") == []


# ── forget_exchanges ────────────────────────────────────────────────────────


def test_forget_removes_only_matched_and_persists(mem, tmp_path, monkeypatch):
    matches = mem.find_exchanges("porn")
    removed = mem.forget_exchanges(matches)
    assert removed == 1
    assert mem.exchange_count == 2
    # the porn exchange is gone; the others remain
    assert mem.find_exchanges("porn") == []
    assert len(mem.find_exchanges("lock my pc")) == 1
    assert len(mem.find_exchanges("what time")) == 1

    # persisted: a fresh instance loading the same file sees the deletion
    reloaded = ConversationMemory()
    assert reloaded.exchange_count == 2
    assert reloaded.find_exchanges("porn") == []


def test_forget_empty_is_noop(mem):
    assert mem.forget_exchanges([]) == 0
    assert mem.exchange_count == 3


def test_forget_tolerates_result_marker_added_after_capture(mem):
    # Root cause of the observed "preview 2 / removed 1": inject_outcome appended a
    # [Result: …] marker to a matched assistant message between find and delete, so
    # exact-content identity matching missed it. forget_exchanges now strips markers.
    matches = mem.find_exchanges("porn")
    with mem._lock:  # noqa: SLF001 — simulate inject_outcome mutating the stored msg
        for m in mem._messages:
            if m["role"] == "assistant" and "search_web" in m["content"]:
                m["content"] += "\n[Result: search_web/google_search → FAILED: failed]"
    removed = mem.forget_exchanges(matches)
    assert removed == 1
    assert mem.find_exchanges("porn") == []


def test_forget_is_identity_based_not_requery(mem):
    # Capture matches, THEN add a new exchange that also contains the query.
    matches = mem.find_exchanges("porn")
    mem.add_exchange("forget what my brother said about porn", '{"intent": "jarvis_meta", "action": "forget_memory"}')
    removed = mem.forget_exchanges(matches)
    # Only the originally-captured pair is removed; the later same-query exchange
    # (e.g. the 'forget X' command itself) survives.
    assert removed == 1
    assert len(mem.find_exchanges("porn")) == 1
    assert "forget_memory" in mem.find_exchanges("porn")[0]["assistant"]


# ── handler routing ─────────────────────────────────────────────────────────


def test_handler_matches_returns_confirmation(tmp_path, monkeypatch):
    from core.handlers.meta import _handle_jarvis_meta
    from core.handlers.shared import abandon_pending_confirmation

    monkeypatch.setattr(mem_mod, "_PERSIST_PATH", tmp_path / "memory.jsonl")
    fresh = ConversationMemory()
    fresh.add_exchange("search for porn movies", '{"intent": "search_web"}')
    monkeypatch.setattr(mem_mod, "memory", fresh)

    abandon_pending_confirmation()
    out = _handle_jarvis_meta("forget_memory", {"query": "porn"})
    try:
        assert out.get("needs_confirmation") is True
    finally:
        abandon_pending_confirmation()


def test_handler_no_match_is_success_noop(tmp_path, monkeypatch):
    from core.handlers.meta import _handle_jarvis_meta

    monkeypatch.setattr(mem_mod, "_PERSIST_PATH", tmp_path / "memory.jsonl")
    fresh = ConversationMemory()
    fresh.add_exchange("what time is it", '{"intent": "jarvis_meta"}')
    monkeypatch.setattr(mem_mod, "memory", fresh)

    out = _handle_jarvis_meta("forget_memory", {"query": "bitcoin"})
    assert out.get("success") is True
    assert not out.get("needs_confirmation")


def test_handler_empty_query_errors(monkeypatch, tmp_path):
    from core.handlers.meta import _handle_jarvis_meta

    monkeypatch.setattr(mem_mod, "_PERSIST_PATH", tmp_path / "memory.jsonl")
    out = _handle_jarvis_meta("forget_memory", {"query": ""})
    assert out.get("success") is False


# ── memory-meta commands are NOT recorded into history ──────────────────────


def test_memory_meta_commands_are_not_logged():
    # ask_claude skips add_exchange for these, so a "forget X" / "wipe" request
    # leaves no trace of X (and won't self-match in the forget preview).
    from core.brain import _is_memory_meta_command

    assert _is_memory_meta_command({"intent": "jarvis_meta", "action": "forget_memory"}) is True
    assert _is_memory_meta_command({"intent": "jarvis_meta", "action": "wipe_memory"}) is True
    # every other command is still logged normally
    assert _is_memory_meta_command({"intent": "jarvis_meta", "action": "tell_time"}) is False
    assert _is_memory_meta_command({"intent": "jarvis_meta", "action": "conversational"}) is False
    assert _is_memory_meta_command({"intent": "search_web", "action": "google_search"}) is False
    assert _is_memory_meta_command({}) is False


def test_pending_confirmation_is_not_recorded_as_outcome(monkeypatch):
    # A needs_confirmation result is pending, not an outcome — _execute_result must
    # NOT call inject_outcome for it (that logged a misleading "FAILED: failed").
    import types

    import core.memory
    import ui.main_window.execution_mixin as em
    from ui.main_window.execution_mixin import _ExecutionMixin

    monkeypatch.setattr(
        em, "dispatch",
        lambda *a, **k: {"needs_confirmation": True, "output": "Forget 1 exchange?"},
    )
    injected: list = []
    monkeypatch.setattr(core.memory.memory, "inject_outcome", lambda **k: injected.append(k))

    stub = types.SimpleNamespace()
    stub._ACTION_INTENTS = _ExecutionMixin._ACTION_INTENTS
    stub._last_result = None
    finished: list = []
    stub._finish_execute = lambda *a, **k: finished.append((a, k))

    _ExecutionMixin._execute_result(
        stub, {"intent": "jarvis_meta", "action": "forget_memory"},
        "jarvis_meta", 0.96, "ok", "STANDBY",
    )

    assert injected == [], "pending confirmation must NOT be recorded as an outcome"
    assert len(finished) == 1, "still finishes so the confirm card shows"
