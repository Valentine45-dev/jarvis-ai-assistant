"""
Theme system for the rebuilt JARVIS HUD UI.

This module is the single source of truth for:
- color tokens
- font tokens and font loading
- application stylesheet (QSS)
- compatibility constants used by existing main.py/ui wiring
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

from PyQt5.QtGui import QColor, QFont, QFontDatabase


# ---------------------------------------------------------------------------
# Canonical design tokens (from project spec)
# ---------------------------------------------------------------------------

COLORS: Dict[str, str] = {
    "background": "#0d1516",
    "surface": "#0d1516",
    "surface_container_low": "#151d1e",
    "surface_container": "#192122",
    "surface_container_high": "#242b2d",
    "surface_container_highest": "#2e3638",
    "surface_container_lowest": "#080f11",
    "outline_variant": "#3b494c",
    "outline": "#849396",
    "on_surface": "#dce4e5",
    "on_surface_variant": "#bac9cc",
    "primary": "#c3f5ff",
    "primary_container": "#00e5ff",
    "primary_fixed_dim": "#00daf3",
    "secondary_container": "#ffdb3c",
    "secondary_fixed": "#ffe16d",
    "secondary_fixed_dim": "#e9c400",
    "tertiary": "#afffbf",
    "tertiary_container": "#71e894",
    "tertiary_fixed": "#83fba5",
    "tertiary_fixed_dim": "#66dd8b",
    "error": "#ffb4ab",
    "error_container": "#93000a",
}

FONTS: Dict[str, Tuple[str, int, int]] = {
    "headline_lg": ("Space Grotesk", 48, QFont.Bold),
    "headline_md": ("Space Grotesk", 32, QFont.DemiBold),
    "data_display": ("Roboto Mono", 24, QFont.Medium),
    "label_caps": ("Roboto Mono", 12, QFont.Bold),
    "label_sm": ("Roboto Mono", 10, QFont.Normal),
    "body_lg": ("Inter", 18, QFont.Normal),
    "body_md": ("Inter", 16, QFont.Normal),
}


# ---------------------------------------------------------------------------
# Compatibility aliases expected by current app/main.py
# ---------------------------------------------------------------------------

PRIMARY = COLORS["primary"]
PRIMARY_DIM = COLORS["primary_fixed_dim"]
PRIMARY_GLOW = COLORS["primary_container"]
PRIMARY_BRIGHT = COLORS["primary_container"]
CYAN = COLORS["primary_container"]
RED = COLORS["error"]
GREEN = COLORS["tertiary_fixed"]
WARNING = COLORS["secondary_fixed"]
BG = COLORS["background"]

# Existing modules still import these while the UI migration is in progress.
PANEL_CLR = (25, 33, 34, 140)
CARD_CLR = (21, 29, 30, 130)
BORDER_A = (0, 229, 255, 40)
BORDER_B = (0, 229, 255, 95)

FN = "Inter"
FM = "Roboto Mono"

SIDEBAR_W = 240
TOPBAR_H = 52
BOTBAR_H = 38
RIGHT_W = 420

# New design has no rounded corners; keep exported names for compatibility.
RADIUS_SM = 0
RADIUS_MD = 0
RADIUS_LG = 0
RADIUS_XL = 0


# ---------------------------------------------------------------------------
# Font loading and factory helpers
# ---------------------------------------------------------------------------

def _fonts_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "fonts"


def load_jarvis_fonts() -> Dict[str, str]:
    """
    Load Space Grotesk, Roboto Mono and Inter if local .ttf files exist.

    Returns a map with the effective family chosen for:
    - sans
    - mono
    - headline
    """
    loaded_families = set()
    folder = _fonts_dir()
    if folder.exists():
        for font_path in folder.glob("*.ttf"):
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                loaded_families.update(families)

    def pick(preferred: str, fallback: str) -> str:
        return preferred if preferred in loaded_families else fallback

    return {
        "sans": pick("Inter", "Segoe UI"),
        "mono": pick("Roboto Mono", "Consolas"),
        "headline": pick("Space Grotesk", "Segoe UI"),
    }


def font(role: str, resolved_families: Dict[str, str] | None = None) -> QFont:
    """Create a QFont for a design role using loaded family fallbacks."""
    family, size, weight = FONTS[role]
    families = resolved_families or {"sans": "Segoe UI", "mono": "Consolas", "headline": "Segoe UI"}
    if family == "Inter":
        family = families["sans"]
    elif family == "Roboto Mono":
        family = families["mono"]
    elif family == "Space Grotesk":
        family = families["headline"]

    f = QFont(family, size, weight)
    if role == "headline_lg":
        f.setLetterSpacing(QFont.PercentageSpacing, 98)
    elif role == "headline_md":
        f.setLetterSpacing(QFont.PercentageSpacing, 105)
    elif role == "data_display":
        f.setLetterSpacing(QFont.PercentageSpacing, 110)
    elif role == "label_caps":
        f.setLetterSpacing(QFont.PercentageSpacing, 115)
    elif role == "label_sm":
        f.setLetterSpacing(QFont.PercentageSpacing, 105)
    return f


# ---------------------------------------------------------------------------
# Global QSS
# ---------------------------------------------------------------------------

def app_stylesheet(resolved_families: Dict[str, str] | None = None) -> str:
    fam = resolved_families or {"sans": "Segoe UI", "mono": "Consolas", "headline": "Segoe UI"}
    return f"""
