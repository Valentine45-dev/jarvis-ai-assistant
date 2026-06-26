"""Theme system: palette resolution + accent substitution.

The HUD was authored in cyan rgb(0,229,255); a non-cyan theme swaps that accent
everywhere via themed constants + apply_accent() over QSS. The default (cyan)
path must be a guaranteed no-op so nothing changes for existing users.
"""

from __future__ import annotations

import ui.theme as theme


def test_default_theme_is_cyan_and_noop():
    # Suite runs with the default config (no theme set) → cyan, byte-identical.
    assert theme.THEME_KEY == "cyan"
    assert theme.ACCENT_RGB == (0, 229, 255)
    assert theme.CYAN == "#00e5ff"
    assert theme.BG == "#080A0A"
    assert theme.THEME_IS_BASE is True
    s = "border:1px solid rgba(0,229,255,0.4); color:#00e5ff;"
    assert theme.apply_accent(s) == s          # no-op for the base theme


def test_palette_table_covers_every_settings_swatch():
    # Keys must match the Settings swatches or a swatch would resolve to cyan.
    assert set(theme._THEME_PALETTES) == {"cyan", "teal", "amber", "indigo", "matrix"}
    for key, pal in theme._THEME_PALETTES.items():
        assert isinstance(pal["accent"], tuple) and len(pal["accent"]) == 3
        assert str(pal["bg"]).startswith("#")


def test_resolve_theme_key_falls_back_to_cyan(monkeypatch):
    from config.settings import config
    monkeypatch.setattr(config, "theme", "amber", raising=False)
    assert theme._resolve_theme_key() == "amber"
    monkeypatch.setattr(config, "theme", "not-a-theme", raising=False)
    assert theme._resolve_theme_key() == "cyan"
    monkeypatch.setattr(config, "theme", "", raising=False)
    assert theme._resolve_theme_key() == "cyan"


def test_hexrgb_and_tint():
    assert theme._hexrgb((0, 229, 255)) == "#00e5ff"
    assert theme._hexrgb((255, 170, 0)) == "#ffaa00"
    assert theme._tint((0, 0, 0), 0.0) == (0, 0, 0)
    assert theme._tint((0, 0, 0), 1.0) == (255, 255, 255)
    # Halfway toward white.
    assert theme._tint((0, 200, 255), 0.5) == (128, 228, 255)


def test_apply_accent_substitutes_for_nonbase_theme(monkeypatch):
    # Simulate the amber theme by overriding the resolved module globals, then
    # check the accent rgb (both spacings), hex, and bg are all swapped.
    monkeypatch.setattr(theme, "THEME_IS_BASE", False)
    monkeypatch.setattr(theme, "ACCENT_RGB", (255, 170, 0))
    monkeypatch.setattr(theme, "ACCENT_HEX", "#ffaa00")
    monkeypatch.setattr(theme, "_ACTIVE_BG", "#0D0A04")
    out = theme.apply_accent(
        "a{border:1px solid rgba(0,229,255,0.4);} "
        "b{color:rgba(0, 229, 255, 0.18); background:#080A0A;} c{color:#00e5ff;}"
    )
    assert "rgba(255,170,0,0.4)" in out
    assert "rgba(255, 170, 0, 0.18)" in out
    assert "#ffaa00" in out
    assert "#0D0A04" in out
    assert "229" not in out                    # no authored cyan left


def test_install_theme_is_idempotent_noop_on_base():
    # On the base theme install_theme must not patch setStyleSheet (no-op).
    assert theme.THEME_IS_BASE is True
    theme.install_theme()
    theme.install_theme()                      # second call safe
    from PyQt5.QtWidgets import QWidget
    # The base path leaves the original method in place (no wrapper installed).
    assert "apply_accent" not in getattr(QWidget.setStyleSheet, "__qualname__", "")
