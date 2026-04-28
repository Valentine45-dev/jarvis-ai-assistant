"""JARVIS HUD sidebar — reference-faithful port of jarvis_main_hud.py Sidebar.

A fixed narrow column with an avatar + STARK_OS / MARK_LXXXV brand at the top,
five nav buttons stacked icon-over-label, and a DIAGNOSTICS footer.
Selection maps to main.py's QStackedWidget indices via `_handle_click`.

Icons are rendered via `qtawesome` using the Phosphor (`ph.*`) icon set, which
gives us a Lucide-React-style clean stroke aesthetic that recolors per state
(active / hover / idle) instead of relying on platform-dependent emoji glyphs.
"""

from __future__ import annotations

import qtawesome as qta
from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import QLabel, QStyle, QStyleOption, QVBoxLayout, QWidget

from ui.bars import draw_glow_right_edge, draw_glow_underline
from ui.theme import CYAN, FM, SIDEBAR_W
from ui.widgets import _mono


# Visual items: (label, icon_name, default_active).
# icon_name uses qtawesome's Phosphor namespace ("ph.*") for a Lucide-like look.
# (label, icon_name, default_active, tooltip)
NAV_ITEMS = [
    ("SYSTEM",   "ph.monitor-play",            True,  "System Dashboard"),
    ("VOICE",    "ph.microphone-fill",         False,  "Voice Interface"),
    ("AUTOMATE", "ph.share-network",            False,  "Automation Workflows"),
    ("HISTORY",  "ph.clock-counter-clockwise", False,  "Command History"),
    ("CONFIG",   "ph.hexagon",                 False,  "System Configuration"),
]
FOOTER_ITEMS = [
    ("DIAGNOSTICS", "ph.activity", False, "Diagnostics"),
]


# State -> icon tint colors. Kept in one place so the look stays consistent.
_ICON_COLOR_ACTIVE = CYAN                      # "#00E5FF"
_ICON_COLOR_HOVER  = "#C3F5FF"
_ICON_COLOR_IDLE   = "rgba(0,229,255,0.35)"    # qtawesome accepts rgba strings


class _BrandZone(QWidget):
    """Sidebar brand container that paints the same glowing cyan underline
    as the TopBar, so the two halves form one continuous horizontal line."""

    def paintEvent(self, _):
        opt = QStyleOption()
        opt.initFrom(self)
        p = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, p, self)
        p.setRenderHint(QPainter.Antialiasing, False)
        draw_glow_underline(self, p)


def _qicon(name: str, color: str):
    """Build a qtawesome icon, swallowing missing-glyph errors gracefully.

    Returns None if the icon can't be created so the caller can fall back to
    a blank label rather than crashing the whole UI.
    """
    try:
        return qta.icon(name, color=color)
    except Exception:
        return None


class SidebarButton(QWidget):
    """One sidebar entry: vector icon stacked over an uppercase label."""

    clicked = pyqtSignal()

    ICON_PX = 26  # Rendered icon size; matches the bolder reference look.

    def __init__(self, label: str, icon_name: str, active: bool = False, parent=None):
        super().__init__(parent)
        self._label = label
        self._icon_name = icon_name
        self._active = active
        self.setFixedHeight(74)
        self.setCursor(Qt.PointingHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 12, 4, 12)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignCenter)

        self.icon_lbl = QLabel()
        self.icon_lbl.setAlignment(Qt.AlignCenter)
        self.icon_lbl.setFixedSize(self.ICON_PX + 4, self.ICON_PX + 4)

        self.text_lbl = QLabel(label)
        self.text_lbl.setFont(_mono(7, bold=True))
        self.text_lbl.setAlignment(Qt.AlignCenter)
        self.text_lbl.setWordWrap(False)

        lay.addWidget(self.icon_lbl, alignment=Qt.AlignCenter)
        lay.addWidget(self.text_lbl)

        self._apply_style(hovered=False)

    # ------------------------------------------------------------------ #

    def set_active(self, active: bool):
        self._active = active
        self._apply_style(hovered=False)

    def _set_icon(self, color: str):
        """Re-render the icon pixmap in the requested color."""
        icon = _qicon(self._icon_name, color)
        if icon is None:
            self.icon_lbl.clear()
            return
        self.icon_lbl.setPixmap(icon.pixmap(QSize(self.ICON_PX, self.ICON_PX)))

    def _apply_style(self, hovered: bool):
        if self._active:
            self.setStyleSheet(
                "background:rgba(0,229,255,0.15);"
                f"border-right:3px solid {CYAN};"
            )
            self._set_icon(_ICON_COLOR_ACTIVE)
            self.icon_lbl.setStyleSheet("background:transparent;border:none;")
            self.text_lbl.setStyleSheet(
                f"color:{CYAN};background:transparent;border:none;letter-spacing:1px;"
            )
        elif hovered:
            self.setStyleSheet("background:rgba(0,229,255,0.07);")
            self._set_icon(_ICON_COLOR_HOVER)
            self.icon_lbl.setStyleSheet("background:transparent;border:none;")
            self.text_lbl.setStyleSheet(
                f"color:{_ICON_COLOR_HOVER};background:transparent;border:none;letter-spacing:1px;"
            )
        else:
            self.setStyleSheet("background:transparent;")
            self._set_icon(_ICON_COLOR_IDLE)
            self.icon_lbl.setStyleSheet("background:transparent;border:none;")
            self.text_lbl.setStyleSheet(
                "color:rgba(0,229,255,0.35);background:transparent;border:none;letter-spacing:1px;"
            )

    # ------------------------------------------------------------------ #

    def enterEvent(self, _):
        if not self._active:
            self._apply_style(hovered=True)

    def leaveEvent(self, _):
        if not self._active:
            self._apply_style(hovered=False)

    def mousePressEvent(self, _):
        self.clicked.emit()


