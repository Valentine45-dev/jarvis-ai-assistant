"""VoiceView — VOICE_CORE.

Redesigned 2026-05 to match the shared HUD grammar:
  - Top 5-tile hero strip (State · Capture · Device · Wake word · TTS provider)
  - Left active panel: big circular mic + waveform + idle hint
  - Right panel: transcript with intent badges (divide-y rows, last 20 turns)
  - Bottom action bar: Start / Pause wake / Clear + hotkey hint

Public API preserved so main.py needs no changes:
  - mic_toggled signal
  - set_state(state)
  - update_transcript(cmd, resp, intent, conf)
  - append_jarvis_continuation(resp, intent, conf)
  - set_execution(intent, action, conf, success, error)
  - set_pending(intent, action, conf, message)
  - clear_pending()
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import qtawesome as qta
from PyQt5.QtCore import Qt, QPointF, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.settings import config
from ui.components.design import (
    AMBER,
    BG_PANEL,
    CYAN_FAINT,
    CYAN_SOFT,
    GREEN,
    GREEN_DIM,
    INK,
    INK_DIM,
    INK_FAINT,
    RED,
    DivideRow,
    HeroMetric,
    IntentBadge,
    PanelCard,
    StatusPip,
)
from ui.theme import BG, CYAN, FM
# WaveformStrip dropped — the OrbMic carries the state visual now.


# ── Big circular mic button (kept from prior implementation; mostly the same) ──


class _OrbMic(QWidget):
    """Iridescent Siri-style orb. Multi-color radial gradient composition.

    Matches the M5 mockup pixel-for-pixel:
      * Cyan base radial gradient
      * Amber wash through the center
      * Magenta blob bottom-left
      * Purple blob bottom-right
      * Cyan blob top-right
      * White highlight top-left
      * Outer multi-color glow halo (cyan + magenta + purple) painted as
        very-large faint radial gradients outside the orb body.

    Subtle pulse animation when listening: orb grows ~3% and brightens the
    inner highlight. No hard pulse rings — the orb is the energy.
    """

    # Orb body diameter. Widget total is bigger to leave room for the halo.
    # WIDGET_SIZE must be generous enough that the halo gradients fully fade to
    # transparent inside the widget's *inscribed circle* — otherwise the
    # rectangular widget bounds clip a still-visible glow into a square box.
    ORB_DIAMETER  = 240
    WIDGET_SIZE   = 400         # orb + outer glow halo padding

    pressed_toggled = pyqtSignal()

    # Color stops re-used across paint() — keeping them as class attrs makes
    # tweaks easy and avoids reallocating QColor on every frame.
    _C_CYAN      = QColor(0, 229, 255)
    _C_MAGENTA   = QColor(255, 155, 214)
    _C_PURPLE    = QColor(199, 146, 234)
    _C_AMBER     = QColor(255, 209, 102)
    _C_WHITE     = QColor(255, 255, 255)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._listening = False
        self._pulse_phase = 0.0
        self.setFixedSize(self.WIDGET_SIZE, self.WIDGET_SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Toggle microphone (Voice command capture)")
        # QWidget (not QPushButton) so no default button chrome / focus
        # rectangle paints behind the orb. We handle the click manually via
        # mousePressEvent below.
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.NoFocus)

        # Slow pulse — 40ms tick gives ~25fps which is smooth enough for an
        # orb that doesn't need to spike on audio. Faster pulse looks twitchy.
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(40)
        self._pulse_timer.timeout.connect(self._tick)

    def set_listening(self, listening: bool) -> None:
        if listening == self._listening:
            return
        self._listening = listening
        if listening:
            self._pulse_phase = 0.0
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
        self.update()

    def _tick(self) -> None:
        # phase wraps every 2.0 — gives a slow ~3-second breath cycle at 25fps.
        self._pulse_phase = (self._pulse_phase + 0.025) % 2.0
        self.update()

    def mousePressEvent(self, e) -> None:
        # Emit on left-click only — QWidget gets ALL mouse events including
        # right-click, so we filter here. (QPushButton handled that for free
        # before; the trade for losing the focus rect is a 3-line check.)
        if e.button() == Qt.LeftButton:
            self.pressed_toggled.emit()
        super().mousePressEvent(e)

    # ── Painting ─────────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        cx = self.width() / 2.0
        cy = self.height() / 2.0

        # Slight breathing scale when listening — orb gets ~3% bigger at peak.
        breath = 0.0
        if self._listening:
            # phase 0..2 → sine-like 0→1→0
            import math
            breath = (math.sin(self._pulse_phase * math.pi) + 1.0) * 0.5  # 0..1
        scale = 1.0 + breath * 0.03
        r = (self.ORB_DIAMETER / 2.0) * scale

        # ── 1) Outer multi-color glow halo (box-shadow equivalent) ──────────
        # Three large faint radial gradients in cyan / magenta / purple,
        # painted BIGGER than the orb to bleed past its edge.
        self._paint_halo(p, cx, cy, r, self._C_CYAN,
                         radius_mult=2.4, peak_alpha=int(80 + breath * 30))
        self._paint_halo(p, cx, cy, r, self._C_MAGENTA,
                         radius_mult=3.0, peak_alpha=40)
        self._paint_halo(p, cx, cy, r, self._C_PURPLE,
                         radius_mult=3.8, peak_alpha=26)

        # ── 2) Orb body — base cyan gradient ────────────────────────────────
        # The orb itself starts with a fully-saturated cyan core fading to
        # ~40% at the midpoint and to transparent at the edge.
        base = QRadialGradient(QPointF(cx, cy), r)
        base.setColorAt(0.0,  QColor(0, 229, 255, 242))
        base.setColorAt(0.50, QColor(0, 229, 255, 100))
        base.setColorAt(0.80, QColor(0, 229, 255, 0))
        p.setBrush(QBrush(base))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # ── 3) Color blob overlays (composited on top of the cyan base) ─────
        # These mirror the M5 CSS radial-gradient positions: each one is an
        # off-center color hotspot that fades quickly to transparent so it
        # blends with the cyan base.
        self._paint_blob(p, cx, cy, r,
                         offset=(-0.45, -0.45), spread=0.45,
                         color=self._C_WHITE, peak_alpha=int(120 + breath * 35))
        self._paint_blob(p, cx, cy, r,
                         offset=(0.40, -0.36), spread=0.55,
                         color=self._C_CYAN, peak_alpha=200)
        self._paint_blob(p, cx, cy, r,
                         offset=(-0.50, 0.40), spread=0.55,
                         color=self._C_MAGENTA, peak_alpha=200)
        self._paint_blob(p, cx, cy, r,
                         offset=(0.56, 0.50), spread=0.55,
                         color=self._C_PURPLE, peak_alpha=200)
        self._paint_blob(p, cx, cy, r,
                         offset=(0.0, 0.0), spread=0.85,
                         color=self._C_AMBER, peak_alpha=100)

        # ── 4) Top-left specular highlight — gives the orb a 3D wet sheen ──
        self._paint_blob(p, cx, cy, r,
                         offset=(-0.30, -0.40), spread=0.32,
                         color=self._C_WHITE, peak_alpha=160)

        # ── 5) Mic glyph in the center ──────────────────────────────────────
        self._paint_mic_glyph(p, cx, cy, r)

    def _paint_halo(self, p: QPainter, cx: float, cy: float, r: float,
                    color: QColor, *, radius_mult: float, peak_alpha: int) -> None:
        """Paint one outer glow halo — large radial gradient outside the orb.

        Critical: the gradient must reach alpha 0 by the widget's inscribed
        radius (WIDGET_SIZE / 2). Beyond that fraction QRadialGradient pads the
        last (transparent) stop, so every pixel at the rectangular widget edges
        and corners is fully transparent — no clipped "square" of glow.
        """
        halo_r = r * radius_mult
        grad = QRadialGradient(QPointF(cx, cy), halo_r)
        c0 = QColor(color)
        c0.setAlpha(peak_alpha)
        c1 = QColor(color)
        c1.setAlpha(0)
        inner = min(r / halo_r * 0.7, 0.95)
        # Fraction at which the glow must already be fully transparent: the
        # nearest widget edge. Clamp <1 so the fade always lands inside the
        # widget; anything past it (incl. the corners) pads to alpha 0.
        edge_frac = min((self.WIDGET_SIZE / 2.0) / halo_r, 0.999)
        # Inside the orb body radius: a soft plateau. Then fade to nothing by
        # the inscribed edge.
        grad.setColorAt(0.0, c0)
        if inner < edge_frac:
            grad.setColorAt(inner, c0)
        grad.setColorAt(edge_frac, c1)
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), halo_r, halo_r)

    def _paint_blob(self, p: QPainter, cx: float, cy: float, r: float,
                    *, offset: tuple[float, float], spread: float,
                    color: QColor, peak_alpha: int) -> None:
        """Paint one off-center color blob clipped to the orb's body.

        ``offset`` is (-1..+1) fractions of r relative to center.
        ``spread`` is the gradient's radius as a fraction of r.
        """
        ox = cx + offset[0] * r
        oy = cy + offset[1] * r
        blob_r = r * spread
        grad = QRadialGradient(QPointF(ox, oy), blob_r)
        c0 = QColor(color)
        c0.setAlpha(peak_alpha)
        c1 = QColor(color)
        c1.setAlpha(0)
        grad.setColorAt(0.0, c0)
        grad.setColorAt(1.0, c1)
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        # Clip to the orb body so blobs don't leak outside the sphere.
        p.save()
        clip = QPainterPath()
        clip.addEllipse(QPointF(cx, cy), r, r)
        p.setClipPath(clip)
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.restore()

    def _paint_mic_glyph(self, p: QPainter, cx: float, cy: float, r: float) -> None:
        """White microphone silhouette centered on the orb. Drawn with
        QPainterPath so it scales cleanly and gets a white drop-glow."""
        # Mic geometry scales with the orb radius — 0.22r body width is
        # tuned to look balanced against the 240px default diameter.
        body_w = r * 0.22
        body_h = r * 0.46
        body_x = cx - body_w / 2.0
        body_y = cy - body_h / 2.0 - r * 0.04

        # Capsule body
        path = QPainterPath()
        path.addRoundedRect(body_x, body_y, body_w, body_h, body_w / 2.0, body_w / 2.0)

        # U-shaped cradle under the capsule
        cradle_y = body_y + body_h * 0.55
        cradle_w = body_w * 2.4
        cradle_h = body_h * 0.85
        cradle_x = cx - cradle_w / 2.0

        # Stem + base
        stem_top = cradle_y + cradle_h - body_h * 0.05
        stem_bot = stem_top + r * 0.16
        base_w   = body_w * 1.6

        # Outer glow underlay (white at low alpha, slightly larger)
        glow = QColor(255, 255, 255, 90)
        p.setPen(QPen(glow, 3.5, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(glow)
        p.drawPath(path)

        # Main white fill
        white = QColor(255, 255, 255, 240)
        p.setBrush(white)
        p.setPen(Qt.NoPen)
        p.drawPath(path)

        # Cradle arc (open at top)
        pen = QPen(white, max(2.0, r * 0.018), Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(int(cradle_x), int(cradle_y),
                  int(cradle_w), int(cradle_h),
                  180 * 16, 180 * 16)

        # Stem
        p.drawLine(QPointF(cx, stem_top), QPointF(cx, stem_bot))

        # Base bar
        p.drawLine(QPointF(cx - base_w / 2.0, stem_bot),
                   QPointF(cx + base_w / 2.0, stem_bot))


# ── Transcript list ──────────────────────────────────────────────────────────


class _TranscriptList(QWidget):
    """T2-style card-stack transcript: one card per exchange.

    Each card is a QFrame with a cyan-left border (red on failure), a 1px
    cyan-faint outer border, and a faint cyan-tint background. Inside:
    header (time + IntentBadge + confidence), the user prompt as a dim
    green italic line, and the JARVIS response in white (or red).

    Preserves the previous ``_TranscriptList`` public API:
      * add_user(time_str, text) — stashes for the next add_jarvis pairing
      * add_jarvis(time_str, text, intent, conf, *, status) — emits the card
      * add_system(text) — emits a standalone system card
      * _row_count — incremented per logical row so external math like
        ``pairs = _row_count // 2`` keeps working with no code changes.
    """

    MAX_CARDS = 40

    # Sizing tuned for the JARVIS panel context — same body font size as
    # the rest of the redesigned rows so the card reads at consistent weight.
    _TEXT_SIZE  = 13
    _USER_SIZE  = 12.5
    _TIME_SIZE  = 11
    _META_SIZE  = 10

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 6px; }"
            "QScrollBar::handle:vertical {"
            "background: rgba(0,229,255,0.30); border-radius: 3px; min-height: 20px;"
            "}"
            "QScrollBar::handle:vertical:hover { background: rgba(0,229,255,0.55); }"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height: 0; }"
        )

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._rows_lay = QVBoxLayout(self._container)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        # 10px gap between cards — matches the T2 mockup. Tight enough to read
        # as a stream, generous enough to separate each exchange visually.
        self._rows_lay.setSpacing(10)
        self._rows_lay.addStretch(1)
        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, 1)

        # Logical row count — kept for back-compat with external code that
        # does ``pairs = _row_count // 2``. Bumped by add_user (even though
        # the user line gets stashed) and by add_jarvis / add_system.
        self._row_count = 0
        # The most recent add_user() call gets stashed here and consumed by
        # the next add_jarvis() so they collapse into ONE card per exchange.
        self._pending_user: Optional[tuple[str, str]] = None
        # Track card widgets so we can prune the oldest when MAX_CARDS hit.
        self._cards: list[QWidget] = []

    # ── Public API ───────────────────────────────────────────────────────────

    def add_user(self, time_str: str, text: str) -> None:
        # Stash for binding to the next jarvis call. No widget emitted yet.
        # _row_count still bumps so external "pairs = _row_count // 2" math
        # holds across the api change.
        self._pending_user = (time_str, text)
        self._row_count += 1

    def add_jarvis(self, time_str: str, text: str, intent: str, conf: float,
                   *, status: str = "ok") -> None:
        user_pair = self._pending_user
        self._pending_user = None
        card = self._build_card(
            time=(user_pair[0] if user_pair else time_str),
            user=(user_pair[1] if user_pair else None),
            jarvis=text,
            intent=intent,
            conf=conf,
            status=status,
        )
        self._insert_card(card)

    def add_system(self, text: str) -> None:
        # System messages don't pair with anything — they get their own card
        # with no IntentBadge and amber text (consistent with the prior
        # implementation's system styling).
        self._pending_user = None
        card = self._build_system_card(text)
        self._insert_card(card)

    # ── Card builders ────────────────────────────────────────────────────────

    def _build_card(self, *, time: str, user: Optional[str], jarvis: str,
                    intent: str, conf: float, status: str) -> QFrame:
        is_fail = status == "fail"
        card = QFrame()
        # T2 chrome: cyan-left border (red on fail), 1px cyan-faint outer
        # border, 3% cyan-tint background.
        left_color = RED if is_fail else CYAN
        card.setStyleSheet(
            "QFrame {"
            "background: rgba(0,229,255,0.03);"
            f"border: 1px solid {CYAN_FAINT};"
            f"border-left: 2px solid {left_color};"
            "}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(6)

        # ── Header: time + badge + confidence ──
        head = QHBoxLayout()
        head.setSpacing(10)
        head.setContentsMargins(0, 0, 0, 0)

        time_lbl = QLabel(time[:8])
        time_lbl.setStyleSheet(
            f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: {self._TIME_SIZE}px;"
            "letter-spacing: 0.5px; }}"
        )
        head.addWidget(time_lbl)

        badge_key = "fail" if is_fail else intent
        head.addWidget(IntentBadge(badge_key))
        head.addStretch(1)

        if is_fail:
            err_lbl = QLabel("err")
            err_lbl.setStyleSheet(
                f"QLabel {{ color: {RED}; background: transparent; border: none;"
                f"font-family: '{FM}'; font-size: {self._META_SIZE}px;"
                "letter-spacing: 1.4px; font-weight: 700; }}"
            )
            head.addWidget(err_lbl)
        elif 0.0 < conf < 1.0:
            pct = QLabel(f"{int(conf * 100)}%")
            pct.setStyleSheet(
                f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
                f"font-family: '{FM}'; font-size: {self._META_SIZE}px; }}"
            )
            head.addWidget(pct)
        lay.addLayout(head)

        # ── User line (optional, italic dim green) ──
        if user:
            you_lbl = QLabel(f'"{user}"')
            you_lbl.setWordWrap(True)
            you_lbl.setToolTip(user)
            you_lbl.setStyleSheet(
                f"QLabel {{ color: {GREEN_DIM}; background: transparent; border: none;"
                f"font-family: '{FM}'; font-size: {self._USER_SIZE}px;"
                "font-style: italic; }}"
            )
            lay.addWidget(you_lbl)

        # ── Response line ──
        resp_color = RED if is_fail else INK
        resp_lbl = QLabel(jarvis)
        resp_lbl.setWordWrap(True)
        resp_lbl.setToolTip(jarvis)
        resp_lbl.setStyleSheet(
            f"QLabel {{ color: {resp_color}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: {self._TEXT_SIZE}px; }}"
        )
        lay.addWidget(resp_lbl)
        return card

    def _build_system_card(self, text: str) -> QFrame:
        # System cards: amber-left border + amber text. Same chrome shape as
        # a command card so the stream reads cohesively.
        card = QFrame()
        card.setStyleSheet(
            "QFrame {"
            "background: rgba(255,209,102,0.04);"
            f"border: 1px solid {CYAN_FAINT};"
            f"border-left: 2px solid {AMBER};"
            "}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(2)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"QLabel {{ color: {AMBER}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: {self._TEXT_SIZE}px;"
            "letter-spacing: 0.5px; }}"
        )
        lay.addWidget(lbl)
        return card

    # ── Insertion + pruning ─────────────────────────────────────────────────

    def _insert_card(self, card: QWidget) -> None:
        self._rows_lay.insertWidget(self._rows_lay.count() - 1, card)
        self._cards.append(card)
        # Bump the logical row count so external "pairs" math keeps working.
        self._row_count += 1
        # Prune oldest cards above the cap. Each card may represent two
        # logical rows (user + jarvis), so we trim by card count not _row_count.
        while len(self._cards) > self.MAX_CARDS:
            oldest = self._cards.pop(0)
            oldest.deleteLater()
            # Decrement _row_count by 2 because a pruned exchange card
            # accounted for one add_user + one add_jarvis call.
            self._row_count = max(0, self._row_count - 2)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())


# ── Action button helper ─────────────────────────────────────────────────────


def _action_button(text: str, *, primary: bool = False, danger: bool = False) -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    if primary:
        bg = CYAN
        color = "#001a1f"
        border = CYAN
        hover = "background: #5ff2ff;"
    elif danger:
        bg = "transparent"
        color = RED
        border = RED
        hover = "background: rgba(255,107,107,0.10);"
    else:
        bg = "transparent"
        color = CYAN
        border = CYAN_SOFT
        hover = "background: rgba(0,229,255,0.10);"
    btn.setStyleSheet(
        "QPushButton {"
        f"background: {bg};"
        f"color: {color};"
        f"border: 1px solid {border};"
        f"font-family: '{FM}';"
        "font-size: 11px;"
        "font-weight: 700;"
        "padding: 11px 22px;"   # roomier — was 6x14, now ~2x vertical breathing room
        "letter-spacing: 2.5px;"
        "}"
        "QPushButton:hover {" + hover + "}"
    )
    return btn


# ── Hotkey hint label ────────────────────────────────────────────────────────


def _hotkey_hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
        f"font-family: '{FM}'; font-size: 10px; letter-spacing: 1.4px; }}"
    )
    return lbl


# ── Main view ───────────────────────────────────────────────────────────────


class VoiceView(QWidget):
    """VOICE_CORE. See module docstring."""

    mic_toggled = pyqtSignal()

    _STATE_LABEL: dict[str, tuple[str, str]] = {
        # state -> (display, color)
        "idle":      ("IDLE",      INK_DIM),
        "listening": ("LISTENING", GREEN),
        "thinking":  ("THINKING",  CYAN),
        "speaking":  ("SPEAKING",  CYAN),
        "awaiting":  ("AWAITING",  AMBER),
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = "idle"
        self._bg_px: Optional[QPixmap] = None
        self._bg_sz = (-1, -1)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # ── Header ──────────────────────────────────────────────────────────
        head = QHBoxLayout()
        head.setSpacing(12)
        title = QLabel("VOICE_CORE")
        title.setStyleSheet(
            "QLabel {"
            f"color: {CYAN};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 32px;"
            "font-weight: 700;"
            "letter-spacing: 5px;"
            "}"
        )
        head.addWidget(title, 0, Qt.AlignBottom)

        subtitle = QLabel("COMMAND INTERFACE · AUDIO PIPELINE")
        subtitle.setStyleSheet(
            "QLabel {"
            f"color: {INK_DIM};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "letter-spacing: 2px;"
            "padding-bottom: 6px;"  # nudge the baseline up so it visually
                                    # sits alongside the bigger title's lower-case zone
            "}"
        )
        head.addWidget(subtitle, 0, Qt.AlignBottom)
        head.addStretch(1)
        root.addLayout(head)

        # ── Hero strip ──────────────────────────────────────────────────────
        self._hero_wrap = self._build_hero_strip()
        root.addWidget(self._hero_wrap)

        # ── Main 2-column body ──────────────────────────────────────────────
        cols = QHBoxLayout()
        cols.setSpacing(14)
        cols.addWidget(self._build_left_panel(), 1)
        cols.addWidget(self._build_right_panel(), 1)
        root.addLayout(cols, 1)

        # ── Bottom action bar ───────────────────────────────────────────────
        actions = self._build_action_bar()
        root.addWidget(actions)

    # ── Builders ─────────────────────────────────────────────────────────────

    def _build_hero_strip(self) -> QWidget:
        """Top 5-metric row. No outer container, no dividers between cells —
        the dotted page backdrop shows through. Metrics float on it as
        labels + values, separated by horizontal gap. Mirrors the HTML
        mockup layout exactly.
        """
        wrap = QWidget()
        wrap.setStyleSheet("QWidget { background: transparent; }")
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(4, 6, 4, 6)
        lay.setSpacing(28)  # the visual "gap" between metrics — mockup uses 14px,
                            # bumped here to compensate for the lost dividers

        # 5 tiles. Per-metric value sizes mirror the HTML mockup explicitly:
        # Capture lvl is the largest (32px) because "−18" is the hero number;
        # State sits at 22 because LISTENING is short and bold-cased;
        # text-heavy metrics (Device, TTS) get 14 to avoid wrapping; Wake gets
        # 18 because `"jarvis"` is short but should read prominently.
        self._hm_state = HeroMetric("State", "IDLE", sub="mic closed",
                                    value_color=INK_DIM, value_size=22)
        self._hm_capture = HeroMetric("Capture lvl", "—", unit="dB",
                                      sub="ambient only", value_size=32)
        device_name = "Default · 16kHz"
        if config.mic_device != -1:
            try:
                import sounddevice as _sd  # type: ignore
                d = _sd.query_devices(config.mic_device)
                device_name = f"{d['name'][:24]}"
            except Exception:
                pass
        self._hm_device = HeroMetric("Device", device_name,
                                     sub=("noise-gate ON" if config.noise_gate else "noise-gate OFF"),
                                     value_size=14)
        self._hm_wake = HeroMetric("Wake word", f'"{config.wake_word}"',
                                   sub="listening" if config.wake_word_enabled else "disabled",
                                   value_color=GREEN if config.wake_word_enabled else INK_DIM,
                                   value_size=18)
        self._hm_tts = HeroMetric("TTS provider", "—", sub="resolving…",
                                  value_size=14)
        self._refresh_tts_tile()

        for metric in (self._hm_state, self._hm_capture, self._hm_device,
                       self._hm_wake, self._hm_tts):
            lay.addWidget(metric, 1)
        return wrap

    def _refresh_tts_tile(self) -> None:
        """Best-effort provider resolution at construction time."""
        if config.elevenlabs_api_key:
            self._hm_tts.set_value("ElevenLabs", color=CYAN)
            self._hm_tts.set_sub("primary")
        elif getattr(config, "gemini_api_key", ""):
            self._hm_tts.set_value("Gemini · Kore", color=CYAN)
            self._hm_tts.set_sub("free tier")
        else:
            self._hm_tts.set_value("pyttsx3", color=INK_DIM)
            self._hm_tts.set_sub("local fallback")

    def _build_left_panel(self) -> PanelCard:
        # M5 — Siri orb. Self-sufficient mic experience: orb is the visual
        # anchor + state indicator; the old waveform strip got dropped.
        panel = PanelCard(active=True)
        body = panel.body()

        body.addStretch(1)

        # Centered orb
        mic_row = QHBoxLayout()
        mic_row.addStretch(1)
        self._mic = _OrbMic()
        self._mic.pressed_toggled.connect(self.mic_toggled.emit)
        mic_row.addWidget(self._mic)
        mic_row.addStretch(1)
        body.addLayout(mic_row)

        body.addSpacing(8)

        hint = QLabel(f'Tap or say "{config.wake_word}"')
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(
            "QLabel {"
            f"color: {INK_FAINT};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 10px;"
            "letter-spacing: 3px;"
            "text-transform: uppercase;"
            "}"
        )
        body.addWidget(hint)

        body.addStretch(2)
        return panel

    def _build_right_panel(self) -> PanelCard:
        panel = PanelCard()

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        title = QLabel("TRANSCRIPT · THIS SESSION")
        title.setStyleSheet(
            "QLabel {"
            f"color: {CYAN};"
            "background: transparent;"
            "border: none;"
            f"font-family: '{FM}';"
            "font-size: 9.5px;"
            "font-weight: 700;"
            "letter-spacing: 2.2px;"
            "}"
        )
        head.addWidget(title)
        head.addStretch(1)
        self._exchange_count = QLabel("0 exchanges")
        self._exchange_count.setStyleSheet(
            f"QLabel {{ color: {INK_FAINT}; background: transparent; border: none;"
            f"font-family: '{FM}'; font-size: 9.5px; letter-spacing: 1.2px; }}"
        )
        head.addWidget(self._exchange_count)
        panel.body().addLayout(head)

        self._transcript = _TranscriptList()
        panel.add(self._transcript, stretch=1)
        return panel

    def _build_action_bar(self) -> QWidget:
        """Bottom action bar. No outer container — buttons float on the
        dotted page backdrop with a `QWidget` (not `QFrame`) wrapper so
        no border/background cascades to inner labels (the hotkey hint).
        """
        bar = QWidget()
        bar.setStyleSheet("QWidget { background: transparent; }")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(10)

        self._btn_start = _action_button("⏵ START LISTENING", primary=True)
        self._btn_start.clicked.connect(self.mic_toggled.emit)
        lay.addWidget(self._btn_start)

        self._btn_pause = _action_button("⏸ PAUSE WAKE")
        # Pause/resume is handled externally; we just toggle visible label.
        # Wire to wake_word_changed via mic_toggled? Keep stub for now.
        lay.addWidget(self._btn_pause)

        self._btn_clear = _action_button("⌫ CLEAR TRANSCRIPT")
        self._btn_clear.clicked.connect(self._on_clear_transcript)
        lay.addWidget(self._btn_clear)

        lay.addStretch(1)
        lay.addWidget(_hotkey_hint("HOTKEY  Ctrl+Shift+M  toggles mic"))
        return bar

    # ── Event handlers ───────────────────────────────────────────────────────

    def _on_clear_transcript(self) -> None:
        # Drop all child rows from the transcript list
        lay = self._transcript._rows_lay  # noqa: SLF001 — local accessor
        while lay.count() > 1:  # leave the trailing stretch
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._transcript._row_count = 0
        self._exchange_count.setText("0 exchanges")

    # ── Public API (preserved) ───────────────────────────────────────────────

    def set_state(self, state: str) -> None:
        self._state = state
        # Update hero tile
        display, color = self._STATE_LABEL.get(state, (state.upper(), INK_DIM))
        self._hm_state.set_value(display, color=color)
        if state == "listening":
            self._hm_state.set_sub("mic open")
            self._mic.set_listening(True)
            # waveform dropped in the M5 redesign — orb carries the state cue now.
        elif state == "thinking":
            self._hm_state.set_sub("routing through Claude")
            self._mic.set_listening(False)
        elif state == "speaking":
            self._hm_state.set_sub("TTS playback")
            self._mic.set_listening(False)
        elif state == "awaiting":
            self._hm_state.set_sub("user confirmation needed")
            self._mic.set_listening(False)
        else:  # idle
            self._hm_state.set_sub("mic closed")
            self._mic.set_listening(False)

    def update_transcript(self, cmd: str, resp: str, intent: str, conf: float) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self._transcript.add_user(now, cmd)
        self._transcript.add_jarvis(now, resp, intent, conf)
        # Each exchange = 1 user + 1 jarvis row → 2 rows; "exchanges" counts pairs.
        pairs = self._transcript._row_count // 2  # noqa: SLF001
        self._exchange_count.setText(f"{pairs} exchange{'s' if pairs != 1 else ''}")

    def append_jarvis_continuation(self, resp: str, intent: str, conf: float) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self._transcript.add_jarvis(now, resp, intent, conf)

    def set_execution(
        self,
        intent: str,
        action: str,
        conf: float,
        success: bool,
        error: Optional[str] = None,
    ) -> None:
        if not success:
            short = (error or "Failed").strip()
            if len(short) > 80:
                short = short[:77] + "…"
            now = datetime.now().strftime("%H:%M:%S")
            self._transcript.add_jarvis(now, short, intent, conf, status="fail")

    def set_pending(self, intent: str, action: str, conf: float, message: str) -> None:
        self.set_state("awaiting")
        self._transcript.add_system(
            f"Confirmation required · {intent}/{action} · {message[:80]}"
        )

    def clear_pending(self) -> None:
        self.set_state(self._state if self._state != "awaiting" else "idle")
        self._transcript.add_system("Confirmation cancelled.")

    # ── Paint (dotted backdrop) ──────────────────────────────────────────────

    def _rebuild_bg(self) -> None:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            self._bg_px = None
            return
        px = QPixmap(w, h)
        p = QPainter(px)
        p.fillRect(0, 0, w, h, QColor(BG))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 229, 255, 18))
        for x in range(0, w + 28, 28):
            for y in range(0, h + 28, 28):
                p.drawEllipse(x - 1, y - 1, 2, 2)
        p.end()
        self._bg_px = px
        self._bg_sz = (w, h)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._bg_px = None

    def paintEvent(self, _event) -> None:
        w, h = self.width(), self.height()
        if self._bg_px is None or self._bg_sz != (w, h):
            self._rebuild_bg()
        p = QPainter(self)
        if self._bg_px is not None:
            p.drawPixmap(0, 0, self._bg_px)
