"""Phase 1 — multi-engine foundation for the controlled browser.

Chrome, Edge and Firefox can run CONCURRENTLY off one Playwright driver; the
active engine is a pointer (`_active`) and the mixins stay engine-agnostic because
`_page` / `_context` / `_ready` / `_ref_map` are properties routed to the active
engine's `_EngineSession`. These tests cover the pure pieces (launch config,
profile dirs, engine resolution, availability detection) and the concurrent
start/switch behaviour with a faked Playwright driver (no real browser launched).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

import core.browser.session as session


# ── _launch_config: the only engine-specific code ────────────────────────────

def test_launch_config_chrome() -> None:
    s = session._SessionBase()
    type_name, profile_dir, kwargs = s._launch_config("chrome")
    assert type_name == "chromium"
    assert profile_dir == session._BROWSER_PROFILE_DIR            # unchanged path
    assert kwargs["channel"] == "chrome"
    assert kwargs["headless"] is False
    assert "--disable-blink-features=AutomationControlled" in kwargs["args"]
    assert "--enable-automation" in kwargs["ignore_default_args"]
    assert "--no-sandbox" in kwargs["ignore_default_args"]


def test_launch_config_edge_is_chromium_with_msedge_channel() -> None:
    s = session._SessionBase()
    type_name, profile_dir, kwargs = s._launch_config("edge")
    assert type_name == "chromium"                               # Edge IS Chromium
    assert profile_dir.name == "browser_profile_edge"
    assert kwargs["channel"] == "msedge"
    # Same stealth flags reused verbatim.
    assert kwargs["args"] == session._CHROMIUM_ARGS
    assert kwargs["ignore_default_args"] == session._CHROMIUM_IGNORE_DEFAULT_ARGS


def test_launch_config_firefox_has_prefs_no_chromium_switches() -> None:
    s = session._SessionBase()
    type_name, profile_dir, kwargs = s._launch_config("firefox")
    assert type_name == "firefox"
    assert profile_dir.name == "browser_profile_firefox"
    assert "firefox_user_prefs" in kwargs
    # Chromium-only keys must NOT be present (they raise on a firefox launch).
    assert "channel" not in kwargs
    assert "args" not in kwargs
    assert "ignore_default_args" not in kwargs


def test_profile_dirs_are_distinct_siblings() -> None:
    dirs = {k: session._PROFILE_DIRS[k] for k in ("chrome", "edge", "firefox")}
    assert dirs["chrome"] == session._BROWSER_PROFILE_DIR
    assert len({str(p) for p in dirs.values()}) == 3            # all distinct
    parent = session._BROWSER_PROFILE_DIR.parent
    assert all(p.parent == parent for p in dirs.values())       # siblings under data/


# ── _resolve_engine ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("given,expected", [
    ("edge", "edge"),
    ("FIREFOX", "firefox"),
    ("chrome", "chrome"),
    ("safari", "chrome"),     # unknown → default
])
def test_resolve_engine_explicit(given: str, expected: str) -> None:
    assert session._SessionBase()._resolve_engine(given) == expected


def test_resolve_engine_none_uses_configured_default() -> None:
    # config.browser_engine defaults to "chrome".
    assert session._SessionBase()._resolve_engine(None) == "chrome"


def test_resolve_engine_auto_picks_first_available(monkeypatch: pytest.MonkeyPatch) -> None:
    s = session._SessionBase()
    # Chrome unavailable, Edge available → auto should land on edge.
    avail = {"chrome": False, "edge": True, "firefox": True}
    monkeypatch.setattr(s, "_engine_available", lambda e: (avail.get(e, False), ""))
    assert s._resolve_engine("auto") == "edge"


# ── _engine_available ────────────────────────────────────────────────────────

def test_engine_available_chromium(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session, "_find_chromium_channel",
                        lambda e: r"C:\fake\chrome.exe" if e == "chrome" else None)
    s = session._SessionBase()
    ok, _ = s._engine_available("chrome")
    assert ok is True
    ok, reason = s._engine_available("edge")
    assert ok is False and "Edge" in reason


def test_engine_available_firefox(monkeypatch: pytest.MonkeyPatch) -> None:
    s = session._SessionBase()
    monkeypatch.setattr(session, "_playwright_firefox_present", lambda pw: False)
    ok, reason = s._engine_available("firefox")
    assert ok is False and "playwright install firefox" in reason


def test_engine_available_unknown() -> None:
    ok, reason = session._SessionBase()._engine_available("netscape")
    assert ok is False and "Unknown" in reason


# ── active-engine routing properties (keep mixins engine-agnostic) ───────────

def test_active_engine_routing_properties() -> None:
    s = session._SessionBase()
    chrome = session._EngineSession("chrome")
    chrome.page, chrome.context, chrome.ready, chrome.ref_map = "CP", "CC", True, {1: {"a": 1}}
    edge = session._EngineSession("edge")
    edge.page, edge.context, edge.ready, edge.ref_map = "EP", "EC", False, {}
    s._sessions = {"chrome": chrome, "edge": edge}

    s._active = "chrome"
    assert (s._page, s._context, s._ready, s._ref_map) == ("CP", "CC", True, {1: {"a": 1}})
    assert s.is_ready is True

    s._active = "edge"                       # flip the pointer = "switch"
    assert (s._page, s._ready) == ("EP", False)

    # setters route to the active engine only
    s._page = "EP2"; s._ready = True; s._ref_map = {9: {}}
    assert (edge.page, edge.ready, edge.ref_map) == ("EP2", True, {9: {}})
    assert chrome.page == "CP"               # other engine untouched


def test_no_active_engine_safe_defaults() -> None:
    s = session._SessionBase()               # never started
    assert s._page is None
    assert s._context is None
    assert s._ready is False
    assert s._ref_map == {}
    assert s.is_ready is False
    assert s.start_error == ""
    assert s.active_engine == ""


# ── concurrent start / switch with a faked Playwright driver ─────────────────

class _FakeContext:
    def __init__(self) -> None:
        self.pages = [object()]
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeType:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def launch_persistent_context(self, user_data_dir: str, **kwargs: Any) -> _FakeContext:
        self.calls.append({"user_data_dir": user_data_dir, **kwargs})
        return _FakeContext()


class _FakePW:
    def __init__(self) -> None:
        self.chromium = _FakeType()
        self.firefox = _FakeType()
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def fake_pw(monkeypatch: pytest.MonkeyPatch) -> _FakePW:
    pw = _FakePW()
    fake_mod = types.ModuleType("playwright.sync_api")
    fake_mod.sync_playwright = lambda: types.SimpleNamespace(start=lambda: pw)
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_mod)
    return pw


def test_concurrent_engines_alive_and_switch_without_relaunch(fake_pw: _FakePW) -> None:
    s = session._SessionBase()
    s.start("chrome")
    assert s.active_engine == "chrome" and s.is_ready is True

    s.start("edge")                          # Edge launches; Chrome STAYS alive
    assert s.active_engine == "edge" and s.is_ready is True
    assert set(s._sessions) == {"chrome", "edge"}
    assert s._sessions["chrome"].ready and s._sessions["edge"].ready
    assert s._sessions["chrome"].context.closed is False   # not closed by the switch

    s.start("chrome")                        # switch back = pointer flip, no relaunch
    assert s.active_engine == "chrome"
    assert len(fake_pw.chromium.calls) == 2  # chrome + edge once each, no 3rd launch
    # channels are correct per engine
    channels = sorted(c["channel"] for c in fake_pw.chromium.calls)
    assert channels == ["chrome", "msedge"]


def test_start_firefox_uses_firefox_type(fake_pw: _FakePW) -> None:
    s = session._SessionBase()
    s.start("firefox")
    assert s.active_engine == "firefox" and s.is_ready is True
    assert len(fake_pw.firefox.calls) == 1
    assert "firefox_user_prefs" in fake_pw.firefox.calls[0]
    assert "channel" not in fake_pw.firefox.calls[0]


def test_stop_closes_all_engines(fake_pw: _FakePW) -> None:
    s = session._SessionBase()
    s.start("chrome")
    s.start("edge")
    chrome_ctx = s._sessions["chrome"].context
    edge_ctx = s._sessions["edge"].context
    s.stop()
    assert chrome_ctx.closed is True
    assert edge_ctx.closed is True
    assert fake_pw.stopped is True
    assert s._sessions == {} and s.active_engine == ""


def test_recover_relaunches_only_active_engine(fake_pw: _FakePW) -> None:
    s = session._SessionBase()
    s.start("chrome")
    s.start("edge")
    edge_ctx_before = s._sessions["edge"].context
    chrome_ctx = s._sessions["chrome"].context
    # active is edge; simulate external close then recover
    s._active = "edge"
    s._ready = False
    assert s._recover() is True
    assert s._sessions["edge"].context is not edge_ctx_before   # edge relaunched
    assert s._sessions["chrome"].context is chrome_ctx          # chrome untouched
    assert chrome_ctx.closed is False