QWidget {{
    background-color: {COLORS["background"]};
    color: {COLORS["on_surface"]};
    font-family: '{fam["sans"]}';
    border: none;
    border-radius: 0px;
}}
QScrollBar:vertical {{
    background: {COLORS["surface_container_lowest"]};
    width: 4px;
}}
QScrollBar::handle:vertical {{
    background: rgba(0, 229, 255, 0.4);
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QLineEdit {{
    background: transparent;
    border: none;
    border-bottom: 1px solid rgba(59, 73, 76, 0.6);
    color: {COLORS["primary"]};
    font-family: '{fam["mono"]}';
    padding: 4px 2px;
}}
QLineEdit:focus {{
    border-bottom: 1px solid {COLORS["primary_container"]};
}}
QPushButton {{
    background: transparent;
    border: 1px solid {COLORS["primary_container"]};
    color: {COLORS["primary_container"]};
    font-family: '{fam["mono"]}';
    font-size: 12px;
    letter-spacing: 2px;
    padding: 6px 16px;
    border-radius: 0px;
}}
QPushButton:hover {{
    background: rgba(0, 229, 255, 0.15);
}}
QPushButton:pressed {{
    background: rgba(0, 229, 255, 0.3);
}}
QTableWidget {{
    background: transparent;
    gridline-color: rgba(59, 73, 76, 0.3);
    font-family: '{fam["mono"]}';
    font-size: 10px;
}}
QTableWidget::item {{
    padding: 6px 8px;
}}
QTableWidget::item:hover {{
    background: rgba(0, 229, 255, 0.05);
}}
QHeaderView::section {{
    background: rgba(21, 29, 30, 0.9);
    color: {COLORS["outline"]};
    font-family: '{fam["mono"]}';
    font-size: 10px;
    letter-spacing: 2px;
    border-bottom: 1px solid rgba(59, 73, 76, 0.5);
    padding: 6px 8px;
}}
QComboBox {{
    background: {COLORS["surface_container_lowest"]};
    border: 1px solid rgba(59, 73, 76, 0.5);
    color: {COLORS["primary_container"]};
    font-family: '{fam["mono"]}';
    font-size: 14px;
    padding: 6px 8px;
    border-radius: 0px;
}}
QComboBox:focus {{
    border-color: {COLORS["primary_container"]};
}}
QComboBox QAbstractItemView {{
    background: {COLORS["surface_container_lowest"]};
    border: 1px solid {COLORS["primary_container"]};
    color: {COLORS["primary_container"]};
    selection-background-color: rgba(0, 229, 255, 0.2);
}}
""".strip()


# ---------------------------------------------------------------------------
# QColor helper utilities kept for existing imports
# ---------------------------------------------------------------------------

def _c(r: int, g: int, b: int, a: int = 255) -> QColor:
    return QColor(r, g, b, a)


def _primary(a: int = 255) -> QColor:
    return QColor(0, 229, 255, a)


def _cyan(a: int = 255) -> QColor:
    return QColor(0, 229, 255, a)


def _border() -> QColor:
    return _c(*BORDER_A)


def _border_b() -> QColor:
    return _c(*BORDER_B)
