"""Opt-in explicit-content search gate (controller, not a filter).

Covers the detector's true-positives and (importantly) its false-positive
avoidance, plus the handler wiring: OFF by default = unchanged behaviour, ON =
a confirmation card for an explicit query and a normal search for a clean one.
"""

from __future__ import annotations

import core.handlers.app_launcher as al
import core.handlers.shared as shared
from config.settings import config
from core.content_gate import is_explicit_query


# ── detector ────────────────────────────────────────────────────────────────

def test_explicit_terms_and_phrases_match():
    for q in [
        "porn", "watch porn", "porn movies", "best onlyfans",
        "hentai stream", "xnxx", "pornhub link", "leaked sex tape",
        "nude photos of someone", "rule34",
    ]:
        assert is_explicit_query(q) is True, q


def test_clean_queries_do_not_match():
    # The crux: ordinary searches must NOT trip the gate (word-boundary matching
    # + the most ambiguous singles deliberately excluded).
    for q in [
        "weather in kuwait", "essex county council", "sussex university",
        "analysis of sales data", "cumulative gpa calculator",
        "naked mole rat", "nude lipstick shades", "sex education netflix",
        "scotts valley", "documentary about the cold war", "",
    ]:
        assert is_explicit_query(q) is False, q


# ── handler wiring ──────────────────────────────────────────────────────────

def _reset_pending():
    shared.abandon_pending_confirmation()


def test_gate_off_searches_directly(monkeypatch):
    # Default OFF: even an explicit query goes straight through (no confirmation).
    _reset_pending()
    monkeypatch.setattr(config, "safe_search_confirm", False, raising=False)
    called = {}
    monkeypatch.setattr(al, "_do_search_web",
                        lambda q, p: (called.__setitem__("q", q), {"success": True})[1])
    out = al._handle_search_web("google_search", {"query": "porn movies"})
    assert called.get("q") == "porn movies"
    assert not out.get("needs_confirmation")


def test_gate_on_explicit_query_asks_confirmation(monkeypatch):
    _reset_pending()
    monkeypatch.setattr(config, "safe_search_confirm", True, raising=False)
    ran = {"n": 0}
    monkeypatch.setattr(al, "_do_search_web",
                        lambda q, p: ran.__setitem__("n", ran["n"] + 1) or {"success": True})
    out = al._handle_search_web("google_search", {"query": "porn movies"})
    assert out.get("needs_confirmation") is True, "explicit query must gate"
    assert ran["n"] == 0, "search must NOT run before the user confirms"
    # The pending callback runs the real search once confirmed.
    pending = shared.get_pending_confirmation()
    assert pending and pending.get("fn")
    pending["fn"]()
    assert ran["n"] == 1
    _reset_pending()


def test_gate_on_clean_query_searches_directly(monkeypatch):
    _reset_pending()
    monkeypatch.setattr(config, "safe_search_confirm", True, raising=False)
    called = {}
    monkeypatch.setattr(al, "_do_search_web",
                        lambda q, p: (called.__setitem__("q", q), {"success": True})[1])
    out = al._handle_search_web("google_search", {"query": "kuwait weather"})
    assert called.get("q") == "kuwait weather"
    assert not out.get("needs_confirmation")