class HudSidebar(QWidget):
    """Narrow reference-style sidebar. Emits `nav_changed(int)` with stack index."""

    nav_changed = pyqtSignal(int)

    # Map each visible button position to the main.py QStackedWidget index.
    #   Stack order: 0 Dashboard, 1 Voice, 2 Automation, 3 History, 4 Settings
    _NAV_TO_STACK = [0, 1, 2, 3, 4]   # SYSTEM, VOICE, AUTOMATE, HISTORY, CONFIG
    _FOOTER_TO_STACK = [3]            # DIAGNOSTICS → History (secondary path)

    AVATAR_PX = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(SIDEBAR_W)
        # Background only; the glowing right-edge line is painted in
        # paintEvent so it matches the TopBar's bottom underline exactly.
        self.setStyleSheet("background:rgba(8,15,17,0.85);")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Avatar + brand ──
        # Uses _BrandZone so its bottom edge is painted with the same glowing
        # cyan underline as the TopBar (matching `draw_glow_underline`),
        # giving one continuous horizontal line across the screen.
        top = _BrandZone()
        top.setFixedHeight(64)
        top.setStyleSheet("background:transparent;")
        tl = QVBoxLayout(top)
        tl.setAlignment(Qt.AlignCenter)
        tl.setContentsMargins(0, 6, 0, 6)
        tl.setSpacing(2)

        avatar = QLabel()
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setFixedSize(self.AVATAR_PX + 2, self.AVATAR_PX + 2)
        avatar_icon = _qicon("ph.hexagon-fill", CYAN)
        if avatar_icon is not None:
            avatar.setPixmap(avatar_icon.pixmap(QSize(self.AVATAR_PX, self.AVATAR_PX)))
        avatar.setStyleSheet("background:transparent;border:none;")

        brand1 = QLabel("STARK_OS")
        brand1.setFont(_mono(6, bold=True))
        brand1.setAlignment(Qt.AlignCenter)
        brand1.setStyleSheet(
            f"color:{CYAN};letter-spacing:1px;background:transparent;border:none;"
        )

        brand2 = QLabel("MARK_LXXXV")
        brand2.setFont(_mono(5))
        brand2.setAlignment(Qt.AlignCenter)
        brand2.setStyleSheet(
            f"color:{CYAN};letter-spacing:1px;background:transparent;border:none;"
        )

        tl.addWidget(avatar, alignment=Qt.AlignCenter)
        tl.addWidget(brand1)
        tl.addWidget(brand2)
        lay.addWidget(top)

        # ── Nav items ──
        nav_wrap = QWidget()
        nav_wrap.setStyleSheet("background:transparent;")
        nav_lay = QVBoxLayout(nav_wrap)
        nav_lay.setContentsMargins(0, 8, 0, 0)
        nav_lay.setSpacing(2)

        self._nav_buttons: list[SidebarButton] = []
        for i, (label, icon_name, active, tip) in enumerate(NAV_ITEMS):
            btn = SidebarButton(label, icon_name, active=active)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda idx=i: self._handle_click("nav", idx))
            nav_lay.addWidget(btn)
            self._nav_buttons.append(btn)
        nav_lay.addStretch(1)
        lay.addWidget(nav_wrap, 1)

        # ── Footer items ──
        footer_wrap = QWidget()
        footer_wrap.setStyleSheet(
            "background:transparent;"
            "border-top:1px solid rgba(0,229,255,0.18);"
        )
        footer_lay = QVBoxLayout(footer_wrap)
        footer_lay.setContentsMargins(0, 4, 0, 8)
        footer_lay.setSpacing(2)

        self._footer_buttons: list[SidebarButton] = []
        for i, (label, icon_name, active, tip) in enumerate(FOOTER_ITEMS):
            btn = SidebarButton(label, icon_name, active=active)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda idx=i: self._handle_click("footer", idx))
            footer_lay.addWidget(btn)
            self._footer_buttons.append(btn)
        lay.addWidget(footer_wrap)

    # ------------------------------------------------------------------ #

    def paintEvent(self, _):
        # Draw QSS background, then layer the glowing cyan line on the
        # right edge — same falloff as the TopBar's bottom underline.
        opt = QStyleOption()
        opt.initFrom(self)
        p = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, p, self)
        p.setRenderHint(QPainter.Antialiasing, False)
        draw_glow_right_edge(self, p)

    # ------------------------------------------------------------------ #

    def _handle_click(self, source: str, idx: int):
        if source == "nav":
            stack_idx = self._NAV_TO_STACK[idx]
            active_nav, active_footer = idx, -1
        else:
            stack_idx = self._FOOTER_TO_STACK[idx]
            active_nav, active_footer = -1, idx

        for i, b in enumerate(self._nav_buttons):
            b.set_active(i == active_nav)
        for i, b in enumerate(self._footer_buttons):
            b.set_active(i == active_footer)

        self.nav_changed.emit(stack_idx)

    def goto(self, nav_idx: int) -> None:
        """Public navigation hook for code that doesn't own the sidebar buttons.

        Mirrors a real user click on nav slot *nav_idx* (0=System, 1=Voice,
        2=Automate, 3=History, 4=Config) so the active highlight + nav_changed
        signal stay consistent regardless of who triggered the navigation.
        """
        if 0 <= nav_idx < len(self._nav_buttons):
            self._handle_click("nav", nav_idx)
