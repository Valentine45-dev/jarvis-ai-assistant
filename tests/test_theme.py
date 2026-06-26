"""Theme system: palette resolution, accent substitution, and accent wiring.

The HUD was authored in cyan rgb(0,229,255); a non-cyan theme swaps that accent
everywhere via themed constants/tokens + apply_accent() over QSS + per-site token
reads for painted/icon/asset colours. The default (cyan) path must be a guaranteed
no-op so nothing changes for existing users.

These tests are AMBIENT-INDEPENDENT: they don't assume which theme config resolves
to at import (a dev may have any theme saved). Accent wiring is proved by asserting
each site reads the ACCENT token; theme-divergence is proved by monkeypatching the
resolved globals on the pure functions.
"""

from __future__ import annotations

import pytest
from PyQt5.QtGui import QColor

import ui.theme as theme


# ── pure palette / helpers ──────────────────────────────────────────────────

def test_palette_table_covers_every_settings_swatch():
    assert set(theme._THEME_PALETTES) == {"cyan", "teal", "amber", "indigo", "matrix"}
    for _key, pal in theme._THEME_PALETTES.items():
        assert isinstance(pal["accent"], tuple) and len(pal["accent"]) == 3
        assert str(pal["bg"]).startswith("#")
    # cyan must be the authored base (so its path is byte-identical).
    assert theme._THEME_PALETTES["cyan"]["accent"] == (0, 229, 255)


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
    assert theme._tint((0, 200, 255), 0.5) == (128, 228, 255)


# ── apply_accent (QSS substitution) ─────────────────────────────────────────

def test_apply_accent_noop_when_base(monkeypatch):
    monkeypatch.setattr(theme, "THEME_IS_BASE", True)
    s = "border:1px solid rgba(0,229,255,0.4); color:#00e5ff;"
    assert theme.apply_accent(s) == s          # base path byte-identical


def test_apply_accent_substitutes_for_nonbase_theme(monkeypatch):
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


def test_install_theme_noop_on_base(monkeypatch):
    monkeypatch.setattr(theme, "THEME_IS_BASE", True)
    monkeypatch.setattr(theme, "_THEME_INSTALLED", False)
    theme.install_theme()                       # must not patch setStyleSheet
    from PyQt5.QtWidgets import QWidget
    assert "apply_accent" not in getattr(QWidget.setStyleSheet, "__qualname__", "")


# ── accent wiring: each painted/icon site reads the ACCENT token ────────────
# (ambient-independent: holds whether the resolved theme is cyan or not — under a
# non-cyan theme ACCENT_* is non-cyan, so these prove the sites follow the theme;
# the paired semantic literals must stay fixed.)

def test_states_map_routes_glow_to_accent_keeps_semantic():
    import ui.dashboard as d
    for key in ("idle", "listening", "thinking", "wake"):
        assert d.STATES[key][1] == theme.ACCENT_HEX, key
    assert d.STATES["speaking"][1] == "#83fba5"   # semantic success
    assert d.STATES["error"][1] == "#ffb4ab"      # semantic error


def test_tag_highlighter_accent_and_semantic():
    from ui.widgets.inputs import _TagHighlighter
    assert _TagHighlighter._CYAN.getRgb()[:3] == tuple(theme.ACCENT_RGB)   # accent
    assert _TagHighlighter._GOLD.getRgb()[:3] == QColor("#FFE16D").getRgb()[:3]  # semantic


def test_sidebar_icon_colours_route_to_tokens():
    import ui.sidebar as sb
    assert sb._ICON_COLOR_IDLE == theme.IDLE_CYAN
    assert sb._ICON_COLOR_ACTIVE == theme.CYAN
    assert sb._ICON_COLOR_HOVER == theme.PRIMARY


# ── logo SVG recolour ───────────────────────────────────────────────────────

def test_recolor_logo_noop_on_base(monkeypatch):
    monkeypatch.setattr(theme, "THEME_IS_BASE", True)
    svg = '<svg><stop stop-color="#00E5FF"/><path stroke="#00e5ff"/></svg>'
    assert theme.recolor_logo_svg(svg) == svg     # byte-identical under cyan


def test_recolor_logo_swaps_accent_for_nonbase(monkeypatch):
    monkeypatch.setattr(theme, "THEME_IS_BASE", False)
    monkeypatch.setattr(theme, "ACCENT_HEX", "#ffaa00")
    svg = 'a #00E5FF b #00e5ff c stroke="#00E5FF"'
    out = theme.recolor_logo_svg(svg)
    assert "#ffaa00" in out
    assert "#00e5ff" not in out.lower()           # all 3 (any case) replaced


def test_real_logo_svg_recolours_under_nonbase(monkeypatch):
    # The shipped asset has the accent baked in 8 places; prove the helper swaps
    # them under a non-cyan theme and leaves it identical under cyan.
    svg = theme.jarvis_logo_svg_path().read_text(encoding="utf-8")
    assert "#00e5ff" in svg.lower()
    monkeypatch.setattr(theme, "THEME_IS_BASE", True)
    assert theme.recolor_logo_svg(svg) == svg
    monkeypatch.setattr(theme, "THEME_IS_BASE", False)
    monkeypatch.setattr(theme, "ACCENT_HEX", "#00ff66")
    out = theme.recolor_logo_svg(svg)
    assert "#00ff66" in out and "#00e5ff" not in out.lower()


# ── visuals reactor state colours (needs a QApplication → opt-in qtgui) ──────

@pytest.mark.qtgui
def test_visuals_state_colours_route_to_accent():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    from ui.widgets.visuals import ArcReactorWidget
    w = ArcReactorWidget()
    try:
        sc = w._state_colors
        for key in ("idle", "listening", "thinking", "wake"):
            assert sc[key].getRgb()[:3] == tuple(theme.ACCENT_RGB), key
        assert sc["speaking"].getRgb()[:3] == QColor("#83fba5").getRgb()[:3]
        assert sc["error"].getRgb()[:3] == QColor("#ffb4ab").getRgb()[:3]
    finally:
        w.deleteLater()
