"""BUG 1 — open_browser with NO engine named honours config.browser_engine.

The handler used `(params.get("browser") or "chrome")`, hardcoding Chrome whenever
no engine was named — so the Default Browser setting (config.browser_engine) was
never respected. A bare "open browser" now resolves to the configured default; a
named engine ("open firefox") still wins.
"""

from __future__ import annotations

import core.browser
import core.handlers.app_launcher as al
from config.settings import config


class _FakeBrowser:
    def __init__(self):
        self.engine_calls = []

    def ensure_engine(self, engine):
        self.engine_calls.append(engine)
        return {"success": True, "output": engine, "error": ""}


def _run(params, monkeypatch, *, configured="chrome"):
    fake = _FakeBrowser()
    monkeypatch.setattr(core.browser, "browser", fake, raising=False)
    monkeypatch.setattr(config, "browser_engine", configured, raising=False)
    res = al._handle_open_app_inner("open_browser", params)
    return res, fake


def test_no_engine_named_uses_configured_default(monkeypatch):
    res, fake = _run({}, monkeypatch, configured="firefox")
    assert res["success"] is True
    assert fake.engine_calls == ["firefox"]      # NOT the old hardcoded "chrome"


def test_named_engine_overrides_config(monkeypatch):
    _res, fake = _run({"browser": "edge"}, monkeypatch, configured="firefox")
    assert fake.engine_calls == ["edge"]         # explicit engine wins over config


def test_config_auto_passes_through(monkeypatch):
    _res, fake = _run({}, monkeypatch, configured="auto")
    assert fake.engine_calls == ["auto"]         # 'auto' resolves downstream


def test_config_chrome_still_chrome(monkeypatch):
    _res, fake = _run({}, monkeypatch, configured="chrome")
    assert fake.engine_calls == ["chrome"]


def test_blank_browser_param_treated_as_no_engine(monkeypatch):
    # an empty/whitespace browser value is the same as "not named" -> config
    _res, fake = _run({"browser": "  "}, monkeypatch, configured="firefox")
    assert fake.engine_calls == ["firefox"]
