"""Shared pytest fixtures for the JARVIS test suite.

These fixtures provide hermetic substitutes for the major external
dependencies — Anthropic, Playwright, sounddevice, persisted settings —
so individual tests don't have to reach out to real APIs or devices.

Conventions:
- `mock_*` fixtures yield the patched object so tests can inspect calls.
- `isolated_settings` always uses a fresh tmp dir for `data/jarvis.json`.
- Network-touching or real-device tests should mark themselves with
  `@pytest.mark.integration` so CI can deselect them.
"""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest

# Make the repo root importable without each test repeating sys.path.insert.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ── Interactive runner scripts — exclude from pytest collection ──────────────
# These three files are CLI runners (each has a "Run with: uv run python
# tests/test_X.py" docstring) that call input() for pause-and-confirm prompts
# between steps. Their `test_*` function names cause pytest to collect them,
# and every call then errors with `OSError: pytest: reading from stdin while
# output is captured`. They're not unit tests; they belong to the manual
# audit-tests workflow. Skip them at collection time.
collect_ignore = [
    "test_browser.py",
    "test_computer_control.py",
    "test_executor.py",
]


# ── CI env hardening ─────────────────────────────────────────────────────────
# GitHub Actions runs without ANTHROPIC_API_KEY / GEMINI_API_KEY in scope.
# Most tests mock the SDK, but a few touch `config.anthropic_api_key` (e.g.
# via `_get_client()` cache invalidation) and crash with empty-string keys
# at import time. Seed sentinel values so import succeeds and SDK calls are
# the responsibility of `mock_anthropic` / `mock_playwright` fixtures rather
# than tripping on an env var miss.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("ELEVENLABS_API_KEY", "test-key")
os.environ.setdefault("OPENWEATHER_API_KEY", "test-key")


@pytest.fixture
def mock_anthropic(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    """Replace the anthropic.Anthropic client with a MagicMock.

    Tests can configure return values on the yielded mock — e.g.::

        mock_anthropic.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(text='{"intent": "open_app", ...}')],
        )
    """
    client = MagicMock(name="AnthropicClient")
    try:
        import anthropic  # type: ignore
    except ImportError:  # pragma: no cover — env without the SDK
        anthropic = types.ModuleType("anthropic")
        sys.modules["anthropic"] = anthropic

    monkeypatch.setattr(anthropic, "Anthropic", MagicMock(return_value=client), raising=False)
    # core.brain caches a singleton — wipe it so the next call picks up the mock.
    try:
        import core.brain as _brain
        monkeypatch.setattr(_brain, "_client", None, raising=False)
        monkeypatch.setattr(_brain, "_client_key", None, raising=False)
    except ImportError:
        pass
    yield client


@pytest.fixture
def mock_playwright(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    """Replace `sync_playwright()` so browser tests never spawn Chromium."""
    pw = MagicMock(name="PlaywrightSession")
    factory = MagicMock(name="sync_playwright")
    factory.return_value.__enter__.return_value = pw
    factory.return_value.start.return_value = pw

    try:
        import playwright.sync_api as _pw_sync  # type: ignore
        monkeypatch.setattr(_pw_sync, "sync_playwright", factory, raising=False)
    except ImportError:
        pw_module = types.ModuleType("playwright")
        sync_module = types.ModuleType("playwright.sync_api")
        sync_module.sync_playwright = factory  # type: ignore[attr-defined]
        sys.modules["playwright"] = pw_module
        sys.modules["playwright.sync_api"] = sync_module
    yield pw


@pytest.fixture
def mock_sounddevice(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    """Stub `sounddevice` so audio tests don't open a real input stream."""
    sd = MagicMock(name="sounddevice")
    sd.query_devices.return_value = [
        {"name": "MockMic", "max_input_channels": 1, "default_samplerate": 16000},
    ]
    sd.default = MagicMock(samplerate=16000, channels=1)
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    yield sd


@pytest.fixture
def isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Point `config.settings` at a throwaway jarvis.json in tmp_path.

    Yields the path so tests can pre-seed it or inspect the post-test state.
    """
    cfg_path = tmp_path / "jarvis.json"
    cfg_path.write_text(json.dumps({}), encoding="utf-8")

    try:
        import config.settings as _settings
    except ImportError:
        # Module not importable in this environment — yield the path anyway.
        yield cfg_path
        return

    monkeypatch.setattr(_settings, "_JSON_PATH", cfg_path, raising=False)
    # Reset the module-level singleton so the next .load() reads our tmp file.
    if hasattr(_settings, "config"):
        try:
            fresh = _settings.AppConfig.load()
            monkeypatch.setattr(_settings, "config", fresh, raising=False)
        except Exception:
            pass
    yield cfg_path


@pytest.fixture(autouse=True)
def _no_qt_app_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent stale QApplication instances from leaking between tests.

    Tests that genuinely need Qt should request `qtbot` from pytest-qt or
    create their own QCoreApplication; this fixture only guards against
    handlers that lazy-import PyQt5 and then probe for a running app.
    """
    # No-op default; ensures the fixture exists for tests that want to extend.
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[Any]) -> None:
    """Auto-skip integration tests on CI unless explicitly enabled.

    Set `JARVIS_RUN_INTEGRATION=1` to opt back in.
    """
    if os.environ.get("JARVIS_RUN_INTEGRATION"):
        return
    skip_integration = pytest.mark.skip(reason="integration test (set JARVIS_RUN_INTEGRATION=1)")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
