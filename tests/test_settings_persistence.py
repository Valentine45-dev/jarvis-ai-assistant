"""P7 — settings actually persist and apply (fake-success #3 & #4).

7b set_wake_word: the WRITE always worked (config.save persists wake_word), but
config.load() overlaid wake_word from from_env() whose default is the truthy
literal "jarvis" -> every restart clobbered a persisted custom wake word back to
the default. Fixed: only an EXPLICIT WAKE_WORD env var overrides the persisted value.

7a change_theme: used to return _ok without persisting or applying anything (the
theme never changed). Now it validates against the real palettes, persists
config.theme, and reports honestly that a restart applies it; an unknown theme is
an honest error, not a silent fallback dressed as success.
"""

from __future__ import annotations

import json

import config.settings as settings_mod
from config.settings import AppConfig
from core.handlers.meta import _handle_jarvis_meta


# ── 7b: wake_word survives restart (read-back) ──────────────────────────────

def _load_with_json(tmp_path, monkeypatch, payload, wake_env=None):
    p = tmp_path / "jarvis.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(settings_mod, "_JSON_PATH", p)
    if wake_env is None:
        monkeypatch.delenv("WAKE_WORD", raising=False)
    else:
        monkeypatch.setenv("WAKE_WORD", wake_env)
    return AppConfig.load()


def test_persisted_wake_word_survives_load(tmp_path, monkeypatch):
    cfg = _load_with_json(tmp_path, monkeypatch, {"wake_word": "stark"})
    assert cfg.wake_word == "stark"   # NOT clobbered back to "jarvis"


def test_persisted_wake_word_wins_over_env_seed(tmp_path, monkeypatch):
    # THE REAL REPRO: .env has WAKE_WORD=jarvis, jarvis.json has the user's "stark".
    # jarvis.json is authoritative for a persisted user setting — the .env value is
    # only a seed, so it must NOT clobber the saved wake word.
    cfg = _load_with_json(tmp_path, monkeypatch, {"wake_word": "stark"}, wake_env="jarvis")
    assert cfg.wake_word == "stark"


def test_env_seeds_wake_word_only_when_json_has_none(tmp_path, monkeypatch):
    # fresh install: jarvis.json has no wake_word key -> the WAKE_WORD env seeds it
    cfg = _load_with_json(tmp_path, monkeypatch, {"theme": "cyan"}, wake_env="atlas")
    assert cfg.wake_word == "atlas"


def test_default_wake_word_when_no_json_key_no_env(tmp_path, monkeypatch):
    cfg = _load_with_json(tmp_path, monkeypatch, {"theme": "cyan"})
    assert cfg.wake_word == "jarvis"   # dataclass default


# ── 7a: change_theme persists + validates ───────────────────────────────────

def test_change_theme_valid_persists(monkeypatch):
    from config.settings import config
    monkeypatch.setattr(config, "theme", "cyan", raising=False)
    saved = {}
    monkeypatch.setattr(config, "save", lambda: saved.setdefault("called", True))
    res = _handle_jarvis_meta("change_theme", {"theme": "matrix"})
    assert res["success"] is True
    assert config.theme == "matrix"
    assert saved.get("called") is True
    assert "restart" in res["output"].lower()   # honest: restart applies it


def test_change_theme_alias(monkeypatch):
    from config.settings import config
    monkeypatch.setattr(config, "theme", "cyan", raising=False)
    monkeypatch.setattr(config, "save", lambda: None)
    res = _handle_jarvis_meta("change_theme", {"theme": "gold"})
    assert res["success"] is True
    assert config.theme == "amber"   # gold -> amber alias


def test_change_theme_unknown_is_honest_error(monkeypatch):
    from config.settings import config
    monkeypatch.setattr(config, "theme", "cyan", raising=False)
    called = {"save": False}
    monkeypatch.setattr(config, "save", lambda: called.__setitem__("save", True))
    res = _handle_jarvis_meta("change_theme", {"theme": "crimson"})
    assert res["success"] is False
    assert "crimson" in res["error"]
    assert config.theme == "cyan"     # unchanged
    assert called["save"] is False    # never persisted an invalid theme


def test_change_theme_save_failure_rolls_back(monkeypatch):
    from config.settings import config
    monkeypatch.setattr(config, "theme", "cyan", raising=False)

    def _boom():
        raise OSError("disk full")

    monkeypatch.setattr(config, "save", _boom)
    res = _handle_jarvis_meta("change_theme", {"theme": "teal"})
    assert res["success"] is False
    assert config.theme == "cyan"     # rolled back after the save failure
