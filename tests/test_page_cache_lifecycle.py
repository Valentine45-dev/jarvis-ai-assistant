"""P3 follow-up — page-cache lifecycle + conversational no-raw-dump.

Two regressions the physical test surfaced after §46:
  BUG A: the `conversational` handler dumped the RAW cached scrape verbatim
         (overriding the brain's synthesized answer). It must return empty so the
         brain's grounded `resp` speaks instead.
  BUG B: the cache never expired/cleared, so a stale page leaked into unrelated
         follow-ups. Now it (1) TTL-expires and (2) is cleared on a new
         search/navigation. This file covers the TTL + clear + no-dump behaviour;
         the search/nav clear-points are covered in test_search_grounding.py.
"""

from __future__ import annotations

import time

from core.handlers import shared
from core.handlers.meta import _handle_jarvis_meta


def teardown_function():
    shared._clear_page_cache()  # keep the process-global cache from leaking across tests


def test_cache_returns_value_within_ttl():
    shared._set_page_cache("fresh page text")
    assert shared.get_page_cache() == "fresh page text"


def test_cache_expires_after_ttl():
    shared._set_page_cache("stale page text")
    # backdate the timestamp past the TTL without sleeping
    shared._PAGE_CACHE["ts"] = time.monotonic() - (shared._PAGE_CACHE_TTL_S + 5)
    assert shared.get_page_cache() is None
    # expiry also drops the entry so it can't resurface
    assert shared._PAGE_CACHE == {}


def test_clear_page_cache():
    shared._set_page_cache("something")
    shared._clear_page_cache()
    assert shared.get_page_cache() is None


def test_conversational_does_not_dump_raw_cache():
    # BUG A: even with a cached page present, conversational returns EMPTY so the
    # composer falls through to the brain's synthesized resp — no raw scrape read.
    shared._set_page_cache("--- Page content ---\nMVP: Jalen Brunson ... raw scrape")
    res = _handle_jarvis_meta("conversational", {})
    assert res["success"] is True
    assert res["output"] == ""
