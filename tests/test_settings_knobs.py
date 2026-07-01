"""SettingsView wiring for the two new knobs: stt_settle_ms + safe_search_confirm.

Builds the real SettingsView offscreen, flips the new controls, and asserts
_apply_cfg() writes them to config (and that initial values are read FROM config).
Kept qt-marked + offscreen so it runs headless without a display.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PyQt5")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from config.settings import config  # noqa: E402
from ui.settings import SettingsView  # noqa: E402

pytestmark = pytest.mark.qtgui


@pytest.fixture(scope="module")
def _app():
    # Set offscreen only when this gated test actually runs (not at import), so
    # merely collecting the module can't change the process-wide Qt platform.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


def test_new_knobs_read_initial_values_from_config(_app, monkeypatch):
    monkeypatch.setattr(config, "stt_settle_ms", 400, raising=False)
    monkeypatch.setattr(config, "safe_search_confirm", True, raising=False)
    view = SettingsView()
    try:
        assert view._settle_slider.value() == 400
        assert view._settle_val.text() == "400"
        assert view._flag_safesearch.isChecked() is True
    finally:
        view.deleteLater()


def test_apply_writes_new_knobs_to_config(_app, isolated_settings, monkeypatch):
    monkeypatch.setattr(config, "stt_settle_ms", 0, raising=False)
    monkeypatch.setattr(config, "safe_search_confirm", False, raising=False)
    view = SettingsView()
    try:
        view._settle_slider.setValue(350)
        view._flag_safesearch.setChecked(True)
        view._apply_cfg()
        assert config.stt_settle_ms == 350
        assert config.safe_search_confirm is True
    finally:
        view.deleteLater()


def test_expanded_config_fields_read_from_config(_app, monkeypatch):
    # The six previously JSON-only fields now surface in the CONFIG page.
    monkeypatch.setattr(config, "stt_provider", "deepgram", raising=False)
    monkeypatch.setattr(config, "stt_persistent", True, raising=False)
    monkeypatch.setattr(config, "code_exec_enabled", False, raising=False)
    monkeypatch.setattr(config, "allow_ai_command_autorun", True, raising=False)
    monkeypatch.setattr(config, "browser_engine", "firefox", raising=False)
    monkeypatch.setattr(config, "weather_default_city", "Accra,GH", raising=False)
    view = SettingsView()
    try:
        assert view._stt_provider_combo.currentData() == "deepgram"
        assert view._flag_stt_persistent.isChecked() is True
        assert view._flag_code_exec.isChecked() is False
        assert view._flag_autorun.isChecked() is True
        assert view._browser_engine_combo.currentData() == "firefox"
        assert view._weather_city_input.text() == "Accra,GH"
    finally:
        view.deleteLater()


def _select(combo, value):
    combo.setCurrentIndex(
        next(i for i in range(combo.count()) if combo.itemData(i) == value)
    )


def test_apply_writes_expanded_config_fields(_app, isolated_settings, monkeypatch):
    monkeypatch.setattr(config, "stt_provider", "google", raising=False)
    monkeypatch.setattr(config, "stt_persistent", False, raising=False)
    monkeypatch.setattr(config, "code_exec_enabled", True, raising=False)
    monkeypatch.setattr(config, "allow_ai_command_autorun", False, raising=False)
    monkeypatch.setattr(config, "browser_engine", "chrome", raising=False)
    monkeypatch.setattr(config, "weather_default_city", "Monrovia,LR", raising=False)
    view = SettingsView()
    try:
        _select(view._stt_provider_combo, "deepgram")
        view._flag_stt_persistent.setChecked(True)
        view._flag_code_exec.setChecked(False)
        view._flag_autorun.setChecked(True)
        _select(view._browser_engine_combo, "edge")
        view._weather_city_input.setText("London,GB")
        view._apply_cfg()
        assert config.stt_provider == "deepgram"
        assert config.stt_persistent is True
        assert config.code_exec_enabled is False
        assert config.allow_ai_command_autorun is True
        assert config.browser_engine == "edge"
        assert config.weather_default_city == "London,GB"
    finally:
        view.deleteLater()


def test_every_config_widget_marks_dirty(_app):
    # BUG 2: flipping ANY config-writing widget must show UNSAVED. Previously the
    # 5 session toggles + all 6 new fields were unwired, so e.g. Code Execution
    # flipped silently. Uses isHidden() (works offscreen without show()).
    view = SettingsView()
    try:
        def _flip_toggle(t):
            # ToggleSwitch emits `toggled` only on a real click (mousePressEvent),
            # not on programmatic setChecked() — exercise the actual user path.
            t.mousePressEvent(None)

        def _cycle_combo(c):
            c.setCurrentIndex((c.currentIndex() + 1) % c.count())

        toggles = [
            view._flag_mic, view._flag_tts, view._flag_conf, view._flag_dim,
            view._flag_wake, view._flag_stt_persistent, view._flag_code_exec,
            view._flag_autorun,
            # already-wired ones, re-checked so the audit covers the whole page
            view._debug_toggle, view._scan_toggle, view._noise_toggle,
            view._flag_safesearch,
        ]
        for t in toggles:
            view._mark_clean()
            assert view._unsaved_lbl.isHidden() is True
            _flip_toggle(t)
            assert view._unsaved_lbl.isHidden() is False, f"{t} did not mark dirty"

        for c in (view._stt_provider_combo, view._browser_engine_combo,
                  view._voice_combo, view._model_combo, view._mic_device_combo):
            if c.count() < 2:
                continue
            view._mark_clean()
            _cycle_combo(c)
            assert view._unsaved_lbl.isHidden() is False, f"{c} did not mark dirty"

        view._mark_clean()
        view._weather_city_input.setText("Testville,TT")
        assert view._unsaved_lbl.isHidden() is False
    finally:
        view.deleteLater()


def test_settle_readout_shows_off_at_zero(_app):
    assert SettingsView._fmt_settle(0) == "Off"
    assert SettingsView._fmt_settle(350) == "350"


def test_theme_swatch_fill_is_own_palette_not_active_accent(_app):
    # Each HUD-THEME swatch must paint its OWN palette colour regardless of the
    # active theme. The fill is a PAINTED _SwatchBar (not setStyleSheet), so the
    # global accent hook can't recolour STARK's cyan to the active accent.
    from ui.settings import _SwatchBar, _ThemeSwatch
    from ui.theme import _THEME_PALETTES

    for key in ("cyan", "teal", "amber", "indigo", "matrix"):
        sw = _ThemeSwatch(key, key.title(), "#000000", "#000000")
        try:
            bars = sw.findChildren(_SwatchBar)
            assert bars, f"{key}: swatch must paint its preview (not setStyleSheet)"
            # first bar = accent fill; must equal THIS palette's accent, not the token
            assert bars[0]._color.getRgb()[:3] == _THEME_PALETTES[key]["accent"], key
        finally:
            sw.deleteLater()
