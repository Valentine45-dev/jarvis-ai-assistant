"""navigate() timeout salvage — a slow-but-loaded page is a SUCCESS, not a FAIL.

No Playwright/Qt: a fake page stands in for the Playwright Page. goto() either
succeeds or raises a Timeout-flavoured exception; url / readyState / title / body
are stubbed so we can exercise the salvage decision and its guards directly.
"""

from __future__ import annotations

import contextlib

from core.browser.interaction import _InteractionMixin


class _TimeoutError(Exception):
    """Stand-in for Playwright's TimeoutError — navigate() keys off the word
    'timeout' in the message (case-insensitive)."""


class _FakePage:
    def __init__(self, *, raise_timeout=False, url="https://github.com/",
                 ready="complete", title="GitHub", body=""):
        self._raise = raise_timeout
        self.url = url
        self._ready = ready
        self._title = title
        self._body = body
        self.goto_timeouts: list[int] = []

    def goto(self, url, wait_until=None, timeout=None):
        self.goto_timeouts.append(timeout)
        if self._raise:
            raise _TimeoutError("Timeout 30000ms exceeded.")
        return object()

    def title(self):
        return self._title

    def evaluate(self, js):
        if "readyState" in js:
            return self._ready
        if "body" in js:
            return self._body
        return None


class _Nav(_InteractionMixin):
    """Minimal host for the navigation mixin — stubs the session plumbing."""

    def __init__(self, page):
        self._page = page
        self._lock = contextlib.nullcontext()
        self._ready = True

    def _not_ready(self):
        return None

    def _recover(self):
        return False


def _nav(**page_kw):
    return _Nav(_FakePage(**page_kw))


# ── clean load (unchanged behaviour) ────────────────────────────────────────

def test_clean_load_is_success():
    out = _nav(raise_timeout=False, title="GitHub").navigate("https://github.com")
    assert out["success"] is True
    assert "GitHub" in out["output"]
    assert "loaded slowly" not in out["output"]      # not a salvage


# ── salvage: slow but actually loaded ───────────────────────────────────────

def test_timeout_but_committed_interactive_with_title_salvages_to_success():
    out = _nav(raise_timeout=True, url="https://github.com/", ready="interactive",
               title="GitHub").navigate("https://github.com")
    assert out["success"] is True
    assert "loaded slowly" in out["output"]          # distinct salvage wording


def test_timeout_committed_complete_with_body_only_salvages():
    # No title, but real body text → still a loaded page.
    out = _nav(raise_timeout=True, url="https://github.com/", ready="complete",
               title="", body="Sign in to GitHub").navigate("https://github.com")
    assert out["success"] is True
    assert "loaded slowly" in out["output"]


def test_www_redirect_same_registrable_domain_salvages():
    out = _nav(raise_timeout=True, url="https://www.github.com/", ready="complete",
               title="GitHub").navigate("https://github.com")
    assert out["success"] is True


# ── guards: must still FAIL ─────────────────────────────────────────────────

def test_timeout_committed_but_blank_fails():
    out = _nav(raise_timeout=True, url="https://github.com/", ready="complete",
               title="", body="").navigate("https://github.com")
    assert out["success"] is False
    assert "too long" in (out.get("error") or "").lower()


def test_timeout_pre_interactive_fails():
    out = _nav(raise_timeout=True, url="https://github.com/", ready="loading",
               title="GitHub").navigate("https://github.com")
    assert out["success"] is False


def test_timeout_wrong_host_fails():
    # Committed somewhere else (e.g. stuck on old page / off-host) → not salvaged.
    out = _nav(raise_timeout=True, url="https://example.com/", ready="complete",
               title="Example").navigate("https://github.com")
    assert out["success"] is False


# ── configurable timeout, read at call time ─────────────────────────────────

def test_nav_timeout_reads_config(monkeypatch):
    from config.settings import config
    nav = _nav()
    monkeypatch.setattr(config, "browser_nav_timeout_ms", 45000, raising=False)
    assert nav._nav_timeout() == 45000
    # default when unset/garbage
    monkeypatch.setattr(config, "browser_nav_timeout_ms", "oops", raising=False)
    assert nav._nav_timeout() == 30000


def test_navigate_passes_config_timeout_to_goto(monkeypatch):
    from config.settings import config
    monkeypatch.setattr(config, "browser_nav_timeout_ms", 30000, raising=False)
    page = _FakePage(raise_timeout=False)
    _Nav(page).navigate("https://github.com")
    assert page.goto_timeouts == [30000]             # the configurable value, not 15000
