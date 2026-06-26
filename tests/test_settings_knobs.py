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
