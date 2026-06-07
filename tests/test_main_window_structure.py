"""R2-17a structural guards for the JarvisWindow package split.

These do NOT instantiate the window (pytest must stay window-free — Qt
wiring/virtual-dispatch is proved separately by tests/smoke_window.py via a
real launch). They assert the *structure* survives the mixin decomposition:

  - the public surface is re-exported from both ``main`` and the package,
  - JarvisWindow's MRO contains every method-group mixin,
  - all nine thread-bridge ``pyqtSignal``s remain class attributes of
    JarvisWindow itself (NOT moved onto a mixin — sip only processes signals
    on a QObject subclass, so this is load-bearing),
  - the cross-cutting class constants are still reachable.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5")

from PyQt5.QtCore import pyqtSignal  # noqa: E402

import main as root_main  # noqa: E402
from ui.main_window import JarvisWindow, main  # noqa: E402
from ui.main_window.voice_mixin import _VoiceMixin  # noqa: E402
from ui.main_window.confirm_mixin import _ConfirmMixin  # noqa: E402
from ui.main_window.execution_mixin import _ExecutionMixin  # noqa: E402
from ui.main_window.backend_signals_mixin import _BackendSignalsMixin  # noqa: E402
from ui.main_window.settings_mixin import _SettingsMixin  # noqa: E402
from ui.main_window.state_hud_mixin import _StateHudMixin  # noqa: E402
from ui.main_window.lifecycle_mixin import _LifecycleMixin  # noqa: E402


ALL_MIXINS = (
    _VoiceMixin,
    _ConfirmMixin,
    _ExecutionMixin,
    _BackendSignalsMixin,
    _SettingsMixin,
    _StateHudMixin,
    _LifecycleMixin,
)

# The nine worker-thread → Qt-main-thread bridge signals. Moving any of these
# off JarvisWindow would silently break delivery, so we pin them here.
EXPECTED_SIGNALS = (
    "_brain_result_ready",
    "_voice_text_ready",
    "_voice_error_ready",
    "_confirmation_resolved_ready",
    "_resume_executor_confirm",
    "_tts_ready",
    "_tts_done_signal",
    "_wake_word_signal",
    "_action_followup_tts",
)


def test_public_surface_reexported():
    assert root_main.JarvisWindow is JarvisWindow
    assert root_main.main is main
    assert callable(main)


def test_mro_contains_every_mixin():
    mro = JarvisWindow.__mro__
    for mixin in ALL_MIXINS:
        assert mixin in mro, f"{mixin.__name__} missing from JarvisWindow MRO"


def test_all_nine_signals_present_at_class_level():
    for name in EXPECTED_SIGNALS:
        attr = JarvisWindow.__dict__.get(name)
        assert isinstance(attr, pyqtSignal), (
            f"{name} is not a pyqtSignal defined directly on JarvisWindow "
            f"(got {attr!r}); signals must stay on the QObject subclass."
        )


def test_signals_not_defined_on_any_mixin():
    # A mixin is a plain object subclass; a pyqtSignal there would never be
    # processed by sip. Guard against an accidental move.
    for mixin in ALL_MIXINS:
        for name in EXPECTED_SIGNALS:
            assert name not in mixin.__dict__, (
                f"{name} must not live on mixin {mixin.__name__}"
            )


def test_cross_cutting_constants_reachable():
    assert JarvisWindow.VIEW_NAMES[0] == "Dashboard"
    assert JarvisWindow._RUN_WORKFLOW_PREFIX
    assert JarvisWindow._INTENT_HUD["open_app"] == "LAUNCHING APP"
