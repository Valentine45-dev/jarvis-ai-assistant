"""Priority 3 (fake-success #2) — a Google search grounds follow-ups in the RESULTS.

Bug (sweep find): search_web only NAVIGATED to the SERP — it never read the results or
populated the page cache. So a follow-up ("summarize", "yes briefly") had no <page_content>
to work from, and the brain answered current/dated facts from its TRAINING: it gave the
2025 NBA Finals MVP (SGA) for a *2026* question, confidently and unsourced. When the user
forced "read the top result" it grounded correctly (Brunson) — proving the grounding channel
works; search just never fed it.

Fix (structural half): after a successful google navigate, read the SERP into the page
cache (the SAME channel read_page uses; the brain injects it as <page_content>). Google only
— youtube/github/etc. are navigational, not fact-answering. (The prompt half — the brain must
answer current facts FROM <page_content>, not memory — is a Claude.md rule, physical-only.)
"""

from __future__ import annotations

import core.browser
import core.handlers.app_launcher as al
from core.handlers import shared


class _FakeBrowser:
    def __init__(self, page_output="Google\nhttps://google.com/search\nresults about the 2026 MVP"):
        self.is_ready = True
        self._page_output = page_output
        self.read_calls = 0
        self.last_url = None

    def start(self):
        pass

    def navigate(self, url):
        self.last_url = url
        return {"success": True, "output": "", "error": ""}

    def read_page(self):
        self.read_calls += 1
        return {"success": True, "output": self._page_output, "error": ""}


def _run(platform, monkeypatch):
    fake = _FakeBrowser()
    monkeypatch.setattr(core.browser, "browser", fake, raising=False)
    shared._set_page_cache("SENTINEL")  # known prior cache state
    res = al._do_search_web("latest nba final mvp 2026", platform)
    return res, fake


def test_google_search_caches_serp_for_grounding(monkeypatch):
    res, fake = _run("google", monkeypatch)
    assert res["success"] is True
    assert fake.read_calls == 1                       # SERP was read
    assert "2026 MVP" in shared.get_page_cache()      # ...into the grounding cache


def test_youtube_search_clears_stale_cache_and_does_not_autoread(monkeypatch):
    # navigational search — no read, and it CLEARS any stale page (topic change)
    # so a prior page can't leak into this search's follow-ups (P3 BUG B).
    res, fake = _run("youtube", monkeypatch)
    assert res["success"] is True
    assert fake.read_calls == 0
    assert shared.get_page_cache() is None            # SENTINEL cleared, nothing re-read


def test_github_search_clears_stale_cache_and_does_not_autoread(monkeypatch):
    res, fake = _run("github", monkeypatch)
    assert res["success"] is True
    assert fake.read_calls == 0
    assert shared.get_page_cache() is None


def test_google_read_failure_does_not_break_search(monkeypatch):
    # best-effort: a read that raises must NOT fail the search itself. The stale
    # cache is still cleared (the search cleared it before the failed read).
    fake = _FakeBrowser()

    def _boom():
        raise RuntimeError("read exploded")

    fake.read_page = _boom
    monkeypatch.setattr(core.browser, "browser", fake, raising=False)
    shared._set_page_cache("SENTINEL")
    res = al._do_search_web("anything", "google")
    assert res["success"] is True                     # search still succeeded
    assert shared.get_page_cache() is None            # cleared; failed read set nothing
