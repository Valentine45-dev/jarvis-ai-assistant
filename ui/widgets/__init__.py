"""Reusable HUD widgets for the JARVIS UI rebuild.

Split from a single ui/widgets.py file (R2-17e) into the ``ui/widgets``
package. The public API is unchanged — every prior importer keeps working:
    from ui.widgets import _mono, ArcReactorWidget, CommandBar, ...
    from ui.widgets import GlassPanel, TerminalLog, TranscriptPanel  # re-exports

Sub-modules:
  - primitives.py — canonical font/header helpers + simple QLabel widgets
  - visuals.py    — painted indicators + Mark-LXXXV arc reactor + charts
  - inputs.py     — interactive controls (toggles, mic, command bar)
  - surfaces.py   — composite cards + overlays (GreetingCard, ToastNotification, ConfirmationBar)
"""

from __future__ import annotations

from ui.widgets.primitives import (
    AnimatedLabel,
    HudStatusLabel,
    LastActionStrip,
    ModuleIDLabel,
    StatusPip,
    _mono,
    _panel_header,
)
from ui.widgets.visuals import (
    ArcReactorWidget,
    ConfidenceGauge,
    LineChartWidget,
    OrbWidget,
    ScanLineOverlay,
    SegmentedBar,
    SparklineWidget,
    WaveformStrip,
)
from ui.widgets.inputs import (
    CommandBar,
    MicButton,
    ToggleSwitch,
    _TagHighlighter,
    _TagLineEdit,
)
from ui.widgets.surfaces import (
    ConfirmationBar,
    GreetingCard,
    ToastNotification,
    TypingIndicator,
)

# Re-exports preserved from the pre-split widgets.py module (used by dashboard.py)
from ui.components.panels import GlassPanel
from ui.components.transcript import TerminalLog, TranscriptPanel

__all__ = [
    # Helpers
    "_mono", "_panel_header",
    # Primitives
    "ModuleIDLabel", "StatusPip", "AnimatedLabel",
    "HudStatusLabel", "LastActionStrip",
    # Visuals
    "SegmentedBar", "ScanLineOverlay", "LineChartWidget", "ArcReactorWidget",
    "WaveformStrip", "ConfidenceGauge", "OrbWidget", "SparklineWidget",
    # Inputs
    "ToggleSwitch", "MicButton", "_TagHighlighter", "_TagLineEdit", "CommandBar",
    # Surfaces
    "GreetingCard", "TypingIndicator", "ToastNotification", "ConfirmationBar",
    # Re-exports
    "GlassPanel", "TerminalLog", "TranscriptPanel",
]
