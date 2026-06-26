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
from typing import Dict, Tuple, TYPE_CHECKING

from PyQt5.QtGui import QColor, QFont, QFontDatabase, QIcon

if TYPE_CHECKING:
    from PyQt5.QtGui import QPixmap


# ---------------------------------------------------------------------------
# Canonical design tokens (from project spec)
# ---------------------------------------------------------------------------

COLORS: Dict[str, str] = {
    "background": "#080A0A",
    "surface": "#080A0A",
    "surface_container_low": "#0D0F0F",
    "surface_container": "#111313",
    "surface_container_high": "#181A1A",
    "surface_container_highest": "#1E2020",
    "surface_container_lowest": "#050707",
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
# Theme palette — accent + background per theme key (matches the Settings
# swatches). The whole HUD was authored in the cyan accent rgb(0,229,255); a
# non-cyan theme swaps that accent everywhere via (a) the constants/helpers
# below and (b) apply_accent() installed over setStyleSheet (see install_theme).
# Resolved once at import from config.theme; switching themes needs an app
# restart (the wake-word convention). The "cyan" branch reproduces the original
# constants byte-for-byte, so the default path is unchanged.
# ---------------------------------------------------------------------------

_BASE_ACCENT_RGB: Tuple[int, int, int] = (0, 229, 255)   # the authored cyan accent
_BASE_BG = "#080A0A"

_THEME_PALETTES: Dict[str, Dict[str, object]] = {
    # key:      accent rgb,            bg hex
    "cyan":   {"accent": (0, 229, 255),   "bg": "#080A0A"},
    "teal":   {"accent": (61, 199, 214),  "bg": "#0A1010"},
    "amber":  {"accent": (255, 170, 0),   "bg": "#0D0A04"},
    "indigo": {"accent": (129, 140, 248), "bg": "#060912"},
    "matrix": {"accent": (0, 255, 102),   "bg": "#050A06"},
}


def _resolve_theme_key() -> str:
    """Active theme key from config (default 'cyan'); never raises at import."""
    try:
        from config.settings import config
        key = (getattr(config, "theme", "cyan") or "cyan").strip().lower()
        return key if key in _THEME_PALETTES else "cyan"
    except Exception:
        return "cyan"


def _hexrgb(rgb: Tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _tint(rgb: Tuple[int, int, int], f: float) -> Tuple[int, int, int]:
    """Blend *rgb* toward white by fraction f (0 = rgb, 1 = white)."""
    return tuple(int(round(c + (255 - c) * f)) for c in rgb)  # type: ignore[return-value]


THEME_KEY = _resolve_theme_key()
ACCENT_RGB: Tuple[int, int, int] = _THEME_PALETTES[THEME_KEY]["accent"]  # type: ignore[assignment]
ACCENT_HEX = _hexrgb(ACCENT_RGB)
_ACTIVE_BG = str(_THEME_PALETTES[THEME_KEY]["bg"])
# True when the active theme is the authored cyan — lets apply_accent() short
# circuit to a guaranteed no-op so the default path is byte-identical.
THEME_IS_BASE = ACCENT_RGB == _BASE_ACCENT_RGB

# Re-point the accent-bearing palette entries at the active accent so anything
# reading COLORS / the aliases below is themed. Light foreground cyan (#c3f5ff)
# becomes a matching light tint of the active accent.
COLORS["primary"] = _hexrgb(_tint(ACCENT_RGB, 0.62)) if not THEME_IS_BASE else COLORS["primary"]
COLORS["primary_container"] = ACCENT_HEX
COLORS["primary_fixed_dim"] = ACCENT_HEX if not THEME_IS_BASE else COLORS["primary_fixed_dim"]
COLORS["background"] = _ACTIVE_BG
COLORS["surface"] = _ACTIVE_BG


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
BG = _ACTIVE_BG

# Existing modules still import these while the UI migration is in progress.
PANEL_CLR = (12, 14, 14, 140)
CARD_CLR = (14, 16, 16, 130)
BORDER_A = (*ACCENT_RGB, 40)
BORDER_B = (*ACCENT_RGB, 95)

FN = "Inter"
FM = "Roboto Mono"

SIDEBAR_W = 128   # single source of truth — sidebar.py must not redefine this
TOPBAR_H = 52
BOTBAR_H = 40
RIGHT_W = 420

# ---------------------------------------------------------------------------
# Semantic design tokens — use these instead of hardcoded rgba() values
# ---------------------------------------------------------------------------

# Text hierarchy: both values pass WCAG AA (≥4.5:1) on BG = #080A0A
TEXT_MUTED     = "rgba(186,201,204,0.75)"   # hint/label/secondary text
TEXT_SECONDARY = "rgba(186,201,204,0.88)"   # supporting body text

# Unified idle state — same color on Dashboard reactor and Voice mic strip
IDLE_CYAN = f"rgba({ACCENT_RGB[0]},{ACCENT_RGB[1]},{ACCENT_RGB[2]},0.35)"

# Glass panel fill — replaces QColor(10,17,19,220) hardcoded in 15+ places
BG_PANEL = "rgba(10,17,19,220)"

# New design has no rounded corners; keep exported names for compatibility.
RADIUS_SM = 0
RADIUS_MD = 0
RADIUS_LG = 0
RADIUS_XL = 0


# ---------------------------------------------------------------------------
# Font loading and factory helpers
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _fonts_dir() -> Path:
    return _project_root() / "fonts"


def jarvis_logo_svg_path() -> Path:
    """`assets/jarvis_logo.svg` (hex reactor mark)."""
    return _project_root() / "assets" / "jarvis_logo.svg"


def recolor_logo_svg(svg_text: str) -> str:
    """Swap the logo's baked accent (#00E5FF, any case) for ACCENT_HEX.

    A no-op on the cyan theme (THEME_IS_BASE) so the original SVG bytes are
    preserved exactly. Split out from jarvis_logo_pixmap so it's unit-testable
    without rendering."""
    if THEME_IS_BASE:
        return svg_text
    import re
    return re.sub(r"#00e5ff", ACCENT_HEX, svg_text, flags=re.IGNORECASE)


def jarvis_logo_pixmap(side: int = 32) -> "QPixmap | None":
    """Rasterise the logo SVG to a square pixmap, or None if unavailable.

    The logo SVG bakes the accent (#00E5FF, 8 places) into its gradients/strokes,
    which no token can reach. On a non-cyan theme we read the SVG text and replace
    that accent with ACCENT_HEX (case-insensitive) before rendering, so the brand
    mark matches the active theme. On cyan (THEME_IS_BASE) the file is read
    unchanged — byte-identical to the original path-based load."""
    path = jarvis_logo_svg_path()
    if not path.is_file():
        return None
    try:
        from PyQt5.QtCore import Qt, QRectF
        from PyQt5.QtGui import QPainter, QPixmap
        from PyQt5.QtSvg import QSvgRenderer
    except Exception:
        return None
    if THEME_IS_BASE:
        renderer = QSvgRenderer(str(path))
    else:
        from PyQt5.QtCore import QByteArray
        svg = recolor_logo_svg(path.read_text(encoding="utf-8"))
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        return None
    pm = QPixmap(side, side)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    renderer.render(p, QRectF(0, 0, float(side), float(side)))
    p.end()
    return pm


def jarvis_logo_icon() -> QIcon:
    """Window / taskbar icon; prefers a crisp raster from the SVG."""
    pm = jarvis_logo_pixmap(64)
    if pm is not None and not pm.isNull():
        return QIcon(pm)
    p = jarvis_logo_svg_path()
    return QIcon(str(p)) if p.is_file() else QIcon()


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

def tooltip_qss() -> str:
    """Readable tooltips on dark Fusion (avoids system near–black on black text)."""
    return f"""
QToolTip {{
    background-color: {COLORS["surface_container"]};
    color: {COLORS["on_surface"]};
    border: 1px solid rgba(0, 229, 255, 0.45);
    padding: 5px 8px;
    font-size: 11px;
    border-radius: 2px;
}}
""".strip()


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
    return QColor(*ACCENT_RGB, a)


def _cyan(a: int = 255) -> QColor:
    return QColor(*ACCENT_RGB, a)


def _border() -> QColor:
    return _c(*BORDER_A)


def _border_b() -> QColor:
    return _c(*BORDER_B)


# ---------------------------------------------------------------------------
# Accent substitution for inline QSS — the centralized half of theming
# ---------------------------------------------------------------------------
#
# The HUD has ~93 inline `rgba(0,229,255,a)` / `#00e5ff` literals baked into
# per-widget stylesheets (and every f-string that interpolates {CYAN}). Rather
# than rewrite each call site, apply_accent() rewrites the authored cyan to the
# active accent in any stylesheet string, and install_theme() runs it over every
# QWidget/QApplication.setStyleSheet call. For the cyan theme it's a guaranteed
# no-op, so the default path is byte-identical.

def apply_accent(qss: str) -> str:
    """Swap the authored cyan accent for the active accent in a QSS string."""
    if THEME_IS_BASE or not qss:
        return qss
    r, g, b = ACCENT_RGB
    out = qss.replace("0, 229, 255", f"{r}, {g}, {b}").replace("0,229,255", f"{r},{g},{b}")
    out = out.replace("#00e5ff", ACCENT_HEX).replace("#00E5FF", ACCENT_HEX)
    if _ACTIVE_BG.lower() != _BASE_BG.lower():
        out = out.replace(_BASE_BG, _ACTIVE_BG).replace(_BASE_BG.lower(), _ACTIVE_BG)
    return out


_THEME_INSTALLED = False


def install_theme() -> None:
    """Route every setStyleSheet through apply_accent so inline QSS literals get
    the active accent. Idempotent; a no-op for the cyan theme. Call once at
    startup, before widgets are built. Painted widgets (QColor literals) are
    themed separately via ACCENT_RGB at their call sites."""
    global _THEME_INSTALLED
    if _THEME_INSTALLED or THEME_IS_BASE:
        _THEME_INSTALLED = True
        return
    try:
        from PyQt5.QtWidgets import QApplication, QWidget
    except Exception:
        return
    for cls in (QWidget, QApplication):
        orig = cls.setStyleSheet

        def _patched(self, qss, _orig=orig):
            return _orig(self, apply_accent(qss))

        cls.setStyleSheet = _patched
    _THEME_INSTALLED = True
