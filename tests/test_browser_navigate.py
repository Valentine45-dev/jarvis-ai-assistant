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


# ── salvage for the SIBLING nav methods: go_back / go_forward / refresh ───────
#
# §28 follow-up to §27: a slow-but-loaded go_back / go_forward / refresh used to
# hard-FAIL on timeout (the same false-FAIL §27 fixed only for navigate). They now
# reuse the SAME _salvage_after_timeout helper. navigate/refresh host-match an
# explicit target; go_back/go_forward have no destination URL to match, so they
# require the URL actually MOVED off the pre-nav page instead.

class _HistPage:
    """Fake Page for go_back / go_forward / refresh. On a timeout it optionally
    commits a destination URL first (simulating "nav committed, load then timed
    out"), so the salvage's moved_from / host checks can be exercised."""

    def __init__(self, *, url="https://github.com/", dest=None, raise_timeout=False,
                 no_history=False, ready="complete", title="GitHub", body=""):
        self.url = url
        self._dest = dest
        self._raise = raise_timeout
        self._no_history = no_history
        self._ready = ready
        self._title = title
        self._body = body

    def _history_nav(self, timeout=None):
        if self._no_history:
            return None
        if self._raise:
            if self._dest is not None:
                self.url = self._dest         # navigation committed; load then timed out
            raise _TimeoutError("Timeout 30000ms exceeded.")
        if self._dest is not None:
            self.url = self._dest
        return object()

    def go_back(self, wait_until=None, timeout=None):
        return self._history_nav(timeout)

    def go_forward(self, wait_until=None, timeout=None):
        return self._history_nav(timeout)

    def reload(self, wait_until=None, timeout=None):
        if self._raise:
            if self._dest is not None:
                self.url = self._dest         # redirected to another URL on reload
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


def _hist(**kw):
    return _Nav(_HistPage(**kw))


# go_back -----------------------------------------------------------------------

def test_go_back_clean_is_success():
    out = _hist(dest="https://github.com/issues", title="Issues").go_back()
    assert out["success"] is True and "Back to" in out["output"]


def test_go_back_no_history_fails():
    out = _hist(no_history=True).go_back()
    assert out["success"] is False and "no previous page" in (out.get("error") or "").lower()


def test_go_back_timeout_committed_with_title_salvages():
    out = _hist(raise_timeout=True, dest="https://github.com/issues",
                ready="complete", title="Issues").go_back()
    assert out["success"] is True and "loaded slowly" in out["output"]


def test_go_back_timeout_committed_body_only_salvages():
    out = _hist(raise_timeout=True, dest="https://github.com/issues",
                ready="interactive", title="", body="Issue list").go_back()
    assert out["success"] is True and "loaded slowly" in out["output"]


def test_go_back_timeout_not_committed_fails():
    # dest=None → the URL never moved off the pre-nav page → not a real history nav.
    out = _hist(raise_timeout=True, dest=None, title="GitHub").go_back()
    assert out["success"] is False and "timed out" in (out.get("error") or "").lower()


def test_go_back_timeout_committed_but_blank_fails():
    out = _hist(raise_timeout=True, dest="https://github.com/issues",
                ready="complete", title="", body="").go_back()
    assert out["success"] is False


def test_go_back_timeout_pre_interactive_fails():
    out = _hist(raise_timeout=True, dest="https://github.com/issues",
                ready="loading", title="Issues").go_back()
    assert out["success"] is False


# go_forward --------------------------------------------------------------------

def test_go_forward_timeout_committed_salvages():
    out = _hist(raise_timeout=True, dest="https://github.com/pulls",
                ready="complete", title="Pull requests").go_forward()
    assert out["success"] is True and "loaded slowly" in out["output"]


def test_go_forward_timeout_not_committed_fails():
    out = _hist(raise_timeout=True, dest=None, title="GitHub").go_forward()
    assert out["success"] is False and "timed out" in (out.get("error") or "").lower()


# refresh -----------------------------------------------------------------------

def test_refresh_clean_is_success():
    out = _hist(title="GitHub").refresh()
    assert out["success"] is True and "Reloaded" in out["output"]


def test_refresh_timeout_same_host_salvages():
    # Reload targets the same URL; on timeout it's still on the same host → salvage.
    out = _hist(raise_timeout=True, dest=None, ready="complete", title="GitHub").refresh()
    assert out["success"] is True and "loaded slowly" in out["output"]


def test_refresh_timeout_offhost_redirect_fails():
    # A reload that redirected to another host → conservative fail (host-match).
    out = _hist(raise_timeout=True, dest="https://example.com/",
                ready="complete", title="Example").refresh()
    assert out["success"] is False and "timed out" in (out.get("error") or "").lower()


def test_refresh_timeout_blank_fails():
    out = _hist(raise_timeout=True, dest=None, ready="complete", title="", body="").refresh()
    assert out["success"] is False
