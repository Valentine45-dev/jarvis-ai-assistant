"""Deterministic Default-Browser backstop in the brain.

BUG 1 kept failing for the compound phrasing "open browser and navigate to youtube":
the brain copied `browser:"chrome"` into the open_browser workflow step (from the
morning_routine example), so the handler opened Chrome regardless of
config.browser_engine. Prompt fixes are model-dependent; _normalize_default_browser
makes it deterministic — when the user names NO engine, strip a model-added browser
param (direct open_browser OR workflow step) so the handler uses config.browser_engine.
A named engine is respected.
"""

from __future__ import annotations

import core.brain as brain


def test_direct_open_browser_no_engine_strips_browser():
    r = {"intent": "open_app", "action": "open_browser", "parameters": {"browser": "chrome"}}
    brain._normalize_default_browser(r, "open browser")
    assert "browser" not in r["parameters"]


def test_direct_open_browser_named_engine_kept():
    r = {"intent": "open_app", "action": "open_browser", "parameters": {"browser": "chrome"}}
    brain._normalize_default_browser(r, "open chrome")
    assert r["parameters"]["browser"] == "chrome"


def test_workflow_open_browser_step_stripped():
    r = {"intent": "automation_task", "action": "run_workflow", "parameters": {"steps": [
        {"intent": "open_app", "action": "open_browser", "parameters": {"browser": "chrome"}},
        {"intent": "browser_automation", "action": "navigate",
         "parameters": {"url": "https://www.youtube.com"}},
    ]}}
    brain._normalize_default_browser(r, "open browser and navigate to youtube")
    assert "browser" not in r["parameters"]["steps"][0]["parameters"]
    # the navigate step is untouched
    assert r["parameters"]["steps"][1]["parameters"]["url"] == "https://www.youtube.com"


def test_workflow_named_engine_kept():
    r = {"intent": "automation_task", "action": "run_workflow", "parameters": {"steps": [
        {"intent": "open_app", "action": "open_browser", "parameters": {"browser": "firefox"}},
    ]}}
    brain._normalize_default_browser(r, "open firefox and go to youtube")
    assert r["parameters"]["steps"][0]["parameters"]["browser"] == "firefox"


def test_non_open_browser_untouched():
    r = {"intent": "open_app", "action": "open_spotify", "parameters": {}}
    brain._normalize_default_browser(r, "open spotify")
    assert r == {"intent": "open_app", "action": "open_spotify", "parameters": {}}


def test_open_browser_without_browser_param_no_crash():
    r = {"intent": "open_app", "action": "open_browser", "parameters": {}}
    brain._normalize_default_browser(r, "open browser")
    assert r["parameters"] == {}


# ── response text is corrected to match what actually opens ──────────────────

def test_response_renamed_to_configured_engine(monkeypatch):
    from config.settings import config
    monkeypatch.setattr(config, "browser_engine", "firefox", raising=False)
    r = {"intent": "open_app", "action": "open_browser", "parameters": {"browser": "chrome"},
         "response": "Chrome up, heading to Claude's platform now."}
    brain._normalize_default_browser(r, "open browser and navigate to claude")
    assert "browser" not in r["parameters"]
    assert "Firefox" in r["response"] and "Chrome" not in r["response"]
    assert "Claude" in r["response"]   # non-engine text left alone (Claude != chrome)


def test_response_generic_when_configured_auto(monkeypatch):
    from config.settings import config
    monkeypatch.setattr(config, "browser_engine", "auto", raising=False)
    r = {"intent": "open_app", "action": "open_browser", "parameters": {},
         "response": "Opening Chrome now."}
    brain._normalize_default_browser(r, "open the browser")
    assert "your browser" in r["response"] and "Chrome" not in r["response"]


def test_response_untouched_when_engine_named(monkeypatch):
    from config.settings import config
    monkeypatch.setattr(config, "browser_engine", "firefox", raising=False)
    r = {"intent": "open_app", "action": "open_browser", "parameters": {"browser": "chrome"},
         "response": "Chrome's up."}
    brain._normalize_default_browser(r, "open chrome")
    assert r["response"] == "Chrome's up."          # user named chrome → keep
    assert r["parameters"]["browser"] == "chrome"


def test_workflow_response_renamed(monkeypatch):
    from config.settings import config
    monkeypatch.setattr(config, "browser_engine", "firefox", raising=False)
    r = {"intent": "automation_task", "action": "run_workflow", "parameters": {"steps": [
        {"intent": "open_app", "action": "open_browser", "parameters": {"browser": "chrome"}},
        {"intent": "browser_automation", "action": "navigate",
         "parameters": {"url": "https://platform.claude.com/"}},
    ]}, "response": "Chrome up, heading to Claude's platform now."}
    brain._normalize_default_browser(r, "open browser and navigate to https://platform.claude.com/")
    assert "browser" not in r["parameters"]["steps"][0]["parameters"]
    assert "Firefox" in r["response"] and "Chrome" not in r["response"]
